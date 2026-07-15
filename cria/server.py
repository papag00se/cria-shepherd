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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import focustrim, massage, prompts, responses, rumination
from .classify import Classifier
from .content_reduce import est_tokens
from .config import Config
from .envfile import env_secret
from .events import EventLog
from .heartbeat import Heartbeat
from .indicators import MARKER, Indicator, inject_buffered, strip_history, strip_note_lines, wrap_stream
from .loop import (
    GuardStore,
    Loop,
    _add_note,
    _clean_completion,
    _strip_completion_banners,
    _strip_cria_file_ops,
    LoopContext,
    LoopStore,
    _clip_tail,
    _completion_final,
    _completion_text,
    _completion_toolcalls,
    _has_tool_calls,
    _history_root,
    _read_tool_result,
    _stable_session,
    completion_to_sse,
    reframe_compaction,
    guard_gate_op,
    guard_gate_verdict,
    guard_intervene,
    guard_probe_reissue,
    guard_probe_steer,
    guard_rumination,
    guard_track_repetition,
    guard_track_write_streak,
    guard_truncation,
    reframe_preamble,
    session_key,
)
from .planner import Planner
from .routing import Router
from .toolmenu import add_cheatsheet, cheatsheet, focus_tools
from .turnstats import StatsStore
from .upstream import Upstream, UpstreamError
from .writeproxy import advertise, native_search_name, needs_translation, represent_inbound, translate_outbound


def _error_sse(message: str) -> bytes:
    """Convey an error inside an already-open SSE stream (headers are 200 by then)."""
    payload = {"error": {"message": message, "type": "upstream_error"}}
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\ndata: [DONE]\n\n"


def _warn_config(cfg: Config, has_reasoner: bool, has_coder: bool, log) -> None:
    """One-time startup sanity: warn when a configured-looking feature CAN'T actually run, so a
    misconfiguration is visible instead of silently degrading — the class that hid the Brave-key
    bug (web_search just quietly never ran; the planner was quietly a passthrough)."""
    if cfg.planner.enabled and not (has_reasoner and has_coder):
        missing = [r for r, ok in (("reasoner", has_reasoner), ("coder", has_coder)) if not ok]
        log.emit("config.warn", level="warn", issue="planner_inert",
                 detail=f"[planner] enabled but missing role(s): {', '.join(missing)} — the plan loop will not run")
    if cfg.planner.search_api_key_env and not env_secret(cfg.planner.search_api_key_env):
        log.emit("config.warn", level="warn", issue="web_search_disabled",
                 detail=f"web_search configured (search_api_key_env={cfg.planner.search_api_key_env}) "
                        "but that env var is empty in the process — search disabled (is env_file set and loaded?)")


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


def _direct_coder_body(body: dict) -> dict:
    """Planner-bypass framing ([planner] enabled = false): drop the harness system prompt and LEAD
    with cria's own coder system prompt (prompts/coder_system.txt) — the SAME guidance the plan
    loop gives the coder, minus the plan. So turning planning off is a fair 'coder without a
    planner' (like codex-local drives it), not a bare passthrough with no coding-agent framing."""
    # Strip cria's own artifacts from the REPLAYED history (its ⟦cria⟧ banners + any historical
    # `.cria/` writes) before reframing — same scrub the loop's _frame_for_item does — so a
    # resumed/compacted plan-off conversation can't feed them to the coder to imitate.
    src = _strip_cria_file_ops(body.get("messages") or [])
    msgs = [reframe_preamble(m) for m in src if m.get("role") not in ("system", "developer")]
    # Carry the menu-derived tool hint into cria's OWN system message: add_cheatsheet folded it
    # into the harness system message during prep, which we just dropped — so the coder would
    # otherwise get no tool guidance and the prompt could name tools not in the menu.
    hint = cheatsheet(body.get("tools"))
    system = prompts.load("coder_system") + (f"\n\n{hint}" if hint else "")
    return {**body, "messages": [{"role": "system", "content": system}] + msgs}


class CriaServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cfg: Config, log: EventLog, upstream: Upstream) -> None:
        self.cfg = cfg
        self.log = log
        self.upstream = upstream
        # Routing engages only when configured. With no [models.local]/[failover],
        # cria is a plain phase-1 passthrough.
        roles = cfg.routing.local_roles  # per-role sampling + reasoning (cria.toml); NO model alias —
        # the wire model is always the server's loaded model. A role is "configured" by the PRESENCE
        # of its [models.local.<role>] table, so every gate below keys on membership in `roles`.
        self.classifier = (
            Classifier(upstream, cfg.routing.engagement_bias, role=roles.get("classifier"))
            if "classifier" in roles
            else None
        )
        self.router = (
            Router(cfg.routing, upstream, timeout=cfg.upstream.timeout_seconds)
            if (roles or cfg.routing.failover)
            else None
        )
        # The plan-driven loop (phase 6) — active when a reasoner AND a coder role are configured
        # and the planner is enabled. It owns the planner and drives a coding task item by item.
        # Without it, cria is a smart proxy.
        has_reasoner = "reasoner" in roles
        has_coder = "coder" in roles
        # The coder role's sampling/reserve — needed for the rumination budget on BOTH the loop
        # and the plan-off proxy path (the guards are not gated behind the planner).
        self.coder_role = roles.get("coder")
        # Per-session repetition/wheel-spin guard state for the plan-off path (the loop keeps its
        # own in PlanSession). Same shared guard implementation drives both.
        self.guard_store = GuardStore()
        # Per-session end-of-turn stats (calls, tok/s, guard fires, wall time).
        self.stats_store = StatsStore()
        # In-flight streaming responses (Heartbeat -> resp_id), so a shutdown can END each one with a
        # clean, RETRYABLE terminal event instead of the bare mid-stream EOF that wedges the client.
        self.active_streams: dict = {}
        self._streams_lock = threading.Lock()
        # Conversation-shape store for HARNESS-COMPACTION detection — shared by BOTH paths. It lives
        # OUTSIDE the planner gate: the plan-off/proxy path (the user's path) equally needs to notice
        # when the harness replaced the history and re-anchor the coder, or it treats its own prior
        # work as a stranger's and duplicates files. Within one process the planner is globally on or
        # off, so a session is only ever driven by the loop OR by plan-off — never both — so one store
        # serves both with no contention. When the loop is built it uses this same instance.
        self.loop_store = LoopStore(state_path=os.path.join(cfg.logging.dir, "loopstate.json"))
        self.loop = None
        # Surface a misconfigured-looking feature at startup instead of silently degrading — the
        # class of failure that hid the Brave-key bug (web_search just quietly never ran).
        _warn_config(cfg, has_reasoner, has_coder, log)
        if cfg.planner.enabled and has_reasoner and has_coder:
            # The web-search key comes from its env var (never stored in config); env_secret reads
            # it normalized (CRLF-safe) — the CRLF was the illegal-header footgun, fixed once at the
            # source (envfile) rather than stripped per-consumer.
            search_key = env_secret(cfg.planner.search_api_key_env) or ""
            # The coder runs on the STREAMING-guarded path so its reasoning is watched live: a
            # runaway thinking loop is aborted mid-flight (rumination detector) instead of burning
            # the window to an empty turn / truncation. Budget seeded from the coder's output_reserve.
            coder_role = self.coder_role
            detector = rumination.Detector.from_reasoning_budget(
                coder_role.output_reserve if coder_role else None)

            def coder_chat(body, rlog, _up=upstream, _det=detector):
                return _up.chat_watched(body, rlog, watch=_det.check)

            self.loop = Loop(
                LoopContext(
                    planner=Planner(upstream, role=roles.get("reasoner"),
                                    search_key=search_key, max_gather_rounds=cfg.planner.max_gather_rounds),
                    coder_chat=coder_chat,
                    reasoner_chat=upstream.chat,
                    coder_role=coder_role,
                    reasoner_role=roles.get("reasoner"),
                    # ONE folder per run: plan mirror + verify dumps join the call captures
                    # under <capture_dir>/<session>/ — a single place per session.
                    runs_dir=cfg.logging.capture_dir,
                    focus_trim=cfg.context.focus_trim,
                ),
                # The SAME store the plan-off path uses (created above). Completed-work briefings +
                # session shapes survive a cria restart (the restarts this project makes constantly
                # were wiping the context a follow-up / a post-compaction continuation needs). Live
                # plans are NOT persisted — see LoopStore.
                self.loop_store,
            )
        super().__init__((cfg.server.host, cfg.server.port), CriaHandler)

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
        path = self.path.rstrip("/")
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
        self._setup_translation(body, rlog)

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
        stats.observe(completion, getattr(rlog, "last_tok_per_s", None))
        completion = self._decorate(completion)
        tool_turn = any((ch.get("message") or {}).get("tool_calls") for ch in completion.get("choices", []))
        if not tool_turn and stats.calls >= 2:  # a text answer after real work → the turn ended
            if ic.enabled and ic.stats and _has_visible_output(completion):
                _append_content_line(completion, stats.summary())
            self.server.stats_store.reset(sess_key)
        return completion

    def _setup_translation(self, body: dict, rlog) -> None:
        """Set up the synthetic-tool ↔ shell round-trip for this request: STATELESSLY re-present prior
        shell translations as the tool the model called (from the sentinel in history), then advertise
        cria's synthetic tools. Records what to lower outbound (self._synthetic), the harness's search
        backend to route web_search to (self._native_search — read BEFORE advertise renames it), and
        the Brave key for a synthesized web_search."""
        self._shell_tool = needs_translation(body.get("tools"))
        self._synthetic: set[str] = set()
        self._native_search = None
        self._brave_key = env_secret(self.server.cfg.planner.search_api_key_env)
        if self._shell_tool is not None:
            self._native_search = native_search_name(body.get("tools"))
            body["messages"] = represent_inbound(body.get("messages", []), rlog)
            self._synthetic = advertise(body, rlog, brave_key=self._brave_key)

    def _translate_out(self, completion: dict, rlog) -> dict:
        """Lower the model's synthetic-tool calls to shell, when translation is active for this
        request. Set up in `_setup_translation`."""
        if self._shell_tool is not None:
            translate_outbound(completion, self._shell_tool, rlog, injected=getattr(self, "_synthetic", set()),
                               brave_key=getattr(self, "_brave_key", None),
                               native_search=getattr(self, "_native_search", None))
        return completion

    def _guarded_coder_chat(self, provider):
        """A coder call carrying the loop's in-flight rumination watch (a fresh detector per
        request, budgeted from the coder role's output_reserve) and returning a buffered
        completion — so the plan-off direct-coder path runs the SAME guard as the loop. A
        provider without watching (a cloud provider) falls back to a plain buffered chat."""
        coder_role = self.server.coder_role
        detector = rumination.Detector.from_reasoning_budget(
            coder_role.output_reserve if coder_role else None)
        watched = getattr(provider, "chat_watched", None)
        if watched is None:
            return provider.chat
        return lambda body, rlog: watched(body, rlog, watch=detector.check)

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

    def _run_coder(self, framed: dict, coder_chat, gs, rlog):
        """One guarded + cleaned coder call on the plan-off path (shared by the main turn and the
        LEG0 re-call): call → rumination + truncation guards → hygiene → repetition/wheel-spin
        tracking if it acted. Returns the completion, or None on a decode failure."""
        try:
            comp = massage.apply(json.loads(coder_chat(framed, rlog)), framed.get("tools"), rlog)
        except (json.JSONDecodeError, TypeError):
            return None
        comp = guard_rumination(comp, framed, coder_chat, rlog, phase="direct-coder")
        comp = guard_truncation(comp, framed, coder_chat, rlog, phase="direct-coder")
        _strip_completion_banners(comp)
        if self.server.coder_role is not None:
            _clean_completion(comp, self.server.coder_role)
        if _has_tool_calls(comp):
            guard_track_repetition(gs, comp, rlog)
            guard_track_write_streak(gs, comp, rlog)
        return comp

    def _detect_rewrite(self, sess_key: str, body: dict, rlog) -> bool:
        """Harness-compaction detection on the plan-off path — the SAME structural signal the loop
        uses (a changed conversation root under a stable session key = the history was replaced), via
        the SAME shared LoopStore. No phrase-matching. Records this turn's shape every call so a later
        rewrite is caught; returns True on the first turn after a rewrite (sticky until cleared)."""
        store = self.server.loop_store
        if store is None or not _stable_session(sess_key):
            return False  # only content-independent (sid:) keys can detect this — see the loop
        msgs = body.get("messages", [])
        _root_text, fp = _history_root(msgs)
        rewritten = store.observe_shape(sess_key, fp, len(msgs))
        if rewritten:
            rlog.emit("loop.history_rewritten", plan_off=True, n_messages=len(msgs))
        return rewritten

    def _drive_direct_coder(self, gs, provider, indic, body: dict, sess_key: str, rlog):
        """The plan-off direct-coder turn with the SAME protections the loop gives its coder: the
        repetition/wheel-spin guard (probe → steer), the completion gate on a bare 'done' (verify
        against the repo's checks before ending the turn), harness-compaction re-anchoring, and
        per-turn hygiene. Cross-turn state lives in the per-session GuardState + the shared shape
        store. Returns the completion to send, or None on decode fail."""
        coder_chat = self._guarded_coder_chat(provider)
        rewritten = self._detect_rewrite(sess_key, body, rlog)
        # A probe whose result a harness compaction erased is re-issued (parity with the loop),
        # rather than fail-open / downgrade to a canned steer with no ground truth.
        reissue = guard_probe_reissue(gs, body, rlog, rewritten=rewritten)
        if reissue is not None:
            return reissue
        # A completion-gate probe we emitted last turn (to verify a 'done') has now run.
        if gs.done_probe:
            gs.done_probe = False
            errors = guard_gate_verdict(gs, body, rlog)
            if not errors:  # checks passed → the 'done' is genuine; forward the held answer
                rlog.emit("loop.gate", plan_off=True, blocked=False)
                held, gs.pending_done, gs.leg0_nudged = gs.pending_done, "", False
                return _completion_final(held or "Done.")
            rlog.emit("loop.gate", plan_off=True, blocked=True)  # checks failed → steer to fix
            gs.nudge_reason = prompts.render("gate_fail_steer", errors=_clip_tail(errors, 1800))
            gs.steer_source = "completion gate (repo checks failed)"
        # A guard probe (repetition/wheel-spin) result, or a fresh detection this turn.
        steer, intervention = None, None
        if gs.awaiting_probe:
            gs.awaiting_probe = False
            steer = guard_probe_steer(gs, body, rlog)  # canned (no reasoner on plan-off)
        elif not gs.nudge_reason:  # (a gate-fail steer is already parked — don't double-intervene)
            intervention = guard_intervene(gs, body, rlog)
        if intervention is not None:
            return intervention
        if steer is None and gs.nudge_reason:
            steer, gs.nudge_reason = gs.nudge_reason, ""
        framed = _direct_coder_body(body)
        extra = []
        if rewritten:  # first turn after a harness compaction → re-orient the coder (the seed fix)
            extra.append({"role": "user", "content": prompts.render("nudge", reason=prompts.load("reanchor"))})
            self.server.loop_store.clear_rewrite(sess_key)  # acted on it (framing rebuilt each turn)
        if steer:  # inject the steer into the coder framing this turn
            extra.append({"role": "user", "content": prompts.render("nudge", reason=steer)})
        if extra:
            framed = {**framed, "messages": framed["messages"] + extra}
        framed = self._apply_route_role(framed, indic)
        framed, _ = self._focus_trim(framed, rlog)  # focus the OUTBOUND view (logged, not bannered —
        comp = self._run_coder(framed, coder_chat, gs, rlog)  # routine housekeeping, not an intervention)
        if comp is None:
            return None
        if rewritten:  # no hidden guards: surface that cria re-anchored the turn
            _add_note(comp, "re-anchored after a harness compaction")
        if steer:  # no hidden guards: surface WHICH guard steered the coder (not just "a guard")
            _add_note(comp, f"steered the coder — {gs.steer_source or 'guard'}")
            gs.steer_source = ""
        if _has_tool_calls(comp):
            return comp  # acting → forward
        return self._gate_direct_done(gs, comp, framed, body, coder_chat, rlog)

    def _gate_direct_done(self, gs, comp, framed: dict, body: dict, coder_chat, rlog):
        """The coder answered with NO tool call (thinks it's done). Verify before ending the turn:
        LEG0 (never acted this session → one act-first nudge, re-call once), then the OBJECTIVE
        completion gate (run the repo's checks; on failure the next turn steers, on pass the 'done'
        is forwarded). The same protection the loop's LEG0 + gate give — no false 'done, tests pass'.
        NOTE: the gate reads cwd from the ORIGINAL body (reframe_preamble stripped the <cwd> tags
        from `framed`)."""
        if gs.action_seq == 0 and not gs.leg0_nudged:  # the session never acted at all
            gs.leg0_nudged = True
            rlog.emit("loop.step_incomplete", plan_off=True, reason="no tools used")
            conv = framed["messages"] + [{"role": "user", "content": prompts.render("nudge", reason=prompts.load("leg0_nudge"))}]
            recall = self._run_coder({**framed, "messages": conv}, coder_chat, gs, rlog)
            if recall is not None:
                comp = recall
                if _has_tool_calls(comp):
                    return comp  # it acted after the nudge
        probe = guard_gate_op(gs, body, rlog)  # body, NOT framed — reframe stripped the <cwd> tags
        if probe is not None:
            gs.done_probe = True
            gs.probe_call_id = probe["id"]
            gs.pending_done = _completion_text(comp)
            rlog.emit("loop.completion_probe", plan_off=True)
            return _completion_toolcalls([probe], note="verifying — running the repo's checks")
        return comp  # no shell tool → can't gate; forward the 'done' as-is

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

        if server.router is None or classification is None:
            return passthrough()
        route = server.router.route(classification.task_type, rlog)
        if route is None:
            return passthrough()
        if route.model:  # None = the role omitted its alias → leave the request's model; the
            body["model"] = route.model  # upstream fills the server's loaded model in _prep
        # Show the "which model" line only when the classification is fresh (first
        # turn of a task); on cached turns just the tok/s line, to avoid repeating it.
        return route.provider, Indicator(
            ic.enabled, ic.metrics,
            model=banner_model(route.provider, route.model or str(body.get("model") or "?")), role=route.role,
            show_route=not classification.cached, route=ic.route, assists=ic.assists,
        )

    def _apply_route_role(self, pbody: dict, indic) -> dict:
        """Attach the routed local role's sampling + reasoning (temp/top_p/top_k/repeat_penalty/
        enable_thinking) to a proxy-path body, in place. WITHOUT this a local model on the proxy
        path runs on llama.cpp's defaults — no repeat_penalty (gemma4 then leaks
        `<|tool_call>`/`<|channel>` tokens), wrong temperature, no reasoning toggle — i.e. NOT the
        model the toml configures. The plan loop applies the role per call (loop.py); the proxy and
        direct-coder paths must do the same, or the same model behaves like a different one."""
        role = self.server.cfg.routing.local_roles.get(indic.role) if getattr(indic, "role", None) else None
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
            # Drive the loop when the loop KNOWS this session (a live plan to continue; a completed
            # briefing / recorded shape, so a post-compaction rewrite is detected structurally) OR
            # when a fresh turn is a task. Classification gates only STARTING a fresh plan.
            if server.loop is not None and (server.loop.knows_session(sk) or (classification is not None and classification.engagement == "task")):
                completion = server.loop.drive(body, sk, classification, rlog)
                if completion is not None:
                    yield from completion_to_sse(self._finalize(self._translate_out(completion, rlog), sk, rlog))
                    return
            provider, indic = self._route(body, classification, rlog)
            rlog.phase = "proxy"
            stream = massage.massage_stream(
                provider.stream_chat(self._apply_route_role(_proxy_body(body), indic), rlog),
                body.get("model", ""),
                body.get("tools"),
                rlog,
                post=lambda c: self._translate_out(c, rlog),  # lower a mid-stream-recovered write_file
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
        # Route through the loop when it KNOWS this session (live plan → continue regardless of the
        # turn's classification; completed/shaped → structural compaction-rewrite detection) or when
        # a fresh turn is a task. Classification only gates STARTING a fresh plan. See
        # Loop.knows_session — without this the loop is abandoned mid-plan ("stopped after a command")
        # or a post-compaction continuation is proxied blind.
        if server.loop is not None and (server.loop.knows_session(sess_key) or (classification is not None and classification.engagement == "task")):
            completion = server.loop.drive(body, sess_key, classification, rlog)
            if completion is not None:
                out = self._finalize(self._translate_out(completion, rlog), sess_key, rlog)
                _report_context_usage(out, getattr(self, "_ctx_tokens", 0), rlog)
                return out, None  # loop path carries no indicator
        provider, indic = self._route(body, classification, rlog)
        rlog.phase = "proxy"
        # Planner OFF ([planner] enabled = false) + a coding task → frame the coder directly (its
        # own system prompt, no plan) AND run it through the SAME guards the loop uses (rumination
        # + truncation). Plan-off means NO PLAN, not NO PROTECTION — the guards are not gated behind
        # the planner. A small model left to relay bare is exactly what runs away / thrashes.
        direct = (not server.cfg.planner.enabled and classification is not None
                  and classification.task_type == "coding")
        if direct:
            rlog.emit("route.direct_coder")
            comp = self._drive_direct_coder(server.guard_store.get(sess_key), provider, indic, body, sess_key, rlog)
            if comp is None:
                return {}, indic
        else:
            pbody, _ = self._focus_trim(self._apply_route_role(_proxy_body(body), indic), rlog)
            raw = provider.chat(pbody, rlog)
            try:
                comp = massage.apply(json.loads(raw), body.get("tools"), rlog)
            except (json.JSONDecodeError, TypeError):
                return {}, indic
        if not body.get("tools"):
            # The HARNESS offered no tools (a compaction/summary, a question) — a tool-call answer
            # (native or a recovered dialect leak) is spurious. Coerce it back to text so an empty
            # or dialect-only "answer" recovers the summary from the model's reasoning.
            comp = massage.coerce_text_answer(comp, rlog)
        if massage.is_truncated(comp):
            indic.note = "⚠ output truncated at the token limit"
            rlog.emit("response.truncated")
        out = self._finalize(self._translate_out(comp, rlog), sess_key, rlog)
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

        # Same context-shaping as the chat path: write_file↔shell + cheat-sheet.
        self._setup_translation(body, rlog)
        if self.server.cfg.tools.focus:
            focus_tools(body, rlog)
        if self.server.cfg.tools.cheatsheet:
            add_cheatsheet(body, rlog)

        self._ctx_tokens = _incoming_ctx_tokens(body, rlog)  # honest token accounting for the harness
        stream = bool(rbody.get("stream"))
        rlog.emit("request.recv", api="responses", model=body.get("model"), stream=stream,
                  n_messages=len(body.get("messages", [])), has_tools=bool(body.get("tools")))
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
        hb = Heartbeat(self._raw_write, interval=self.server.cfg.server.heartbeat_seconds).start()
        self.server.register_stream(hb, resp_id)  # so a shutdown can end this stream cleanly
        try:
            hb.write(responses.created_event(resp_id, model))  # open the stream immediately
            try:
                comp, _indic = self._produce_completion(body, rlog, sess_key)
            except UpstreamError as e:
                rlog.emit("response.error", level="error", error=str(e))
                hb.write(responses._event("response.failed",
                    {"response": {"id": resp_id, "status": "failed", "error": {"message": str(e)}}}))
                return
            banner = self._compute_banner(comp, _indic, rlog)
            ind = self.server.cfg.indicators
            show_reasoning = ind.enabled and ind.reasoning
            reasoning_transcript = ind.enabled and ind.reasoning_transcript
            for chunk in responses.body_events(comp, resp_id, model, banner,
                                               show_reasoning=show_reasoning,
                                               reasoning_transcript=reasoning_transcript):
                hb.write(chunk)
            rlog.emit("response.sent", api="responses", stream=True, beats=hb.beats)
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
