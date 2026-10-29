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

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterator

from . import bodykeys
from . import (callcapture, config, contextfloor, failover, generation, indicators, massage, modelview,
               reasoning, rumination, tokenratio)

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
# Timeout for native prompt measurement/capture (shares the upstream slot).
_RENDER_TIMEOUT_S = 8
_MAX_PREFIX_SESSIONS = 256


@dataclass
class _RoleFit:
    floor: contextfloor.FitState = field(default_factory=contextfloor.FitState)
    scope: object = None


@dataclass
class _SessionWire:
    lock: object = field(default_factory=threading.RLock)
    roles: OrderedDict[str, _RoleFit] = field(default_factory=OrderedDict)
    previous: bytes | None = None
    basis: str = ""
    messages: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    tools: str = ""
    phase: str | None = None
    source_parts: tuple[tuple[str, str, str], ...] = ()


def _prefix_projection(body):
    """Observable message/schema projection, distinct from a rendered prompt."""
    return (json.dumps(body.get('tools')) + '\n' + '\n'.join(
        json.dumps(m, sort_keys=True) for m in body.get('messages', []))).encode()


def _observe_prefix(state, out, original, rendered, rlog, *, reduced, invalidated):
    basis = 'rendered-prompt' if rendered is not None else 'messages-and-tools'
    current = rendered.encode() if rendered is not None else _prefix_projection(out)
    previous = state.previous if state is not None and state.basis == basis else None
    shared = len(os.path.commonprefix([previous, current])) if previous is not None else 0
    messages = tuple(contextfloor._fingerprint(m) for m in out.get('messages', []))
    source_parts = tuple(modelview.prefix_source_parts(m) for m in out.get('messages', []))
    inputs = tuple(contextfloor._fingerprint(m) for m in original.get('messages', []))
    tools = contextfloor._fingerprint(out.get('tools'))
    changed = next((i for i, (a, b) in enumerate(zip(state.messages, messages)) if a != b),
                   min(len(state.messages), len(messages))) if state is not None else 0
    if previous is None:
        reason = 'basis_changed' if state is not None and state.previous is not None else 'no_previous_request'
    elif previous == current:
        reason = 'identical'
    elif state.phase != getattr(rlog, 'phase', None):
        reason = 'phase_changed'
    elif tools != state.tools:
        reason = 'tools_changed'
    elif invalidated:
        reason = 'reduction_source_changed'
    elif reduced:
        reason = 'history_reduced'
    elif inputs[:len(state.inputs)] != state.inputs:
        reason = 'input_changed'
    elif messages[:len(state.messages)] == state.messages:
        reason = 'append'
    else:
        reason = 'wire_transform'
    marker = None
    if changed < len(out.get('messages', [])):
        text = contextfloor._msg_text(out['messages'][changed])
        start = text.find('⟦ctx:')
        end = text.find('⟧', start) if start >= 0 else -1
        marker = text[start:end + 1] if end >= 0 else None
    break_source = None
    if reason not in ('no_previous_request', 'identical', 'append'):
        break_source = 'other'
        old = state.source_parts[changed] if changed < len(state.source_parts) else None
        new = source_parts[changed] if changed < len(source_parts) else None
        if old and new and old[0] == new[0] and old[1] != new[1]:
            break_source = 'dependency_annotation'
        elif old and new and old[0] == new[0] and old[2] != new[2]:
            break_source = 'inventory'
        elif ((marker == '⟦ctx:compacted⟧' and text.startswith(marker)) or
              (marker == '⟦ctx:reduced⟧' and changed < len(state.inputs)
               and changed < len(inputs) and state.inputs[changed] == inputs[changed])):
            break_source = 'floor'
    rlog.emit('context.prefix', reshape=None, basis=basis, shared_bytes=shared, break_source=break_source,
              previous_bytes=len(previous) if previous is not None else None,
              request_bytes=len(current), reason=reason, changed_message=changed,
              marker=marker, reduction_source_changed=invalidated,
              comparison_scope='session', phase=getattr(rlog, 'phase', None),
              previous_phase=state.phase if state is not None else None)
    if state is not None:
        state.previous, state.basis = current, basis
        state.messages, state.inputs, state.tools = messages, inputs, tools
        state.phase = getattr(rlog, 'phase', None)
        state.source_parts = source_parts

# A kill can lose at most this much reasoning. Small enough that the tail of a thought survives,
# large enough that streaming does not become one write syscall per token.
_REASONING_FLUSH_BYTES = 2048
# Open partial-reasoning handles, keyed by capture path, so the save at the end of the stream can
# close the one this call opened without threading the handle through four call sites.
_REASONING_SINKS: dict = {}


class UpstreamError(Exception):
    """The upstream model server could not be reached or errored."""

    def __init__(self, message, response_error=None):
        super().__init__(message)
        self.response_error = response_error or {"message": str(message)}


class UpstreamProtocolError(UpstreamError):
    """A typed malformed-generation response, never an availability/retry signal."""
    code = 500


def _http_error_body(err) -> bytes:
    """Retain the single-read rejection for both fitting and protocol translation."""
    if not hasattr(err, "response_body"):
        err.response_body = err.read()
        try:
            payload = json.loads(err.response_body)
        except (ValueError, TypeError):
            payload = None
        inner = payload.get("error", payload) if isinstance(payload, dict) else None
        if isinstance(inner, dict):
            error = dict(inner)
            if not isinstance(error.get("message"), str):
                error["message"] = str(err)
            if generation.is_protocol_error(error):
                err.response_error = error
                return err.response_body
            real, window = error.get("n_prompt_tokens"), error.get("n_ctx")
            if (err.code == 400 and type(real) is int and type(window) is int
                    and real > window > 0):
                error["code"] = "context_length_exceeded"
            elif not isinstance(error.get("code"), str):
                error.pop("code", None)
            err.response_error = error
    return err.response_body


class ContextRefitNoChange(UpstreamError):
    """A parsed context rejection whose normal inner refit has identical final bytes.

    This is private wire provenance, not a classification reconstructed by a caller from an HTTP
    code or event text.  ``final_wire`` is the exact ``Request.data`` that the server rejected.
    """

    def __init__(self, source: BaseException, final_wire: bytes):
        super().__init__(str(source), getattr(source, "response_error", None))
        self.code = getattr(source, "code", None)
        self.final_wire = final_wire


class CallerContextRetryNoChange(UpstreamError):
    """The one opted-in caller retry re-prepared to the same final wire and was not sent."""

    def __init__(self, source: ContextRefitNoChange, final_wire: bytes):
        super().__init__(str(source), source.response_error)
        self.code = source.code
        self.final_wire = final_wire


def _abort_header(aborted: dict) -> str:
    """One line naming the backstop that stopped this stream, with the numbers THAT backstop holds.

    See the call site for the incident. Nothing here reads a counter another guard sets: a field a
    guard did not write is absent, not None-rendered."""
    if aborted.get("window_exhausted"):
        return (f"⟦WINDOW-EXHAUSTED ABORT⟧ the generation used {aborted.get('frames')} of the "
                f"{aborted.get('room')} tokens of room this turn had — past that the server stops it "
                f"and the whole result is discarded, so it was stopped here and labelled instead")
    if aborted.get("dead_stream"):
        return (f"⟦DEAD-STREAM ABORT⟧ {aborted.get('chunks')} frames arrived carrying nothing "
                f"readable — no content, no reasoning, no tool-call fragment")
    if aborted.get("degenerate"):
        return (f"⟦DEGENERATE-RUN ABORT⟧ the last {aborted.get('chars')} characters were one "
                f"repeated unit — a stuck stream")
    return (f"⟦RUMINATION GUARD FIRED⟧ {aborted.get('hits')} second-guessing markers · "
            f"~{aborted.get('reasoning_tokens')} reasoning tokens · aborted mid-stream and "
            f"re-prompted to refocus")


def _abort_footer(aborted: dict) -> str:
    which = ("the window-exhausted backstop" if aborted.get("window_exhausted") else
             "the dead-stream backstop" if aborted.get("dead_stream") else
             "the degenerate-run backstop" if aborted.get("degenerate") else
             "the rumination guard")
    return f"⟦— reasoning stream ABORTED HERE by {which} —⟧\n"


# Summary requests (self-compaction, harness compaction, briefing validation) carry the history
# flattened to text and code, which tokenizes denser than the coder's JSON tool traffic. One ratio
# per model let the coder's ~1.1 stand in for a summary's ~1.33 and under-fit by ~20% (run
# 1792480002 call 0051). Each kind learns its own density; unseen kinds start at the default.
_SUMMARY_PHASES = ("self-compact", "compactor", "compaction", "harness-compaction", "summar")


