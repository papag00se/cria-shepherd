"""cria's HTTP service — a stdlib ``ThreadingHTTPServer`` exposing an
OpenAI-compatible ``/v1/chat/completions`` endpoint.

The harness (codex, or any OpenAI-compatible agent) points its model client at
cria and gets back completions, knowing nothing of what cria did in the middle.
Phase 1 proxies faithfully; phases 2+ insert classification, planning, and the
assists between ``request.recv`` and the upstream call — the ``_handle_chat`` body
is where that pipeline grows.

Streaming uses ``Connection: close`` (no chunked framing) — correct and simple for
a localhost/LAN single-user service; the client reads SSE until EOF.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import callcapture, focustrim, massage, responses, rumination
from .classify import Classifier
from .content_reduce import est_tokens
from .config import Config
from . import brave, webfetch
from .events import EventLog
from .heartbeat import Heartbeat
from .indicators import MARKER, Indicator, inject_buffered, strip_history, strip_note_lines, wrap_stream
from .loop import (
    Loop,
    LoopContext,
    LoopStore,
    _fetch_ground_truth,
    completion_to_sse,
    reframe_compaction,
    session_key,
)
from .planner import Planner, _extract_cwd
from .routing import Router
from .statusline import StatusWriter  # noqa: F401 — re-exported for tests
from . import statusline
from .toolmenu import add_cheatsheet, focus_tools
from .turnstats import StatsStore
from .upstream import Upstream, UpstreamError
from .writeproxy import advertise, native_search_name, needs_translation, redact_secrets, represent_inbound, translate_outbound


def _error_sse(message: str) -> bytes:
    """Convey an error inside an already-open SSE stream (headers are 200 by then)."""
    payload = {"error": {"message": message, "type": "upstream_error"}}
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\ndata: [DONE]\n\n"


def _visible_web_calls(messages: list) -> tuple[list, list]:
    """The web_fetch (url, find, cursor) keys and web_search queries STILL PRESENT in the conversation
    (post-represent_inbound, so the calls are labeled web_fetch/web_search). Feeds the exact-repeat
    gate so it refuses a repeat only while the model can still read that result — not after
    compaction elided it."""
    from .toolargs import parse_args
    fetch_keys, queries = [], []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name")
            if name == "web_fetch":
                a = parse_args(fn.get("arguments"))
                if a.get("url"):
                    find = str(a["find"]) if a.get("find") else ""
                    cursor = str(a["cursor"]) if a.get("cursor") not in (None, "") else ""
                    fetch_keys.append((str(a["url"]), find, cursor))
            elif name in ("web_search", "local_web_search"):
                a = parse_args(fn.get("arguments"))
                if a.get("query"):
                    queries.append(str(a["query"]))
    return fetch_keys, queries


def _warn_config(cfg: Config, has_reasoner: bool, has_coder: bool, log) -> None:
    """One-time startup sanity: warn when a configured-looking feature CAN'T actually run, so a
    misconfiguration is visible instead of silently degrading — the class that hid the Brave-key
    bug (web_search just quietly never ran; the planner was quietly a passthrough)."""
    if cfg.planner.enabled and not (has_reasoner and has_coder):
        missing = [r for r, ok in (("reasoner", has_reasoner), ("coder", has_coder)) if not ok]
        log.emit("config.warn", level="warn", issue="planner_inert",
                 detail=f"[planner] enabled but missing role(s): {', '.join(missing)} — the plan loop will not run")
    if cfg.planner.enabled and not brave.api_key():
        log.emit("config.warn", level="warn", issue="web_search_disabled",
                 detail=f"web_search needs {brave.API_KEY_ENV} but it's empty in the process — "
                        "search disabled (is env_file set and loaded?)")


def _has_visible_output(comp: dict) -> bool:
    """True if the completion carries something the user should see — a tool call or
    non-empty text. Used to decide whether to show the ⟦cria⟧ banner (never on an
    empty turn)."""
    msg = ((comp.get("choices") or [{}])[0].get("message")) or {}
    return bool(msg.get("tool_calls")) or bool((msg.get("content") or "").strip())


def _prepend_content_line(completion: dict, line: str) -> None:
    """Prepend ``line`` as its own line to the first choice's message content (creating it if the
    turn was tool-calls-only). Used to surface cria's out-of-band assist notes as ⟦cria⟧ lines."""
    choices = completion.get("choices") or []
    if not choices:
        return
    msg = choices[0].setdefault("message", {})
    existing = msg.get("content")
    msg["content"] = f"{line}\n{existing}" if isinstance(existing, str) and existing else line


def _append_content_line(completion: dict, line: str) -> None:
    """Append ``line`` after the first choice's message content (a footer, e.g. the turn stats)."""
    choices = completion.get("choices") or []
    if not choices:
        return
    msg = choices[0].setdefault("message", {})
    existing = msg.get("content")
    msg["content"] = f"{existing}\n\n{line}" if isinstance(existing, str) and existing else line

# Renamed from the Rust vehicle's ``X-Nudge-Session-Id`` as part of the rebrand.
# Optional: absent → cria runs stateless (fine for phase 1; session state lands
# in phase 6 with the per-item plan loop).
SESSION_HEADER = "X-Cria-Session-Id"

# The handshake marker a compaction request leads with — the operator wires the harness's
# compaction prompt to start with it (Codex: `compact_prompt = "<<<LOCAL_COMPACT>>> Summarize …"`),
# so cria can recognize a SUMMARIZE turn (correctly tool-less) and route it to the compactor role's
# tuned sampling, never the classifier's guess or a bare passthrough. Harness-agnostic: any harness
# that leads its compaction prompt with this marker gets the compactor.
LOCAL_COMPACT_MARKER = "<<<LOCAL_COMPACT>>>"


def _is_compaction_request(messages: list) -> bool:
    """True when the latest user turn is the harness's compaction/summarize request (see marker)."""
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            return isinstance(c, str) and LOCAL_COMPACT_MARKER in c
    return False


# Last-known harness cwd per session. A harness advertises its workspace (Codex's <cwd>) in the
# environment preamble, but a COMPACTION/summarize turn arrives without it — re-extracting would then
# yield None and the workspace would go "unknown" mid-session. Remember it per session so the dirguard
# keeps bounding to the RIGHT repo (never cria's own dir) across the whole session. Bounded like the
# webfetch gate stores. The loop persists its own copy on the session (sess.workspace_root).
_CWD_BY_SESSION: dict[str, str] = {}


