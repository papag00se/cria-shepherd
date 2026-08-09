"""Upstream client — cria → the OpenAI-compatible model server (llama.cpp today).

Phase 1 is a faithful passthrough: the request body is forwarded verbatim (the
harness's own ``model``, messages, and sampling params) and the response streamed
back unchanged. The only thing cria adds here is *measurement* — time-to-first-
token and tokens/sec — emitted as events so the box's real throughput per turn is
visible (prefill/first-token is the known bottleneck on the shared GPU).

Stdlib only: ``urllib.request`` for the POST, iterating the response line-by-line
to forward Server-Sent Events as they arrive.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

from . import callcapture, contextfloor, failover, massage, rumination, tokenratio

# Sentinel for "window not yet resolved" (distinct from None = "no window / skip floor").
_UNSET = object()
# When the local server's /props can't be read, apply the floor against this conservative
# window rather than DISABLING it — under-guessing over-trims (safe), over-guessing overflows
# (the failure the floor exists to prevent). Retry /props up to _MAX_PROPS_ATTEMPTS times first,
# so a transient miss (GPU busy on the shared box) self-heals before we commit to the fallback.
_FALLBACK_WINDOW = 8192
_MAX_PROPS_ATTEMPTS = 3
# …then back OFF to one probe every N calls. The budget exists so a dead /props doesn't cost a probe
# per call — it is NOT a verdict. Committing the 8192 fallback for the life of the process against a
# 49,152-token model trims ~83% of the real window away, silently and permanently, and the trigger is
# as ordinary as cria restarting while llama.cpp is still loading its model.
_PROPS_RETRY_EVERY = 50
# Fail-fast budget for the debug-only /apply-template render (shares the single inference slot).
_RENDER_TIMEOUT_S = 8
# Re-run the reasoning watcher (rumination check) only after this many new chars of reasoning, so
# the regex isn't recompiled-scanned on every tiny SSE delta. codex-local checks ~every 500 bytes.
_WATCH_STRIDE = 400


class UpstreamError(Exception):
    """The upstream model server could not be reached or errored."""


class Upstream:
    """An OpenAI-compatible chat endpoint. With no ``api_key`` this is the local
    llama.cpp; with one it is an OpenAI-compatible *cloud* provider (Bearer auth) —
    the same wire protocol, so one client serves both roles."""

    def __init__(self, base_url: str, timeout_seconds: int = 600, api_key: str | None = None,
                 context_window: int | None = None, capture_dir=None, capture_rendered: bool = True) -> None:
        self._base_url = base_url.rstrip("/")
        self._chat_url = self._base_url + "/v1/chat/completions"
        self._timeout = timeout_seconds
        self._api_key = api_key
        # When set, capture the EXACT body of every model call to a file here (opt-in).
        self._capture_dir = capture_dir
        # Also capture the rendered prompt (chat template applied) — only for a local server
        # (cloud has no /apply-template). The true string the model tokenizes.
        self._capture_rendered = capture_rendered and api_key is None
        # The context floor's window. A configured value wins; otherwise it is DISCOVERED
        # from the local server's /props (n_ctx of the loaded model) — a property of the
        # model, not a constant to hand-maintain. None (cloud / undiscoverable) skips the
        # floor: cloud windows are large and /props doesn't exist there.
        # The model id ACTUALLY loaded at this server (llama.cpp /v1/models → its --alias),
        # discovered once. cria sends a model NAME but llama serves whatever it has loaded (loose
        # match), so a wrong alias in the config silently runs the WRONG model — this lets cria
        # compare and warn. None for a cloud endpoint (no single loaded model).
        self._loaded_model = None if api_key else _UNSET
        self._props: dict | None = None   # last successful /props payload — the compat banner's
        self._props_seen = False          # source (chat_template + chat_template_caps)
        self._window = context_window if context_window else _UNSET
        self._window_final = bool(context_window)  # a configured value is authoritative — no probe
        self._props_attempts = 0
        if self._api_key and context_window is None:
            self._window = None       # cloud provider, no override → no floor
            self._window_final = True  # …and never probe /props on a cloud endpoint

    @property
    def chat_url(self) -> str:
        return self._chat_url

    def _headers(self, *, sse: bool) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if sse:
            h["Accept"] = "text/event-stream"
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def loaded_model(self, rlog) -> str | None:
        """The model id ACTUALLY loaded at this local server — llama.cpp's /v1/models returns its
        ``--alias``. Discovered once and cached, so cria's banner can show the TRUTH (what's really
        answering) rather than a config label that may not match. None for a cloud endpoint (no
        single loaded model) or when /v1/models can't be read. A model swap needs a cria restart to
        refresh (the same workflow as the fleet swap)."""
        if self._loaded_model is not _UNSET:
            return self._loaded_model
        self._loaded_model = None
        try:
            req = urllib.request.Request(self._base_url + "/v1/models", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            models = data.get("data") if isinstance(data, dict) else None
            if models and isinstance(models[0], dict):
                self._loaded_model = models[0].get("id") or None
        except (urllib.error.URLError, ValueError, KeyError, OSError, IndexError, TypeError) as e:
            rlog.emit("upstream.models", level="info", error=str(e))
        return self._loaded_model

    def props(self, rlog) -> dict | None:
        """The local server's ``/props`` payload — chat template + capability flags — fetched at
        most once and cached. ``None`` for a cloud endpoint or when it can't be read.

        Separate from :meth:`_resolve_window` on purpose, even though that method populates the same
        cache for free on its own probe. The window has an authoritative-config shortcut
        (``context_window`` in the toml → ``_window_final`` → no probe ever), so a banner that piggy-
        backed on it would silently vanish the day someone pinned a window — one mechanism quietly
        disabled by an unrelated setting. This asks for what it needs.

        ONE attempt, no retry budget: the compat banner is decoration, and a decoration that costs a
        probe per call on a sick endpoint is worse than no decoration (#3)."""
        if self._props_seen or self._api_key:
            return self._props
        self._props_seen = True          # attempted — never probe twice for the banner
        try:
            req = urllib.request.Request(self._base_url + "/props", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self._props = json.loads(resp.read())
        except (urllib.error.URLError, ValueError, OSError) as e:
            rlog.emit("compat.props", level="info", error=str(e))
        return self._props

    def _resolve_window(self, rlog) -> int | None:
        """The loaded model's context window (n_ctx), discovered from the local server's /props.
        A configured value or a cloud endpoint is authoritative (no probe). On a LOCAL endpoint
        whose /props can't be read, fall back to a conservative default so the floor STILL runs —
        a transient miss (GPU busy) must NEVER silently disable the fit guarantee for the life of
        the process — and keep retrying on later calls until the attempt budget is spent."""
        if self._window_final:
            return self._window
        self._props_attempts += 1
        if self._props_attempts > _MAX_PROPS_ATTEMPTS and self._props_attempts % _PROPS_RETRY_EVERY:
            return self._window          # backed off: the committed fallback, without a probe
        try:
            req = urllib.request.Request(self._base_url + "/props", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                props = json.loads(resp.read())
            self._props, self._props_seen = props, True   # the compat banner reads this — no 2nd probe
            n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
            if isinstance(n_ctx, int) and n_ctx > 0:
                self._window = n_ctx
                self._window_final = True
                rlog.emit("context.window", source="props", n_ctx=n_ctx)
                return self._window
            rlog.emit("context.window", level="info", source="props", error="no n_ctx in /props")
        except (urllib.error.URLError, ValueError, KeyError, OSError) as e:
            rlog.emit("context.window", level="info", source="props", error=str(e))
        # Discovery missed this attempt: keep the floor ALIVE on a safe fallback (never cache
        # None = "no floor"), and retry next call until the attempt budget commits the fallback.
        self._window = _FALLBACK_WINDOW
        if self._props_attempts == _MAX_PROPS_ATTEMPTS:
            rlog.emit("context.window", level="warning", source="fallback", n_ctx=_FALLBACK_WINDOW,
                      retry_every=_PROPS_RETRY_EVERY)
        return self._window

    def _prep(self, body: dict, stream: bool, rlog, safety_override: float | None = None) -> tuple[bytes, int, str | None]:
        """Serialize the request and return ``(bytes, sent_estimate)``: apply the CONTEXT FLOOR
        (guarantee it fits the window, budgeting with the model's LEARNED density ratio), force the
        stream flag, and MERGE adjacent assistant messages. Codex splits one assistant turn into a
        text item + a function_call item → two adjacent assistant messages; strict templates
        (Fabliq) reject a list ending in 2+ assistant messages. Merge them → the single-turn form.
        ``sent_estimate`` is the chars/4 estimate of what's actually sent, for density calibration.

        ``safety_override`` forces the floor's density factor (used by the overflow refit-retry: the
        server just told us this exact body's real token count, so re-fit against THAT truth rather
        than the per-model average, which lags a single outlier-density request)."""
        if not body.get("model"):
            # A role omitted its `model` alias (the single-loaded-model posture) — fill it from
            # whatever the server reports loaded. Mutate `body` (not just `out`) so the surrounding
            # chat/stream reads (logging, density calibration, the echoed completion model) agree.
            loaded = self.loaded_model(rlog)
            if loaded:
                body["model"] = loaded
        out = {**body, "stream": stream}
        msgs = body.get("messages")
        if isinstance(msgs, list):
            window = self._resolve_window(rlog)
            if window:
                reserve = contextfloor.reserve_for(body)  # reads cria_output_reserve (stripped below)
                tools_in = body.get("tools")
                safety = safety_override if safety_override is not None else tokenratio.observed(body.get("model"))
                msgs, tools, rep = contextfloor.fit(msgs, tools_in, window=window, reserve=reserve, safety=safety)
                if rep.applied or rep.over_budget:
                    lvl = "warning" if rep.over_budget else "info"
                    rlog.emit("context.floor", level=lvl, safety=round(safety, 2), **rep.as_event())
                if rep.tools_compressed and tools is not None:
                    out["tools"] = tools  # send the bounded tool schema, not the fat original
            # A malformed tool_call in the REPLAYED history (a weak model's over-escaped nested-quote
            # shell command) makes a strict template's JSON re-parse 500 on EVERY turn — poisoning the
            # whole session, not just the turn that produced it. Repair the history's args before send.
            msgs = massage.repair_history_tool_args(msgs, rlog)
            # UNCONDITIONAL tool-integrity: an orphan `tool` (its assistant call folded by self-compaction,
            # or dropped) 400s a strict template EVERY turn — and the floor's orphan strip runs only when
            # the request is OVER budget, so a fitting request ships the orphan. Convert it to `user` here,
            # on every request, so no orphan ever reaches the model.
            msgs, deorphaned = contextfloor.ensure_tool_integrity(msgs)
            if deorphaned:
                rlog.emit("context.deorphaned", count=deorphaned, level="info")
            msgs = _merge_consecutive_assistant(msgs)
            # THE LAST message transform, and last is the point. A template that enforces strict
            # user/assistant alternation ({user,tool} vs {assistant}) rejects the body outright, and
            # the merge that satisfies it used to run in `Role.apply` — mid-pipeline, where every
            # later append undid it (focustrim's repeat-note, a rumination/truncation retry turn).
            # nemotron-nano run 1786243834 died that way: six `Conversation roles must alternate`
            # 400s, calls 0075-0081, empty workspace. Here nothing comes after, so no call site can
            # defeat it — the same reasoning that put the orphan-`tool` repair above at the wire.
            # Opt-in per role (`merge_consecutive_turns`); without the hint this is identity, so
            # every model that does not need it ships a byte-identical body.
            if body.get(massage.MERGE_TURNS_KEY):
                msgs = massage.merge_for_alternation(msgs)
            out["messages"] = msgs
        out.pop("cria_output_reserve", None)  # cria-internal reserve hint — never goes on the wire
        out.pop(massage.MERGE_TURNS_KEY, None)  # ditto — the alternation hint is cria's, not the API's
        sent_estimate = contextfloor.est_total(out.get("messages"), out.get("tools"))
        capture_path = None
        if self._capture_dir is not None:  # record EXACTLY what the model will see, per call
            rendered = self._render_prompt(out) if self._capture_rendered else None
            capture_path = callcapture.capture(out, rlog, calls_dir=self._capture_dir,
                                               phase=getattr(rlog, "phase", None), url=self._chat_url, rendered=rendered)
        return json.dumps(out).encode("utf-8"), sent_estimate, capture_path

    def _calibrate(self, model, prompt_tokens, estimate: int, rlog) -> None:
        """Learn the real÷estimate density from a call's REAL prompt-token count (server usage), so
        the floor budgets against truth on later turns. Best-effort — no-op without a usage count."""
        shifted = tokenratio.record(model, prompt_tokens, estimate)
        if shifted is not None:
            rlog.emit("context.calibrated", model=model, real=prompt_tokens, est=estimate, ratio=round(shifted, 2))

    def _overflow_refit(self, err, sent_estimate: int, model, rlog) -> float | None:
        """A 400 'exceeds context' means the floor under-budgeted THIS body (its density ran hotter
        than the per-model average — a base64/blob-heavy turn). The server reports the REAL prompt
        size (``n_prompt_tokens``); return the density factor (real÷estimate) that re-prepping with
        will trim this exact body to fit, and feed it into the per-model average for future turns.
        ``None`` when it isn't a refittable overflow (nothing to re-fit against)."""
        if not isinstance(err, urllib.error.HTTPError):
            return None
        try:
            payload = json.loads(err.read())  # consumes the HTTPError body (readable once)
        except (ValueError, OSError, AttributeError):
            return None
        inner = payload.get("error") if isinstance(payload.get("error"), dict) else payload
        real = inner.get("n_prompt_tokens") if isinstance(inner, dict) else None
        if not real or not sent_estimate:
            return None
        tokenratio.record(model, real, sent_estimate)  # also nudge the running per-model average
        density = float(real) / float(sent_estimate)
        rlog.emit("context.refit", level="warning", model=model, real=real, est=sent_estimate,
                  n_ctx=(inner.get("n_ctx") if isinstance(inner, dict) else None), safety=round(density, 2))
        return density

    def _open_with_refit(self, body: dict, stream: bool, rlog) -> tuple:
        """Prep + POST the request, with ONE context-overflow REFIT-retry. cria's whole job is to
        make every request fit the window; if the floor still under-budgets a hot-density turn and
        the server 400s, re-fit to the REAL token count it reports and retry ONCE — so the harness
        never sees the 400 (its blind same-body retries can't converge fast enough). Returns the
        open ``(resp, sent_estimate, capture_path)``; raises ``UpstreamError`` on any other failure."""
        safety_override: float | None = None
        for attempt in range(2):
            data, sent_estimate, capture_path = self._prep(body, stream, rlog, safety_override=safety_override)
            req = urllib.request.Request(self._chat_url, data=data, method="POST", headers=self._headers(sse=stream))
            rlog.emit("upstream.request", url=self._chat_url, model=body.get("model"),
                      stream=stream, n_messages=len(body.get("messages", [])), refit=(attempt > 0))
            try:
                return urllib.request.urlopen(req, timeout=self._timeout), sent_estimate, capture_path
            except urllib.error.URLError as e:
                refit = self._overflow_refit(e, sent_estimate, body.get("model"), rlog) if attempt == 0 else None
                if refit is not None:
                    safety_override = refit  # re-prep tighter against the server's real count, retry
                    continue
                rlog.emit("upstream.error", level="error", url=self._chat_url, error=str(e))
                err = UpstreamError(str(e))
                err.code = getattr(e, "code", None)  # carry the real HTTP status for classify_failure
                raise err from e

    def _render_prompt(self, body: dict) -> str | None:
        """Ask the server to render the chat body into the flat prompt string the model actually
        tokenizes — chat template applied (tool injection, role markers, reasoning prefill) — via
        /apply-template. This is literally 'what the model sees'. Best-effort; None on failure."""
        payload: dict = {"messages": body.get("messages") or []}
        if body.get("tools"):
            payload["tools"] = body["tools"]
        if body.get("chat_template_kwargs"):
            payload["chat_template_kwargs"] = body["chat_template_kwargs"]
        try:
            req = urllib.request.Request(
                self._base_url + "/apply-template", data=json.dumps(payload).encode("utf-8"),
                method="POST", headers={"Content-Type": "application/json"},
            )
            # Fail FAST: rendering is a debug nicety on the same single slot as real inference —
            # it must never stall the actual call. When the slot is free it's ~4ms; if it can't
            # return quickly the slot is busy, so skip (best-effort) — the JSON body is still
            # captured and the prompt is reconstructable offline from it.
            with urllib.request.urlopen(req, timeout=_RENDER_TIMEOUT_S) as resp:
                p = json.loads(resp.read()).get("prompt")
                return p if isinstance(p, str) else None
        except (urllib.error.URLError, ValueError, OSError):
            return None

    def stream_chat(self, body: dict, rlog) -> Iterator[bytes]:
        """POST a streaming chat completion and yield raw SSE lines (bytes) for the
        caller to forward. Emits ``upstream.request`` / ``upstream.first_token`` /
        ``upstream.done`` with TTFT + tok/s. Token count uses the upstream ``usage``
        block when present, else counts content deltas as a proxy."""
        resp, sent_estimate, _ = self._open_with_refit(body, True, rlog)
        t0 = time.monotonic()
        t_first: float | None = None
        content_chunks = 0
        usage: dict | None = None
        try:
            for raw in resp:
                if raw.startswith(b"data:"):
                    payload = raw[5:].strip()
                    if payload and payload != b"[DONE]":
                        obj = _try_json(payload)
                        if obj is not None:
                            if _has_content_delta(obj):
                                if t_first is None:
                                    t_first = time.monotonic()
                                    rlog.emit(
                                        "upstream.first_token",
                                        ttft_ms=round((t_first - t0) * 1000, 1),
                                    )
                                content_chunks += 1
                            if obj.get("usage"):
                                usage = obj["usage"]
                yield raw
        finally:
            resp.close()
            t_end = time.monotonic()
            tokens = (usage or {}).get("completion_tokens") or content_chunks
            self._calibrate(body.get("model"), (usage or {}).get("prompt_tokens"), sent_estimate, rlog)
            tok_s = (
                round(tokens / (t_end - t_first), 1)
                if (t_first is not None and t_end > t_first and tokens)
                else None
            )
            rlog.emit(
                "upstream.done",
                total_ms=round((t_end - t0) * 1000, 1),
                gen_ms=round((t_end - (t_first or t0)) * 1000, 1),
                tokens=tokens,
                tok_per_s=tok_s,
                from_usage=bool(usage),
            )

    def chat(self, body: dict, rlog) -> bytes:
        """Non-streaming: return the full upstream response body (bytes).

        Retries the SAME endpoint ONCE on a transient TIMEOUT (a slow-prefill / connection-reset on
        the shared GPU that would otherwise be a dead turn) via the failover executor — a single
        local endpoint has no chain to walk, so anything else re-raises. Buffered, so a retry is safe."""
        # Force stream=false (the Responses adapter buffers from a stream=true request;
        # sending that upstream would return unparseable SSE) + merge adjacent assistants.
        attempt = 0
        while True:
            try:
                # t0 BEFORE the open: a non-stream urlopen returns only AFTER the server has finished
                # generating (the whole completion is buffered server-side), so timing from AFTER the
                # open captures just the body READ (~ms) — tokens/that = millions of tok/s. Measuring
                # from before the open gives the real end-to-end generation time.
                t0 = time.monotonic()
                resp, sent_estimate, capture_path = self._open_with_refit(body, False, rlog)
                try:
                    raw = resp.read()
                finally:
                    resp.close()
                break
            except (UpstreamError, OSError) as e:  # OSError → socket read-timeout mid-response
                action = failover.decide_action(
                    failover.classify_failure(getattr(e, "code", None), str(e)),  # real 429/408 status, not None
                    "upstream", "upstream", ("upstream",), attempt)
                if not isinstance(action, failover.RetrySame):
                    raise
                attempt = action.attempt
                rlog.emit("upstream.retry", level="warn", attempt=attempt, wait_ms=action.wait_ms, error=str(e))
                time.sleep(action.wait_ms / 1000.0)
        t_end = time.monotonic()
        usage = (_try_json(raw) or {}).get("usage")
        self._calibrate(body.get("model"), (usage or {}).get("prompt_tokens"), sent_estimate, rlog)
        tokens = (usage or {}).get("completion_tokens")
        tok_s = round(tokens / (t_end - t0), 1) if (tokens and t_end > t0) else None
        rlog.emit(
            "upstream.done",
            total_ms=round((t_end - t0) * 1000, 1),
            tokens=tokens,
            tok_per_s=tok_s,
            from_usage=bool(usage),
        )
        callcapture.capture_response(capture_path, raw, rlog)  # what the model actually answered
        return raw

    def chat_watched(self, body: dict, rlog, watch=None) -> bytes:
        """Stream the completion from the server but RETURN a buffered ``chat.completion`` (bytes),
        so a buffered caller (the loop's coder) is unchanged. While streaming, feed the accumulating
        REASONING to ``watch(reasoning_text, est_tokens) -> dict | None``; a non-None verdict ABORTS
        the in-flight request (closing the connection tells the server to stop and frees the slot)
        and the returned completion carries ``finish_reason="rumination"`` + a ``cria_rumination``
        verdict so the caller can re-prompt.

        Only reasoning/content is watched — a large ``write_file`` streams as tool-call ARGUMENTS,
        so it never trips the watcher; only runaway thinking does. With ``watch=None`` this is just a
        streaming call assembled into a buffered response."""
        # Ask for the usage block on the terminal chunk (llama.cpp honors this) so the assembled
        # completion carries real completion_tokens — the truncation guard reports them to the model.
        body = {**body, "stream_options": {"include_usage": True}}
        resp, sent_estimate, capture_path = self._open_with_refit(body, True, rlog)
        t0 = time.monotonic()
        t_first: float | None = None

        content: list[str] = []
        reasoning: list[str] = []
        tool_acc: dict[int, dict] = {}
        finish: str | None = None
        usage: dict | None = None
        aborted: dict | None = None
        stream_error: str | None = None
        watched_len = 0
        gen_tail = ""  # rolling tail of ALL generated chars (incl. tool-call args) for the degenerate-run backstop
        # LIVE generation counters for the status ticker's beat tick (operator asked for tok/s on the
        # in-between lines): the beat thread reads these while this call streams. Benign racy reads
        # of two scalars; cleared in the finally so a finished call never shows a stale rate.
        rlog.live_t0 = t0
        rlog.live_chars = 0
        try:
            for raw in resp:
                if not raw.startswith(b"data:"):
                    continue
                payload = raw[5:].strip()
                if not payload or payload == b"[DONE]":
                    continue
                obj = _try_json(payload)
                if obj is None:
                    continue
                # An SSE *error* frame ends the stream mid-generation: whatever was accumulated is a
                # FRAGMENT, not the model's answer. Assembling it anyway would hand the caller a
                # truncated tool call wearing finish_reason="tool_calls" — cria asserting the model
                # produced something it never produced. Stop and let the buffered re-issue below get
                # the real answer. (Seen live: llama.cpp raises "Invalid diff" from its streaming
                # tool-call differ when a partial-JSON heal lands mid-escape, killing the stream ~75%
                # through a write_file; the identical request non-streamed returns it complete.)
                if isinstance(obj.get("error"), (dict, str)):
                    err = obj["error"]
                    stream_error = str(err.get("message") or err) if isinstance(err, dict) else str(err)
                    break
                for choice in obj.get("choices", []):
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        if t_first is None:
                            t_first = time.monotonic()
                            rlog.emit("upstream.first_token", ttft_ms=round((t_first - t0) * 1000, 1))
                        content.append(delta["content"])
                    rc = delta.get("reasoning_content") or delta.get("reasoning")
                    if rc:
                        if t_first is None:
                            t_first = time.monotonic()
                            rlog.emit("upstream.first_token", ttft_ms=round((t_first - t0) * 1000, 1))
                        reasoning.append(rc)
                    tcs = delta.get("tool_calls")
                    _accumulate_tool_deltas(tool_acc, tcs)
                    # Feed the degenerate-run backstop from EVERY generated stream — content,
                    # reasoning, AND tool-call arguments (which the rumination watcher below skips) —
                    # so a stuck single-token runaway is caught wherever it streams.
                    for frag in (delta.get("content"), rc,
                                 *(((tc.get("function") or {}).get("arguments")) for tc in (tcs or []))):
                        if frag:
                            gen_tail = (gen_tail + frag)[-rumination.DEGENERATE_RUN_CHARS:]
                            rlog.live_chars += len(frag)  # the ticker's live tok/s numerator
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
                if obj.get("usage"):
                    usage = obj["usage"]
                # Degenerate-run backstop (independent of the rumination watcher: it fires even on a
                # tool-arg runaway and even when watch is None). A tail of identical chars = a stuck
                # stream — abort so the caller re-prompts instead of burning the window to a dead turn.
                if aborted is None and rumination.degenerate_tail(gen_tail):
                    # No `hits` and no `reasoning_tokens`: this detector counts NEITHER. It used to
                    # report hits=0 and pass len(gen_tail) — a CHARACTER count — as reasoning_tokens,
                    # and the notice built from that told the coder it "hit 0 second-guessing phrases
                    # after ~2048 reasoning tokens". A guard must not invent the numbers it fired on.
                    aborted = {"degenerate": True, "chars": len(gen_tail)}
                    rlog.emit("rumination.abort", level="warning", degenerate=True, chars=len(gen_tail))
                    break
                if watch is not None and aborted is None:
                    # Watch reasoning if the server splits it out; else the content stream (a
                    # runaway that never calls a tool). Tool-call args are excluded on purpose.
                    watch_text = "".join(reasoning) or "".join(content)
                    if len(watch_text) - watched_len >= _WATCH_STRIDE:
                        watched_len = len(watch_text)
                        verdict = watch(watch_text, len(watch_text) // 4)
                        if verdict:
                            aborted = verdict
                            rlog.emit("rumination.abort", level="warning",
                                      hits=verdict.get("hits"), reasoning_tokens=verdict.get("reasoning_tokens"))
                            break  # drop the receiver → server stops generating, slot freed
        finally:
            resp.close()
            rlog.live_t0 = None  # the ticker must never compute a rate from a finished call
        if stream_error is not None:
            # Re-ask the SAME request buffered. The answer still comes from the model — cria is not
            # repairing the fragment, it is discarding it and asking again down a path that works.
            # The watcher is forfeited for this turn (nothing to watch in a buffered call), which is
            # the right trade: a whole lost turn costs more than one unwatched one.
            rlog.emit("upstream.stream_error", level="warning", error=stream_error,
                      dropped_tool_arg_chars=sum(len("".join(s["args"])) for s in tool_acc.values()),
                      dropped_content_chars=len("".join(content)))
            return self.chat({k: v for k, v in body.items() if k != "stream_options"}, rlog)
        t_end = time.monotonic()
        completion = _assemble_completion(body.get("model"), content, reasoning, tool_acc, finish, usage, aborted)
        tokens = (usage or {}).get("completion_tokens")
        tok_s = round(tokens / (t_end - (t_first or t0)), 1) if (tokens and t_end > (t_first or t0)) else None
        if tokens and t_end > (t_first or t0):
            # Streamed answers carry no server "timings" block, so every streamed (coder) call was
            # invisible to timing readers of the capture — suite tok/s silently measured crew calls
            # only. Field names mirror llama.cpp's so those readers need no second shape; "source"
            # says these are cria-measured (first token → end), not server-reported.
            completion["timings"] = {"predicted_n": tokens,
                                     "predicted_ms": round((t_end - (t_first or t0)) * 1000, 3),
                                     "source": "cria-measured"}
        self._save_reasoning(capture_path, "".join(reasoning), aborted, rlog)
        callcapture.capture_response(capture_path, completion, rlog)  # the assembled answer, on disk
        self._calibrate(body.get("model"), (usage or {}).get("prompt_tokens"), sent_estimate, rlog)
        rlog.emit("upstream.done", total_ms=round((t_end - t0) * 1000, 1), tokens=tokens,
                  tok_per_s=tok_s, from_usage=bool(usage), aborted=bool(aborted))
        return json.dumps(completion).encode("utf-8")


    def _save_reasoning(self, capture_path: str | None, text: str, aborted, rlog) -> None:
        """Persist the coder's FULL reasoning block — UNTRUNCATED — to a sibling of the call capture
        (``NNNN-<phase>.reasoning.txt``), so every ``<think>`` is inspectable after the fact. cria
        watches the reasoning live for the rumination detector and would otherwise discard it (the
        harness strips reasoning from history), so this is the only record of what the model thought.
        Best-effort; no-op when there's no reasoning or capture is off. A ``coder.reasoning`` event
        points at the file (with token/char counts + whether the detector aborted this turn)."""
        if not text or not capture_path:
            return
        # When the rumination detector aborted this turn, bracket the reasoning with a loud marker so
        # a fired guard is obvious IN the file (not just cross-referenced from the log). Non-fired
        # reasoning stays pure (the full block, no header) so it's still greppable/diffable as-is.
        if aborted:
            bar = "─" * 72
            body = (f"⟦RUMINATION GUARD FIRED⟧ {aborted.get('hits')} second-guessing markers"
                    f" · ~{aborted.get('reasoning_tokens')} reasoning tokens · aborted mid-stream"
                    f" and re-prompted to refocus\n{bar}\n{text}\n\n"
                    f"⟦— reasoning stream ABORTED HERE by the rumination guard —⟧\n")
        else:
            body = text  # the WHOLE block — deliberately not clipped
        try:
            p = Path(capture_path)
            rpath = p.parent / (p.stem + ".reasoning.txt")
            rpath.write_text(body, encoding="utf-8")
            rlog.emit("coder.reasoning", path=str(rpath), chars=len(text),
                      reasoning_tokens=len(text) // 4, aborted=bool(aborted))
        except OSError as e:
            rlog.emit("coder.reasoning_error", level="info", error=str(e))


def _accumulate_tool_deltas(acc: dict[int, dict], deltas) -> None:
    """Reassemble streamed tool-call fragments by index: the first delta for an index carries id +
    name, later deltas carry argument-string fragments to concatenate (OpenAI SSE tool-call shape)."""
    for tcd in deltas or []:
        i = tcd.get("index", 0)
        slot = acc.setdefault(i, {"id": None, "name": None, "args": []})
        if tcd.get("id"):
            slot["id"] = tcd["id"]
        fn = tcd.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            slot["args"].append(fn["arguments"])


def _assemble_completion(model, content, reasoning, tool_acc, finish, usage, aborted) -> dict:
    """Build a non-streaming ``chat.completion`` dict from accumulated stream fragments."""
    tool_calls = []
    for i in sorted(tool_acc):
        slot = tool_acc[i]
        tool_calls.append({
            "id": slot["id"] or f"call_{i}",
            "type": "function",
            "function": {"name": slot["name"] or "", "arguments": "".join(slot["args"])},
        })
    message: dict = {"role": "assistant", "content": ("".join(content) or None)}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if tool_calls:
        message["tool_calls"] = tool_calls
    if aborted:
        finish_reason = "rumination"
    elif finish == "length":
        finish_reason = "length"
    elif tool_calls:
        finish_reason = "tool_calls"
    else:
        finish_reason = finish or "stop"
    completion: dict = {
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    if usage:
        completion["usage"] = usage
    if aborted:
        completion["cria_rumination"] = aborted
    return completion


def _is_empty_assistant(m: dict) -> bool:
    """An assistant message carrying NEITHER meaningful content NOR tool_calls — an empty turn.
    Strict chat templates (gemma/Fabliq) hard-reject it ("Assistant message must contain either
    'content' or 'tool_calls'!"), so it must never go on the wire."""
    if m.get("role") != "assistant":
        return False
    has_content = bool(m.get("content") and str(m["content"]).strip())
    return not has_content and not m.get("tool_calls")


def _merge_consecutive_assistant(messages: list[dict]) -> list[dict]:
    """Collapse runs of adjacent assistant messages into one (content joined, tool_calls
    combined), then DROP any assistant left empty. Codex represents one assistant turn as a text
    `message` item + separate `function_call` items; left split, a list ending in 2+ assistant
    messages is rejected by strict chat templates ("Cannot have 2 or more assistant messages at
    the end").

    A post-compaction turn can carry empty assistant placeholders (an assistant `message` item with
    no text, no tool call); the merge below can also SYNTHESIZE a bare ``{"role": "assistant"}`` when
    it coalesces two such empties. Either way the strict template hard-rejects an assistant with
    neither content nor tool_calls, so drop them. Safe: with no tool_calls, no ``tool`` result
    references the dropped turn, and the merge has already guaranteed no two assistants are adjacent,
    so removing one can't strand a same-role pair."""
    out: list[dict] = []
    for m in messages:
        if m.get("role") == "assistant" and out and out[-1].get("role") == "assistant":
            prev = out[-1]
            parts = [c for c in (prev.get("content"), m.get("content")) if c]
            tcs = (prev.get("tool_calls") or []) + (m.get("tool_calls") or [])
            merged: dict = {"role": "assistant"}
            if parts:
                merged["content"] = "\n".join(parts)
            if tcs:
                merged["tool_calls"] = tcs
            out[-1] = merged
        else:
            out.append(m)
    return [m for m in out if not _is_empty_assistant(m)]


def _try_json(b: bytes) -> dict | None:
    try:
        obj = json.loads(b)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _has_content_delta(chunk: dict) -> bool:
    """True if this streaming chunk carries generated text (a token), so it counts
    toward TTFT and the token tally. Ignores role-only / empty deltas."""
    for choice in chunk.get("choices", []):
        delta = choice.get("delta") or {}
        if delta.get("content"):
            return True
    return False