def _density_key(model, rlog, body=None) -> str:
    phase = getattr(rlog, "phase", None)
    hinted = body.get(bodykeys.DENSITY_KIND) if isinstance(body, dict) else None
    kind = (hinted if isinstance(hinted, str) and hinted else
            "summary" if isinstance(phase, str) and phase.startswith(_SUMMARY_PHASES) else "")
    return f"{model or ''}#{kind}" if kind else model


class Upstream:
    """An OpenAI-compatible chat endpoint. With no ``api_key`` this is the local
    llama.cpp; with one it is an OpenAI-compatible *cloud* provider (Bearer auth) —
    the same wire protocol, so one client serves both roles."""

    def __init__(self, base_url: str, timeout_seconds: int = 600, api_key: str | None = None,
                 context_window: int | None = None, capture_dir=None, capture_rendered: bool = True,
                 engagement_level: int = config.MAX_ENGAGEMENT_LEVEL, open_request=None) -> None:
        # THE ENGAGEMENT LADDER reaches in here because two of its rungs live on this path: the
        # tool-call repairs are level 1 and the context floor is level 3. Passed as a number rather
        # than a Config so the transport keeps knowing nothing about roles, backends or the loop.
        # Defaults to the top of the ladder: an Upstream built without an opinion behaves as it
        # always did, so nothing outside a ladder run changes.
        self._engagement_level = engagement_level
        # Process-local, bounded session state. Only fitting is partitioned by
        # role; observation compares every request in actual preparation order.
        self._prefix_sessions = OrderedDict()
        self._prefix_lock = threading.Lock()
        self._base_url = base_url.rstrip("/")
        self._chat_url = self._base_url + "/v1/chat/completions"
        self._timeout = timeout_seconds
        self._api_key = api_key
        # When set, capture the EXACT body of every model call to a file here (opt-in).
        self._capture_dir = capture_dir
        if open_request is None and capture_dir is not None:
            from .receivecapture import DefaultTransport
            open_request = DefaultTransport()
        self._receive_open = open_request
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
        # Is the current window a number cria INVENTED? `_window_final` answers a different question
        # ("stop probing"), and the window guard was gated on it — so the guard was off in exactly the
        # cases that produce runaways: before the first successful probe, and forever after the
        # fallback was committed. Evidence (config, /props, the server's own 400, a prompt the server
        # ACCEPTED) turns this off; only `_FALLBACK_WINDOW` turns it on.
        self._window_guessed = False
        self._props_attempts = 0
        self._models_attempts = 0
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

    def _ordinary_open(self, req, *, timeout):
        # Preparation and captured dispatch share cache provenance at construction.
        opening = getattr(self._receive_open, 'ordinary', urllib.request.urlopen)
        return opening(req, timeout=timeout)

    def loaded_model(self, rlog) -> str | None:
        """The model id ACTUALLY loaded at this local server — llama.cpp's /v1/models returns its
        ``--alias``. Discovered once and cached, so cria's banner can show the TRUTH (what's really
        answering) rather than a config label that may not match. None for a cloud endpoint (no
        single loaded model) or when /v1/models can't be read. A model swap needs a cria restart to
        refresh (the same workflow as the fleet swap)."""
        if self._api_key:
            return None                  # cloud: no single loaded model, and never a probe. This
            #                              guard is why the retry below cannot touch a cloud
            #                              endpoint — __init__ seeds `None` there to mean "settled",
            #                              which is a different None from "the probe missed".
        if self._loaded_model is not _UNSET and self._loaded_model is not None:
            return self._loaded_model
        if self._loaded_model is None:   # a previous attempt MISSED — retry on the same budget as
            self._models_attempts += 1   # /props; a server still loading its model refuses both
            if (self._models_attempts > _MAX_PROPS_ATTEMPTS
                    and self._models_attempts % _PROPS_RETRY_EVERY):
                return None
        self._loaded_model = None
        try:
            req = urllib.request.Request(self._base_url + "/v1/models", method="GET")
            with self._ordinary_open(req, timeout=5) as resp:
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

        A FAILED probe is retried, a successful one never is. The first cut cached the failure and
        the banner died silently for the life of the process — the exact mistake `_resolve_window`
        already documents ten lines above this file's `_PROPS_RETRY_EVERY`: "the trigger is as
        ordinary as cria restarting while llama.cpp is still loading its model." That is not an edge
        case here, it is the NORMAL case: `suite/run.py` starts the llama service and restarts cria
        immediately after, so the first turns land while the model is still loading and /props
        refuses the connection. Observed live on the mellum2 swap. Bounded by the same budget the
        window uses, so a permanently dead endpoint costs a handful of probes, not one per call
        (#3)."""
        if self._props is not None or self._api_key:
            return self._props
        self._props_attempts += 1
        if self._props_attempts > _MAX_PROPS_ATTEMPTS and self._props_attempts % _PROPS_RETRY_EVERY:
            return None
        try:
            req = urllib.request.Request(self._base_url + "/props", method="GET")
            with self._ordinary_open(req, timeout=5) as resp:
                self._props = json.loads(resp.read())
            self._props_seen = True
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
            with self._ordinary_open(req, timeout=5) as resp:
                props = json.loads(resp.read())
            self._props, self._props_seen = props, True   # the compat banner reads this — no 2nd probe
            n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
            if isinstance(n_ctx, int) and n_ctx > 0:
                self._window = n_ctx
                self._window_final = True
                self._window_guessed = False
                rlog.emit("context.window", source="props", n_ctx=n_ctx)
                return self._window
            rlog.emit("context.window", level="info", source="props", error="no n_ctx in /props")
        except (urllib.error.URLError, ValueError, KeyError, OSError) as e:
            rlog.emit("context.window", level="info", source="props", error=str(e))
        # Discovery missed this attempt: keep the floor ALIVE on a safe fallback (never cache
        # None = "no floor"), and retry next call until the attempt budget commits the fallback.
        self._window = _FALLBACK_WINDOW
        self._window_guessed = True
        if self._props_attempts == _MAX_PROPS_ATTEMPTS:
            rlog.emit("context.window", level="warn", source="fallback", n_ctx=_FALLBACK_WINDOW,
                      retry_every=_PROPS_RETRY_EVERY)
        return self._window

    @property
    def _tool_call_fixes(self) -> bool:
        return self._engagement_level >= config.TOOL_CALL_FIXES

    @property
    def _context_fixes(self) -> bool:
        return self._engagement_level >= config.CONTEXT_FIXES

    def _reconcile_reasoning_convention(self, body: dict, rlog) -> None:
        """THE WIRE INVARIANT (C41): a reasoning knob this body carries must be one the SERVED
        template actually reads, and this is the one place that knows what that template is — the
        last point before serialization, same as every other wire invariant `_prep` enforces.

        `Role.apply` (config.py) writes the reasoning knob in the convention `_think_protocol`
        resolved at CONFIG-LOAD time — a static per-backend guess (`[backends.*].reasoning_style`,
        or the served/keyed default) that goes stale the instant the served model swaps out from
        under it without a matching config edit. Measured live, row p28: `[backends.local]
        reasoning_style = "openai"` was written for ternary-bonsai-2 (61f08e9, whose template takes
        `reasoning_effort` and defaults to xhigh without it); the box then served
        Nemotron-Elastic-12B, whose template's `/props` mentions `enable_thinking` four times and
        `reasoning_effort` zero. Every OFF-reasoning call — the compactor role, every `-noreason`
        retry — sent `reasoning_effort` into a template that ignores it, so reasoning never turned
        off: 0079/0080-proxy each generated the full 37,719-token window and zero content, ~228s
        apiece, for one compaction.

        RESOLUTION, not silent override: `reasoning.detect_served_style` reads the actual
        `chat_template` text this endpoint just served (cached by `props()`, one probe per process
        — a model swap needs a cria restart to refresh, the same posture `loaded_model` already
        documents). A template that gives no clean signal (mentions both conventions, or neither —
        e.g. a served endpoint fronting a remote gateway, 61f08e9's own justification for letting an
        operator name a style on a keyless backend) leaves the body untouched: an explicit config
        choice keeps winning wherever the template does not demonstrably contradict it. Only a
        DEMONSTRATED mismatch — the body carries one convention's key and the template's markers
        say only the other — is corrected, and it is never silent: a structured warning names the
        configured style, the detected one, and what was rewritten, so the stale `cria.toml` line is
        visible in the logs rather than a permanent, undiagnosable no-op.

        A cloud (keyed) endpoint has no local template to read — `props()` returns None for it
        unconditionally — so this is a no-op there, exactly like every other served-only wire fix."""
        if self._api_key:
            return
        ctk = body.get("chat_template_kwargs")
        has_thinking = isinstance(ctk, dict) and "enable_thinking" in ctk
        has_effort = "reasoning_effort" in body
        if not has_thinking and not has_effort:
            # Nothing to reconcile — the common case for a body `Role.apply` never touched
            # (reasoning "auto"/unset, or no role at all). Skip the /props probe entirely rather
            # than pay a network round trip a body with no reasoning knob has no use for.
            return
        props = self.props(rlog)
        tmpl = props.get("chat_template") if isinstance(props, dict) else None
        if not isinstance(tmpl, str) or not tmpl:
            return
        detected = reasoning.detect_served_style(tmpl)
        if detected is None:
            return
        if detected == "chat_template" and has_effort and not has_thinking:
            effort = body.pop("reasoning_effort")
            enable = effort not in ("none", "minimal", None)
            body.setdefault("chat_template_kwargs", {})["enable_thinking"] = enable
            rlog.emit("reasoning.convention_autocorrect", level="warn", from_style="openai",
                      to_style="chat_template", effort=effort, enable_thinking=enable)
        elif detected == "openai" and has_thinking and not has_effort:
            enable = body["chat_template_kwargs"].pop("enable_thinking")
            if not body["chat_template_kwargs"]:
                body.pop("chat_template_kwargs")
            body["reasoning_effort"] = "none" if not enable else "medium"
            rlog.emit("reasoning.convention_autocorrect", level="warn", from_style="chat_template",
                      to_style="openai", enable_thinking=enable, reasoning_effort=body["reasoning_effort"])

    def _prep(self, body: dict, stream: bool, rlog, safety_override: float | None = None,
              _previous_fit: bytes | None = None, _wire_overhead: int = 0) -> tuple[bytes, int, str | None]:
        """Prepare at the sole wire boundary, serializing each session's fitting state."""
        session = getattr(rlog, 'session', None)
        phase = getattr(rlog, 'phase', None) or 'proxy'
        role = 'coder' if phase.startswith('coder-') else phase
        state = None
        if isinstance(session, str) and session:
            with self._prefix_lock:
                key = session
                state = self._prefix_sessions.pop(key, None) or _SessionWire()
                self._prefix_sessions[key] = state
                while len(self._prefix_sessions) > _MAX_PREFIX_SESSIONS:
                    self._prefix_sessions.popitem(last=False)
        if state is None:
            return self._prep_wire(body, stream, rlog, safety_override, _previous_fit,
                                   _wire_overhead=_wire_overhead)
        with state.lock:
            fitting = state.roles.pop(role, None) or _RoleFit()
            state.roles[role] = fitting
            while len(state.roles) > _MAX_PREFIX_SESSIONS:
                state.roles.popitem(last=False)
            return self._prep_wire(body, stream, rlog, safety_override, _previous_fit, state, fitting,
                                   _wire_overhead)

    def _prep_wire(self, body: dict, stream: bool, rlog, safety_override=None,
                   _previous_fit=None, prefix_state=None, fitting=None,
                   _wire_overhead=0) -> tuple[bytes, int, str | None]:
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
        self._reconcile_reasoning_convention(body, rlog)
        from . import assistruntime
        runtime = (assistruntime.current() if assistruntime.is_bound() else
                   assistruntime.AssistRuntime.select(level=self._engagement_level))
        wire_folds = runtime.wire_folds if self._context_fixes else ()
        out = {**body, "stream": stream}
        msgs = body.get("messages")
        fitted_source = None
        reduced = invalidated = False
        if isinstance(msgs, list):
            # A stamped gate call is cria-authored provenance, not marker-shaped text guessed from
            # history. Clean only those linked calls/results at the final coder-bound wire boundary;
            # a body without one remains byte-identical.
            msgs = modelview.wire_messages(msgs)
            if self._context_fixes:
                # Move exact legacy footers losslessly to a quoted tail before
                # fitting. Unknown prose stays intact; the floor owns reduction.
                msgs = modelview.retained_results_truth(msgs)
            window = self._resolve_window(rlog)
            # A GUESSED WINDOW MAY NOT TRIM. `_resolve_window` returns `_FALLBACK_WINDOW` when
            # /props could not be read — an invented number, and the abort guard below already
            # refuses to act on it for exactly that reason (`not self._window_guessed`). The floor
            # was left running against it, which is the destructive direction of the same guess.
            #
            # cria's own measurement of what that cost is in `_window_at_least`: 52 floor runs
            # against the 8,192 fallback, over_budget on 52 of 52, 934 PROTECTED messages destroyed
            # across 6 sessions, while the model's real window was 49,152. The trigger is as
            # ordinary as cria restarting while llama.cpp is still loading.
            #
            # SEND IT AND LET THE SERVER SETTLE IT. An overflow comes back as a 400 carrying
            # `n_prompt_tokens` AND `n_ctx`, and `_overflow_refit` treats that n_ctx as FINAL, clears
            # `_window_guessed` and retries once — so the cost of not guessing is one round trip,
            # after which the window is measured and the floor runs normally for the rest of the
            # process. The cost of guessing is every message the guess threw away, permanently and
            # silently (#5, #5b, #23c: unknown is not a small number, it is unknown).
            # LEVEL 3 — CONTEXT_FIXES. Below this rung cria performs no surgery on the context: it
            # sends what it was given and lets the server answer for the fit. The floor is the most
            # consequential thing on this path — it DROPS OLDEST CONTENT — and it ran 54 times inside
            # the arm the suite called "the model on its own".
            if not self._context_fixes:
                window = None
            elif window and self._window_guessed:
                rlog.emit("context.floor_skipped", level="warn", why="window is a guess",
                          guess=window)
                window = None
            repeat_ptrs_in = modelview.repeat_pointers(msgs)
            if window:
                reserve = contextfloor.reserve_for(body)  # reads cria_output_reserve (stripped below)
                tools_in = body.get("tools")
                from . import capacitypolicy
                safety = (safety_override if safety_override is not None else
                          capacitypolicy.fit_density(_density_key(body.get("model"), rlog, body),
                                                     runtime.capacity))
                pinned = str(body.get(bodykeys.PINNED_TASK) or "")
                source, source_tools = msgs, tools_in
                if prefix_state is not None:
                    root = next((m for m in msgs if m.get('role') == 'user'), None)
                    scope = (body.get('model'), runtime.selected, pinned,
                             contextfloor._fingerprint(root))
                    if fitting.scope != scope:
                        fitting.floor = contextfloor.FitState()
                        fitting.scope = scope
                    msgs, tools_in, invalidated = fitting.floor.reuse(msgs, tools_in)
                fit_options = {'headroom': True} if prefix_state is not None else {}
                if _wire_overhead:
                    fit_options['wire_overhead'] = _wire_overhead
                # THE ONE-COPY FOLD (modelview.fold_evidence) NEVER RUNS BEFORE THE FLOOR DECIDES
                # WHAT SURVIVES. A pointer says "the full copy is further down"; the floor may drop
                # or shrink that copy (an unprotected ⟦ctx:checks⟧ result is a lever-3/4 candidate
                # while the protected continuation that points at it is kept) and the pointer would
                # outlive its target. So: size the body folded — that is what lets it fit WITHOUT
                # trimming — and if the floor touched anything, discard that and fit the UNFOLDED
                # conversation instead; the fold is applied once more below, over whatever survived.
                trial = modelview.fold_selected(modelview.WireInput(msgs), wire_folds).messages
                fitted, tools, rep = contextfloor.fit(
                    trial, tools_in, window=window, reserve=reserve, safety=safety, pinned_task=pinned,
                    **fit_options)
                history_changed = fitted != trial
                if trial is not msgs and fitted != trial:      # the floor removed or shrank a message
                    fitted, tools, rep = contextfloor.fit(
                        msgs, tools_in, window=window, reserve=reserve, safety=safety, pinned_task=pinned,
                        **fit_options)
                    history_changed = fitted != msgs
                reduced = history_changed or tools != tools_in
                history_fitted = fitted if history_changed else msgs
                if (prefix_state is not None and reduced
                        and (msgs != source or tools_in != source_tools)):
                    # A NEW reduction is authored from original evidence, not from
                    # yesterday's stand-in. Otherwise protected notes accumulate,
                    # consume the window and become summaries of summaries.
                    fitted, tools, rep = contextfloor.fit(
                        source, source_tools, window=window, reserve=reserve, safety=safety,
                        pinned_task=pinned, **fit_options)
                    history_fitted = fitted
                # Optional folds own their own delivery-dependent pointers. Save
                # only actual floor edits; repeat folding still runs afresh below.
                fitted_source = (source, source_tools, history_fitted, tools)
                fitted_estimate = contextfloor.est_total(fitted, tools)
                msgs = fitted
                if rep.applied or rep.over_budget:
                    lvl = "warning" if rep.over_budget else "info"
                    rlog.emit("context.floor", reshape="floor-trim", level=lvl, safety=round(safety, 2),
                              **rep.as_event())
                if tools != body.get('tools') and tools is not None:
                    out["tools"] = tools  # send the bounded tool schema, not the fat original
            # UNCONDITIONAL tool-integrity: an orphan `tool` (its assistant call folded by self-compaction,
            # or dropped) 400s a strict template EVERY turn — and the floor's orphan strip runs only when
            # the request is OVER budget, so a fitting request ships the orphan. Convert it to `user` here,
            # on every request, so no orphan ever reaches the model.
            msgs, deorphaned = (contextfloor.ensure_tool_integrity(msgs) if self._tool_call_fixes
                                else (msgs, 0))
            if deorphaned:
                rlog.emit("context.deorphaned", reshape="deorphan", count=deorphaned, level="info")
            # Settle any legacy inventory to its stable reference before final folds. Native paired
            # messages establish availability; a changing list must not rewrite an earlier handoff.
            if self._context_fixes:       # L0-L2 send what they were given (no context surgery)
                msgs = modelview.retained_results_truth(msgs)
                # Last, over what survived: every pointer's full copy is in `msgs` by construction.
                msgs = modelview.fold_selected(modelview.WireInput(msgs), wire_folds).messages
                repeats = modelview.repeat_pointers(msgs) - repeat_ptrs_in
                if repeats > 0:
                    rlog.emit("context.repeat_dedup", reshape="dedup", folded=repeats)
            # C44 R1 (review 9eaadebe): THE WIRE INVARIANT. `indicators.PROSE_DROPPED_MARKER` must
            # never reach a model (#17: no literal "cria"-family token; #24: a wire invariant belongs
            # at the wire). `loop.reframe_compaction` and `server._strip_and_reframe_inbound` are the
            # two upstream owners that interpret/strip it, but this is the LAST point before
            # serialization \u2014 unconditional, independent of engagement level, so no missed call
            # site anywhere upstream can put it on the wire.
            msgs = indicators.strip_prose_dropped_marker(msgs)
            # WHAT THE FILE-TEXT BLOCK'S CLAIMS ARE TRUE OF, settled on the body actually sent: a block the
            # floor reduced or dropped is no delivery, so it earns no whole-read credit and the ledger no
            # longer says "its current text is below". Read back by the loop from `rlog` (#24).
            msgs, on_wire = modelview.settle_restored_text(msgs)
            if rlog is not None:
                try:
                    rlog.restored_on_wire = on_wire
                except AttributeError:
                    pass
            # Existing promises are required settlement, not optional production.
            # Keep the actual producer through copies/refits and later disabled scopes.
            from . import focustrim
            producers = body.get(bodykeys.FOCUS_PRODUCERS)
            pending = any(isinstance(m.get(bodykeys.SUPERSEDED_WRITES), focustrim.SupersededWriteNotice)
                          for m in msgs)
            if pending and isinstance(producers, assistruntime.FocusWireBindings):
                settlement = producers.definitions
            elif pending:
                # Genuine standalone canonical notices predate request binding. This
                # qualifies their existing factual promise; it produces no history.
                settlement = (focustrim.SUPERSESSION,)
            else:
                settlement = ()
            msgs = focustrim.settle_focus(focustrim.FocusInput(msgs), settlement).messages
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
        # EVERY cria-internal key, from the ONE list, at the ONE place (#24). This was two hand-written
        # pops while `bodykeys.ALL` — whose own docstring promises "the wire strips this set wholesale,
        # so adding a key here is all it takes to keep it off the API" — had no reader anywhere in the
        # package. The promise was inert: a sixth key added to that tuple would have shipped. The
        # completion-side keys pop harmlessly here, which is what makes the list safe to trust.
        for _k in bodykeys.ALL:
            out.pop(_k, None)
        # Caller-instruction provenance is a cria message hint, never an upstream API field.
        if isinstance(out.get("messages"), list):
            out["messages"] = [{k: v for k, v in m.items()
                                if k not in (bodykeys.CALLER_INSTRUCTIONS, bodykeys.CALLER_PERSONA,
                                             bodykeys.CALLER_SPAN, bodykeys.RESTORED_FILES,
                                             bodykeys.PAYLOAD_BOUNDARY, bodykeys.SUPERSEDED_WRITES,
                                             bodykeys.FOCUS_PRODUCERS, bodykeys.ANNOTATION_SOURCE,
                                             bodykeys.RESULT_OUTCOME, bodykeys.READ_OBSERVATION, bodykeys.RESULT_REPORT)}
                               if isinstance(m, dict) else m for m in out["messages"]]
        # Historical arguments are a final-wire invariant: role merges/folds can
        # introduce calls after any earlier repair. Optional recovery is selected
        # once here; disabled/proxy calls still retain the exact malformed text in
        # a valid, lossless envelope. Nothing below changes message contents.
        if isinstance(out.get("messages"), list):
            from . import assistruntime, historyarguments
            runtime = (assistruntime.current() if assistruntime.is_bound() else
                       assistruntime.AssistRuntime.select(level=self._engagement_level))
            definition = historyarguments.selected_definition(runtime.definitions)
            out["messages"] = historyarguments.prepare_history(
                out["messages"], rlog, definition=definition, recover=self._tool_call_fixes)
        sent_estimate = contextfloor.est_total(out.get("messages"), out.get("tools"))
        # The pre-frame observer never rides in ``out``.  It is correlated here, after every wire
        # transform and internal-key strip, with the exact bytes about to be POSTed.  A non-coder
        # role or a coder call without a fresh observer remains silent rather than inheriting state.
        data = json.dumps(out).encode("utf-8")
        rendered = None
        real = None
        if (isinstance(msgs, list) and window and self._api_key is None
                and ((isinstance(self._props, dict) and self._props.get("chat_template"))
                     or sent_estimate * safety > window - rep.reserve)):
            # A configured window can leave /props uncached. Measure this exact
            # final body before refusing an estimated overflow; unavailable
            # native metadata grants no new admission authority.
            # Average density cannot settle THIS prompt: numeric evidence can run much
            # hotter than prose. Measure the final template before POST or capture, then
            # let the one floor refit the ORIGINAL input (never trim a trimmed copy).
            rendered = self._render_prompt(out)
            real = self._tokenize_prompt(rendered, rlog) if rendered is not None else None
            if real is not None:
                rlog.emit("context.measured", tokens=real, n_ctx=window, reserve=rep.reserve)
                tokenratio.record(_density_key(body.get("model"), rlog, body), real, sent_estimate)
                # The reply's room is part of the fit. A prompt that merely fits the window
                # leaves the answer no space: a self-compaction briefing measured 48,192 of a
                # 49,152 window and was cut off after 959 tokens (run 1792480002 call 0051).
                if real > window - rep.reserve:
                    if data == _previous_fit:
                        raise UpstreamError("Measured input cannot fit the context window without losing protected input")
                    tighter = max(safety, real / max(sent_estimate, 1))
                    return self._prep(body, stream, rlog, safety_override=tighter,
                                      _previous_fit=data, _wire_overhead=_wire_overhead)
        if (isinstance(msgs, list) and window and real is None
                and sent_estimate * safety > window - rep.reserve):
            # All protocol repairs, settlements and labels have now run. Never
            # POST or capture a request the one floor still knows cannot fit.
            if rep.over_budget or data == _previous_fit:
                raise UpstreamError("Input cannot fit the context window without losing protected input")
            # Structural wire growth is measured in the same estimate space,
            # separately from model density and the role's generation reserve.
            overhead = max(_wire_overhead, sent_estimate - fitted_estimate)
            rlog.emit('context.wire_refit', reshape=None, wire_overhead=overhead,
                      fitted_estimate=fitted_estimate, final_estimate=sent_estimate)
            return self._prep(body, stream, rlog, safety_override=safety,
                              _previous_fit=data, _wire_overhead=overhead)
        phase = getattr(rlog, "phase", None)
        # Observe exact surviving offered notes only after final fitting and role
        # repair. The caller commits these only when this transport returns.
        if isinstance(phase, str) and phase.startswith('coder-'):
            visible = [m.get('content') for m in out.get('messages', [])
                       if isinstance(m.get('content'), str)]
            rlog.guidance_on_wire = [m['content'] for m in body.get('messages', [])
                if m.get('role') == 'user' and isinstance(m.get('content'), str)
                and m['content'].startswith('⟦ctx:steer⟧ ')
                and any(m['content'] in text for text in visible)]
        state = getattr(rlog, "coder_preframe", None)
        receipt = None
        if isinstance(phase, str) and phase.startswith("coder-") and isinstance(state, dict):
            receipt = {"state": state,
                       "final_wire": {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}}
        capture_path = None
        if self._capture_dir is not None:  # record EXACTLY what the model will see, per call
            from .assistruntime import current
            selection = current()
            rendered = (rendered if rendered is not None else self._render_prompt(out)) if self._capture_rendered else None
            capture_path = callcapture.capture(out, rlog, calls_dir=self._capture_dir,
                                               phase=phase, url=self._chat_url, rendered=rendered,
                                               coder_preframe=receipt,
                                               assist_selection={"selected": list(selection.selected),
                                                                 "engagement_level": selection.engagement_level})
        if receipt is not None:
            rlog.emit("loop.coder_preframe_serialized", **receipt, capture_path=capture_path)
        if prefix_state is not None and fitted_source is not None and not rep.over_budget:
            fitting.floor.remember(*fitted_source)
        if prefix_state is not None:
            _observe_prefix(prefix_state, out, body, rendered, rlog,
                            reduced=reduced, invalidated=invalidated)
        return data, sent_estimate, capture_path

    def _window_at_least(self, prompt_tokens, rlog) -> None:
        """A prompt the server ACCEPTED proves its window is at least that big.

        THE FALLBACK IS NOT CONSERVATIVE, it is destructive, and cria held the disproof in its hand
        on every call. Measured over the captured log-days: 52 floor runs against the 8,192 fallback,
        `over_budget` on 52 of 52, 934 PROTECTED messages destroyed across 6 sessions — while the
        model's real window was 49,152, six times larger, and the server was answering every one of
        those calls and reporting the real prompt size back in `usage`. Erring LARGE is recoverable
        (a 400 → :func:`_overflow_refit` re-preps once against the server's own count, 47 of them in
        the same window); erring small is silent and permanent.

        A lower bound, so the window is NOT marked final and /props probing continues. Only ever
        raises, and never touches a configured or discovered window — those are authoritative. #12:
        the number comes from the authoritative event, not from a constant someone chose."""
        if self._window_final or not isinstance(prompt_tokens, int) or prompt_tokens <= 0:
            return
        if self._window is _UNSET or self._window is None or prompt_tokens > self._window:
            was = None if self._window is _UNSET else self._window
            rlog.emit("context.window", level="warn", source="accepted-prompt",
                      n_ctx=prompt_tokens, was=was)
            self._window = prompt_tokens
            self._window_guessed = False   # measured, not invented — even though it is a lower bound

    def _calibrate(self, model, usage, estimate: int, rlog, body=None) -> None:
        """Learn the real÷estimate density from a call's REAL prompt-token count (server usage), so
        the floor budgets against truth on later turns. Best-effort — no-op without a usage count.

        The same record also proves how much the server FIT — see :func:`_window_at_least`."""
        usage = usage if isinstance(usage, dict) else {}
        prompt_tokens = usage.get("prompt_tokens")
        # TOTAL, not prompt: the server held the prompt AND the completion at once, so total_tokens
        # is the true lower bound on its window. Using the prompt alone would set the window to
        # roughly the prompt size, and the floor's budget is window MINUS the output reserve — which
        # on a 20k prompt would leave 3.6k and trim harder than the guess it replaced.
        self._window_at_least(usage.get("total_tokens")
                              or ((prompt_tokens or 0) + (usage.get("completion_tokens") or 0))
                              or None, rlog)
        shifted = tokenratio.record(_density_key(model, rlog, body), prompt_tokens, estimate)
        if shifted is not None:
            rlog.emit("context.calibrated", model=model, real=prompt_tokens, est=estimate, ratio=round(shifted, 2))

    def _observe_capacity(self, facts, model, rlog, body=None) -> None:
        """Record authoritative counts/window; no optional refit choice or return value."""
        real, n_ctx = facts.rejection.real, facts.rejection.window
        sent_estimate = facts.prepared.estimate
        tokenratio.record(_density_key(model, rlog, body), real, sent_estimate)
        density = float(real) / float(sent_estimate)
        rlog.emit("context.refit", level="warn", model=model, real=real, est=sent_estimate,
                  n_ctx=n_ctx, safety=round(density, 2))
        # THE SERVER JUST STATED ITS WINDOW. It was being logged and thrown away while the floor ran
        # against a guess. This is the same class of authority as /props — the server's own number
        # about its own context — so it is FINAL, unlike the accepted-prompt lower bound above.
        if isinstance(n_ctx, int) and n_ctx > 0 and not self._window_final:
            rlog.emit("context.window", source="server-error", n_ctx=n_ctx,
                      was=(None if self._window is _UNSET else self._window))
            self._window, self._window_final = n_ctx, True
            self._window_guessed = False

    def _open_with_refit(self, body: dict, stream: bool, rlog, *, _transport=None) -> tuple:
        """Selected capacity policy over required final preparation and single-send custody."""
        from . import assistruntime, capacitypolicy
        runtime = (assistruntime.current() if assistruntime.is_bound() else
                   assistruntime.AssistRuntime.select(level=self._engagement_level))
        transport = ((self._receive_open, urllib.request.urlopen)
                     if _transport is None else _transport)
        sends = 0

        def prepare(safety):
            return capacitypolicy.Prepared(*self._prep(body, stream, rlog, safety_override=safety))

        def send(prepared):
            nonlocal sends
            attempt = sends
            sends += 1
            return self._send_capacity(prepared, body, stream, rlog, attempt, runtime, transport)

        def observe(facts):
            self._observe_capacity(facts, body.get('model'), rlog, body)

        def no_change(source, wire):
            rlog.emit('upstream.error', level='error', url=self._chat_url, error=str(source))
            return ContextRefitNoChange(source, wire)

        services = capacitypolicy.Services(
            prepare, send, observe, rlog.emit,
            lambda value: (capacitypolicy.NoChangeProvenance(value, value.final_wire)
                           if isinstance(value, ContextRefitNoChange) else None),
            no_change, CallerContextRetryNoChange)
        with assistruntime.bound(runtime):
            result = capacitypolicy.dispatch(services, runtime.capacity,
                caller_refit=body.get(bodykeys.CONTEXT_REFIT_NO_CHANGE),
                model=lambda: body.get('model'))
        if isinstance(result.outcome, capacitypolicy.Accepted):
            return result.outcome.response, result.prepared.estimate, result.prepared.capture_path
        e = result.outcome.source
        rlog.emit('upstream.error', level='error', url=self._chat_url, error=str(e))
        error_class = (UpstreamProtocolError if generation.is_protocol_error(
            getattr(e, 'response_error', None)) else UpstreamError)
        err = error_class(str(e), getattr(e, 'response_error', None))
        err.code = getattr(e, 'code', None)
        raise err from e

    def _send_capacity(self, prepared, body, stream, rlog, attempt, runtime, transport):
        """One transport open; custody and parsed facts never grant optional retry authority."""
        from . import assistruntime, capacitypolicy
        data, sent_estimate, capture_path = prepared.wire, prepared.estimate, prepared.capture_path
        with assistruntime.bound(runtime):
            req = urllib.request.Request(self._chat_url, data=data, method="POST", headers=self._headers(sse=stream))
            rlog.emit("upstream.request", url=self._chat_url, model=body.get("model"),
                      stream=stream, n_messages=len(body.get("messages", [])), refit=(attempt > 0))
            receipt = None
            try:
                # THE DEAD-STREAM DEADLINE LIVES AT THE WIRE, FOR STREAMING OPENS.
                #
                # `urlopen`'s timeout is a PER-READ socket deadline, not a total one: a stream that
                # keeps delivering frames may run for hours under it, and one that goes silent
                # raises. That is exactly the condition `rumination.DEAD_STREAM_SECONDS` describes,
                # and the socket is the only place it cannot be suppressed.
                #
                # It used to be checked inside `for raw in resp:` in `chat_watched`, whose own
                # comment reads "The clock is the one signal a quiet server cannot suppress" — and a
                # quiet enough server suppressed it. Walked on shipping-rates-rb x gemma4: TWO
                # frames in twelve and a half minutes, so the loop body ran twice and the 180s test
                # could not be evaluated until the second frame landed at 743.4s. That one call was
                # 78% of the run's wall clock; the coder needed 72 seconds of generation across every
                # other call in the run. Its unit test drives 300 frames and never exercised this.
                #
                # `stream_chat` — the buffered proxy's passthrough, which carries EVERY non-loop
                # request and therefore the whole assists-off arm — had no dead-stream check at all.
                # Measured: the baseline's longest single call is 525 seconds of nothing. At the
                # wire both readers get the deadline without either owning it (#24, #23).
                #
                # Buffered POSTs keep the long timeout: their whole generation arrives as one read,
                # so a short deadline there would cut a working call.
                read_deadline = rumination.WIRE_SILENCE_SECONDS if stream else self._timeout
                from . import receivecapture
                if self._capture_dir is not None and capture_path is None:
                    raise receivecapture.CaptureFailure('configured request capture unavailable; no dispatch')
                receipt = (receivecapture.Receipt(capture_path, request_sha256=hashlib.sha256(data).hexdigest())
                           if capture_path is not None else None)
                receive_open, ordinary_open = transport
                opening = receive_open or receivecapture.default_open_request
                try:
                    if receive_open is None and self._capture_dir is None:
                        # Capture-off retains the transport captured for this operation.
                        resp = ordinary_open(req, timeout=max(read_deadline, 1.0))
                    else:
                        resp = opening(req, timeout=max(read_deadline, 1.0), receipt=receipt)
                except BaseException as exc:
                    if receipt is not None:
                        receipt.partial(exc)
                        if not isinstance(exc, urllib.error.HTTPError):
                            receipt.finish(exc)
                    raise
                return capacitypolicy.Accepted(resp)
            except urllib.error.URLError as e:
                failed_custody = False
                if isinstance(e, urllib.error.HTTPError):
                    from .receivecapture import finalize_http_error
                    try:
                        rejected = _http_error_body(e)
                        callcapture.capture_response(capture_path, rejected, rlog)
                    except BaseException as secondary:
                        # Retain the rejection as primary, but never refit after lost evidence.
                        failed_custody = True
                        e.add_note('secondary HTTP rejection evidence failure: ' + str(secondary))
                        if receipt is not None:
                            receipt.partial(secondary)
                    finally:
                        failed_custody = finalize_http_error(e, receipt) or failed_custody
                real = window = None
                if isinstance(e, urllib.error.HTTPError) and not failed_custody:
                    try:
                        payload = json.loads(_http_error_body(e))
                        inner = payload.get('error') if isinstance(payload.get('error'), dict) else payload
                        if isinstance(inner, dict):
                            real, window = inner.get('n_prompt_tokens'), inner.get('n_ctx')
                    except (ValueError, OSError, AttributeError):
                        pass
                return capacitypolicy.Rejection(e, isinstance(e, urllib.error.HTTPError),
                                                real, window, not failed_custody)

    def _render_prompt(self, body: dict) -> str | None:
        """Ask the server to render the chat body into the flat prompt string the model actually
        tokenizes — chat template applied (tool injection, role markers, reasoning prefill) — via
        /apply-template. This is literally 'what the model sees'. Best-effort; None on failure."""
        payload: dict = {"messages": body.get("messages") or []}
        if body.get("tools"):
            payload["tools"] = body["tools"]
        if body.get("chat_template_kwargs"):
            payload["chat_template_kwargs"] = body["chat_template_kwargs"]
        # EVERY KEY THE TEMPLATE BRANCHES ON, or the capture is a different prompt than the one
        # that ran. `reasoning_effort` was missing, and Bonsai 2's template opens with a line
        # chosen by it: "Reasoning effort is set to low. Keep your thinking brief" vs "...xhigh.
        # Please think carefully ... consider plausible alternatives". It defaults to xhigh, so
        # every capture showed xhigh no matter what was sent, and a walk of those captures reads
        # a knob as dead when it is live (5b, in the evidence a walk is conducted on).
        if body.get("reasoning_effort") is not None:
            payload["reasoning_effort"] = body["reasoning_effort"]
        try:
            req = urllib.request.Request(
                self._base_url + "/apply-template", data=json.dumps(payload).encode("utf-8"),
                method="POST", headers={"Content-Type": "application/json"},
            )
            # Native measurement is best-effort within this endpoint timeout.
            # Unavailability grants no admission authority; successful captures
            # reuse the same complete rendered prompt.
            with self._ordinary_open(req, timeout=_RENDER_TIMEOUT_S) as resp:
                result = json.loads(resp.read())
                p = result.get("prompt") if isinstance(result, dict) else None
                return p if isinstance(p, str) and p else None
        except (urllib.error.URLError, ValueError, OSError):
            return None

    def _tokenize_prompt(self, prompt: str, rlog) -> int | None:
        """Measure the exact rendered local prompt; unavailable is unknown, not zero."""
        try:
            req = urllib.request.Request(
                self._base_url + "/tokenize",
                data=json.dumps({"content": prompt, "add_special": False}).encode("utf-8"),
                method="POST", headers={"Content-Type": "application/json"})
            with self._ordinary_open(req, timeout=_RENDER_TIMEOUT_S) as resp:
                result = json.loads(resp.read())
                tokens = result.get("tokens") if isinstance(result, dict) else None
            return (len(tokens) if isinstance(tokens, list) and tokens
                    and all(type(token) is int and token >= 0 for token in tokens) else None)
        except (urllib.error.URLError, ValueError, OSError):
            return None

    def stream_chat(self, body: dict, rlog) -> Iterator[bytes]:
        """Capture request selection now, not when a delayed iterator starts."""
        from . import assistruntime
        runtime = (assistruntime.current() if assistruntime.is_bound() else
                   assistruntime.AssistRuntime.select(level=self._engagement_level))
        transport = (self._receive_open, urllib.request.urlopen)
        iterator = self._stream_chat(body, rlog, _transport=transport)

        def selected_stream():
            try:
                while True:
                    with assistruntime.bound(runtime):
                        try:
                            item = next(iterator)
                        except StopIteration:
                            return
                    yield item
            finally:
                with assistruntime.bound(runtime):
                    iterator.close()
        return selected_stream()

    def _stream_chat(self, body: dict, rlog, *, _transport) -> Iterator[bytes]:
        """POST a streaming chat completion and yield raw SSE lines (bytes) for the
        caller to forward. Emits ``upstream.request`` / ``upstream.first_token`` /
        ``upstream.done`` with TTFT + tok/s. Token count uses the upstream ``usage``
        block when present, else counts content deltas as a proxy."""
        resp, sent_estimate, capture_path = self._open_with_refit(
            body, True, rlog, _transport=_transport)
        t0 = time.monotonic()
        t_first: float | None = None
        content_chunks = 0
        usage: dict | None = None
        # THE PROXY PATH LOGGED NO REASONING AT ALL. It forwards raw SSE and only counted content
        # deltas, so every passthrough turn's thinking went to the harness — which strips it from
        # history — and nowhere else. 34 of the 47 long turns in one sweep were this path, and not
        # one had a reasoning file to read. The accumulation is a list append per delta; the write
        # happens once, in the finally, so it survives a client disconnect mid-generator too.
        reasoning: list[str] = []
        _rsink: dict = {}
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
                            for ch in obj.get("choices") or []:
                                d = ch.get("delta") or {}
                                rc = d.get("reasoning_content") or d.get("reasoning")
                                if rc:
                                    reasoning.append(rc)
                                    self._stream_reasoning_to_disk(_rsink, capture_path, rc)
                                    if t_first is None:
                                        # A reasoning delta IS a first token. Counting only CONTENT
                                        # meant a turn that thought for four minutes and then errored
                                        # looked, in the log, like a stream that never spoke.
                                        t_first = time.monotonic()
                                        rlog.emit("upstream.first_token",
                                                  ttft_ms=round((t_first - t0) * 1000, 1),
                                                  channel="reasoning")
                            if obj.get("usage"):
                                usage = obj["usage"]
                yield raw
        finally:
            resp.close()
            t_end = time.monotonic()
            # Whether the generator ran to [DONE], the client hung up, or something raised.
            self._save_reasoning(capture_path, "".join(reasoning), None, rlog,
                                 ending="" if usage else "the stream ended without a usage block")
            tokens = (usage or {}).get("completion_tokens") or content_chunks
            self._calibrate(body.get("model"), usage, sent_estimate, rlog, body)
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
        """Capture the operation's selection and bound retry services before its first attempt."""
        from . import assistruntime
        runtime = (assistruntime.current() if assistruntime.is_bound() else
                   assistruntime.AssistRuntime.select(level=self._engagement_level))
        opening, sleeper = self._open_with_refit, time.sleep
        transport = (self._receive_open, urllib.request.urlopen)
        with assistruntime.bound(runtime):
            return self._chat(body, rlog, runtime, opening, sleeper, transport)

    def _chat(self, body: dict, rlog, runtime, opening, sleeper, transport) -> bytes:
        """Non-streaming: return the full upstream response body (bytes).

        Retries the SAME endpoint ONCE on a transient TIMEOUT (a slow-prefill / connection-reset on
        the shared GPU that would otherwise be a dead turn), using the failover module's POLICY
        (`classify_failure` + `decide_action`) with the loop written out here — `failover.run` is the
        generic executor for a multi-route chain and this has exactly one route, so walking is never
        the answer and what it would cost is the error string in the retry log. Buffered, so a retry
        is safe; a stream cannot be."""
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
                resp, sent_estimate, capture_path = opening(body, False, rlog, _transport=transport)
                try:
                    raw = resp.read()
                finally:
                    resp.close()
                break
            except (UpstreamError, OSError) as e:  # OSError → socket read-timeout mid-response
                # Proven capacity no-change is terminal regardless of provider wording.
                # Preserve the original typed exception before any transient classification.
                if isinstance(e, (ContextRefitNoChange, CallerContextRetryNoChange)):
                    raise
                if generation.is_protocol_error(getattr(e, "response_error", None)):
                    raise
                from . import transientpolicy
                choice = transientpolicy.selected_choice(runtime.transient_recovery,
                    lambda: transientpolicy.FailureFacts(
                        failover.classify_failure(getattr(e, 'code', None), str(e)),
                        'upstream', 'upstream', ('upstream',), attempt))
                if choice is None:
                    raise
                action = choice.action
                if not isinstance(action, failover.RetrySame):
                    raise
                attempt = action.attempt
                rlog.emit("upstream.retry", level="warn", attempt=attempt, wait_ms=action.wait_ms, error=str(e))
                sleeper(action.wait_ms / 1000.0)
        t_end = time.monotonic()
        usage = (_try_json(raw) or {}).get("usage")
        self._calibrate(body.get("model"), usage, sent_estimate, rlog, body)
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
        so it never trips the watcher; only runaway thinking does. ``watch=None`` disables only the
        reasoning scanner; selected stream backstops remain active. Explicit policy absence disables
        those optional decisions too, without disabling transport safety."""
        # Ask for the usage block on the terminal chunk (llama.cpp honors this) so the assembled
        # completion carries real completion_tokens — the truncation guard reports them to the model.
        body = {**body, "stream_options": {"include_usage": True}}
        resp, sent_estimate, capture_path = self._open_with_refit(body, True, rlog)
        t0 = time.monotonic()
        t_first: float | None = None

        content: list[str] = []
        reasoning: list[str] = []
        _rsink: dict = {}
        tool_acc: dict[int, dict] = {}
        choice_indices: set = set()
        finished_choices: set = set()
        unsafe_stream = False
        finish: str | None = None
        usage: dict | None = None
        aborted: dict | None = None
        stream_error: str | dict | None = None
        generation_evidence = {}
        wire_raw = bytearray()
        chunks_seen = 0     # SSE frames carrying a choices delta
        streamed_chars = 0  # of those, how many characters cria could actually read
        from . import assistruntime, generationguards
        stream_guard = None
        terminal = False
        saved = False  # the reasoning has been written by an early-exit path; do not write it twice
        # LIVE generation counters for the status ticker's beat tick (operator asked for tok/s on the
        # in-between lines): the beat thread reads these while this call streams. Benign racy reads
        # of two scalars; cleared in the finally so a finished call never shows a stale rate.
        rlog.live_t0 = t0
        rlog.live_chars = 0
        try:
            runtime = (assistruntime.current() if assistruntime.is_bound() else
                       assistruntime.AssistRuntime.select(level=self._engagement_level))
            selected = generationguards.SelectedGuards.from_definitions(runtime.definitions)
            if self._engagement_level < config.DONE_REFUSALS_ENABLED:
                selected = generationguards.SelectedGuards(None, None)
            stream_guard = selected.stream(lambda: generationguards.StreamInput(
                self._resolve_window(rlog), sent_estimate, self._window_guessed, watch, lambda: terminal))
            for raw in resp:
                wire_raw.extend(raw)
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
                    stream_error = dict(err) if generation.is_protocol_error(err) else str(err.get("message") or err) if isinstance(err, dict) else str(err)
                    break
                incoming_evidence = obj.get(generation.EVIDENCE) or {}
                generation_evidence.update(incoming_evidence)
                unsafe_stream = unsafe_stream or incoming_evidence.get("incomplete") is True
                chunks_seen += 1
                for choice in obj.get("choices", []):
                    choice_index = choice.get("index", 0)
                    unsafe_stream = unsafe_stream or choice_index in finished_choices
                    choice_indices.add(choice_index)
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
                        self._stream_reasoning_to_disk(_rsink, capture_path, rc)
                    tcs = delta.get("tool_calls")
                    for tc in tcs or []:
                        prior = tool_acc.get(tc.get("index", 0), {})
                        fn = tc.get("function") or {}
                        unsafe_stream = unsafe_stream or bool(
                            (prior.get("id") and tc.get("id") and prior["id"] != tc["id"])
                            or (prior.get("name") and fn.get("name") and prior["name"] != fn["name"])
                            or (tc.get("type") and tc["type"] != "function"))
                    _accumulate_tool_deltas(tool_acc, tcs)
                    # Feed the degenerate-run backstop from EVERY generated stream — content,
                    # reasoning, AND tool-call arguments (which the rumination watcher below skips) —
                    # so a stuck single-token runaway is caught wherever it streams.
                    for frag in (delta.get("content"), rc,
                                 *(((tc.get("function") or {}).get("arguments")) for tc in (tcs or []))):
                        if frag:
                            streamed_chars += len(frag)   # anything cria could actually read
                            rlog.live_chars += len(frag)  # the ticker's live tok/s numerator
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
                        finished_choices.add(choice_index)
                        unsafe_stream = unsafe_stream or finish not in ("stop", "tool_calls")
                if obj.get("usage"):
                    usage = obj["usage"]
                if stream_guard is not None:
                    choices = obj.get("choices", [])
                    terminal = (len(choice_indices) == 1 and not unsafe_stream
                                and (not choices or (len(choices) == 1
                                     and choices[0].get("finish_reason") == "tool_calls"))
                                and finish == "tool_calls" and _complete_native_calls(tool_acc))
                    decision = stream_guard.feed(obj, lambda: time.monotonic() - t0,
                                                 lambda: "".join(reasoning), lambda: "".join(content), rlog)
                    if decision.status is generationguards.StreamStatus.ABORT:
                        aborted = decision.verdict
                        break
        except TimeoutError as e:
            # The mandatory socket deadline survives optional-policy opt-out.
            # A selected guard owns the abort verdict; without one, preserve an
            # incomplete-stream error and its raw evidence, never new coaching.
            elapsed = round(time.monotonic() - t0, 1)
            if stream_guard is not None:
                aborted = stream_guard.wire_timeout(elapsed, str(e), rlog).verdict
            else:
                # The socket deadline is required transport safety, not consent
                # to optional coaching. Preserve the incomplete-stream error path.
                finish = None
                generation_evidence["wire_timeout"] = {"seconds": elapsed, "error": str(e)}
            self._save_reasoning(capture_path, "".join(reasoning), aborted, rlog,
                                 ending=f"the wire went silent for {elapsed}s and the read was cut")
            saved = True
        except BaseException as e:                       # noqa: BLE001 — re-raised below
            # WHATEVER KILLED THE READ, THE THINKING SURVIVES IT. Saved here rather than only on the
            # clean path, because the turns where the answer is lost are the ones whose reasoning is
            # worth most.
            self._save_reasoning(capture_path, "".join(reasoning), aborted, rlog,
                                 ending=f"{type(e).__name__}: {e}")
            saved = True
            raise
        finally:
            resp.close()
            rlog.live_t0 = None  # the ticker must never compute a rate from a finished call
        if stream_error is not None and generation.is_protocol_error(stream_error):
            self._save_reasoning(capture_path, "".join(reasoning), aborted, rlog,
                                 ending=stream_error.get("reason") or stream_error.get("message"))
            evidence = dict(stream_error.get(generation.EVIDENCE) or {})
            evidence["wire_raw_hex"] = bytes(wire_raw).hex()
            evidence["stream_prefix"] = {"content": "".join(content), "reasoning_content": "".join(reasoning),
                                         "action_prefixes": tool_acc}
            stream_error[generation.EVIDENCE] = evidence
            callcapture.capture_response(capture_path, {"error": stream_error}, rlog)
            raise UpstreamProtocolError(stream_error.get("message", ""), stream_error)
        if stream_error is not None:
            # …and before the buffered re-ask discards it. The model really did think this; the only
            # thing wrong with the turn is that its transport broke.
            self._save_reasoning(capture_path, "".join(reasoning), aborted, rlog,
                                 ending=f"the stream errored and the request was re-asked buffered: {stream_error}")
            saved = True
            # Re-ask the SAME request buffered. The answer still comes from the model — cria is not
            # repairing the fragment, it is discarding it and asking again down a path that works.
            # The watcher is forfeited for this turn (nothing to watch in a buffered call), which is
            # the right trade: a whole lost turn costs more than one unwatched one.
            rlog.emit("upstream.stream_error", level="warn", error=stream_error,
                      dropped_tool_arg_chars=sum(len("".join(s["args"])) for s in tool_acc.values()),
                      dropped_content_chars=len("".join(content)))
            return self.chat({k: v for k, v in body.items() if k != "stream_options"}, rlog)
        if finish is None and aborted is None:
            message = "Upstream stream ended without a terminal generation status"
            evidence = {**generation_evidence, "wire_raw_hex": bytes(wire_raw).hex(),
                        "stream_prefix": {"content": "".join(content), "reasoning_content": "".join(reasoning),
                                          "action_prefixes": tool_acc}}
            error = {"type": generation.INCOMPLETE_STREAM_ERROR, "message": message, generation.EVIDENCE: evidence}
            self._save_reasoning(capture_path, "".join(reasoning), aborted, rlog, ending=message)
            callcapture.capture_response(capture_path, {"error": error}, rlog)
            failure = UpstreamError(message, error)
            failure.code = None
            raise failure
        t_end = time.monotonic()
        completion = _assemble_completion(body.get("model"), content, reasoning, tool_acc, finish, usage, aborted)
        if generation_evidence:
            completion[generation.EVIDENCE] = generation_evidence
        if aborted is not None:
            completion.setdefault(generation.EVIDENCE, {})["wire_raw_hex"] = bytes(wire_raw).hex()
        completion = generation.safe_completion(completion)
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
        if not saved:
            self._save_reasoning(capture_path, "".join(reasoning), aborted, rlog)
        callcapture.capture_response(capture_path, completion, rlog)  # the assembled answer, on disk
        self._calibrate(body.get("model"), usage, sent_estimate, rlog, body)
        # FRAMES AND READABLE CHARS, ALWAYS. Diagnosing why a guard declined needs the numbers it
        # declined on, and nothing recorded them: the 12-minute dead call above could only be pinned
        # down by DEDUCING the frame count from which guards did NOT fire (#12).
        rlog.emit("upstream.done", total_ms=round((t_end - t0) * 1000, 1), tokens=tokens,
                  tok_per_s=tok_s, from_usage=bool(usage), aborted=bool(aborted),
                  frames=chunks_seen, read_chars=streamed_chars)
        return json.dumps(completion).encode("utf-8")


    @staticmethod
    def _partial_path(capture_path: str | None) -> str:
        return f"{capture_path}.reasoning.partial.txt" if capture_path else ""

    @staticmethod
    def _stream_reasoning_to_disk(state: dict, capture_path: str | None, chunk: str) -> None:
        """Append a reasoning delta to a partial file AS IT ARRIVES, so a killed process still leaves
        the thinking behind.

        `_save_reasoning` writes at the END of the stream, which covers a clean finish, a stream error
        and an exception — but not the process being terminated. The suite kills a run at its
        milestone floor, and `rust-toml-cli x ternary-bonsai` call 0043 has a prompt and a request
        body and no reasoning file at all: the model's last thoughts before the kill, which are the
        ones that say what it was about to do, gone. The operator's instruction was "all streamed
        reasoning logged, whether it finishes or not", and a SIGKILL cannot run a `finally`.

        Flushed every few kilobytes rather than every token: a delta is a handful of bytes and an
        fsync per token would put the disk in the streaming path. The bound on what a kill can lose
        is one flush window, not the whole turn."""
        if not capture_path:
            return
        try:
            fh = state.get("fh")
            if fh is None:
                fh = state["fh"] = open(Upstream._partial_path(capture_path), "w",
                                        encoding="utf-8", errors="replace")
                _REASONING_SINKS[capture_path] = state
            fh.write(chunk)
            state["pending"] = state.get("pending", 0) + len(chunk)
            if state["pending"] >= _REASONING_FLUSH_BYTES:
                fh.flush()
                state["pending"] = 0
        except OSError:
            state["fh"] = None            # disk trouble is never worth breaking the stream over

    @staticmethod
    def _close_partial(_unused, capture_path: str | None) -> None:
        """Drop the partial once the real file is written — it exists only to survive a kill."""
        state = _REASONING_SINKS.pop(capture_path, {}) or {}
        fh = state.get("fh")
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass
            state["fh"] = None
        try:
            p = Upstream._partial_path(capture_path)
            if p and os.path.exists(p):
                os.unlink(p)
        except OSError:
            pass

    def _save_reasoning(self, capture_path: str | None, text: str, aborted, rlog,
                        ending: str = "") -> None:
        """Persist the coder's FULL reasoning block — UNTRUNCATED — to a sibling of the call capture
        (``NNNN-<phase>.reasoning.txt``), so every ``<think>`` is inspectable after the fact. cria
        watches the reasoning live for the rumination detector and would otherwise discard it (the
        harness strips reasoning from history), so this is the only record of what the model thought.
        Best-effort; no-op when there's no reasoning or capture is off. A ``coder.reasoning`` event
        points at the file (with token/char counts + whether the detector aborted this turn).

        WHETHER THE STREAM FINISHED OR NOT (operator, 2026-08-13: "I want all streamed reasoning
        logged. Whether it finishes or not."). This used to run only on the ONE clean exit past the
        stream-error branch, so two whole classes of turn wrote nothing:

          * a mid-stream error — cria re-asks the request buffered and RETURNS from inside the loop's
            aftermath, discarding everything the model had already thought;
          * any exception in the read loop — the `finally` closed the socket and nothing saved.

        Those are exactly the turns whose thinking is worth most, because the answer is gone. The
        save now happens on every exit, and ``ending`` names which one so a partial file is never
        mistaken for a complete one."""
        if not capture_path:
            return
        if not text:
            self._close_partial(getattr(self, "_rsink_last", {}), capture_path)
            return
        # When the rumination detector aborted this turn, bracket the reasoning with a loud marker so
        # a fired guard is obvious IN the file (not just cross-referenced from the log). Non-fired
        # reasoning stays pure (the full block, no header) so it's still greppable/diffable as-is.
        bar = "─" * 72
        if aborted:
            # SAY WHICH GUARD, AND ONLY ITS OWN NUMBERS. Four different backstops abort a stream and
            # this header described all four as the RUMINATION guard, rendering that guard's two
            # counters — which only IT sets. Measured on cycle 4 cell 4 (feed-pipeline-java ×
            # gemma4): a WINDOW-EXHAUSTED abort was filed as
            #   "⟦RUMINATION GUARD FIRED⟧ None second-guessing markers · ~None reasoning tokens"
            # A guard must not invent the numbers it fired on (#12), and "None second-guessing
            # markers" is a false fact about why the stream stopped (#5b) — the same defect this
            # file's degenerate-tail branch already records having fixed once, left standing on the
            # three siblings. Each guard now names itself and prints what it actually counted.
            body = _abort_header(aborted) + f"\n{bar}\n{text}\n\n" + _abort_footer(aborted)
        elif ending:
            # An UNFINISHED block, labelled as one at both ends. A partial trace read as a complete
            # one is the same lie as a truncated file (#5b) — and the label is the whole reason this
            # is worth keeping rather than dropping.
            body = (f"⟦INCOMPLETE REASONING⟧ the stream did not finish: {ending}\n"
                    f"⟦what the model had thought up to that point is below, unclipped⟧\n{bar}\n"
                    f"{text}\n\n⟦— stream ENDED HERE: {ending} —⟧\n")
        else:
            body = text  # the WHOLE block — deliberately not clipped
        self._close_partial(getattr(self, "_rsink_last", {}), capture_path)
        try:
            p = Path(capture_path)
            rpath = p.parent / (p.stem + ".reasoning.txt")
            rpath.write_text(body, encoding="utf-8")
            rlog.emit("coder.reasoning", path=str(rpath), chars=len(text),
                      reasoning_tokens=len(text) // 4, aborted=bool(aborted),
                      incomplete=bool(ending), ending=ending or None)
        except OSError as e:
            rlog.emit("coder.reasoning_error", level="info", error=str(e))


def _complete_native_calls(acc: dict[int, dict]) -> bool:
    """Only an unambiguous, fully parsed native call set can settle the reasoning watch."""
    if not acc:
        return False
    ids = set()
    for slot in acc.values():
        cid, name = slot.get('id'), slot.get('name')
        if not isinstance(cid, str) or not cid or cid in ids or not isinstance(name, str) or not name:
            return False
        ids.add(cid)
        try:
            args = json.loads(''.join(slot.get('args', [])))
        except (ValueError, TypeError):
            return False
        if not isinstance(args, dict):
            return False
    return True


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
        completion[bodykeys.RUMINATION] = aborted
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