def _session_cwd(sess_key: str, messages: list) -> str | None:
    """The harness's workspace cwd for this session: the freshly-advertised <cwd>, else the last one
    remembered for the session. NEVER '.' (cria's own dir) — an unknown cwd stays None so callers skip
    disk work rather than target cria's source tree."""
    cwd = _extract_cwd(messages)
    if cwd:
        if len(_CWD_BY_SESSION) > 512:
            _CWD_BY_SESSION.clear()
        _CWD_BY_SESSION[sess_key] = cwd
        return cwd
    return _CWD_BY_SESSION.get(sess_key)


def _proxy_body(body: dict) -> dict:
    """The proxy (relay) path — used when cria isn't orchestrating (a question, or an aux
    harness call the loop declined, e.g. Codex's UI title-generation) — still DROPS the
    harness's agent system/developer prompt. That persona is harness-specific and often
    absurd overhead (Codex prepends its ~5.6K-token "You are Codex" boilerplate even to a
    36-char title call). The request's own instructions live in its user messages and still
    drive it; cria imposes no orchestration prompt of its own here. (The coder path drops it
    separately, in loop._frame_for_item, and leads with cria's coder system prompt.)"""
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return body
    kept = [m for m in msgs if m.get("role") not in ("system", "developer")]
    if len(kept) == len(msgs):
        return body  # nothing to strip → same object
    return {**body, "messages": kept}


def _workspace_listing(ws: str | None) -> str:
    """FILES ALREADY IN THIS WORKSPACE, names only (top level + one level down), for the compaction
    summary. Empty string when the workspace is unknown/absent — silence over noise."""
    if not ws or not os.path.isdir(ws):
        return ""
    lines: list[str] = []
    try:
        for name in sorted(os.listdir(ws))[:40]:
            if name.startswith(".") or name == "tmp" or name.endswith(".pyc"):
                continue
            full = os.path.join(ws, name)
            if os.path.isdir(full):
                inner = sorted(x for x in os.listdir(full) if not x.startswith((".", "__pycache__")))[:12]
                lines.append(f"  {name}/" + (("  (" + ", ".join(inner) + ")") if inner else ""))
            else:
                lines.append(f"  {name}")
    except OSError:
        return ""
    if not lines:
        return ""
    return "FILES ALREADY IN THIS WORKSPACE (on disk right now — do not re-create them):\n" + "\n".join(lines)


def _harden_compaction_reply(comp: dict, body: dict, provider, server, rlog) -> dict:
    """The harness stores this reply as the session's ENTIRE remembered past — everything not in it
    is gone (self-compaction's anchors cannot protect messages the harness itself discards). Two
    hardenings, both from captured failures:

    (1) EMPTY-BRIEFING RETRY. The compactor sometimes answers a summarize with only a hallucinated
    tool call and NO salvageable prose (run 0729-gemma4 B3 0094): the harness then carries an empty
    summary and the coder wakes to "Your summary of the work so far:" followed by nothing. The
    loop-side ``summarize()`` already retries reasoning-OFF for exactly this shape; this is the same
    retry for the harness path — thinking suppressed, the summary lands straight in content instead
    of being drafted in reasoning and lost behind a fake call.

    (2) FETCH-FACTS APPENDIX. Post-compaction coders re-guessed API knowledge the session had
    already obtained (an invented /v1 base, a made-up /resolve endpoint) because the fetched-spec
    facts lived only in the discarded transcript. The deterministic fetch ledger (final status per
    URL + surfaced endpoint routes) is computed from the history being folded and appended to the
    summary — cria appends only facts it can re-derive from the record, never judgment."""
    def _text_of(c: dict) -> str:
        for ch in c.get("choices") or []:
            t = (ch.get("message") or {}).get("content")
            if isinstance(t, str):
                return t
        return ""

    text = _text_of(comp).strip()
    if not text or massage.has_tool_call_leak(text):
        role = server.cfg.routing.roles.get("compactor") or server.cfg.routing.roles.get("reasoner")
        pb = _proxy_body(dict(body))
        if role is not None:
            replace(role, reasoning="off").apply(pb)
        else:
            pb.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        rlog.emit("route.compaction_retry", level="info", had_leak=bool(text))
        try:
            comp2 = massage.coerce_text_answer(
                massage.apply(json.loads(provider.chat(pb, rlog)), None, rlog), rlog)
            text2 = _text_of(comp2).strip()
            if text2 and not massage.has_tool_call_leak(text2):
                comp, text = comp2, text2
            else:
                # both passes produced no usable prose (observed: two pseudo write_file dumps in a
                # row, run g1 0093/0094) — the summary will be the deterministic appendices ONLY.
                # Without this emit that fact was invisible in the events.
                rlog.emit("route.compaction_no_briefing", level="warning", retry_leak=bool(text2))
        except Exception:  # noqa: BLE001 — best-effort: a failed retry must never break the reply
            rlog.emit("route.compaction_retry_failed", level="warning")
    facts = _fetch_ground_truth(body.get("messages", []))
    # WORKSPACE LEDGER — the fetch-facts pattern extended to files. g1's compaction summary carried
    # endpoint facts but no file inventory; the post-compaction coder, told to inspect before
    # creating, didn't — and wrote a DUPLICATE test suite beside the one it had already built.
    # A name-only listing (top level + one level down) is re-derivable truth, judgment-free.
    ws = _session_cwd(session_key({}, body.get("messages", [])), body.get("messages", []))
    inventory = _workspace_listing(ws)
    facts = "\n\n".join(t for t in (facts, inventory) if t)
    if facts:
        merged = (text + "\n\n" + facts).strip()
        chs = [dict(ch) for ch in comp.get("choices") or []]
        if chs:
            chs[0] = {**chs[0], "message": {**(chs[0].get("message") or {}), "content": merged}}
            comp = {**comp, "choices": chs}
    return comp


class CriaServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cfg: Config, log: EventLog, upstream: Upstream) -> None:
        self.cfg = cfg
        self.log = log
        self.upstream = upstream
        # Routing engages only when configured. With no [roles]/[failover], cria is a plain
        # phase-1 passthrough.
        roles = cfg.routing.roles  # each role = a backend binding + per-request sampling + reasoning.
        # A role is "configured" by the PRESENCE of its [roles.<name>] table, so every gate below keys
        # on membership in `roles`.
        self.router = (
            Router(cfg.routing, upstream, timeout=cfg.upstream.timeout_seconds)
            if (roles or cfg.routing.failover)
            else None
        )
        # PER-ROLE ENDPOINT: every role resolves its OWN base_url (or the shared endpoint), not just the
        # coder — closes the bug where the classifier / reasoner / planner / compactor were hardwired to
        # the shared upstream and silently ignored a per-role base_url (a role may run on another box).
        def _ep(role):
            return self.router.endpoint_for(role) if self.router is not None else upstream
        self._endpoint_for = _ep
        self.classifier = (
            Classifier(_ep("classifier"), cfg.routing.engagement_bias, role=roles.get("classifier"))
            if "classifier" in roles
            else None
        )
        # The loop is cria's ONE coder driver: with the planner ON it decomposes and drives item by
        # item; with the planner OFF it drives a degenerate 1-item (synthetic) plan — the relocated
        # plan-off direct-coder path. So it is built whenever a coder exists (and, when the planner is
        # on, a reasoner too). Without a coder, cria is a smart proxy.
        has_reasoner = "reasoner" in roles
        has_coder = "coder" in roles
        # The coder role's sampling/reserve — the rumination budget for the loop's coder call.
        self.coder_role = roles.get("coder")
        self.reasoner_role = roles.get("reasoner")  # for the single-item satisfaction critic (task-level judge)
        # The ENDPOINTS the reasoner-family roles run on (each honors its own base_url) — used by the
        # loop's reasoner calls (satisfaction judge, redirect author) and self-compaction summaries,
        # so they hit the reasoner/compactor box, not always the shared upstream.
        self.reasoner_upstream = _ep("reasoner")
        self.compactor_upstream = _ep("compactor") if "compactor" in roles else self.reasoner_upstream
        # Compaction/summarization sampling. The [roles.compactor] role exists precisely for
        # folding transcript spans into briefings (temp 0.6, reasoning on) — NOT the coder role
        # (temp 0.1, coding-primed: it misreads "summarize this" as "continue the task" and emits a
        # next-action instead of a backward-looking rollup). Fall back to the reasoner (same sampling
        # family) when no compactor table is configured, never the coder.
        self.compactor_role = roles.get("compactor") or roles.get("reasoner")
        # Per-session end-of-turn stats (calls, tok/s, guard fires, wall time).
        self.stats_store = StatsStore()
        # In-flight streaming responses (Heartbeat -> resp_id), so a shutdown can END each one with a
        # clean, RETRYABLE terminal event instead of the bare mid-stream EOF that wedges the client.
        self.active_streams: dict = {}
        self._session_t0: dict[str, float] = {}
        self._streams_lock = threading.Lock()
        # Conversation-shape store for HARNESS-COMPACTION detection (structural rewrite detection +
        # the completion-briefing `done` bit) — persisted so a cria restart doesn't orphan detection.
        self.loop_store = LoopStore(state_path=os.path.join(cfg.logging.dir, "loopstate.json"))
        self.loop = None
        # Surface a misconfigured-looking feature at startup instead of silently degrading — the
        # class of failure that hid the Brave-key bug (web_search just quietly never ran).
        _warn_config(cfg, has_reasoner, has_coder, log)
        # Always build the loop when a coder exists; require a reasoner only when the planner is ON.
        # Planner OFF → the loop drives the synthetic 1-item path (guards but no decomposition).
        if has_coder and (has_reasoner or not cfg.planner.enabled):
            # The web-search key comes from the fixed BRAVE_SEARCH_API_KEY env var (never stored in
            # config); brave.api_key() reads it normalized (CRLF-safe) — the CRLF was the illegal-
            # header footgun, fixed once at the source (envfile) rather than stripped per-consumer.
            search_key = brave.api_key() or ""
            # The coder runs on the STREAMING-guarded path so its reasoning is watched live: a
            # runaway thinking loop is aborted mid-flight (rumination detector) instead of burning
            # the window to an empty turn / truncation. Budget seeded from the coder's output_reserve.
            coder_role = self.coder_role
            detector = rumination.Detector.from_reasoning_budget(
                coder_role.output_reserve if coder_role else None)

            def coder_chat(body, rlog, _up=_ep("coder"), _det=detector):
                return _up.chat_watched(body, rlog, watch=_det.check)

            self.loop = Loop(
                LoopContext(
                    planner=Planner(_ep("reasoner"), role=roles.get("reasoner"),
                                    search_key=search_key, max_gather_rounds=cfg.planner.max_gather_rounds),
                    coder_chat=coder_chat,
                    # reasoner_chat/reasoner_role are wired UNCONDITIONALLY (even with no reasoner role,
                    # _ep resolves the shared endpoint and role is None) — the single-item off-ramps gate
                    # on `reasoner_role is not None`, so a plan-off Loop without a reasoner just skips them.
                    reasoner_chat=_ep("reasoner").chat,
                    coder_role=coder_role,
                    reasoner_role=roles.get("reasoner"),
                    compactor_role=self.compactor_role,
                    # The compactor ENDPOINT's chat for the single-item self-compaction (rides the
                    # compactor box like the plan-off _summarize did); None-safe (falls back to reasoner).
                    compactor_chat=self.compactor_upstream.chat,
                    planner_enabled=cfg.planner.enabled,
                    satisfaction_check_start=cfg.context.satisfaction_check_start,
                    satisfaction_check_every=cfg.context.satisfaction_check_every,
                    # ONE folder per run: plan mirror + verify dumps join the call captures
                    # under <capture_dir>/<session>/ — a single place per session.
                    runs_dir=cfg.logging.capture_dir,
                    focus_trim=cfg.context.focus_trim,
                    self_compact=cfg.context.self_compact,
                    trigger_compaction=cfg.context.trigger_compaction,
                ),
                # Completed-work briefings + session shapes survive a cria restart (the restarts this
                # project makes constantly were wiping the context a follow-up / a post-compaction
                # continuation needs). Live multi-item plans + synthetic sessions on stable keys are
                # persisted; unstable task: keys are ephemeral — see LoopStore.
                self.loop_store,
            )
        super().__init__((cfg.server.host, cfg.server.port), CriaHandler)

    def session_started(self, sess_key: str) -> float:
        """Unix-epoch start time for a session — the ticker's TOTAL running clock. A Codex session
        id is a UUIDv7, so its BIRTH TIME rides in the key itself: durable across cria restarts with
        no stored state (the in-memory dict amnesia showed the operator "t+0s" on an hour-old
        session after a restart). Non-v7 keys fall back to first-seen, in-memory."""
        if sess_key.startswith("sid:"):
            born = callcapture.uuid7_epoch(sess_key[4:])
            if born is not None:
                return born
        with self._streams_lock:
            return self._session_t0.setdefault(sess_key, time.time())

    def register_stream(self, hb, resp_id: str) -> None:
        with self._streams_lock:
            self.active_streams[hb] = resp_id

    def unregister_stream(self, hb) -> None:
        with self._streams_lock:
            self.active_streams.pop(hb, None)

    def drain_streams(self) -> int:
        """On shutdown, END every in-flight SSE stream with a terminal, RETRYABLE response.failed so
        the client re-sends the turn cleanly. Without this a restart mid-generation kills the daemon
        request thread while it's blocked in the model call, the socket EOFs mid-stream, and the
        harness mislabels the disconnect as a user interrupt (the '<turn_aborted>' + manual 'continue'
        wedge). We write the terminal from HERE (the shutdown thread) via each Heartbeat's write lock,
        since the request thread can't (it's blocked upstream)."""
        with self._streams_lock:
            streams = list(self.active_streams.items())
        for hb, resp_id in streams:
            try:
                hb.drain(responses.failed_event(resp_id, "cria is restarting — retry shortly"))
            except Exception:  # noqa: BLE001 — best effort; shutting down regardless
                pass
        return len(streams)


class CriaHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "cria"
    sys_version = ""

    # Route the base handler's own access noise through our event log (debug), so
    # there is exactly one logging path.
    def log_message(self, fmt: str, *args) -> None:
        self.server.log.emit("http.access", level="debug", line=(fmt % args))

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/health":
            self._send_json(200, {"status": "ok"})
        elif path == "/v1/models":
            # Two consumers, two shapes: Codex's model manager wants a top-level
            # `models` list (empty is fine — it falls back to config metadata, and
            # [server] pins the context window); plain OpenAI clients want `data`.
            models = [self.server.upstream.loaded_model(self.server.log) or "cria"]
            self._send_json(200, {
                "object": "list",
                "data": [{"id": m, "object": "model", "owned_by": "cria"} for m in models],
                "models": [],
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")   # strip any query string (parity with do_GET)
        if path == "/v1/chat/completions":
            self._handle_chat()
        elif path == "/v1/responses":
            self._handle_responses()
        else:
            self._send_json(404, {"error": "not found"})

    # ------------------------------------------------------------------ chat

    def _handle_chat(self) -> None:
        log: EventLog = self.server.log
        session = self.headers.get(SESSION_HEADER)
        turn = uuid.uuid4().hex[:8]
        rlog = log.bind(session=session, turn=turn)

        try:
            body = self._read_json_body()
        except ValueError as e:
            rlog.emit("request.bad", level="warn", error=str(e))
            self._send_json(400, {"error": f"invalid JSON body: {e}"})
            return

        # INBOUND STRIP: remove cria's own indicator lines from the history before
        # the model re-reads them (they were injected only for the human's view).
        messages = body.get("messages")
        if isinstance(messages, list):
            cleaned, stripped = strip_history(messages)
            cleaned, reframed = reframe_compaction(cleaned)  # reattribute the harness compaction turn
            if stripped or reframed:
                body["messages"] = cleaned
                if stripped:
                    rlog.emit("indicators.stripped", lines=stripped)
                if reframed:
                    rlog.emit("loop.compaction_reframed")

        # write_file↔shell: if the harness has shell but not write_file, re-present
        # our prior shell translations as write_file (so the model sees its own
        # tool) and advertise write_file to the model. Outbound lowering happens at
        # the send points via _translate_out.
        # Chat path: the downstream _translate_out uses session_key(self.headers, messages) too, so the
        # fetch gate's write/read keys match here (session_key hashes the stable root, unchanged by
        # represent_inbound).
        self._setup_translation(body, session_key(self.headers, body.get("messages", [])), rlog)

        # Tool-menu FOCUS: curate the harness's menu to the coding essentials (drop the
        # goal/MCP/connector firehose) — after advertise so cria's write_file survives.
        if self.server.cfg.tools.focus:
            focus_tools(body, rlog)
        # Tool cheat-sheet: a terse per-tool usage note for the (now curated) tools.
        if self.server.cfg.tools.cheatsheet:
            add_cheatsheet(body, rlog)

        # Honest token accounting for the connected harness (see _report_context_usage): the size
        # of the context IT sent, not cria's internal call usages. cria fits it to the window itself.
        self._ctx_tokens = _incoming_ctx_tokens(body, rlog)
        stream = bool(body.get("stream"))
        rlog.emit(
            "request.recv",
            model=body.get("model"),
            stream=stream,
            n_messages=len(body.get("messages", [])),
            has_tools=bool(body.get("tools")),
        )

        # Streaming does the model work behind a heartbeat; buffered does not (no
        # stream to heartbeat into). The classify → loop|route dispatch lives inside.
        if stream:
            self._respond_stream(body, rlog)
        else:
            self._respond_buffered(body, rlog)

    def _classify(self, body: dict, rlog):
        server: CriaServer = self.server
        if server.classifier is None:
            return None
        return server.classifier.classify(body.get("messages", []), rlog)

    def _decorate(self, completion: dict) -> dict:
        """[indicators] assists: surface EVERY cria assist that fired as a ⟦cria⟧ line — the
        out-of-band `cria_notes` channel the guards append to (rumination/truncation/steer) PLUS any
        ⟦cria⟧ note already in the content (the repetition/wheel-spin probes). 'No hidden guards':
        under the flag a fired guard is always visible; with the flag off, all of it is stripped."""
        ic = self.server.cfg.indicators
        notes = completion.pop("cria_notes", None) or []
        if ic.enabled and ic.assists:
            for note in reversed(notes):  # each note becomes its own ⟦cria⟧ line, ahead of the content
                _prepend_content_line(completion, f"{MARKER}{note}")
        else:
            strip_note_lines(completion)  # drop content ⟦cria⟧ notes too (cria_notes already popped)
        return completion

    def _finalize(self, completion: dict, sess_key: str, rlog) -> dict:
        """The single completion-finalization chokepoint: fold this response into the turn stats
        (before _decorate consumes the notes), apply the [indicators] decoration, and — when the
        agent has FINISHED the user turn (a text answer, no tool call, after real multi-step work)
        — append the terse end-of-turn summary and reset the turn."""
        ic = self.server.cfg.indicators
        stats = self.server.stats_store.get(sess_key)
        stats.observe(getattr(rlog, "last_tok_per_s", None),
                      getattr(rlog, "gen_tokens", 0), getattr(rlog, "model_calls", 0),
                      getattr(rlog, "events", None))
        completion = self._decorate(completion)
        tool_turn = any((ch.get("message") or {}).get("tool_calls") for ch in completion.get("choices", []))
        if not tool_turn and stats.calls >= 2:  # a text answer after real work → the turn ended
            # Reset ONLY once the tally has actually been REPORTED. The reset used to be
            # unconditional while the summary was gated on visible output, so an EMPTY answer
            # (no tool calls, no content — which this path sees often) threw the counts away with
            # nothing shown. Measured on run 0728-m2: 1711 real upstream.done calls, two summaries
            # emitted, 86 calls between them — ~1625 calls silently unaccounted, and the operator
            # reads "🧮 43 calls" as the cost of the run. Carrying the tally forward means the next
            # summary covers everything since the last REPORT, so no call goes unattributed.
            if ic.enabled and ic.stats and _has_visible_output(completion):
                _append_content_line(completion, stats.summary())
                self.server.stats_store.reset(sess_key)
        return completion

    def _setup_translation(self, body: dict, sess_key: str, rlog) -> None:
        """Set up the synthetic-tool ↔ shell round-trip for this request: STATELESSLY re-present prior
        shell translations as the tool the model called (from the sentinel in history), then advertise
        cria's synthetic tools. Records what to lower outbound (self._synthetic), the harness's search
        backend to route web_search to (self._native_search — read BEFORE advertise renames it), and
        the Brave key for a synthesized web_search.

        ``sess_key`` MUST be the SAME key the outbound lowering uses (``_translate_out`` → ``fetch_nav``),
        or the exact-repeat fetch/search gate is dead: it records the visible set under one key and
        checks under another. On the Responses path the reader key is ``sid:<sess>`` (from the body's
        cache key), NOT ``session_key(headers, messages)`` — so passing the caller's sess_key here is
        what lets the 'you already fetched this' refusal fire (it re-fetched openapi.json 10+ times)."""
        self._shell_tool = needs_translation(body.get("tools"))
        self._synthetic: set[str] = set()
        self._native_search = None
        self._brave_key = brave.api_key()
        # The workspace root (from the harness env-context <cwd>) — the boundary the external-dir
        # guard classifies paths against when it bounds a fledgling model on the --yolo harness.
        self._workspace_root = _session_cwd(sess_key, body.get("messages", []))
        # Re-present prior lowered shell calls as the synthetic tool the model actually called —
        # UNCONDITIONALLY, before the shell-tool gate. A harness compaction/summarize turn arrives with
        # tools:[] (no shell tool), yet its history still holds cria's ⟦ctx:tool⟧-lowered write_file/
        # edit_file/read_file calls; without this the model summarizes ~28 raw `python3 - <<HEREDOC`
        # blobs instead of its own tool calls, and that degraded summary becomes the next ⟦ctx:
        # continuation⟧. No-op when no sentinel is present, so a plain passthrough is unaffected.
        body["messages"] = redact_secrets(represent_inbound(body.get("messages", []), rlog),
                                           [self._brave_key])
        if self._shell_tool is not None:
            self._native_search = native_search_name(body.get("tools"))
            self._synthetic = advertise(body, rlog, brave_key=self._brave_key)
            # The exact-repeat fetch/search gate refuses a repeat ONLY while its result is still in
            # context — feed it the web calls STILL PRESENT, so a compacted-away result (an OpenAPI
            # spec the model needs to re-read) can be re-fetched instead of blocked forever.
            fk, sq = _visible_web_calls(body.get("messages", []))
            webfetch.set_visible(sess_key, fk, sq)

    def _translate_out(self, completion: dict, sess_key: str, rlog) -> dict:
        """Lower the model's synthetic-tool calls to shell, when translation is active for this
        request (set up in `_setup_translation`). ``sess_key`` enables webfetch's per-session
        fetch/search repeat + stop-guessing gates."""
        if self._shell_tool is not None:
            translate_outbound(completion, self._shell_tool, rlog, injected=getattr(self, "_synthetic", set()),
                               brave_key=getattr(self, "_brave_key", None),
                               native_search=getattr(self, "_native_search", None), session=sess_key,
                               workspace_root=getattr(self, "_workspace_root", None),
                               external_dir_permission=self.server.cfg.safety.external_dir_permission)
        return completion

    def _focus_trim(self, framed: dict, rlog) -> tuple[dict, bool]:
        """Collapse exact-duplicate tool calls in the OUTBOUND coder body so the model stays focused
        on current state — applied to the FRAMED copy, never the history cria's detectors read.
        Gated by [context] focus_trim. Returns (body, applied?)."""
        if not self.server.cfg.context.focus_trim:
            return framed, False
        msgs = framed.get("messages")
        if not isinstance(msgs, list):
            return framed, False
        trimmed, rep = focustrim.trim(msgs)
        if not rep.applied:
            return framed, False
        rlog.emit("context.focus_trim", dropped_calls=rep.dropped_calls, dropped_msgs=rep.dropped_msgs)
        return {**framed, "messages": trimmed}, True

    def _route(self, body: dict, classification, rlog) -> tuple[object, Indicator]:
        """Resolve the provider/model for this classification and build the
        indicator. Falls back to the local upstream (passthrough) when routing isn't
        configured or nothing resolves. Mutates ``body["model"]``."""
        server: CriaServer = self.server
        ic = server.cfg.indicators

        def banner_model(provider, fallback: str) -> str:
            """The name to SHOW: the model actually loaded at the server (llama.cpp /v1/models), so
            the banner is the TRUTH, not a config label that may not match what's loaded. Cloud
            providers report None → the routed model name stands."""
            loaded = provider.loaded_model(rlog) if hasattr(provider, "loaded_model") else None
            return loaded or fallback

        def passthrough() -> tuple[object, Indicator]:
            return server.upstream, Indicator(ic.enabled, ic.metrics,
                                              model=banner_model(server.upstream, str(body.get("model") or "?")),
                                              role=None, route=ic.route, assists=ic.assists)

        # A harness COMPACTION request (the `<<<LOCAL_COMPACT>>>` handshake) is a SUMMARIZE — route it
        # to the compactor role's tuned sampling on the compactor endpoint, not the classifier's guess
        # (its text reads as a plain 'question' → the reasoner). The compactor endpoint falls back to the
        # reasoner/shared upstream when no [roles.compactor] is set, so this is safe unconfigured too.
        if _is_compaction_request(body.get("messages", [])):
            role_name = "compactor" if "compactor" in server.cfg.routing.roles else "reasoner"
            rlog.emit("route.compaction", role=role_name)
            return server.compactor_upstream, Indicator(
                ic.enabled, ic.metrics,
                model=banner_model(server.compactor_upstream, str(body.get("model") or "?")),
                role=role_name, route=ic.route, assists=ic.assists)

        if server.router is None or classification is None:
            return passthrough()
        route = server.router.route(classification.task_type, rlog)
        if route is None:
            return passthrough()
        if route.model:  # None = a served role with no alias → leave the request's model; the
            body["model"] = route.model  # upstream fills the server's loaded model in _prep
        # (Sampling + reasoning are applied by _apply_route_role → role.apply, which translates the
        # role's one portable reasoning value into its backend's convention — served or remote alike.)
        # Show the "which model" line only when the classification is fresh (first
        # turn of a task); on cached turns just the tok/s line, to avoid repeating it.
        return route.provider, Indicator(
            ic.enabled, ic.metrics,
            model=banner_model(route.provider, route.model or str(body.get("model") or "?")), role=route.role,
            show_route=not classification.cached, route=ic.route, assists=ic.assists,
        )

    def _apply_route_role(self, pbody: dict, indic) -> dict:
        """Attach the routed role's sampling + reasoning (temp/top_p/top_k/repeat_penalty + the
        reasoning toggle, translated to its backend's convention) to a proxy-path body, in place.
        WITHOUT this a model on the proxy path runs on the server's defaults — no repeat_penalty
        (gemma4 then leaks `<|tool_call>`/`<|channel>` tokens), wrong temperature, no reasoning
        toggle — i.e. NOT the model the toml configures. The plan loop applies the role per call
        (loop.py); the proxy and direct-coder paths must do the same, or the same model behaves like
        a different one."""
        role = self.server.cfg.routing.roles.get(indic.role) if getattr(indic, "role", None) else None
        if role is not None:
            role.apply(pbody)
        return pbody

    def _respond_stream(self, body: dict, rlog) -> None:
        """Stream the response as SSE, with a heartbeat covering the dead time before
        the first real byte (classify / plan / coder / verify / upstream prefill)."""
        self.close_connection = True  # no keep-alive; client reads SSE to EOF
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def raw_write(data: bytes) -> None:
            self.wfile.write(data)
            self.wfile.flush()

        hb = Heartbeat(raw_write, interval=self.server.cfg.server.heartbeat_seconds).start()
        try:
            for raw in self._produce_stream(body, rlog):
                hb.write(raw)
            rlog.emit("response.sent", stream=True, beats=hb.beats)
        except (BrokenPipeError, ConnectionResetError):
            rlog.emit("response.client_gone", level="warn")
        finally:
            hb.stop()

    def _engages_loop(self, sk: str, classification) -> bool:
        """Should this turn go through the loop (cria's ONE coder driver) rather than the proxy?
        A KNOWN session always continues — a mid-plan tool result / a post-compaction continuation
        classifies as non-task, and gating on per-turn classification would abandon the work. For a
        FRESH turn, classification gates STARTING: planner ON → an ``engagement == "task"``; planner
        OFF → a ``task_type == "coding"`` (the synthetic 1-item path). Used by BOTH producers so the
        buffered and streaming transports dispatch identically."""
        loop = self.server.loop
        if loop is None:
            return False
        if loop.knows_session(sk):
            return True
        if classification is None:
            return False
        if self.server.cfg.planner.enabled:
            return classification.engagement == "task"
        return classification.task_type == "coding"

    def _produce_stream(self, body: dict, rlog):
        """The SSE chunk generator. The blocking model work happens here on the first
        iteration, so the heartbeat running in `_respond_stream` covers it.

        Every model-touching step — classify, the plan loop, and the routed call — is
        under one guard: an upstream failure (e.g. a 500 from a strict chat template)
        becomes a clean in-stream error, never a dead handler thread."""
        server: CriaServer = self.server
        try:
            classification = self._classify(body, rlog)
            sk = session_key(self.headers, body.get("messages", []))
            # ONE coder driver: engage the loop when it should (a known session, or a fresh turn the
            # loop would start — see _engages_loop). It drives a real multi-item plan OR the synthetic
            # 1-item plan-off path; both come back as a completion. Otherwise fall through to the proxy.
            if self._engages_loop(sk, classification):
                completion = server.loop.drive(body, sk, classification, rlog)
                if completion is not None:
                    yield from completion_to_sse(self._finalize(self._translate_out(completion, sk, rlog), sk, rlog))
                    return
            provider, indic = self._route(body, classification, rlog)
            rlog.phase = "proxy"
            stream = massage.massage_stream(
                provider.stream_chat(self._apply_route_role(_proxy_body(body), indic), rlog),
                body.get("model", ""),
                body.get("tools"),
                rlog,
                post=lambda c: self._translate_out(c, sk, rlog),  # lower a mid-stream-recovered write_file
            )
            yield from wrap_stream(stream, indic)
        except UpstreamError as e:
            rlog.emit("response.error", level="error", error=str(e))
            yield _error_sse(str(e))

    def _produce_completion(self, body: dict, rlog, sess_key: str):
        """Run the pipeline and return ``(chat-completion dict, Indicator|None)`` —
        the plan loop's completion, or a routed+massaged+lowered one. Raises
        ``UpstreamError`` on a model failure (callers turn that into a clean error).
        Shared by the buffered chat path and the Responses adapter."""
        server: CriaServer = self.server
        classification = self._classify(body, rlog)
        # ONE coder driver: engage the loop (a real multi-item plan OR the synthetic 1-item plan-off
        # path) whenever it should; otherwise proxy. See _engages_loop — a known session ALWAYS
        # continues (a mid-plan tool result / continuation classifies as non-task, and gating on that
        # would abandon the work: "stopped after a command"); classification only gates STARTING.
        if self._engages_loop(sess_key, classification):
            completion = server.loop.drive(body, sess_key, classification, rlog)
            if completion is not None:
                out = self._finalize(self._translate_out(completion, sess_key, rlog), sess_key, rlog)
                _report_context_usage(out, getattr(self, "_ctx_tokens", 0), rlog)
                return out, None  # loop path carries no indicator
        provider, indic = self._route(body, classification, rlog)
        rlog.phase = "proxy"
        pbody, _ = self._focus_trim(self._apply_route_role(_proxy_body(body), indic), rlog)
        raw = provider.chat(pbody, rlog)
        try:
            comp = massage.apply(json.loads(raw), body.get("tools"), rlog)
        except (json.JSONDecodeError, TypeError) as e:
            # A chat completion MUST be JSON; a non-JSON 200 (an intermediary's HTML 502 page, a
            # truncated body) is an upstream error — NOT a successful empty turn. Fail closed so the
            # caller surfaces a clean 502/failed and the client retries, instead of recording "done".
            raise UpstreamError(f"upstream returned a non-JSON 200 body: {raw[:200]!r}") from e
        if not body.get("tools"):
            # The HARNESS offered no tools (a compaction/summary, a question) — a tool-call answer
            # (native or a recovered dialect leak) is spurious. Coerce it back to text so an empty
            # or dialect-only "answer" recovers the summary from the model's reasoning.
            comp = massage.coerce_text_answer(comp, rlog)
            if _is_compaction_request(body.get("messages", [])):
                comp = _harden_compaction_reply(comp, body, provider, server, rlog)
        if massage.is_truncated(comp):
            indic.note = "⚠ output truncated at the token limit"
            rlog.emit("response.truncated")
        out = self._finalize(self._translate_out(comp, sess_key, rlog), sess_key, rlog)
        _report_context_usage(out, getattr(self, "_ctx_tokens", 0), rlog)
        return out, indic

    def _respond_buffered(self, body: dict, rlog) -> None:
        try:
            comp, indic = self._produce_completion(body, rlog, session_key(self.headers, body.get("messages", [])))
        except UpstreamError as e:
            rlog.emit("response.error", level="error", error=str(e))
            self._send_json(502, {"error": f"upstream error: {e}"})
            return
        raw = json.dumps(comp).encode("utf-8")
        if indic is not None:  # loop path has none; routed path decorates
            raw = inject_buffered(raw, indic)
        self._send_raw_json(raw)
        rlog.emit("response.sent", stream=False, bytes=len(raw))

    # -------------------------------------------------------------- responses api

    def _raw_write(self, data: bytes) -> None:
        self.wfile.write(data)
        self.wfile.flush()

    def _handle_responses(self) -> None:
        """OpenAI Responses API endpoint (what Codex 0.142.5 speaks). Translate the
        request to a chat body, run the SAME pipeline, and emit the chat completion
        as Responses SSE events."""
        log: EventLog = self.server.log
        turn = uuid.uuid4().hex[:8]
        try:
            rbody = self._read_json_body()
        except ValueError as e:
            self._send_json(400, {"error": f"invalid JSON body: {e}"})
            return
        sess = responses.session_key_of(rbody)
        rlog = log.bind(session=sess, turn=turn)
        body = responses.to_chat_body(rbody)
        sess_key = f"sid:{sess}" if sess else session_key(None, body.get("messages", []))

        # INBOUND STRIP (mirrors the chat path): remove cria's own "⟦cria⟧" indicator lines
        # from the history before anything re-reads them — the classifier, the plan's rewrite
        # summary, the model. Without it the banner leaked into the compaction summary and the
        # plan task on this (the Responses) path, which Codex speaks.
        messages = body.get("messages")
        if isinstance(messages, list):
            cleaned, stripped = strip_history(messages)
            cleaned, reframed = reframe_compaction(cleaned)  # reattribute the harness compaction turn
            if stripped or reframed:
                body["messages"] = cleaned
                if stripped:
                    rlog.emit("indicators.stripped", lines=stripped)
                if reframed:
                    rlog.emit("loop.compaction_reframed")

        # Same context-shaping as the chat path: write_file↔shell + cheat-sheet. Pass THIS path's
        # sess_key (sid:<sess>) so the fetch gate's visible-set is recorded under the SAME key the
        # outbound lowering reads — without this the exact-repeat gate is dead on the Responses path.
        self._setup_translation(body, sess_key, rlog)
        if self.server.cfg.tools.focus:
            focus_tools(body, rlog)
        if self.server.cfg.tools.cheatsheet:
            add_cheatsheet(body, rlog)

        self._ctx_tokens = _incoming_ctx_tokens(body, rlog)  # honest token accounting for the harness
        stream = bool(rbody.get("stream"))
        # Definitive tool attribution (harness-vs-us): what the harness SENT (raw inbound, pre-convert)
        # + its tool TYPES (catches a non-`function` type our converter would drop) vs what SURVIVES
        # cria's convert + focus. inbound>0 but after==0 ⇒ cria dropped them; inbound==0 ⇒ harness sent none.
        _raw_tools = rbody.get("tools") or []
        rlog.emit("request.recv", api="responses", model=body.get("model"), stream=stream,
                  n_messages=len(body.get("messages", [])),
                  inbound_tools=len(_raw_tools),
                  inbound_tool_types=sorted({(t.get("type") if isinstance(t, dict) else "?") for t in _raw_tools}),
                  tools_after=len(body.get("tools") or []))
        if stream:
            self._respond_responses_stream(body, sess_key, rlog)
        else:
            self._respond_responses_buffered(body, sess_key, rlog)

    def _respond_responses_stream(self, body: dict, sess_key: str, rlog) -> None:
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        model = body.get("model", "") or ""
        resp_id = responses._new_id("resp")
        hb = Heartbeat(self._raw_write, interval=self.server.cfg.server.heartbeat_seconds,
                       payload=responses.in_progress_event(resp_id)).start()
        self.server.register_stream(hb, resp_id)  # so a shutdown can end this stream cleanly
        try:
            hb.write(responses.created_event(resp_id, model))  # open the stream immediately
            # LIVE STATUS TICKER (operator: "for the first 7 mins there was no feedback"). A status
            # message item opens BEFORE any model work; the rlog hook streams ⟦cria⟧ phase lines into
            # it as the pipeline grinds (planner rounds, judges, compaction). Stripped inbound like
            # the banner — the coder never reads them.
            ind = self.server.cfg.indicators
            status_lines: list[str] = []
            status_id = None
            if ind.enabled and ind.status:
                added, part, status_id = responses.status_item_open()
                hb.write(added); hb.write(part)
                t0 = self.server.session_started(sess_key)
                total = lambda: time.time() - t0
                writer = statusline.StatusWriter(
                    lambda line: (status_lines.append(line),
                                  hb.write(responses.status_delta(status_id, line + "\n")))[-1],
                    total_elapsed=total)
                rlog.on_event = writer.on_event
                # The in-between: one long model call fires no events, so the beat thread ticks a
                # visible "still working" line (~every 30s) with the live phase and elapsed time.
                def _beat_tick(_elapsed: float, _sid=status_id) -> None:
                    # Live tok/s exists only for the STREAMED call (the coder): chat_watched keeps
                    # live_chars/live_t0 on the rlog while streaming and clears them on exit.
                    rate = None
                    t0 = getattr(rlog, "live_t0", None)
                    chars = getattr(rlog, "live_chars", 0)
                    if t0 is not None and chars:
                        import time as _time
                        dt = _time.monotonic() - t0
                        if dt > 1.0:
                            rate = (chars / 4) / dt   # ≈ tokens; the same chars/4 the watchers use
                    # The session total rides IN the head — "(coder ~0.5 tok/s - 1h34m) ⋯ working" —
                    # so no with_total suffix here (the per-call timer was dropped as redundant).
                    line = statusline.still_working_line(rlog.phase, total(), rate)
                    status_lines.append(line)
                    hb.write(responses.status_delta(_sid, line + "\n"))
                hb._on_beat = _beat_tick
            try:
                comp, _indic = self._produce_completion(body, rlog, sess_key)
            except UpstreamError as e:
                rlog.emit("response.error", level="error", error=str(e))
                hb.write(responses._event("response.failed",
                    {"response": {"id": resp_id, "status": "failed", "error": {"message": str(e)}}}))
                return
            finally:
                rlog.on_event = None
            extra_items = []
            start_index = 0
            if status_id is not None:
                closing, done_item = responses.status_item_close(status_id, "\n".join(status_lines))
                for ev in closing:
                    hb.write(ev)
                extra_items = [done_item]
                start_index = 1
            banner = self._compute_banner(comp, _indic, rlog)
            show_reasoning = ind.enabled and ind.reasoning
            reasoning_transcript = ind.enabled and ind.reasoning_transcript
            for chunk in responses.body_events(comp, resp_id, model, banner,
                                               show_reasoning=show_reasoning,
                                               reasoning_transcript=reasoning_transcript,
                                               start_index=start_index, extra_items=extra_items):
                hb.write(chunk)
            rlog.emit("response.sent", api="responses", stream=True, beats=hb.beats,
                      status_lines=len(status_lines))
        except (BrokenPipeError, ConnectionResetError):
            rlog.emit("response.client_gone", level="warn")
        finally:
            self.server.unregister_stream(hb)
            hb.stop()

    def _compute_banner(self, comp: dict, indic, rlog) -> str | None:
        """The ⟦cria⟧ route line for this turn, or None. Shared by the streaming and buffered
        Responses paths so both surface the same banner. Only when the turn carries visible output
        (a bare banner on an empty turn litters the TUI and reads to the harness as 'agent done')."""
        ic = self.server.cfg.indicators
        if not (ic.enabled and ic.route and _has_visible_output(comp)):  # [indicators] route
            return None
        # Show the model ACTUALLY LOADED on the server (the truth from /v1/models), never a config
        # label that may not match, and never the client picker's name (e.g. "gpt-5.5").
        loaded = self.server.upstream.loaded_model(rlog)
        if indic is not None and getattr(indic, "model", None):
            shown, role = indic.model, (indic.role or "local")
        else:  # plan-loop path carries no indicator
            shown, role = "local", "coder"
        shown = loaded or shown  # loaded model wins — the banner is the truth
        banner = f"{MARKER}{role} · {shown}"
        tps = getattr(rlog, "last_tok_per_s", None)  # this turn's model generation speed
        if ic.metrics and tps:  # [indicators] metrics — the "· N tok/s" suffix
            banner += f" · {tps:.0f} tok/s"
        return banner

    def _respond_responses_buffered(self, body: dict, sess_key: str, rlog) -> None:
        try:
            comp, _indic = self._produce_completion(body, rlog, sess_key)
        except UpstreamError as e:
            rlog.emit("response.error", level="error", error=str(e))
            self._send_json(502, {"error": f"upstream error: {e}"})
            return
        ind = self.server.cfg.indicators
        show_reasoning = ind.enabled and ind.reasoning
        reasoning_transcript = ind.enabled and ind.reasoning_transcript
        banner = self._compute_banner(comp, _indic, rlog)  # parity with the streaming path
        self._send_raw_json(json.dumps(responses.to_responses_json(
            comp, body.get("model", "") or "", show_reasoning=show_reasoning,
            reasoning_transcript=reasoning_transcript, banner=banner)).encode("utf-8"))
        rlog.emit("response.sent", api="responses", stream=False)

    def _send_raw_json(self, raw: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self._write(raw)

    # ------------------------------------------------------------------ util

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            raise ValueError("empty body")
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError("body must be a JSON object")
        return obj

    def _send_json(self, code: int, obj: dict) -> None:
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self._write(raw)

    def _write(self, raw: bytes) -> None:
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _incoming_ctx_tokens(body: dict, rlog=None) -> int:
    """Estimate the token size of the whole INCOMING request — the harness's conversation PLUS
    the tools schema (fixed per-request overhead). Reported back as usage (see
    _report_context_usage) so ANY connected harness sees honest token accounting for the context
    it sent — not the size of whichever internal cria call produced a given completion. Purely
    accounting/observability: cria guarantees the request fits the model window itself, in the
    context floor (`contextfloor.fit`, applied at the upstream call), so overflow no longer
    depends on the harness reacting to this number. Logs the msg-vs-tools breakdown."""
    msg = 0
    for m in body.get("messages") or []:
        c = m.get("content")
        if isinstance(c, str):
            msg += est_tokens(c)
        elif isinstance(c, list):
            for p in c:
                if isinstance(p, dict):
                    msg += est_tokens(p.get("text") or "")
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            msg += est_tokens((fn.get("name") or "") + str(fn.get("arguments") or ""))
    tools_list = body.get("tools") or []
    tools = est_tokens(json.dumps(tools_list))
    if rlog is not None:
        top = sorted(
            ((est_tokens(json.dumps(t)), (t.get("function") or {}).get("name") or t.get("name") or "?") for t in tools_list),
            reverse=True,
        )[:8]
        rlog.emit("ctx.estimate", msg_tokens=msg, tools_tokens=tools, total=msg + tools,
                  n_tools=len(tools_list), top_tools=[f"{n}={s}" for s, n in top])
    return msg + tools


def _report_context_usage(completion: dict, ctx_tokens: int, rlog) -> None:
    """Report honest token accounting to whatever harness is connected: set input_tokens to the
    size of the context IT sent (ctx_tokens), not whichever internal cria call produced this
    completion. Harness-agnostic — a truthful gauge for any client's display/limits. cria does
    NOT rely on the harness acting on it; the context floor keeps the request under the window."""
    if ctx_tokens <= 0:
        return
    u = completion.get("usage") or {}
    out = u.get("completion_tokens") or 0
    completion["usage"] = {"prompt_tokens": ctx_tokens, "completion_tokens": out,
                           "total_tokens": ctx_tokens + out}
    rlog.emit("usage.context_reported", input_tokens=ctx_tokens, output_tokens=out)
