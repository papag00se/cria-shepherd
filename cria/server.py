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

import copy
import functools
import hashlib
import json
import os
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, replace
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .imageworkflow import current as _image_current
from . import imageassembly
from . import upstream as _image_wire
from .imageprotocol import ImageUnavailable

from . import bodykeys, callauth, repohealth, dirguard, handoffdistill, handoffmemo, memoryhandoff, privatenames, system1wiring, windowcaps
from . import (callcapture, compat, focustrim, groundtruth, massage, modelview, probegate, prompts,
               responses, rumination, selfcompact)
from . import admission, classify, loweringoptions
from .classify import JUDGE_MAX_TOKENS, Classifier
from . import content_reduce
from .content_reduce import est_tokens
from . import config, assistruntime
from .config import Config
from . import brave, envfile, webfetch
from .events import EventLog
from .heartbeat import Heartbeat
from .indicators import MARKER, Indicator, inject_buffered, strip_history, strip_note_lines, wrap_stream
from .loop import (
    Loop,
    _briefing_disk_truth,
    _drop_harness_frame,
    _PROSE_DROPPED_MARKER,
    _HandoffOrigin,
    CONTINUATION_MARKER,
    LoopContext,
    LoopStore,
    _fetch_ground_truth,
    _history_root,
    ask_closed,
    completion_to_sse,
    gate_age,
    newer_own_run,
    reframe_compaction,
    strip_prose_dropped_marker,
    validate_compaction_briefing,
    session_key,
    SUMMARIZE_MAX_TOKENS,
)
from .planner import Planner, _extract_cwd
from .routing import Router
from .statusline import StatusWriter  # noqa: F401 — re-exported for tests
from . import statusline
from . import toolmenu
from .shelltool import find_shell_tool
from .turnstats import StatsStore
from .upstream import Upstream, UpstreamError, ReadFitUnknown, ReadFitOverflow
from . import wsview, generation
from .writeproxy import (advertise, native_search_name, needs_translation, redact_secrets,
                         represent_inbound, translate_outbound, retain_externalizations,
                         observe_externalization_results)


def _error_sse(message: str | dict) -> bytes:
    """Convey an error inside an already-open SSE stream (headers are 200 by then)."""
    payload = {"error": message if isinstance(message, dict) else {"message": message, "type": "upstream_error"}}
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\ndata: [DONE]\n\n"


def _visible_web_calls(messages: list) -> tuple[list, list]:
    """The web_fetch (url, find, cursor) keys and web_search queries STILL PRESENT in the conversation
    (post-represent_inbound, so the calls are labeled web_fetch/web_search). Feeds the exact-repeat
    gate so it refuses a repeat only while the model can still read that result — not after
    compaction elided it."""
    from . import denial, researchpolicies
    from .toolargs import parse_args
    # A CALL THAT WAS REFUSED NEVER RAN, so its result is not in the conversation and cannot be
    # "still present" in it. This scanned assistant tool_calls only, and a refused call is still an
    # assistant tool_call — so cria recorded a query it had itself blocked as one the coder had run,
    # then refused the NEXT attempt with "You already ran web_search … Its results are already in
    # this conversation above — use them". The query never ran; the results exist nowhere. Walked on
    # shipping-rates-rb x nemotron-elastic 1787432916, three refusals deep. The sibling branch — the
    # one that names a spill file — carries a comment describing this same failure costing 8 refusals
    # in an earlier run; the fix was applied there and not here (#5b).
    refused = denial.refused_call_ids(messages)
    paired = denial.paired_results(messages)
    fetch_keys, queries = [], []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            if str(tc.get("id") or "") in refused:
                continue
            fn = tc.get("function") or {}
            name = fn.get("name")
            if name == "web_fetch":
                a = parse_args(fn.get("arguments"))
                if a.get("url"):
                    find = str(a["find"]) if a.get("find") else ""
                    cursor = str(a["cursor"]) if a.get("cursor") not in (None, "") else ""
                    raw = bool(a.get("raw"))
                    if raw:
                        cursor = ""
                    result = paired.get(str(tc.get("id") or ""))
                    report = (result.get(bodykeys.RESULT_REPORT) or {}) if result else {}
                    fetch_keys.append(researchpolicies.VisibleFetch.from_report(
                        (str(a["url"]), find, cursor, raw),
                        ran=denial.proof(result) == denial.RAN, facts=report.get("fx"),
                        stored="st" in report))
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
    # NOT GATED ON THE PLANNER. web_search reaches the coder whether the planner is on or off, and
    # the planner is off on every real run — so the one warning that exists to make a missing key
    # visible was itself silent in exactly the configuration everything uses. That is the failure
    # this function's own docstring names: "a misconfiguration is visible instead of silently
    # degrading — the class that hid the Brave-key bug".
    if not brave.api_key():
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
# NO CAPS. This listing rides in the reply the HARNESS stores as the session's entire remembered
# past, under a header reading "on disk right now — do not re-create them" — so an entry past a cap
# was not merely missing, it was implicitly denied. Naming the remainder ("…and 17 more entries")
# does not fix that: the coder cannot avoid re-creating a file it was never told the name of.
# Names are cheap and the context floor is the one place a list may be narrowed (#5).
_COMPACT_TOP_MAX = None
_COMPACT_KIDS_MAX = None
LOCAL_COMPACT_MARKER = admission.LOCAL_COMPACT_MARKER


def _latest_user_text(messages: list) -> str:
    """The latest user turn's text, or "" — the ONE walk both `_is_compaction_request` (the marker
    check) and `_recognize_compaction` (the unmarked-compaction judge) read a turn's text through,
    so neither can drift from what the other considers "the latest user turn"."""
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            return _text_of_msg(m)
    return ""


def _is_compaction_request(messages: list) -> bool:
    """True when the latest user turn is the harness's compaction/summarize request (see marker)."""
    return LOCAL_COMPACT_MARKER in _latest_user_text(messages)


def _selected_handoff(server=None):
    runtime = (assistruntime.current() if assistruntime.is_bound()
               else getattr(server, "pilot_runtime", assistruntime.current()))
    return runtime.harness_memory_handoff


def _recognize_compaction(body: dict, server, rlog, *, definition=...) -> bool:
    """Selected Source recognition; marker-only routing remains mandatory when absent.

    Harness-agnostic recognition of a compaction/summarize turn the operator has NOT wired the
    `<<<LOCAL_COMPACT>>>` marker onto (see `_is_compaction_request`) — Codex's own default
    `compact_prompt` is exactly this case, and with no `compact_prompt` set in the harness config it
    is what EVERY harness compaction sends. Layered, per principle #8/#18: no Codex metadata sniff,
    no keyword/verb list standing in for judgment — deterministic structure narrows the field, and
    only a genuinely ambiguous remainder ever reaches a reasoner.

    1) DETERMINISTIC TRIGGERS, all free (no model call):
       - the request's tool menu is empty/absent. An ordinary coding turn always advertises its
         tool menu; a summarize turn structurally has nothing for the model to call. Alone this
         already excludes every ordinary task, so a request with tools present costs nothing extra
         here — same call count as before this function existed.
       - `[routing] context_fixes` (LEVEL 3+) is on. Nothing downstream of recognition (the
         hardening in `_compaction_body`/`_harden_compaction_reply`) is reachable below level 3, so
         asking below it would spend a call whose answer cannot change what ships.
       - the transcript has a PRIOR assistant/tool turn. A checkpoint/handoff summary always has
         prior work to fold — by construction it cannot be a session's first turn. This is
         structural (a role check), not a reading of what the turn says, and for free excludes the
         ordinary "no tools, first message" chat/title call that would otherwise cost a reasoner
         call on every such turn campaign-wide.
    2) ONE FOCUSED CLOSED QUESTION — only once every trigger above fires and the marker is absent:
       "is the latest user turn a request to summarize this conversation for continuation?" (#8's
       corollary: a single focused question beats a keyword list that must be retuned every time a
       harness phrases its prompt differently).

    FAIL-SAFE DIRECTION: no reasoner CONFIGURED (`server.reasoner_role is None`, checked explicitly
    below — `reasoner_upstream` alone is not proof of a reasoner: it falls back to the shared/coder
    endpoint unconditionally), an empty/unreadable turn, or a NO/undecidable verdict all mean
    "not recognized" — the turn proxies exactly as it did before this function existed (today's
    status quo, the bug this candidate targets). The opposite failure — misrouting an ordinary
    no-tool turn (a plain question) through the compaction hardening machinery: the compactor's
    tuned sampling, fetch/inventory/check appendices built for a session's transcript, the
    empty-briefing retry — would inject compaction-shaped assists into a reply that isn't one and
    risks answering the wrong question entirely (assists are footguns, #1). An unrecognized
    compaction is a known, bounded, PRE-EXISTING gap; a wrongly hardened ordinary reply would be a
    NEW one. So this recognizer only ever WIDENS what counts as compaction from the marker-only
    baseline, never narrows it, and any doubt resolves toward that baseline.
    """
    definition = _selected_handoff(server) if definition is ... else definition
    if definition is None:
        return _is_compaction_request(body.get("messages", []))  # required routing handshake
    def chat(call, log):
        return server.reasoner_upstream.chat(call, log)
    recognized = definition.recognize(body, selected=True,
        context_fixes=server.cfg.routing.context_fixes, chat_fn=chat,
        role=server.reasoner_role, ask=ask_closed, rlog=rlog)
    if type(recognized) is not bool:
        raise ValueError("Harness handoff recognition must return bool")
    return recognized


# Last-known harness cwd per session. A harness advertises its workspace (Codex's <cwd>) in the
# environment preamble, but a COMPACTION/summarize turn arrives without it — re-extracting would then
# yield None and the workspace would go "unknown" mid-session. Remember it per session so the dirguard
# keeps bounding to the RIGHT repo (never cria's own dir) across the whole session. Bounded like the
# webfetch gate stores. The loop persists its own copy on the session (sess.workspace_root).
_CWD_BY_SESSION: dict[str, str] = {}


def _session_cwd(sess_key: str, messages: list, rlog=None, *, lexical: bool = False) -> str | None:
    """The harness's workspace cwd for this session: the freshly-advertised <cwd>, else the last one
    remembered for the session. NEVER '.' (cria's OWN dir) — an unknown cwd stays None so callers do
    no workspace work rather than target cria's source tree.

    IT IS NOT CHECKED AGAINST CRIA'S DISK, and it must not be. This is a path the HARNESS announced,
    about the HARNESS's filesystem. `os.path.isdir` on it answers for the machine cria runs on, which
    is the same machine only by accident — the likely deployment is cria beside the model server
    while the harness runs on someone's workstation. A reachability test here would blank a perfectly
    valid workspace whenever the two differ, and every mechanism downstream would then abstain while
    reporting no problem at all.

    What replaced the test is :mod:`cria.wsview`: the path is a NAME, and everything anyone wants to
    know about what is at that name is answered by asking the harness. So this function's only job is
    the name, and ``lexical`` no longer distinguishes anything — it is kept because callers pass it
    and because it says at the call site that a containment boundary is a string comparison."""
    cwd = _extract_cwd(messages)
    if cwd == ".":
        # A stray "." IS cria's own working directory, and a workspace reader pointed at it would
        # inspect cria's source tree and report it as the coder's project. Refused here, where the
        # path is decided, rather than at each of the callers that once had to remember to.
        cwd = ""
    if cwd:
        if len(_CWD_BY_SESSION) > 512:
            _CWD_BY_SESSION.clear()
        _CWD_BY_SESSION[sess_key] = cwd
    return cwd or _CWD_BY_SESSION.get(sess_key)


def _remember_session_cwd(sess_key: str, cwd: str) -> str:
    """Record a workspace root learned from somewhere other than `<cwd>`, under the same key
    `_session_cwd` reads. One owner for "the harness's workspace for this session"."""
    if cwd and cwd != ".":
        if len(_CWD_BY_SESSION) > 512:
            _CWD_BY_SESSION.clear()
        _CWD_BY_SESSION[sess_key] = cwd
    return cwd


def carry_chat_system(body: dict) -> None:
    """Chat Completions: carry the caller's system/developer text as CALLER INSTRUCTIONS, exactly as the
    Responses translation (`responses.to_chat_body`) carries `instructions` and developer items.

    Until now a Chat caller's system message was removed twice — `_proxy_body` on the relay path and
    `steppreparation.assemble_base` on the coder path, both of which keep only messages carrying
    `bodykeys.CALLER_INSTRUCTIONS` — and nothing told the model. A 100-token persona and a 60,000-token
    rulebook vanished identically while the same text sent as Responses `instructions` reached the
    model. One owner now marks it at the Chat edge: every system/developer message is folded, in order,
    into ONE leading `system` message with the marker (a second leading system message breaks strict
    chat templates). The text of the first `system`-role message is the harness's base prompt and rides
    as `CALLER_PERSONA`, the only part the context floor may swap for its labelled stand-in under window
    pressure; `developer` messages are the caller's configured constraints and are never reducible.
    cria's own coder system leads and cria's safety/tool rules are not displaced (`assemble_base`).

    A body with no system/developer message, an already-marked one (Responses), or no usable text is
    left byte-for-byte as it was."""
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return
    carried, rest, persona, at, used = [], [], "", 0, 0
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") not in ("system", "developer"):
            rest.append(m)
            continue
        if m.get(bodykeys.CALLER_INSTRUCTIONS):
            return                      # Responses translation already did this
        content = m.get("content")
        text = ("\n".join(p.get("text") or "" for p in content if isinstance(p, dict))
                if isinstance(content, list) else content if isinstance(content, str) else "")
        if not text.strip():
            rest.append(m)
            continue
        if not persona and m["role"] == "system":
            persona, at = text, used
        carried.append(text)
        used += len(text) + 2
    if not carried:
        return
    # The span lets the context floor reduce the persona on the relay path too (the coder path anchors its own
    # span in `assemble_base`); without it an oversized one is refused whole rather than reduced with its label.
    body["messages"] = [{"role": "system", "content": "\n\n".join(carried), bodykeys.CALLER_INSTRUCTIONS: True,
                         **({bodykeys.CALLER_PERSONA: persona, bodykeys.CALLER_SPAN: {"start": at, "text": persona}}
                            if persona else {})}, *rest]


def _proxy_body(body: dict, own_prompt: bool = False, workspace: str | None = None) -> dict:
    """The proxy (relay) path — used when cria isn't orchestrating (a question, or an aux
    harness call the loop declined, e.g. Codex's UI title-generation) — still DROPS the
    harness's agent system/developer prompt unless it is marked caller instructions (Responses
    `instructions`/developer items, and a Chat caller's system/developer text via
    :func:`carry_chat_system`). The request's own instructions live in its user messages and still
    drive it; cria imposes no orchestration prompt of its own here. (The coder path replaces any
    UNMARKED system text separately, in loop._frame_for_item, and leads with cria's coder system
    prompt; marked caller instructions ride behind it.)"""
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return body
    if own_prompt and any(m.get("role") in ("system", "developer") for m in msgs if isinstance(m, dict)):
        # From CONTEXT_FIXES up cria owns the prompt on this path too: every system/developer slot the harness
        # filled (found by slot, never by wording) is replaced by cria's coder prompt and its short harness brief.
        rest = [m for m in msgs if m.get("role") not in ("system", "developer")]
        brief = prompts.render("harness_brief", workspace=workspace) if workspace else ""
        system = prompts.load("coder_system") + (f"\n\n{brief}" if brief else "")
        return {**body, "messages": [{"role": "system", "content": system}, *rest]}
    kept = [m for m in msgs if m.get("role") not in ("system", "developer")
            or m.get(bodykeys.CALLER_INSTRUCTIONS)]
    if len(kept) == len(msgs):
        return body  # nothing to strip → same object
    return {**body, "messages": kept}


def _last_gate_flag(server, sess_key: str) -> str:
    """The session's last gate verdict, or "". One lookup for both users of it — the compactor's
    INPUT (`selfcompact.checks_input`, so the writer does not derive build state by reading) and the
    briefing's OUTPUT appendix (`_last_checks_note`, so the fact survives if the writer omits it)."""
    loop = getattr(server, "loop", None)
    sess = loop._store.get(sess_key) if loop is not None else None
    return getattr(sess, "last_gate_flag", "") if sess is not None else ""


def _gate_age(server, sess_key: str) -> int:
    """How many of the coder's OWN calls have run since the last gate. 0 when cria cannot say.

    ONE OWNER for both halves of the same fact. The OUTPUT appendix (`_last_checks_note`) has stamped
    the age since the incident that cost a green build; the compaction WRITER's input framing went on
    telling the writer the pinned block outranks the transcript however old it was, and that cost a
    second run (see `selfcompact.checks_input`)."""
    loop = getattr(server, "loop", None)
    sess = loop._store.get(sess_key) if loop is not None else None
    return gate_age(sess)


def _last_checks_note(server, sess_key: str) -> str:
    """The most recent gate verdict, verbatim, for the compaction summary — deterministic check
    truth the model-authored briefing kept omitting (and on gemma the briefing never materializes
    at all: 4-of-4 compactor passes across g1/g2 leaked, so the appendices ARE the memory; the
    post-compaction coder otherwise re-learns 'tests are failing' by re-running them). Empty when
    no gate has spoken or the last gate was clean — silence over noise."""
    flag = _last_gate_flag(server, sess_key)
    if not flag:
        return ""
    # HOW OLD, NOT JUST WHAT. "most recent run" is true of a finding gathered twenty calls ago and
    # reads as current; when the coder's own build has gone green since, the block is cria asserting
    # a state the coder has already disproved. It cost a green build once — see `last_gate_seq`.
    since = _gate_age(server, sess_key)
    # `since` is a loop.GateAge: the age AND whether no edit/write tool call has landed in it. Only when
    # cria's own record shows none does the note say so; otherwise (or when it cannot tell) it is the
    # unconditional wording.
    stale = (prompts.fill(prompts.load("checks_note_staleness_unedited" if getattr(since, "unedited", False)
                                       else "checks_note_staleness"), calls=str(since))
             if since >= _CHECKS_STALE_AFTER else "")
    # Anchored to the HANDOFF, never to "now": this text is baked into the briefing the harness keeps
    # in its history, so a "N calls ago" would stay N for every later call while the truth moved on
    # (A6 walk seg-11/18/19: "You have run 8 of your own commands since" repeated unchanged). Said
    # as of the moment it was written, it stays true however long it is carried (#5b).
    ages = prompts.load_map("compaction_check_age")
    age = prompts.fill(ages["aged"], calls=str(since)) if since else ages["fresh"]
    loop = getattr(server, "loop", None)
    newer = newer_own_run(loop._store.get(sess_key)) if loop is not None else ""
    return prompts.fill(prompts.load("checks_note"), age=age, flag=flag, staleness=stale + newer)


# How many of the coder's own forwarded calls may pass before the check block stops presenting
# itself as the current state. Two is enough for one build-and-look; the incident ran 24 prompts.
# The compaction writer's INPUT framing is gated on the same number, so the two halves of one fact
# cannot disagree about when it went stale.
_CHECKS_STALE_AFTER = selfcompact.CHECKS_STALE_AFTER


def _session_gate_plan(server, sess_key: str):
    """The live GatePlan for this session, or None. Same store lookup as :func:`_last_checks_note`.

    The harness-compaction path composes a transcript from the HARNESS's messages, which carry raw
    gate results that never passed through the loop's cleaner. Without the plan those clean to the
    most forgiving sentence cria can produce (see selfcompact.compaction_request)."""
    loop = getattr(server, "loop", None)
    sess = loop._store.get(sess_key) if loop is not None else None
    return getattr(sess, "gate_plan", None) if sess is not None else None


@dataclass(frozen=True)
class _HandoffEvidenceAdapter:
    """Required role filtering and selected preamble, not an optional hardener."""
    drop_harness_frame: Callable[[list[dict]], list[dict]]


def _compaction_messages(messages: list) -> list[dict]:
    """The model-authored history eligible to become compaction evidence — everything except the
    harness's own compaction/summarize ASK, excluded BY POSITION (the latest user turn, the same
    walk `_is_compaction_request`/`_latest_user_text` do), not by matching `LOCAL_COMPACT_MARKER`
    text.

    Matching the marker text left the UNMARKED case (Codex's own default `compact_prompt`,
    recognized via `_recognize_compaction`) with nothing to match: its ask — "...What remains to
    be done (clear next steps)..." — stayed in the evidence as the LAST transcript line, reading
    as an instruction still to follow rather than a request to fold (replayed live against p27
    CALL0046: it survived into the writer's evidence, the empty-briefing retry, and the validator's
    transcript — exactly the g8 0187/0188 failure `_compaction_transcript`'s own "ask goes last"
    comment exists to prevent, and `tests/compaction_handoff/test_compaction_handoff_evidence.py`
    asserts for the marked case: the harness's own ask never reaches the evidence). A compaction
    ask is ALWAYS the harness's latest user turn, whatever it says — so drop that one turn by position, unconditionally."""
    return memoryhandoff.evidence_messages(messages, _HandoffEvidenceAdapter(_drop_harness_frame))


def _compaction_transcript(messages: list, files_list: str = "", gate_plan=None,
                           checks: str = "", checks_age: int = 0) -> str:
    """The conversation to be briefed, as flat text — the SAME preparation cria's internal
    compaction and steer author use: the harness's agent frame dropped (Codex ships ~7.8K tokens of
    update_plan/apply_patch docs and PLUGIN BLURBS — measured leading the g7 transcript, so the
    briefing model read plugin ads before any work), gate blobs cleaned, then serialized. Structured
    tool-call turns become text lines: nothing for a weak model to pattern-match into a tool call."""
    # cria's ask goes LAST, after the evidence — so nothing in the transcript out-recencies it.
    # Composed in ONE place (selfcompact.compaction_request) so this path and loop's self-compaction
    # cannot drift apart again; they already did once, and the sibling failed for months.
    return selfcompact.compaction_request(_compaction_messages(messages), files_list, gate_plan,
                                          checks, checks_age)


def _handoff_services(system1=None):
    """The shared handoff services. ``system1`` (the service's trained classifier, or None) is bound
    into the briefing validator here so the harness-owned compaction asks the same retrospective
    question the loop's self-compaction does; without it the validator is the unchanged function."""
    validate = (validate_compaction_briefing if system1 is None
                else functools.partial(validate_compaction_briefing, system1=system1))
    return memoryhandoff.EvidenceServices(_drop_harness_frame,
        lambda root: groundtruth.workspace_inventory(root, flavor="briefing"),
        _workspace_listing, _fetch_ground_truth, _briefing_disk_truth,
        validate, _proxy_body, SUMMARIZE_MAX_TOKENS, topic_judge=system1)


def _handoff_session(server, key):
    driver = getattr(server, "loop", None)
    return driver._store.get(key) if driver is not None else None


def _observe_handoff_write_results(server, key, messages):
    owner = _handoff_session(server, key)
    if owner is not None:
        from .loop import _note_write_results
        _note_write_results(owner, messages)
    return owner


def _handoff_facts(server, key, body, rlog, owner):
    messages = body.get("messages", [])
    origin = getattr(owner, "handoff_origin", None)
    roots = [messages[i] for i in selfcompact.root_user_indices(messages)]
    if isinstance(origin, _HandoffOrigin):
        # A proven prior handoff is history, even if the harness moved it into the root.
        prior = [m for m in roots if (origin.matches_continuation(_text_of_msg(m))
                                      or origin.matches_summary(_text_of_msg(m)))]
        roots = [m for m in roots if m not in prior]
    else:
        prior = []
    task = "\n\n".join(_text_of_msg(m) for m in roots)
    session_task = getattr(getattr(owner, "plan", None), "task", "")
    if prior:
        if getattr(origin, "packet", None) is not None:
            task = origin.packet.task
        elif session_task and (task == session_task or any(_text_of_msg(m) == session_task for m in roots)):
            task = session_task
        else:
            task = ""
    # Only session-authenticated anchors need this separate path: ordinary history
    # already reaches the writer, while anchored handoffs are excluded by _folded.
    ask_index = next((i for i in range(len(messages) - 1, -1, -1)
                      if isinstance(messages[i], dict) and messages[i].get("role") == "user"), None)
    prior_handoffs = tuple(_text_of_msg(m) for i, m in enumerate(messages)
        if i != ask_index and isinstance(origin, _HandoffOrigin) and isinstance(m, dict)
        and m.get("role") == "user"
        and (origin.matches_summary(_text_of_msg(m)) or
             (selfcompact.has_anchor(m) and origin.matches_continuation(_text_of_msg(m)))))
    if prior_handoffs and getattr(origin, "packet", None) is not None:
        task = origin.packet.task
    return memoryhandoff.SessionFacts(
        workspace_root=_session_cwd(key, messages, rlog) or "",
        original_task=task, prior_handoffs=prior_handoffs,
        prior_packet=getattr(origin, "packet", None) if prior_handoffs else None,
        task_rides_reply=bool(body.get(bodykeys.CHAT_WIRE)),
        gate_plan=_session_gate_plan(server, key),
        gate_flag=_last_gate_flag(server, key), gate_age=_gate_age(server, key),
        checks=_last_checks_note(server, key),
        carried_ledger=_carried_ledger(messages, origin=getattr(owner, "handoff_origin", None)))


def _handoff_distiller(provider, server, rlog):
    """Bind chunked distillation (handoffdistill) to the live provider's real window.

    Abstains (None) when the window is unknown or guessed: without a real budget nothing can be
    sized, and the single request plus the labelled floor remain the behavior."""
    if provider is None:
        return None
    role = server.cfg.routing.roles.get("compactor") or server.cfg.routing.roles.get("reasoner")
    def apply_role(body):
        if role is not None:
            role.apply(body, internal=True, rlog=rlog)
    return handoffdistill.binder(provider.chat, windowcaps.window_of(provider.chat, rlog),
                                 SUMMARIZE_MAX_TOKENS, apply_role, rlog)


def _compaction_body(pbody: dict, workspace_root: str | None = None, gate_plan=None,
                     checks: str = "", checks_age: int = 0, *, definition=..., facts=None,
                     distill=None) -> dict:
    """Selected Source framing, with no replacement when its lifecycle is absent.

    The compaction request, re-asked in CRIA'S OWN WORDS.

    LEVEL 3 — CONTEXT_FIXES, and it ran at EVERY level until 2026-08-27. Discarding the harness's
    own summarize instruction and replacing it with cria's, then flattening a structured history into
    one text message, is context surgery by the ladder's own definition. Its sibling
    (`reframe_compaction`, which rewrites the REPLY) was gated on 2026-08-24; this half, which
    rewrites the REQUEST, was missed — the gate went on one of the two call sites' mechanisms and not
    on the other's.

    Found by walking the level-0 and level-1 arms of six cells. Two walkers reported it independently:
    it fired at level 1 in `handles-cli-node x gemma4` (23 reframes) and in BOTH arms of
    `shipping-rates-rb x ternary-bonsai`. So neither of those rows is a clean measurement of its rung.

    IT IS NOT FREE. Flattening the history into one fresh user message throws away the model server's
    prefix cache. Measured on that ruby run's call 0102: `cached_tokens: 0`, a cold 42,586-token
    prefill costing **453 seconds**, against 25 seconds on the neighbouring call that reused 46,267
    cached tokens. On the level-1 arm the same call was still in flight when the run's gate fired.

    A test that reads the event log could not catch this: this function emits no event. Gated at
    the call site, which is where its own docstring says a mechanism should be gated when its
    state is not set anywhere else.

    THE CAUSE of the blank briefings (g1 0093/0094, g2 0087/0088, forensics 07-30): the proxy path
    drops the harness system prompt, the compactor role's reasoning-off then injects
    nothink_directive ("Do not think out loud... Respond directly") as the ONLY system line, and the
    history below it is 100% tool-call turns (42-0 vs prose in g2). A summarize task whose entire
    framing forbids narration, atop a context that has only ever spoken tool calls, yields a tool
    call. The briefing framing must lead the FIRST pass — and it is the SAME battle-tested framing
    the internal rolling compaction uses (selfcompact_summary), not a parallel variant (operator: one
    compaction prompt).

    …and the history is FLATTENED to a text transcript in ONE user message, exactly as cria's
    internal rolling compaction does. THIS is why internal briefings succeed and harness ones failed:
    passed 89 STRUCTURED turns — 42 of them its own tool calls — a weak model continues the pattern
    and answers with a tool call, whatever the system prompt says (measured g6: correct framing led,
    and both replies were still `call:write_file{...}`). With no tool-call turns in front of it,
    there is no shape to mimic.

    The harness's own compaction wording never reaches the model: `_compaction_transcript` drops the
    marker turn, and this system line replaces the instruction. cria knows the turn is a compaction —
    so cria, not the harness, gets to say what a good briefing is. ONE owner, so the streaming and
    buffered transports cannot drift apart (they already did: streaming passed the harness's raw
    prompt and the full structured history for months)."""
    definition = _selected_handoff() if definition is ... else definition
    if definition is None:
        return pbody
    if facts is None:
        facts = memoryhandoff.SessionFacts(workspace_root=workspace_root or "",
            gate_plan=gate_plan, gate_flag=checks, gate_age=checks_age)
    services = _handoff_services()
    if distill is not None:
        services = replace(services, distill=distill)
    framed = definition.frame(pbody, facts, services, selected=True)
    if not isinstance(framed, dict) or not isinstance(framed.get("messages"), list):
        raise ValueError("Harness handoff framing must return a message body")
    return framed


def _text_of_msg(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        return " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
    return c if isinstance(c, str) else ""


def _workspace_listing(ws: str | None) -> str:
    """FILES ALREADY IN THIS WORKSPACE, names only (top level + one level down), for the compaction
    summary. Empty string when the workspace is unknown/absent — silence over noise."""
    if not ws:
        return ""
    view = wsview.current(ws)
    top = view.listdir(ws)
    if top is None:
        return ""          # nobody has surveyed it yet — say nothing rather than "no files"
    lines: list[str] = []
    # THE LISTING THAT BECOMES THE SESSION'S MEMORY MAY NOT LIE BY OMISSION. `top[:40]` and the
    # `[:12]` below were bare literals under a header reading "FILES ALREADY IN THIS WORKSPACE
    # (on disk right now — do not re-create them)" — so a file past the cap was not merely missing,
    # it was implicitly denied, in the one reply whose own docstring says everything not in it is
    # gone. The caps stay (this rides in a summary); the remainder is now named.
    labels = prompts.load_map("workspace_inventory")
    for name in top:
        if name.startswith(".") or name.endswith(".pyc"):
            continue
        full = os.path.join(ws, name)
        if name == _SPILL_ROOT:
            lines.extend(_spill_listing(ws, view, labels))
            continue
        if view.isdir(full) is True:
            kids = [x for x in (view.listdir(full) or [])
                    if not x.startswith((".", "__pycache__"))]
            inner = prompts.named_list(kids)
            lines.append(f"  {name}/" + (f"  ({inner})" if inner else ""))
        else:
            lines.append(f"  {name}")
    if not lines:
        return ""
    # This shallow names-only appendix is not an absence check. It must still carry
    # the survey's independent coverage and freshness limits into the frozen handoff.
    if not view.complete or view.authored_folds:
        lines.append(labels["partial"])
    if view.may_have_changed:
        lines.append(labels["stale"])
    return labels["compaction_header"] + "\n" + "\n".join(lines)


# cria's own scratch root inside the workspace, and the directory under it where `webfetch` saves a
# document too large to inline. Derived from `SPILL_DIR` rather than spelled twice.
_SPILL_ROOT = os.path.normpath(webfetch.SPILL_DIR).split(os.sep)[0]


def _spill_listing(ws: str, view, labels: dict) -> list[str]:
    """The lines for cria's scratch root — the reference directory, LABELLED, and nothing else.

    SPILL ENTRIES ARE LABELLED, NEVER REMOVED. `_label_spill_entries` and `workspace_inventory`'s
    own `spill_note` already say so; this listing was the one place that removed instead, skipping
    the whole of `tmp` on the reasonable grounds that build junk is not the coder's memory. cria's
    saved copy of a fetched page lives in `tmp/reference`, so the one artifact cria created to hold
    an answer was the one artifact it deleted from the session's memory — under a docstring reading
    "THE LISTING THAT BECOMES THE SESSION'S MEMORY MAY NOT LIE BY OMISSION."

    Walked on the sub-40 pass, cart-billing-go x nemotron-elastic (scored 32). cria had fetched
    shopspring/decimal's README to `./tmp/reference/`, and lines 84-93 of it name `NewFromFloat`,
    the exact constructor the run then spent 42 consecutive calls failing to guess. The
    re-orientation author at call 0049 got this listing — four files, no reference directory — and
    its own system prompt forbids naming a file the listing does not name. It stayed quiet, and the
    coder rebuilt the API from memory.

    The rest of `tmp` stays out: it is where installs and builds land, and a package manager's tree
    is not something the coder wrote."""
    ref = os.path.join(ws, os.path.normpath(webfetch.SPILL_DIR))
    kids = [x for x in (view.listdir(ref) or []) if not x.startswith(".")]
    if not kids:
        return []
    rel = os.path.normpath(webfetch.SPILL_DIR).replace(os.sep, "/")
    note = labels.get("spill_note", "").strip()
    return [f"  {rel}/  ({prompts.named_list(kids)}) {note}".rstrip()]


def _completion_text(c: dict) -> str:
    for ch in c.get("choices") or []:
        t = (ch.get("message") or {}).get("content")
        if isinstance(t, str):
            return t
    return ""


def _carried_ledger(messages: list, *, origin: _HandoffOrigin | None = None) -> str:
    """Carry only this session's actual deterministic hardener output.

    A role, lead, private marker or even a full historical producer signature
    locates a candidate; none proves its origin. Missing session grounding (also
    after a restart) abstains. The ledger itself comes from the producer record,
    never from a quoted account's heading or an invented event in its payload.
    """
    from .loop import _COMPACTION_BOUNDARY, _COMPACTION_MARKER, CONTINUATION_MARKER
    if not isinstance(origin, _HandoffOrigin) or not origin.dropped:
        return ""
    for m in reversed(messages):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        text = _text_of_msg(m)
        if text.lstrip().startswith(CONTINUATION_MARKER):
            return origin.ledger if origin.matches_continuation(text.strip()) else ""
        if _COMPACTION_MARKER in text and _COMPACTION_BOUNDARY in text:
            summary = text.split(_COMPACTION_BOUNDARY, 1)[1].lstrip("\n")
            return origin.ledger if origin.matches_summary(summary) else ""
    return ""


def _mark_replayed_handoffs(before: list, after: list, origin) -> list:
    """Give every message `reframe_compaction` REWROTE into a continuation the typed ``bodykeys.HarnessHandoff`` provenance:
    the one authority by which the context floor may cut a user-role message (`contextfloor._cuttable_user_text`). A message is
    marked only if the reframe produced it here (not an object of the inbound list) and it opens with cria's own continuation
    marker; ``authenticated`` records whether the replayed text matched the identity cria recorded when it produced it."""
    inbound = {id(m) for m in before}
    out = []
    for m in after:
        content = m.get("content") if isinstance(m, dict) else None
        if (isinstance(m, dict) and id(m) not in inbound and m.get("role") == "user" and isinstance(content, str)
                and content.startswith(CONTINUATION_MARKER) and bodykeys.ANNOTATION_SOURCE not in m):
            authenticated = isinstance(origin, _HandoffOrigin) and origin.continuation == content
            m = {**m, bodykeys.HARNESS_HANDOFF: bodykeys.HarnessHandoff(authenticated)}
        out.append(m)
    return out


def _harden_compaction_reply(comp: dict, body: dict, provider, server, rlog, sess_key: str = "",
                             *, definition=..., _defer_commit=None, _owner=..., _facts=None) -> dict:
    """Bind selected hardening; authenticate only the matching, actually returned output.

    The harness stores this reply as the session's ENTIRE remembered past — everything not in it
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
    sk = sess_key or session_key({}, body.get("messages", []))
    observed = _observe_handoff_write_results(server, sk, body.get("messages", []))
    owner = observed if _owner is ... else _owner
    definition = _selected_handoff(server) if definition is ... else definition
    if definition is None:
        return comp
    facts = _handoff_facts(server, sk, body, rlog, owner) if _facts is None else _facts
    settlement = []
    def settle(reply, ledger, dropped):
        if (settlement or not isinstance(reply, str) or not isinstance(ledger, str)
                or type(dropped) is not bool):
            raise ValueError("Invalid harness handoff producer settlement")
        settlement.append((reply, ledger, dropped))
    role = server.cfg.routing.roles.get("reasoner")
    services = _handoff_services(getattr(server, "system1", None))
    coder = server._endpoint_for("coder") if hasattr(server, "_endpoint_for") else None
    if coder is not None:
        window = windowcaps.known_window(coder, rlog)
        tokenize = getattr(coder, "_tokenize_prompt", None)
        if window and callable(tokenize):
            services = replace(services, packet_window=window,
                               packet_measure=lambda text: tokenize(text, rlog))
    distill = _handoff_distiller(provider, server, rlog)
    if distill is not None:
        # The empty/cut-off briefing retry re-frames the request; it must distill too.
        services = replace(services, distill=distill)
    result = definition.execute(comp, body, facts, services, selected=True,
        chat_fn=provider.chat if provider is not None else None,
        role=role, rlog=rlog, settle=settle, frame_hook=definition.frame)
    if (not isinstance(result, memoryhandoff.HandoffResult) or not isinstance(result.completion, dict)
            or not isinstance(result.prose, str) or not isinstance(result.ledger, str)
            or result.effect not in (memoryhandoff.Effect.NO_OP, memoryhandoff.Effect.DELIVERED,
                                     memoryhandoff.Effect.WITHHELD)):
        raise ValueError("Harness handoff replacement must return HandoffResult")
    if result.effect is memoryhandoff.Effect.NO_OP:
        if settlement or result.prose or result.ledger:
            raise ValueError("No-op harness handoff cannot publish a producer record")
        return result.completion
    reply = _completion_text(result.completion)
    prose_matches = (not result.prose or reply == result.prose
                     or reply.startswith(result.prose + "\n\n"))
    ledger_prefix = _PROSE_DROPPED_MARKER + "\n" + result.ledger
    ledger_matches = (not result.ledger or reply == ledger_prefix
                      or reply.startswith(ledger_prefix + "\n\n"))
    expected = (reply, result.ledger, result.effect is memoryhandoff.Effect.WITHHELD)
    if (settlement != [expected] or not prose_matches or not ledger_matches
            or bool(result.prose) != (result.effect is memoryhandoff.Effect.DELIVERED)):
        raise ValueError("Harness handoff settlement must match its returned result")
    # The record holds the reply AS EVERY INBOUND READER WILL SEE IT: without the lines that open with cria's
    # marker. That is the footer `_finalize` appends, and also any such line the briefing writer itself quoted
    # (a record keyed to the unstripped text could never equal the stored, stripped copy).
    def as_stored(text: str) -> str:
        return strip_history([{"role": "assistant", "content": text}])[0][0]["content"]
    origin = _HandoffOrigin(as_stored(expected[0]), *expected[1:], packet=result.packet)
    def commit(retained):
        # Compared WITHOUT cria's own `⟦cria⟧` lines, which every inbound reader strips before it reads
        # the stored reply: `_finalize` appends the turn-stats footer to this text answer, and comparing
        # the decorated copy recorded no producer for any decorated drop (ornith1.5_9b / Java run 4,
        # 0042: the coder then read cria's own ledger framed as an ungrounded handoff).
        live = _handoff_session(server, sk)
        if owner is None:
            why = "no_session"
        elif live is not owner:
            why = "session_replaced"
        elif as_stored(_completion_text(retained)) != origin.reply:
            why = "reply_changed_in_finalization"
        else:
            owner.handoff_origin = origin
            rlog.emit("handoff.origin_recorded", reply_chars=len(origin.reply),
                      blocks=len(result.packet.blocks) if result.packet is not None else 0)
            return
        # The identity a later continuation is matched against was NOT recorded: that continuation will stay an
        # unexpanded, unreducible user message. Say which input differed (2026-11-10 phi4: the fifth handoff).
        rlog.emit("handoff.origin_unrecorded", level="warn", why=why, reply_chars=len(origin.reply),
                  owner_at_start=type(owner).__name__, owner_now=type(live).__name__,
                  guard_now=type(server.loop_store.get_guard(sk)).__name__ if getattr(server, "loop_store", None) else "none")
    if _defer_commit is None:
        commit(result.completion)  # compatibility caller receives this exact returned result
    else:
        _defer_commit(commit)  # actual producer waits for successful finalization
    return result.completion


def _note_failover(indic, rlog) -> None:
    """Show a chain walk on the indicator (the event ``failover.walk`` is the record)."""
    note = getattr(rlog, "failover_note", None)
    if note and indic is not None:
        if not indic.note:
            indic.note = note
        walked = getattr(rlog, "failover_to", None)
        role, model = walked if isinstance(walked, tuple) else (None, None)
        if role:  # the route banner names the role/model that answered, not the one that was asked first
            indic.role, indic.model = role, model or indic.model


class _ClientHungUp(Exception):
    """The HARNESS's socket failed on a write. A reset or broken pipe raised while reading the MODEL's
    stream is the same exception type, so only a failed write to the harness is converted to this."""


def _terminal_upstream_error(e: BaseException) -> bool:
    """An error the buffered call itself never retries: a typed refit/overflow outcome or a malformed-
    generation protocol error. Asking the model again would repeat the doomed request, or (a protocol
    error) replace the evidence with a fresh answer the buffered path would not have produced."""
    from .upstream import ContextRefitNoChange, CallerContextRetryNoChange, UpstreamProtocolError
    return isinstance(e, (ContextRefitNoChange, CallerContextRetryNoChange, ReadFitUnknown, ReadFitOverflow,
                          UpstreamProtocolError)) or generation.is_protocol_error(
                              getattr(e, "response_error", None))


def _failover_noted(chunks, indic, rlog):
    """The stream opens (and may walk the chain) before its first chunk: surface the walk on the
    indicator before the header is flushed ahead of the first content delta."""
    for raw in chunks:
        _note_failover(indic, rlog)
        yield raw


class CriaServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cfg: Config, log: EventLog, upstream: Upstream, *, system1=None) -> None:
        self.cfg = cfg
        self.log = log
        self.upstream = upstream
        # The optional trained classifier: ONE immutable runtime for the whole service, built (or the
        # service refuses to start) before anything binds a socket. ``system1`` is an explicit
        # injection for callers that already hold a runtime; it is only meaningful when enabled.
        if system1 is not None and not cfg.system1.enabled:
            raise ValueError("a System 1 runtime was supplied but [system1] is not enabled")
        self.system1 = system1 if system1 is not None else system1wiring.build(
            cfg.system1, log,
            capture_dir=cfg.logging.capture_dir_path if cfg.logging.capture_calls else None)
        # Routing engages only when configured. With no [roles]/[failover], cria is a plain
        # phase-1 passthrough.
        roles = cfg.routing.roles  # each role = a backend binding + per-request sampling + reasoning.
        # A role is "configured" by the PRESENCE of its [roles.<name>] table, so every gate below keys
        # on membership in `roles`.
        self.router = (
            Router(cfg.routing, upstream, timeout=cfg.upstream.timeout_seconds,
                   context_window=cfg.upstream.context_window)
            if (roles or cfg.routing.failover)
            else None
        )
        # PER-ROLE ENDPOINT: every role resolves its OWN base_url (or the shared endpoint), not just the
        # coder — closes the bug where the classifier / reasoner / planner / compactor were hardwired to
        # the shared upstream and silently ignored a per-role base_url (a role may run on another box).
        def _ep(role):
            return self.router.endpoint_for(role) if self.router is not None else upstream
        self._endpoint_for = _ep
        self.image_workflow = imageassembly.ConfiguredImages(self, _image_wire)
        self.classifier = (
            Classifier(_ep("classifier"), cfg.routing.engagement_bias, role=roles.get("classifier"))
            # The wire-only control never consumes a classifier verdict. Do not even
            # construct an auxiliary caller that could spend active baseline time.
            if "classifier" in roles and cfg.routing.engagement_level != config.PURE_PROXY
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
        repohealth.configure(cfg.tools.github_token_env)
        self.compactor_upstream = _ep("compactor") if "compactor" in roles else self.reasoner_upstream
        # Compaction/summarization sampling. The [roles.compactor] role exists precisely for
        # folding transcript spans into briefings (temp 0.6, reasoning on) — NOT the coder role
        # (temp 0.1, coding-primed: it misreads "summarize this" as "continue the task" and emits a
        # next-action instead of a backward-looking rollup). Fall back to the reasoner (same sampling
        # family) when no compactor table is configured, never the coder.
        self.compactor_role = roles.get("compactor") or roles.get("reasoner")
        # Per-session end-of-turn stats (calls, tok/s, guard fires, wall time).
        self.stats_store = StatsStore()
        self.retention = None   # AutoPruner, only when the operator configured [retention] auto_prune_after
        from .ops import Ops
        self.ops = Ops(safe_path=cfg.harness.safe_path)   # operations carried out through the harness primitives (ledger under ~/.cria/ops)
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
        # Request/task binding supplies the immutable output-stage selection. Server
        # construction must not change another request's unbound library opt-out.
        self.pilot_runtime = assistruntime.AssistRuntime.select(
            level=cfg.routing.engagement_level, disabled=cfg.assists.disabled,
            profile=cfg.assists.profile,
            experimental_planning=cfg.planner.enabled and cfg.routing.assists_enabled)
        _warn_config(cfg, has_reasoner, has_coder, log)
        # Always build the loop when a coder exists; require a reasoner only when the planner is ON.
        # Planner OFF → the loop drives the synthetic 1-item path (guards but no decomposition).
        # LEVEL 4 — DONE_REFUSALS_ENABLED — is where the loop first exists. Below it cria is a plain
        # proxy and never drives. At exactly 4 the loop answers a completion CLAIM and nothing else;
        # at 5 it does everything. Which of the two is decided ONCE here, by the `assists` flag on
        # the context, so no stage has to re-derive it (see LoopContext.assists for the 4/5 rule).
        if cfg.routing.done_refusals and has_coder and (has_reasoner or not cfg.planner.enabled):
            # The web-search key comes from the fixed BRAVE_SEARCH_API_KEY env var (never stored in
            # config); brave.api_key() reads it normalized (CRLF-safe) — the CRLF was the illegal-
            # header footgun, fixed once at the source (envfile) rather than stripped per-consumer.
            search_key = brave.api_key() or ""
            # The coder runs on the STREAMING-guarded path so its reasoning is watched live: a
            # runaway thinking loop is aborted mid-flight (rumination detector) instead of burning
            # the window to an empty turn / truncation. Budget seeded from the coder's output_reserve.
            coder_role = self.coder_role
            def coder_chat(body, rlog, _up=_ep("coder")):
                from . import generationguards
                runtime = assistruntime.current() if assistruntime.is_bound() else self.pilot_runtime
                selected = generationguards.SelectedGuards.from_definitions(runtime.definitions)
                detector = selected.detector(lambda: coder_role.output_reserve if coder_role else None)
                return _up.chat_watched(body, rlog, watch=detector.check if detector is not None else None)
            coder_chat.upstream = _ep("coder")  # the window owner, for pre-floor sizing in the loop

            def reasoner_buffered_chat(body, rlog):
                route = self.router.internal_route('reasoner', rlog) if self.router is not None else None
                if route is None:
                    raise RuntimeError('reasoner route unavailable')
                if route.role != 'reasoner':
                    origin = body.get(bodykeys.ROLE_ORIGIN)
                    target_role = roles.get(route.role)
                    if isinstance(origin, config.RoleOrigin) and target_role is not None:
                        origin.restore(body)
                        target_role.apply(body, internal=True, rlog=rlog)
                if route.model:
                    body['model'] = route.model
                else:
                    body.pop('model', None)
                return route.provider.chat(body, rlog)

            self.loop = Loop(
                LoopContext(
                    planner=Planner(_ep("reasoner"), role=roles.get("reasoner"),
                                    search_key=search_key, max_gather_rounds=cfg.planner.max_gather_rounds,
                                    policies=self.pilot_runtime.initial_planning),
                    coder_chat=coder_chat,
                    # reasoner_chat/reasoner_role are wired UNCONDITIONALLY (even with no reasoner role,
                    # _ep resolves the shared endpoint and role is None) — the single-item off-ramps gate
                    # on `reasoner_role is not None`, so a plan-off Loop without a reasoner just skips them.
                    # chat_watched, NOT chat — for the DEGENERATE-RUN BACKSTOP it already carries.
                    # That backstop fires independently of the rumination watcher (watch=None here),
                    # aborts a stream that has locked into repeating one passage, and returns the
                    # same buffered completion every caller already expects. The reasoner had no
                    # such protection: walked on maple-preview 1785994846 call 0052, the steer author
                    # repeated one ~250-word paragraph about fifteen times, ran to finish_reason=
                    # length at 34,766 bytes, and burned 2m16s of a 5.5-minute endgame producing
                    # nothing — 62% of that run's final stretch was cria's own reasoning calls. The
                    # coder has guard_rumination, but it keys on the CODER's finish_reason; nothing
                    # watched the supervisor. Same mechanism, same owner, one more call path.
                    reasoner_chat=_ep("reasoner").chat_watched,
                    reasoner_buffered_chat=reasoner_buffered_chat,
                    coder_role=coder_role,
                    reasoner_role=roles.get("reasoner"),
                    compactor_role=self.compactor_role,
                    # The compactor ENDPOINT's chat for the single-item self-compaction (rides the
                    # compactor box like the plan-off _summarize did); None-safe (falls back to reasoner).
                    compactor_chat=self.compactor_upstream.chat,
                    satisfaction_check_start_minutes=cfg.context.satisfaction_check_start_minutes,
                    satisfaction_check_every_minutes=cfg.context.satisfaction_check_every_minutes,
                    satisfaction_check_min_turns=cfg.context.satisfaction_check_min_turns,
                    satisfaction_check_max_turns=cfg.context.satisfaction_check_max_turns,
                    # ONE folder per run: plan mirror + verify dumps join the call captures
                    # under <capture_dir>/<session>/ — a single place per session.
                    runs_dir=cfg.logging.capture_dir,
                    focus_trim=cfg.context.focus_trim,
                    self_compact=cfg.context.self_compact,
                    assists=cfg.routing.assists_enabled,
                    pilot_runtime=self.pilot_runtime,
                    system1=self.system1,
                    # THE PLANNER IS AN ASSIST, so below level 5 the loop always drives the
                    # synthetic single-item path however `[planner] enabled` is set. This is also
                    # what makes levels 0-4 planner-AGNOSTIC by construction rather than by
                    # discipline: there is no plan-on branch to diverge from at those rungs.
                    planner_enabled=cfg.planner.enabled and cfg.routing.assists_enabled,
                ),
                # Completed-work briefings + session shapes survive a cria restart (the restarts this
                # project makes constantly were wiping the context a follow-up / a post-compaction
                # continuation needs). Live multi-item plans + synthetic sessions on stable keys are
                # persisted; unstable task: keys are ephemeral — see LoopStore.
                self.loop_store,
            )
        super().__init__((cfg.server.host, cfg.server.port), CriaHandler)

    def secret_values(self) -> list[str]:
        """cria's own credentials as currently set in the environment (read per call: the env file is loaded
        after the config), for redaction from everything retained or shown to the model."""
        return [v for name in sorted(self.cfg.secret_env_vars()) if (v := envfile.env_secret(name))] + callauth.secret_values()

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

    def start_retention(self, home=None):
        """Start the operator-authorized background prune of retained private state, or do nothing.
        Only an explicit ``[retention] auto_prune_after`` enables it; the thread cannot reach a request."""
        after = self.cfg.retention.after_seconds
        if after is None or self.retention is not None:
            return None
        from . import privatepaths
        from .retention import AutoPruner
        self.retention = AutoPruner(home or privatepaths.CRIA_HOME, after, self.cfg.retention.every_seconds,
                                    self.log.emit).start()
        return self.retention

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


#: The largest request body cria will read. The biggest real harness request measured in ~/.cria/calls is
#: under 4 MiB; image turns are the only way to grow past that. Above this a Content-Length is refused
#: with 413 BEFORE any of it is read (``BufferedReader.read(n)`` allocates n bytes up front).
MAX_BODY_BYTES = 64 * 1024 * 1024
#: Total time a client has to deliver a body it has declared (local loopback: seconds; a stalled sender
#: must not pin a handler thread forever).
BODY_DEADLINE_SECONDS = 120.0


class BodyRejected(ValueError):
    """A request body cria will not read: the HTTP status to answer with, and whether the body may be left
    unread on the socket (``close``: then the connection must end so the leftover bytes are never parsed as
    the next request)."""

    def __init__(self, status: int, message: str, *, close: bool = True) -> None:
        super().__init__(message)
        self.status, self.close = status, close


#: Chat message roles a template can render; anything else (or no role) is refused at the edge.
CHAT_ROLES = ("system", "developer", "user", "assistant", "tool", "function")
#: Sampling controls the upstream needs as numbers: a string there used to travel on and come back a 502.
CHAT_NUMERIC_FIELDS = ("temperature", "top_p", "top_k", "min_p", "repeat_penalty", "frequency_penalty", "presence_penalty",
                       "seed", "max_tokens")


def _chat_shape_error(body: dict) -> str | None:
    """Why a chat body cannot be processed at all (wrong JSON types where the pipeline iterates, slices or
    lowercases), naming the field, or None. Valid JSON of the wrong shape used to die deep in the pipeline
    and drop the connection or answer 500. Tool-call ARGUMENTS are deliberately not judged here: a
    malformed historical argument string is the history-arguments owner's to carry byte-faithfully."""
    messages = body.get("messages")
    if messages is not None and (not isinstance(messages, list) or any(not isinstance(m, dict) for m in messages)):
        return "messages must be an array of objects"
    if not messages:
        return "messages must not be empty"     # no model's template renders none: it used to travel upstream and come back a 502
    if body.get("stream") is not None and not isinstance(body["stream"], bool):
        return "stream must be a boolean"
    for key in CHAT_NUMERIC_FIELDS:
        if body.get(key) is not None and (isinstance(body[key], bool) or not isinstance(body[key], (int, float))):
            return f"{key} must be a number"
    if body.get("tools") is not None and (not isinstance(body["tools"], list) or any(not isinstance(t, dict) for t in body["tools"])):
        return "tools must be an array of objects"
    for i, t in enumerate(body.get("tools") or ()):
        if t.get("type", "function") == "function":
            fn = t.get("function")
            if not isinstance(fn, dict) or not isinstance(fn.get("name"), str):
                return f"tools[{i}].function.name must be a string"
    for i, m in enumerate(messages):
        if m.get("role") not in CHAT_ROLES:
            return f"messages[{i}].role must be one of {', '.join(CHAT_ROLES)}: got {m.get('role')!r}"
        content = m.get("content")
        if content is not None and not isinstance(content, (str, list)):
            return f"messages[{i}].content must be a string, an array of parts, or null"
        for j, part in enumerate(content if isinstance(content, list) else ()):
            if not isinstance(part, dict):
                return f"messages[{i}].content[{j}] must be an object"
            if part.get("type") in ("text", "input_text") and not isinstance(part.get("text"), str):
                return f"messages[{i}].content[{j}].text must be a string"
        if m.get("tool_calls") is not None and (not isinstance(m["tool_calls"], list) or any(not isinstance(c, dict) for c in m["tool_calls"])):
            return f"messages[{i}].tool_calls must be an array of objects"
        for j, call in enumerate(m.get("tool_calls") or ()):
            fn = call.get("function")
            if not isinstance(fn, dict) or not isinstance(fn.get("name"), str):
                return f"messages[{i}].tool_calls[{j}].function.name must be a string"
            if call.get("id") is not None and not isinstance(call["id"], str):
                return f"messages[{i}].tool_calls[{j}].id must be a string"
        if m.get("tool_call_id") is not None and not isinstance(m["tool_call_id"], str):
            return f"messages[{i}].tool_call_id must be a string"
    return None


class CriaHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "cria"
    sys_version = ""

    #: Longest a connection may go without delivering a byte of its request line/headers (an idle keep-alive
    #: or half-open connect holds a thread per connection). Ends when the head is read: a model turn can
    #: be silent for minutes after that, so the response side is never under a deadline.
    REQUEST_HEAD_TIMEOUT_SECONDS = 300.0

    def handle_one_request(self) -> None:
        self._answered = False
        self.connection.settimeout(self.REQUEST_HEAD_TIMEOUT_SECONDS)
        super().handle_one_request()

    def parse_request(self) -> bool:
        ok = super().parse_request()
        self.connection.settimeout(None)
        return ok

    def send_response(self, code, message=None) -> None:
        self._answered = True
        super().send_response(code, message)

    def _guarded(self, handle) -> None:
        """Run one request; an exception nothing below handled is LOGGED and answered (500) while the
        status line is still unsent, never swallowed into a bare connection drop."""
        try:
            handle()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
            self.server.log.emit("request.client_gone", level="warn")
        except Exception as e:  # noqa: BLE001 — the HTTP edge's last line: log the cause, answer the client
            self.close_connection = True
            msg = f"{type(e).__name__}: {e}"
            self.server.log.emit("request.error", level="error", error=msg, traceback=traceback.format_exc())
            if not self._answered:
                self._send_json(500, {"error": f"internal error: {msg}"})

    # Route the base handler's own access noise through our event log (debug), so
    # there is exactly one logging path.
    def log_message(self, fmt: str, *args) -> None:
        self.server.log.emit("http.access", level="debug", line=(fmt % args))

    def do_GET(self) -> None:
        self._guarded(self._get)

    def _get(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/health":
            self._send_json(200, {"status": "ok"})
        elif path == "/v1/models":
            # THE REAL MODEL, UNDER ITS REAL NAME, WITH ITS REAL RUNTIME WINDOW — advertised the
            # way the OpenAI-compatible ecosystem actually reads it, so ANY compliant harness can
            # learn the limit and apply its own compaction policy. There is no wire standard for a
            # compaction *trigger*: the standard signal is the context *window*, and each harness
            # derives its own threshold from it (Codex compacts at 90%). cria's only job here is to
            # state the window truthfully; the trigger is the harness's business.
            #
            # No single field name is universal, so we advertise the RUNTIME window under every
            # recognized key at once:
            #   meta.n_ctx           — llama.cpp (this stack's native shape; we FRONT llama.cpp)
            #   max_model_len        — vLLM's OpenAI-compat model card
            #   context_length       — OpenRouter / HF convention
            #   context_window / max_context_window — OpenAI/Codex ModelInfo
            # Every one carries n_ctx (the window the server is RUNNING, e.g. 40960), never
            # n_ctx_train (the trained 262144): advertising the trained max would tell a harness it
            # has room it does not, and it would 400 mid-turn (measured: request 41,662 > ctx
            # 40,960). Sourced live from /props, so it tracks a model swap with nothing to go stale.
            # A placeholder id would be cria stating a false fact about which model is loaded (5b),
            # so a not-yet-loaded server yields an empty list, never an invented name.
            loaded = self.server.upstream.loaded_model(self.server.log)
            n_ctx = None
            props = self.server.upstream.props(self.server.log)
            if isinstance(props, dict):
                n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
            if not loaded:
                self._send_json(200, {"object": "list", "data": [], "models": []})
            else:
                entry = {"id": loaded, "slug": loaded, "object": "model", "owned_by": "cria"}
                if isinstance(n_ctx, int) and n_ctx > 0:
                    entry["context_window"] = n_ctx        # OpenAI / Codex ModelInfo
                    entry["max_context_window"] = n_ctx
                    entry["context_length"] = n_ctx        # OpenRouter / HF
                    entry["max_model_len"] = n_ctx         # vLLM
                    entry["meta"] = {"n_ctx": n_ctx}       # llama.cpp native
                self._send_json(200, {"object": "list", "data": [entry], "models": [entry]})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        self._guarded(self._post)

    def _post(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")   # strip any query string (parity with do_GET)
        from . import readcontext
        with assistruntime.bound(self.server.pilot_runtime), readcontext.bound():
            if path == "/v1/chat/completions":
                self._handle_chat()
            elif path == "/v1/responses":
                self._handle_responses()
            else:
                self.close_connection = True   # the body was not read: it must not be parsed as a request
                self._send_json(404, {"error": "not found"})

    # ------------------------------------------------------------------ chat

    def _handle_chat(self) -> None:
        log: EventLog = self.server.log
        session = self.headers.get(SESSION_HEADER)
        turn = uuid.uuid4().hex[:8]
        rlog = log.bind(session=session, turn=turn)

        try:
            body = self._read_json_body()
            if (shape := _chat_shape_error(body)) is not None:
                raise ValueError(shape)
        except ValueError as e:
            rlog.emit("request.bad", level="warn", error=str(e))
            self._refuse_body(e)
            return

        carry_chat_system(body)
        body[bodykeys.CHAT_WIRE] = True    # a harness compaction reply must then carry the original task (memoryhandoff.harden)
        self._ops_original_body = copy.deepcopy(body)
        sk = session_key(self.headers, body.get('messages', []))
        if self._ops_inbound(body, sk, rlog, api='chat', stream=bool(body.get('stream'))):
            return

        # INBOUND STRIP: remove cria's own indicator lines from the history before
        # the model re-reads them (they were injected only for the human's view).
        messages = body.get("messages")
        if isinstance(messages, list):
            # The view first: `reframe_compaction` asks it whether the workspace is empty, and an
            # unbound view answers "not surveyed" to everything (see _bind_workspace_view).
            self._strip_and_reframe_inbound(body, session_key(self.headers, messages), rlog)

        # write_file↔shell: if the harness has shell but not write_file, re-present
        # our prior shell translations as write_file (so the model sees its own
        # tool) and advertise write_file to the model. Outbound lowering happens at
        # the send points via _translate_out.
        # Chat path: the downstream _translate_out uses session_key(self.headers, messages) too, so the
        # fetch gate's write/read keys match here (session_key hashes the stable root, unchanged by
        # represent_inbound).
        self._setup_translation(body, session_key(self.headers, body.get("messages", [])), rlog)
        if not self._bind_read_facts(body, rlog):
            self._representation_fallback(body, sk, rlog)

        # Observation only (logs `ctx.estimate`): what the harness SENT. The usage reported back is
        # the MODEL-VISIBLE size, computed where the response path is known (see _report_context_usage).
        _incoming_ctx_tokens(body, rlog)
        stream = bool(body.get("stream"))
        rlog.emit(
            "request.recv",
            assist_profile=assistruntime.current().profile,
            pilot_assists=assistruntime.current().selected,
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

    def _read_room(self, rlog) -> int | None:
        """The measured window of the model that will answer, in tokens (None: unknown, which is never read as small). A whole read
        of a file whose chars/4 estimate exceeds it cannot fit however the rest of the request shrinks, so it is not transported."""
        return windowcaps.known_window(self.server._endpoint_for("coder"), rlog)

    def _ops_inbound(self, body, sess_key, rlog, *, api, stream):
        """cria's own operations first: verify each primitive call in the history against the key and the ledger, take the frame each
        one returned, decide the next step from the ledger, and project finished operations to the model's own call and cria's final
        text. What the harness has not yet seen goes back to it without asking the model. Returns True when it answered."""
        before = body.get('messages') or []
        self._ops_session = sess_key       # ONE ledger for the request: results are read from it here and calls are issued into it in _translate_out
        taken = self.server.ops.incoming(sess_key, before, rlog, tools=body.get('tools'), room=lambda: self._read_room(rlog))
        body['messages'] = taken.messages
        self._ops_outcomes, self._ops_reads, self._read_facts = taken.outcomes, taken.reads, taken.facts
        if not taken.calls:
            return False
        completion = {'id': 'ops_' + uuid.uuid4().hex, 'object': 'chat.completion',
                      'created': int(time.time()), 'model': body.get('model') or '',
                      'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': None, 'tool_calls': taken.calls},
                                   'finish_reason': 'tool_calls'}]}
        if not stream:
            payload = (responses.to_responses_json(completion, body.get('model') or '') if api == 'responses'
                       else completion)
            self._send_raw_json(json.dumps(payload).encode('utf-8'))
            return True
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        if api == 'responses':
            resp_id = responses._new_id('resp')
            self._raw_write(responses.created_event(resp_id, body.get('model') or ''))
            for chunk in responses.body_events(completion, resp_id, body.get('model') or ''):
                self._raw_write(chunk)
        else:
            for chunk in completion_to_sse(completion):
                self._raw_write(chunk)
        return True

    def _reproject(self, sess_key: str, rlog) -> dict | None:
        """The harness's own history, projected again after the ledger changed (a read withheld): a copy of the body, or None when
        the projection would ask the harness for more."""
        again = copy.deepcopy(self._ops_original_body)
        taken = self.server.ops.incoming(sess_key, again.get('messages') or [], rlog, tools=again.get('tools'), room=lambda: self._read_room(rlog))
        if taken.calls:
            return None
        again['messages'] = taken.messages
        self._ops_outcomes, self._ops_reads, self._read_facts = taken.outcomes, taken.reads, taken.facts
        self._strip_and_reframe_inbound(again, sess_key, rlog)
        self._setup_translation(again, sess_key, rlog)
        return again

    def _fit_fallback(self, error, sess_key, rlog):
        sess_key = getattr(self, '_ops_session', sess_key)
        from .upstream import ReadFitUnknown, ReadFitOverflow
        if isinstance(error, ReadFitOverflow):
            reads, kind = error.measurement.reads, 'overflow'
        elif isinstance(error, ReadFitUnknown):
            reads, kind = error.reads, 'unknown'
        else:
            raise error
        reported = {read.call_id for read in reads}
        # Fit describes the entire request, not each read. Withdraw one offer at a time and retry the real wire, so a large sibling
        # cannot hide a small one. Until one read remains, even a measured overflow says nothing about any particular read, so its
        # individual outcome is unknown rather than overflow.
        offered = getattr(self, '_read_offered', ())
        ids = tuple(fact.call_id for fact, _content, _prefix in offered)
        if not ids or not reported.issubset(ids):
            raise error
        selected = max(offered, key=lambda item: len(item[0].exact_body))[0].call_id
        if len(ids) > 1:
            kind = 'unknown'
        self.server.ops.withhold(sess_key, (selected,), kind)
        fallback = self._reproject(sess_key, rlog)
        if fallback is None or not self._bind_read_facts(fallback, rlog):
            raise error
        return fallback

    def _representation_fallback(self, body, sess_key, rlog):
        """The verified reads could not be bound to the model's representation of them: they are withheld (not delivered, no credit) and the
        history is projected again, so the model is told that instead of being given a file the wire cannot vouch for."""
        sess_key = getattr(self, '_ops_session', sess_key)
        ids = tuple(f.call_id for f in getattr(self, '_read_facts', ()))
        if ids:
            self.server.ops.withhold(sess_key, ids, 'unknown')
        again = self._reproject(sess_key, rlog)
        if again is not None:
            body.clear()
            body.update(again)
        self._read_offered = ()
        rlog.emit('read.representation_unavailable', level='warn')

    def _bind_read_facts(self, body, rlog):
        """Body content is the canonical *model-facing* representation. Bind each verified read the model's wire has not yet accepted to
        the exact bytes of its result, so the context floor keeps it whole until the wire accepts it."""
        offered = []
        for fact in getattr(self, '_read_facts', ()):
            matches = [m for m in body.get('messages', []) if isinstance(m, dict) and m.get('role') == 'tool'
                       and m.get('tool_call_id') == fact.call_id]
            if len(matches) != 1 or not isinstance(matches[0].get('content'), str):
                return False
            content = matches[0]['content']
            text = fact.exact_body.decode('utf-8')
            prefix = fact.pre if fact.read_instead else ''
            if fact.read_instead:
                from .readcontext import prefix as representation_prefix
                known = representation_prefix(fact.call_id)
                if known is None or known[0] != text:
                    return False
                prefix = known[1]
            if content != prefix + text:
                return False
            offered.append((fact, content, prefix))
        self._read_offered = tuple(offered)
        if offered:
            from .upstream import ProtectedRead, bind_protected_reads, ReadFitUnknown
            reads = []
            for fact, content, prefix in offered:
                def observe(accepted, cid=fact.call_id, session=getattr(self, '_ops_session', None)):
                    if accepted:
                        self.server.ops.settle(session, (cid,))
                reads.append(ProtectedRead(fact.call_id, fact.source, content, fact.exact_body,
                    observe=observe, read_instead=fact.read_instead, pre=prefix if fact.read_instead else None))
            try:
                bound = bind_protected_reads(body, tuple(reads))
            except ReadFitUnknown:
                return False
            body.update(bound)
        return True

    def _classify(self, body: dict, rlog, compaction: bool = False):
        """Classify the turn — unless cria ALREADY KNOWS what it is.

        A compaction turn is self-identifying (the `<<<LOCAL_COMPACT>>>` handshake, or the
        unmarked-but-recognized case `_recognize_compaction` resolves once per request — see its
        caller) and `_route` dispatches it to the compactor without ever reading the verdict.
        Classifying it anyway spent a whole model call to answer a question nobody asks, and the
        question is unanswerable: the classifier must pick coding|reasoning|question for the text
        "Summarize the thread for continuation", which is none of them. Measured over the
        08-11..08-13 suite: 39 classifier calls ran away to the 16,384-token ceiling and returned
        NOTHING — no content, no reasoning, no tool call, `finish_reason: length` — for 131 minutes
        of wall clock, the single largest block of dead time in the campaign. Deciding earlier is
        the fix; capping the runaway would only have made the wasted call cheaper (A, not B)."""
        server: CriaServer = self.server
        if server.classifier is None:
            return None
        # `compaction` is the caller's precomputed answer (marker OR judged); the cheap marker check
        # is repeated here too so a caller that only knows the marker (no `_recognize_compaction`
        # pass yet run) still gets the free, zero-cost recognition it always had.
        if compaction or _is_compaction_request(body.get("messages", [])):
            rlog.emit("classify.skipped", why="compaction")
            return None
        definition = classify.selected_definition()
        if definition is None:
            return None
        return definition.execute(server.classifier, body.get("messages", []), rlog)

    def _decorate(self, completion: dict) -> dict:
        """[indicators] assists: surface EVERY cria assist that fired as a ⟦cria⟧ line — the
        out-of-band `cria_notes` channel the guards append to (rumination/truncation/steer) PLUS any
        ⟦cria⟧ note already in the content (the repetition/wheel-spin probes). 'No hidden guards':
        under the flag a fired guard is always visible; with the flag off, all of it is stripped."""
        ic = self.server.cfg.indicators
        notes = completion.pop(bodykeys.NOTES, None) or []
        completion.pop(bodykeys.FENCED_REFUSED, None)   # cria-internal; the loop consumes it where it matters
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
                      getattr(rlog, "events", None), getattr(rlog, "ledger", None))
        completion = self._decorate(completion)
        # THE CONNECT BANNER, on the path that actually runs. `_route` builds an Indicator carrying
        # it, and that covers the PROXY path — but when the loop engages (every suite run, every
        # real coding turn) `_produce_stream` returns before `_route` is ever reached, so the
        # banner was invisible exactly where it matters. `_finalize` is this file's stated "single
        # completion-finalization chokepoint" and the drive path does go through it; the one-shot
        # flag is shared, so whichever path fires first wins and neither double-prints.
        #
        # Gated on VISIBLE OUTPUT for the reason `inject_buffered` documents in full: a header-only
        # completion is stored and re-summarized by the harness as if it were the model's answer
        # (it once became an entire compaction summary). A banner must decorate a real turn or wait
        # for one.
        if ic.enabled and ic.connect and _has_visible_output(completion):
            for line in reversed(self._take_connect_lines(rlog)):
                _prepend_content_line(completion, f"{MARKER}{line}")
        tool_turn = any((ch.get("message") or {}).get("tool_calls") for ch in completion.get("choices", []))
        if not tool_turn and not generation.incomplete(completion) and stats.calls >= 2:  # a text answer after real work → the turn ended
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
        self._retain_external_output(completion, sess_key)
        return self._retain_pasted_output(completion)

    def _reasoner_question(self, rlog):
        """The one closed-question seat a returned-history assist may use: reasoning off, temperature 0, one reply. None
        when no reasoner role is configured (`reasoner_upstream` alone is not proof of one: it falls back to the coder)."""
        server = self.server
        if server.reasoner_role is None:
            return None
        def chat(call, log):
            return server.reasoner_upstream.chat(call, log)
        return lambda question: ask_closed(chat, server.reasoner_role, question, rlog, phase="package-quality",
                                           max_tokens=JUDGE_MAX_TOKENS, retry_off=False)

    def _bind_workspace_view(self, body: dict, sess_key: str) -> None:
        """THE WORKSPACE VIEW FOR THIS REQUEST. cria answers every question about the coder's files
        from facts the HARNESS gathered — never from its own disk, which is the same machine only by
        accident. Bound before `represent_inbound`, which is the pass that fills it: it walks the
        whole conversation, and every file tool in there is one cria lowered itself.

        AND BEFORE `reframe_compaction`, which is why it lives here rather than inside
        `_setup_translation`. That pass asks `loop._workspace_is_empty` in order to choose between
        two reframes, and the alternative — `compaction_reframe_empty` — is the one whose docstring
        calls the other "the drift ROOT: a fresh/restarted session over an empty cwd took that claim
        at face value and sent the model hunting for its 'prior work' in sibling directories".
        `wsview.bind` is the only bind site in the package and it ran AFTER the reframe on both POST
        paths, so `current()` returned an empty unbound view, `_workspace_is_empty` answered False by
        its own conservative rule, and the empty variant fired **0 times in 8,226 reframes**.

        Called TWICE per request on purpose: once here, early, with the best key the path has at
        that moment, so the reframe has a view to ask; then again from `_setup_translation` under
        the definitive session key. The early view accumulates nothing — `represent_inbound`, the
        pass that fills it, runs after the second bind — so re-binding costs nothing and keeps the
        per-session key exact."""
        self._workspace_root = _session_cwd(sess_key, body.get("messages", []), lexical=True)
        wsview.bind(wsview.View(self._workspace_root, sess_key))

    def _strip_and_reframe_inbound(self, body: dict, sess_key: str, rlog) -> None:
        """Strip cria's own indicator lines from the history, and — at CONTEXT_FIXES and above —
        reattribute the harness's compaction turn.

        ONE OWNER. This was two byte-identical copies, one per transport path, and the level gate
        below had to be written into both. A rung gate at two call sites is honoured at one of them
        the first time someone edits in a hurry; the tool layer had the same shape and the same fix.

        The view is bound FIRST: `reframe_compaction` asks it whether the workspace is empty, and an
        unbound view answers "not surveyed" to everything (see `_bind_workspace_view`).
        """
        messages = body.get("messages")
        if not isinstance(messages, list):
            return
        self._bind_workspace_view(body, sess_key)
        upgraded = privatenames.upgrade_names(messages)     # an earlier release's private names, so every reader below sees one spelling
        cleaned, stripped = strip_history(upgraded)
        # LEVEL 3 — CONTEXT_FIXES. Reattributing the harness's compaction turn REWRITES a message the
        # harness wrote, which is surgery on the context by any reading, so it belongs to the rung
        # that owns surgery. It ran at EVERY level including the pure proxy until 2026-08-25, and
        # escaped notice because a level-0 session is short enough that the harness never compacts —
        # the same blind spot that hid the periodic gate. A mechanism that needs a long conversation
        # to fire cannot be proven gated by a test that sends one short request.
        reframed = 0
        if self.server.cfg.routing.context_fixes:
            live_loop = getattr(self.server, "loop", None)
            sess = live_loop._store.get(sess_key) if live_loop is not None else None
            origin = getattr(sess, "handoff_origin", None)
            before = cleaned
            cleaned, reframed = reframe_compaction(before, origin=origin)
            if reframed:
                cleaned = _mark_replayed_handoffs(before, cleaned, origin)
        # C44 R1 (review 9eaadebe): UNCONDITIONAL, every level — `reframe_compaction` above is the
        # interpreter (picks the right template) for the shapes it recognizes, gated on CONTEXT_FIXES
        # by the same "reattribution is surgery" rule as the reframe itself; this is the blanket net
        # for everything it does not reach (a level below CONTEXT_FIXES never calls it at all; a
        # harness that stores the compaction reply verbatim under a different role, with no Codex
        # preamble, is never recognized by it either). Runs on `cleaned`, AFTER the interpreter has
        # had its chance, so it only ever removes a marker nothing already consumed.
        rescrubbed = strip_prose_dropped_marker(cleaned)
        marker_left = rescrubbed is not cleaned
        if marker_left:
            cleaned = rescrubbed
        if stripped or reframed or marker_left or upgraded is not messages:
            body["messages"] = cleaned
            if stripped:
                rlog.emit("indicators.stripped", lines=stripped)
            if reframed:
                held = getattr(sess, "handoff_origin", None) if self.server.cfg.routing.context_fixes else None
                rlog.emit("loop.compaction_reframed", reshape="reframe",
                          origin="recorded" if held is not None else "absent",
                          origin_reply_chars=len(held.reply) if held is not None else 0)
            if marker_left:
                rlog.emit("loop.prose_dropped_marker_scrubbed", level="warn")

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
        owner = self.server.loop_store.get_guard(sess_key)
        if owner is not None:
            observe_externalization_results(owner, body.get('messages') or [])
        self._shell_tool = None
        self._synthetic: set[str] = set()
        self._native_search = None
        self._brave_key = None
        self._unread_target = None
        self._shrink_services = None
        # LEVEL 2 — SIMPLE_TOOLS. Below this rung cria alters no toolset: the harness's own tools go
        # up exactly as they arrived, nothing is lowered to shell, nothing is re-presented, and the
        # menu is not curated. ONE owner for the whole tool layer, both call sites, so a rung cannot
        # be half-applied on one path (the chat and Responses paths ran identical copies of this,
        # which is precisely how a level gate written once ends up honoured once).
        if not self.server.cfg.routing.simple_tools:
            return
        self._shell_tool = needs_translation(body.get("tools"))
        self._search_only = self._shell_tool is None and find_shell_tool(body.get("tools")) is not None
        if self._search_only:
            self._shell_tool = find_shell_tool(body.get("tools"))
        self._brave_key = brave.api_key()
        # The workspace root (from the harness env-context <cwd>) — the boundary the external-dir
        # guard classifies paths against when it bounds a fledgling model on the --yolo harness.
        self._bind_workspace_view(body, sess_key)   # definitive key; re-binds a fresh view
        # Re-present prior lowered shell calls as the synthetic tool the model actually called —
        # UNCONDITIONALLY, before the shell-tool gate. A harness compaction/summarize turn arrives with
        # tools:[] (no shell tool), yet its history still holds cria's ⟦ctx:tool⟧-lowered write_file/
        # edit_file/read_file calls; without this the model summarizes ~28 raw `python3 - <<HEREDOC`
        # blobs instead of its own tool calls, and that degraded summary becomes the next ⟦ctx:
        # continuation⟧. No-op when no sentinel is present, so a plain passthrough is unaffected.
        # C40's own probe (represent_inbound's tools_present arg) skips a compaction/summarize turn
        # on EITHER signal reachable at this seam: an empty tool menu (the shape this survey's own
        # comment above already relies on) OR the server's own compaction recognition
        # (`_is_compaction_request`, C37's hardened detection -- a reasoner-driven check, not only the
        # `<<<LOCAL_COMPACT>>>` marker), so a compaction turn whose harness still sends a full tool
        # menu is not missed either.
        _c40_active = bool(body.get("tools")) and not _is_compaction_request(body.get("messages", []))
        # The authenticated bootstrap runs a read-only inventory in the workspace;
        # its private transport is not a coder mutation. Keep it for the loop to
        # consume, but do not invalidate the new view while representing history.
        private_readonly = set()
        bootstrap = self.server.loop_store.get_bootstrap(sess_key)
        if bootstrap is not None and bootstrap.initial_inventory:
            from . import initial_inventory
            before = body.get('messages') or []
            after = initial_inventory.strip_calls(before, bootstrap.initial_calls)
            ids = lambda items: {call.get('id') for message in items if message.get('role') == 'assistant'
                                 for call in message.get('tool_calls') or () if isinstance(call, dict)}
            private_readonly = ids(before) - ids(after)
        body["messages"] = redact_secrets(
            represent_inbound(body.get("messages", []), rlog,
                              workspace_root=getattr(self, "_workspace_root", None),
                              sess_key=sess_key, tools_present=_c40_active,
                              window=windowcaps.known_window(self.server._endpoint_for("coder"), rlog),
                              ask=self._reasoner_question(rlog), private_readonly_calls=private_readonly,
                              ledger_outcomes=getattr(self, '_ops_outcomes', None),
                              ledger_reads=getattr(self, '_ops_reads', None)),
            self.server.secret_values())
        # THE SURVEY KNOWS WHERE IT RAN, and cria was throwing that away. `wsview.apply_survey`
        # adopts the reported root when the view has none — "which is how a session whose harness
        # never announced a cwd still gets a workspace", in its own docstring — and `survey_root`
        # has exactly one caller, inside that function. It never reached the session, so 51 call
        # sites across 8 modules went on abstaining on a missing root while the View beside them
        # knew the answer, and `_external_refusal` returned None on its first line
        # (`if level == "write" or not workspace`), making `[safety] external_dir_permission = "none"`
        # enforce nothing at all on a harness that sends no `<cwd>` — against principles.md's flat
        # "File access remains bounded to the workspace even under --yolo".
        #
        # `represent_inbound` above is the pass that folds surveys in, so the answer is here now if
        # it is anywhere. Remembered under the session key, which is the ONE owner of this fact.
        if not self._workspace_root:
            learned = (wsview.current().root or "").strip()
            if learned:
                self._workspace_root = _remember_session_cwd(sess_key, learned)
                rlog.emit("wsview.root_adopted", level="info", root=learned)
        self._declared_roots = dirguard.declared_roots(body.get("messages", []))
        if self._shell_tool is not None:
            self._native_search = native_search_name(body.get("tools"))
            self._synthetic = advertise(body, rlog, brave_key=self._brave_key, search_only=self._search_only)
            if self._search_only and not self._synthetic:
                self._shell_tool = None
            # The exact-repeat fetch/search gate refuses a repeat ONLY while its result is still in
            # context — feed it the web calls STILL PRESENT, so a compacted-away result (an OpenAPI
            # spec the model needs to re-read) can be re-fetched instead of blocked forever.
            fk, sq = _visible_web_calls(body.get("messages", []))
            webfetch.set_visible(sess_key, fk, sq)
            # The files the coder has read or written, as of THIS request, so the write lowering can
            # refuse a whole-file replacement of an existing file it has never seen (None when cria is
            # not engaged enough to keep that record — a guess would be a false fact).
            self._unread_target = (self.server.loop.unread_target_check(
                sess_key, body.get("messages", []), self._workspace_root, rlog)
                if self.server.loop is not None else None)
            self._shrink_services = (self.server.loop.shrinking_write_services(
                sess_key, body.get("messages", []), self._workspace_root, rlog)
                if self.server.loop is not None else None)
        # Tool-menu FOCUS: curate the harness's menu to the coding essentials (drop the goal/MCP/
        # connector firehose), then a terse per-tool cheat-sheet for the curated set. AFTER advertise,
        # so cria's write_file survives the curation.
        policies = toolmenu.selected_policies(assistruntime.current().definitions)
        focused = policies.focus(toolmenu.FocusInput(
            body.get("tools"), configured=self.server.cfg.tools.focus), rlog)
        if focused.applied:
            body["tools"] = focused.tools
        instructions = policies.instructions(toolmenu.InstructionInput(
            body.get("tools"), body.get("messages") or [],
            configured=self.server.cfg.tools.cheatsheet), rlog)
        if instructions.applied:
            body["messages"] = instructions.messages
            body["tools"] = toolmenu.enrich_descriptions(body.get("tools"))

    def _defer_pasted_delivery(self, settle):
        # Invocation-local obligations, never a session cache or serialized packet.
        self._pasted_retention = settle
        self._pasted_lowered = None

    def _retain_pasted_output(self, completion):
        settle = getattr(self, '_pasted_retention', None)
        self._pasted_retention = None
        if settle is not None:
            settle(completion, getattr(self, '_pasted_lowered', None))
        return completion

    def _retain_external_output(self, completion: dict, sess_key: str) -> dict:
        owner = self.server.loop_store.get_guard(sess_key)
        if owner is not None:
            retain_externalizations(owner, completion)
        return completion

    def _translate_out(self, completion: dict, sess_key: str, rlog) -> dict:
        """Lower the model's synthetic-tool calls to shell, when translation is active for this
        request (set up in `_setup_translation`). ``sess_key`` enables webfetch's per-session
        fetch/search repeat + stop-guessing gates."""
        completion = callauth.neutralize(generation.safe_completion(completion))
        research = any((tc.get('function') or {}).get('name') in ('web_fetch', 'web_search')
                       for choice in completion.get('choices', [])
                       for tc in (choice.get('message') or {}).get('tool_calls') or [])
        owner = self.server.loop_store.get_guard(sess_key, create=(research and
            assistruntime.current().externalization is not None))
        admitted = {}
        def observed(original, lowered, proposed_write):
            if proposed_write is not None:
                admitted[lowered.get('id')] = proposed_write
        if self._shell_tool is not None:
            lowering = loweringoptions.resolve(assistruntime.current() if assistruntime.is_bound()
                                               else self.server.pilot_runtime)
            translate_outbound(completion, self._shell_tool, rlog, injected=getattr(self, "_synthetic", set()),
                               brave_key=getattr(self, "_brave_key", None),
                               native_search=getattr(self, "_native_search", None), session=sess_key,
                               workspace_root=getattr(self, "_workspace_root", None),
                               external_dir_permission=self.server.cfg.safety.external_dir_permission,
                               declared_roots=getattr(self, "_declared_roots", ()),
                               unread_target=getattr(self, "_unread_target", None),
                               shrink_services=getattr(self, "_shrink_services", None),
                               # Both options are registered assists (`loweringoptions`: packing L4, echo L5):
                               # the bound selection decides, so below their rung (or opted out) the lowered
                               # command is byte-for-byte what it always was.
                               pack=lowering.pack, edit_echo=lowering.edit_echo,
                               observe_lowering=observed, externalization_owner=owner,
                               only_injected=getattr(self, '_search_only', False), safe_path=self.server.cfg.harness.safe_path,
                               issue_read=lambda call, args, instead: self.server.ops.issue_read(
                                   getattr(self, '_ops_session', sess_key), self._shell_tool, call, args,
                                   workspace_root=getattr(self, "_workspace_root", None),
                                   level=self.server.cfg.safety.external_dir_permission, roots=getattr(self, "_declared_roots", ()),
                                   instead=instead),
                               issue_list_dir=lambda call, args: self.server.ops.issue_list_dir(
                                   getattr(self, '_ops_session', sess_key), self._shell_tool, call, args, workspace_root=getattr(self, "_workspace_root", None),
                                   level=self.server.cfg.safety.external_dir_permission, roots=getattr(self, "_declared_roots", ())))
            self._pasted_lowered = admitted
        else:
            self._pasted_lowered = None
        return completion

    def _focus_trim(self, framed: dict, rlog) -> tuple[dict, bool]:
        """Collapse exact-duplicate tool calls in the OUTBOUND coder body so the model stays focused
        on current state — applied to the FRAMED copy, never the history cria's detectors read.
        Gated by [context] focus_trim, and by the selection: the focus stage's definitions are
        registered at LEVEL 3 — CONTEXT_FIXES (below it cria performs no surgery on the context at
        all, and folding duplicate tool calls is surgery however harmless it looks), and an empty
        selection is an exact bypass. Returns (body, applied?)."""
        if not self.server.cfg.context.focus_trim:
            return framed, False
        msgs = framed.get("messages")
        if not isinstance(msgs, list):
            return framed, False
        selected = assistruntime.current() if assistruntime.is_bound() else self.server.pilot_runtime
        definitions = selected.bindings("coder-focus")
        if not definitions:
            return framed, False
        result = focustrim.focus(focustrim.FocusInput(msgs), definitions)
        framed = assistruntime.retain_focus_bindings(framed, result, definitions)
        if not result.report.applied:
            return framed, False
        rlog.emit("context.focus_trim", reshape="focus-trim", dropped_calls=result.report.dropped_calls,
                  dropped_msgs=result.report.dropped_msgs)
        return {**framed, "messages": result.messages}, True

    def _route(self, body: dict, classification, rlog, compaction: bool = False) -> tuple[object, Indicator]:
        """Resolve the provider/model for this classification and build the
        indicator. Falls back to the local upstream (passthrough) when routing isn't
        configured or nothing resolves. Mutates ``body["model"]``."""
        server: CriaServer = self.server
        ic = server.cfg.indicators

        # L0 is the wire-only control: no classifier/compactor role may replace the requested
        # model, endpoint, sampling, or reasoning effort. Translation still happens around it.
        if getattr(server.cfg.routing, "engagement_level", config.MAX_ENGAGEMENT_LEVEL) == config.PURE_PROXY:
            return server.upstream, Indicator(False, False, model=str(body.get("model") or "?"), role=None)

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

        # A harness COMPACTION request (the `<<<LOCAL_COMPACT>>>` handshake, or one `_recognize_
        # compaction` resolved for a harness that never sends the marker) is a SUMMARIZE — route it
        # to the compactor role's tuned sampling on the compactor endpoint, not the classifier's guess
        # (its text reads as a plain 'question' → the reasoner). The compactor endpoint falls back to the
        # reasoner/shared upstream when no [roles.compactor] is set, so this is safe unconfigured too.
        # `compaction` is the caller's precomputed answer; the cheap marker check is repeated here
        # too so a caller that only knows the marker still gets the free recognition it always had.
        if compaction or _is_compaction_request(body.get("messages", [])):
            evidence_handoff = server.cfg.routing.context_fixes and _selected_handoff(server) is not None
            role_name = "reasoner" if evidence_handoff else ("compactor" if "compactor" in server.cfg.routing.roles else "reasoner")
            endpoint = server.reasoner_upstream if evidence_handoff else server.compactor_upstream
            rlog.emit("route.compaction", role=role_name)
            return endpoint, Indicator(
                ic.enabled, ic.metrics,
                model=banner_model(endpoint, str(body.get("model") or "?")),
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
        shown = banner_model(route.provider, route.model or str(body.get("model") or "?"))
        return route.provider, Indicator(
            ic.enabled, ic.metrics,
            model=shown, role=route.role,
            show_route=not classification.cached, route=ic.route, assists=ic.assists,
        )

    def _take_connect_lines(self, rlog) -> list[str]:
        """The connect banner's lines, ONCE per process — and the once is spent when they are
        PRINTED, not when they are built.

        That distinction is the whole bug this method exists to end. The first two attempts set the
        flag inside the builder, which `_route` called on every routed turn; five different
        renderers can each decline to print what the builder returned (a tool-call-only turn holds
        `pending` and never flushes, `inject_buffered` drops a header on empty content, an upstream
        error 502s the turn, a keyed cloud provider has no /props, and the Responses adapter — the
        API Codex actually speaks — renders only a route STRING and throws the lines away). Any one
        of those spent the process's only chance and the operator saw nothing, forever. Measured on
        the day's own log: 359 of 372 requests were Responses turns and not one carried a banner.

        So there is now exactly ONE caller, `_finalize`, which prepends the lines itself and calls
        this only when it is about to. Every surface that returns a completion goes through it —
        the plan/drive loop, the buffered proxy, and the Responses adapter via `_produce_completion`.
        The streaming CHAT proxy does not, and is deliberately not covered: neither Codex nor the
        suite speaks it, and a second emitter is what caused this in the first place.

        THE SUBJECT IS THE CODER'S ENDPOINT, not `[defaults]`. The banner answers "can cria drive
        the model that does the work", and a role may carry its own base_url, so asking the shared
        upstream could describe a different server than the one answering (#5b)."""
        if getattr(self.server, "_connect_done", False):
            return []
        provider = self._coder_endpoint()
        if provider is None or not hasattr(provider, "props"):
            return []
        coder = self.server.cfg.routing.roles.get("coder")
        loaded = provider.loaded_model(rlog) if hasattr(provider, "loaded_model") else None
        if not loaded:
            # No answer from /v1/models → say nothing rather than print a config label as if it
            # were the model. The same file warns about exactly that substitution.
            return []
        lines = compat.banner(provider.props(rlog), model=loaded,
                              merge_turns=bool(coder and coder.merge_consecutive_turns),
                              collapse_system=bool(coder and coder.collapse_system_prompt))
        if not lines:
            return []
        self.server._connect_done = True   # spent only now, with the lines on their way out
        rlog.emit("compat.connect", model=loaded, lines=len(lines))
        return lines

    def _coder_endpoint(self):
        """The Upstream the CODER role actually runs on — the subject of the compat report."""
        try:
            return self.server.router.endpoint_for("coder") if self.server.router else self.server.upstream
        except (AttributeError, KeyError):
            return self.server.upstream

    def _apply_route_role(self, pbody: dict, indic, rlog=None) -> dict:
        """Attach the routed role's sampling + reasoning (temp/top_p/top_k/repeat_penalty + the
        reasoning toggle, translated to its backend's convention) to a proxy-path body, in place.
        WITHOUT this a model on the proxy path runs on the server's defaults — no repeat_penalty
        (gemma4 then leaks `<|tool_call>`/`<|channel>` tokens), wrong temperature, no reasoning
        toggle — i.e. NOT the model the toml configures. The plan loop applies the role per call
        (loop.py); the proxy and direct-coder paths must do the same, or the same model behaves like
        a different one."""
        if getattr(self.server.cfg.routing, "engagement_level", config.MAX_ENGAGEMENT_LEVEL) == config.PURE_PROXY:
            return pbody
        role = self.server.cfg.routing.roles.get(indic.role) if getattr(indic, "role", None) else None
        if role is not None:
            role.apply(pbody, rlog=rlog)
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
        except (BrokenPipeError, ConnectionResetError, _ClientHungUp):
            rlog.emit("response.client_gone", level="warn")
        finally:
            hb.stop()

    def _engages_loop(self, sk: str, classification, body=None, compaction=False) -> bool:
        """Should this turn go through the loop (cria's ONE coder driver) rather than the proxy?
        A KNOWN session always continues — a mid-plan tool result / a post-compaction continuation
        classifies as non-task, and gating on per-turn classification would abandon the work. For a
        FRESH turn, classification gates STARTING: planner ON → an ``engagement == "task"``; planner
        OFF → a ``task_type == "coding"`` (the synthetic 1-item path). With classification disabled,
        shared admission instead uses actionable harness capabilities, excluding auxiliary requests;
        no semantic verdict is manufactured. BOTH producers and the driver use that same contract."""
        loop = self.server.loop
        if loop is None:
            return False
        if loop.knows_session(sk):
            return True
        return admission.starts_driver(body or {}, classification,
                                       planning=self.server.cfg.planner.enabled,
                                       compaction=compaction)

    def _produce_stream(self, body: dict, rlog):
        """The SSE chunk generator. The blocking model work happens here on the first
        iteration, so the heartbeat running in `_respond_stream` covers it.

        Every model-touching step — classify, the plan loop, and the routed call — is
        under one guard: an upstream failure (e.g. a 500 from a strict chat template)
        becomes a clean in-stream error, never a dead handler thread."""
        server: CriaServer = self.server
        workflow = getattr(server, 'image_workflow', None)
        token = _image_current.set(None)
        try:
            context = workflow.capture(session_key(self.headers, body.get('messages', [])), body) if workflow else None
            _image_current.set(context)
            # Recognized ONCE per request — the marker (free) or, when tools are empty/absent and
            # the marker is absent, the one focused judge call (see _recognize_compaction). Every
            # downstream compaction check in this request reuses this single answer.
            handoff = _selected_handoff(server)
            sk = session_key(self.headers, body.get("messages", []))
            owner = _observe_handoff_write_results(server, sk, body.get("messages", []))
            compaction = _recognize_compaction(body, server, rlog, definition=handoff)
            if compaction and handoff is not None and server.cfg.routing.context_fixes:
                # The entire answer must be judged before any part can be delivered. Use the same
                # hardening/settlement path as buffered requests, then emit the resulting packet.
                completion, indic = self._produce_completion_once({**body, "stream": False}, rlog, sk)
                yield from wrap_stream(completion_to_sse(completion), indic)
                return
            classification = self._classify(body, rlog, compaction)
            # ONE coder driver: engage the loop when it should (a known session, or a fresh turn the
            # loop would start — see _engages_loop). It drives a real multi-item plan OR the synthetic
            # 1-item plan-off path; both come back as a completion. Otherwise fall through to the proxy.
            if self._engages_loop(sk, classification, body, compaction):
                completion = server.loop.drive(body, sk, classification, rlog,
                    pasted_delivery=self._defer_pasted_delivery)
                if completion is not None:
                    yield from completion_to_sse(self._finalize(self._translate_out(
                        completion, sk, rlog), sk, rlog))
                    return
            provider, indic = self._route(body, classification, rlog, compaction)
            rlog.phase = "proxy"
            sbody = _proxy_body(body, self.server.cfg.routing.context_fixes, getattr(self, "_workspace_root", None))
            if self.server.cfg.routing.context_fixes and compaction and handoff is not None:
                facts = _handoff_facts(server, sk, body, rlog, owner)
                sbody = _compaction_body(sbody, definition=handoff, facts=facts,
                                         distill=_handoff_distiller(provider, server, rlog))
            stream = massage.massage_stream(
                _failover_noted(self._image_stream(provider, self._apply_route_role(sbody, indic, rlog), indic, rlog),
                                indic, rlog),
                body.get("model", ""),
                body.get("tools"),
                rlog,
                post=lambda c: self._retain_external_output(self._translate_out(self._image_register(c, body), sk, rlog), sk),
            )
            yield from wrap_stream(stream, indic)
        except (ReadFitUnknown, ReadFitOverflow) as e:
            while True:
                fallback = self._fit_fallback(e, sk, rlog)
                try:
                    completion, _ = self._produce_completion_once(fallback, rlog, sk)
                    break
                except (ReadFitUnknown, ReadFitOverflow) as error:
                    e = error
            yield from completion_to_sse(completion)
        except ImageUnavailable as e:
            rlog.emit("response.error", level="error", error=str(e))
            yield _error_sse(e.response_error)
        except UpstreamError as e:
            rlog.emit("response.error", level="error", error=str(e))
            yield _error_sse(e.response_error if generation.is_generation_error(e.response_error) else str(e))
        except Exception as e:  # noqa: BLE001 — never die silently mid-stream (the g4 hole)
            rlog.emit("response.error", level="error", error=repr(e), traceback=traceback.format_exc())
            yield _error_sse(f"cria internal error: {e}")
        finally:
            _image_current.reset(token)

    def _image_register(self, completion, body):
        context = _image_current.get()
        if context is None or context.prepared.bindings or context.workflow.workspace is None:
            return completion
        # massage_stream's existing terminal quarantine admits the complete action
        # before this source-owned post hook and before any tool fragments emit.
        return context.workflow.workspace.register(context.session, completion, body.get('tools'))

    def _image_stream(self, provider, body, indic, rlog):
        context = _image_current.get()
        if context is None or not context.prepared.bindings:
            yield from provider.stream_chat(body, rlog)
            return
        role = self.server.cfg.routing.roles.get(indic.role) if getattr(indic, 'role', None) else None
        # Internal image tool exchanges finish before exposing a completion to the harness.
        raw = context.workflow.chat(provider, role, body, context, rlog)
        yield from completion_to_sse(json.loads(raw))

    def _produce_completion(self, body: dict, rlog, sess_key: str, progressive=None):
        from .upstream import ReadFitUnknown, ReadFitOverflow
        workflow = getattr(self.server, 'image_workflow', None)
        context = workflow.capture(sess_key, body) if workflow else None
        token = _image_current.set(context)
        try:
            current = body
            while True:
                try:
                    return self._produce_completion_once(current, rlog, sess_key, progressive)
                except (ReadFitUnknown, ReadFitOverflow) as error:
                    current = self._fit_fallback(error, sess_key, rlog)
        finally:
            _image_current.reset(token)

    def _handoff_evidence(self, sess_key: str, body: dict, rlog) -> str:
        """What a harness handoff reads besides the request body: the session's gate facts and the workspace
        listing the writer is shown. A reused briefing must have been made on exactly this (`handoffmemo`). The
        carried ledger is not in it: it follows from the body and from the producer record the briefing's own
        commit replaces."""
        facts = _handoff_facts(self.server, sess_key, body, rlog, _handoff_session(self.server, sess_key))
        return handoffmemo.digest(facts.workspace_root, facts.original_task, facts.gate_flag, facts.gate_age,
                                  facts.checks, _workspace_listing(facts.workspace_root),
                                  groundtruth.workspace_inventory(facts.workspace_root, flavor="briefing"))

    def _produce_completion_once(self, body: dict, rlog, sess_key: str, progressive=None):
        """Run the pipeline and return ``(chat-completion dict, Indicator|None)`` —
        the plan loop's completion, or a routed+massaged+lowered one. Raises
        ``UpstreamError`` on a model failure (callers turn that into a clean error).
        Shared by the buffered chat path and the Responses adapter.

        A harness compaction (the harness offers no tools) is produced ONCE per identical request of a session:
        the harness retries a failed request up to three times, and each retry used to re-run the briefing
        writer and every validator lens. ``handoffmemo`` answers the retry with the first reply's exact bytes."""
        if (_selected_handoff(self.server) is None or body.get("tools")
                or not self.server.cfg.routing.context_fixes):
            return self._produce_completion_fresh(body, rlog, sess_key, progressive)
        with handoffmemo.of(self.server).claim(sess_key, handoffmemo.digest(body)) as claim:
            kept = claim.recall(lambda: self._handoff_evidence(sess_key, body, rlog))
            if kept is not None:
                rlog.emit("handoff.memo_reused")
                return kept
            return self._produce_completion_fresh(body, rlog, sess_key, progressive, claim)

    def _produce_completion_fresh(self, body: dict, rlog, sess_key: str, progressive=None, claim=None):
        server: CriaServer = self.server
        # Recognized ONCE per request — see _produce_stream's twin call for the same reasoning.
        handoff = _selected_handoff(server)
        owner = _observe_handoff_write_results(server, sess_key, body.get("messages", []))
        compaction = _recognize_compaction(body, server, rlog, definition=handoff)
        classification = self._classify(body, rlog, compaction)
        # ONE coder driver: engage the loop (a real multi-item plan OR the synthetic 1-item plan-off
        # path) whenever it should; otherwise proxy. See _engages_loop — a known session ALWAYS
        # continues (a mid-plan tool result / continuation classifies as non-task, and gating on that
        # would abandon the work: "stopped after a command"); classification only gates STARTING.
        if self._engages_loop(sess_key, classification, body, compaction):
            # The model-visible size is taken BEFORE the drive (a finished session drops its state)
            # and from the same framing the coder prompt is built from — see Loop.visible_context_tokens.
            visible = server.loop.visible_context_tokens(
                body, sess_key, fold=bool(server.cfg.routing.context_fixes),
                definitions=server.pilot_runtime.wire_folds)
            completion = server.loop.drive(body, sess_key, classification, rlog,
                pasted_delivery=self._defer_pasted_delivery)
            if completion is not None:
                reply_estimate = modelview.reply_tokens(completion)
                out = self._finalize(self._translate_out(
                    completion, sess_key, rlog),
                    sess_key, rlog)
                _report_context_usage(out, visible, rlog, reply_estimate=reply_estimate)
                return out, None  # loop path carries no indicator
        provider, indic = self._route(body, classification, rlog, compaction)
        rlog.phase = "proxy"
        pbody = _proxy_body(body, self.server.cfg.routing.context_fixes, getattr(self, "_workspace_root", None))
        facts = None
        if self.server.cfg.routing.context_fixes and compaction and handoff is not None:
            facts = _handoff_facts(server, sess_key, body, rlog, owner)
            pbody = _compaction_body(pbody, definition=handoff, facts=facts,
                                     distill=_handoff_distiller(provider, server, rlog))
        pbody, _ = self._focus_trim(pbody, rlog)
        pbody = self._apply_route_role(pbody, indic, rlog)
        image_context = _image_current.get()
        evidence_handoff = self.server.cfg.routing.context_fixes and compaction and handoff is not None
        try:
            if image_context is not None:
                role = self.server.cfg.routing.roles.get(indic.role) if getattr(indic, 'role', None) else None
                raw = image_context.workflow.chat(provider, role, pbody, image_context, rlog)
            elif progressive is not None and not compaction and hasattr(provider, "chat_watched"):
                raw = self._chat_progressive(provider, pbody, progressive, rlog)
            else:
                raw = provider.chat(pbody, rlog)
            _note_failover(indic, rlog)
            try:
                comp = massage.apply(json.loads(raw), body.get("tools"), rlog)
            except (json.JSONDecodeError, TypeError) as e:
                raise UpstreamError("upstream returned a non-JSON 200 body: "
                                    + repr(content_reduce.clip(raw, 200))) from e
        except Exception as e:
            if not evidence_handoff:
                raise
            # The writer is optional. Preserve the actual transcript even if the upstream
            # fails or its response is unreadable; the empty candidate cannot be published.
            rlog.emit("context.compaction_writer_unavailable", level="warn", error=type(e).__name__)
            comp = {"choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}]}
        commit_handoff = None
        decided = None   # the verdict watch of a hardened handoff; None when no handoff ran
        def defer_handoff(commit):
            nonlocal commit_handoff
            commit_handoff = commit
        if evidence_handoff:
            decided = handoffmemo.VerdictWatch(rlog)
            comp = _harden_compaction_reply(comp, body, provider, server, decided, sess_key,
                definition=handoff, _defer_commit=defer_handoff, _owner=owner, _facts=facts)
        elif not body.get("tools") and not generation.incomplete(comp):
            comp = massage.coerce_text_answer(comp, rlog)
        if massage.is_truncated(comp):
            indic.note = "⚠ output truncated at the token limit"
            rlog.emit("response.truncated")
        reply_estimate = (modelview.reply_tokens(comp)
                          if server.cfg.routing.engagement_level != config.PURE_PROXY else None)
        out = self._finalize(self._translate_out(comp, sess_key, rlog), sess_key, rlog)
        # L0 forwards the backend's measured usage; chars/4 is observation, not accounting.
        # The harness uses this count to compact before the next request fills the native window.
        if server.cfg.routing.engagement_level != config.PURE_PROXY:
            # A harness COMPACTION request is reported as the conversation being compacted (the
            # inbound history), not the summary prompt cria rebuilt it into; every other proxied
            # turn as the body the model was shown (post focus-trim), pre-floor.
            shown = body if (self.server.cfg.routing.context_fixes and compaction) else pbody
            _report_context_usage(out, modelview.visible_tokens(
                shown.get("messages") or [], shown.get("tools"),
                fold=bool(self.server.cfg.routing.context_fixes),
                definitions=server.pilot_runtime.wire_folds), rlog, reply_estimate=reply_estimate)
        if commit_handoff is not None:
            commit_handoff(out)
        if (claim is not None and decided is not None and not decided.undecided
                and not massage.is_truncated(comp) and not generation.incomplete(comp)):
            claim.remember(self._handoff_evidence(sess_key, body, rlog), (out, indic))
        return out, indic

    def _chat_progressive(self, provider, pbody: dict, progressive, rlog) -> bytes:
        """The routed call for a turn whose text may leave early: streamed from the model, text handed
        to ``progressive`` as it arrives, the COMPLETE assembled completion returned for exactly the
        post-processing a buffered call gets. Retrying a transient failure is the buffered call's
        job, so a failure before any text was delivered is simply re-asked through it."""
        try:
            return provider.chat_watched(pbody, rlog, on_content=progressive.feed)
        except (UpstreamError, OSError) as e:
            if progressive.opened or _terminal_upstream_error(e):
                raise
            rlog.emit("response.progressive_reask", level="warn", error=str(e))
            return provider.chat(pbody, rlog)

    def _respond_buffered(self, body: dict, rlog) -> None:
        try:
            comp, indic = self._produce_completion(body, rlog, session_key(self.headers, body.get("messages", [])))
        except ImageUnavailable as e:
            rlog.emit("response.error", level="error", error=str(e))
            self._send_json(422, {"error": e.response_error})
            return
        except UpstreamError as e:
            rlog.emit("response.error", level="error", error=str(e))
            if generation.is_generation_error(e.response_error):
                self._send_json(e.code or (500 if generation.is_protocol_error(e.response_error) else 502), {"error": e.response_error})
            else:
                self._send_json(502, {"error": f"upstream error: {e}"})
            return
        except Exception as e:  # noqa: BLE001 — the fail-SILENT hole: any other exception killed the
            # handler thread with no response and no event (g4: FileNotFoundError on a prompt file
            # deleted mid-run — SIX invisible deaths, only journalctl knew; codex retried 5x into
            # silence and exited the whole run). The harness must see a clean error it can surface,
            # and cria's own log must carry the crash.
            rlog.emit("response.error", level="error", error=repr(e), traceback=traceback.format_exc())
            self._send_json(500, {"error": f"cria internal error: {e}"})
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
            rbody, raw = self._read_json_body(retain_raw=True)
        except ValueError as e:
            self._refuse_body(e)
            return
        sess = responses.session_key_of(rbody)
        rlog = log.bind(session=sess, turn=turn)
        if self.server.cfg.logging.capture_calls:
            callcapture.capture_inbound(raw, rlog, calls_dir=self.server.cfg.logging.capture_dir_path,
                                        api="responses", secrets=self.server.secret_values())
        try:
            body = responses.to_chat_body(rbody)
        except ValueError as e:
            rlog.emit("request.unsupported", level="warn", api="responses", error=str(e))
            self._send_json(400, {"error": str(e)})
            return
        if not body["messages"]:
            rlog.emit("request.unsupported", level="warn", api="responses", error="no input")
            self._send_json(400, {"error": "input holds no message (nothing to answer)"})
            return
        sess_key = f"sid:{sess}" if sess else session_key(None, body.get("messages", []))
        self._ops_original_body = copy.deepcopy(body)
        if self._ops_inbound(body, sess_key, rlog, api='responses', stream=bool(rbody.get('stream'))):
            return

        # INBOUND STRIP (mirrors the chat path): remove cria's own "⟦cria⟧" indicator lines
        # from the history before anything re-reads them — the classifier, the plan's rewrite
        # summary, the model. Without it the banner leaked into the compaction summary and the
        # plan task on this (the Responses) path, which Codex speaks.
        messages = body.get("messages")
        if isinstance(messages, list):
            # The view first: `reframe_compaction` asks it whether the workspace is empty, and an
            # unbound view answers "not surveyed" to everything (see _bind_workspace_view).
            self._strip_and_reframe_inbound(body, sess_key, rlog)

        # Same context-shaping as the chat path: write_file↔shell + cheat-sheet. Pass THIS path's
        # sess_key (sid:<sess>) so the fetch gate's visible-set is recorded under the SAME key the
        # outbound lowering reads — without this the exact-repeat gate is dead on the Responses path.
        self._setup_translation(body, sess_key, rlog)
        if not self._bind_read_facts(body, rlog):
            self._representation_fallback(body, sess_key, rlog)

        _incoming_ctx_tokens(body, rlog)  # observation only; reported usage is model-visible (see _produce_completion)
        stream = bool(rbody.get("stream"))
        # Definitive tool attribution (harness-vs-us): what the harness SENT (raw inbound, pre-convert)
        # + its tool TYPES (catches a non-`function` type our converter would drop) vs what SURVIVES
        # cria's convert + focus. inbound>0 but after==0 ⇒ cria dropped them; inbound==0 ⇒ harness sent none.
        _raw_tools = rbody.get("tools") or []
        rlog.emit("request.recv", api="responses", assist_profile=assistruntime.current().profile,
                  pilot_assists=assistruntime.current().selected,
                  model=body.get("model"), stream=stream,
                  n_messages=len(body.get("messages", [])),
                  inbound_tools=len(_raw_tools),
                  inbound_tool_types=sorted({(t.get("type") if isinstance(t, dict) else "?") for t in _raw_tools}),
                  tools_after=len(body.get("tools") or []))
        if stream:
            self._respond_responses_stream(body, sess_key, rlog, responses.custom_tool_names(rbody))
        else:
            self._respond_responses_buffered(body, sess_key, rlog, responses.custom_tool_names(rbody))

    def _respond_responses_stream(self, body: dict, sess_key: str, rlog,
                                  custom_tools: frozenset[str] = frozenset()) -> None:
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
            # TOKEN-PROGRESSIVE TEXT, for the turns where nothing can sit in front of, or reorder, the
            # model's own words: no cria line/item/footer of any family, and no loop or generation
            # guard that can abort or re-ask the call (levels below DONE_REFUSALS). Everything else
            # keeps the complete-completion-first path, so every guard that needs the whole answer runs
            # before a word reaches the harness.
            progressive = None
            if not ind.decorates() and not self.server.cfg.routing.done_refusals:
                def deliver(data: bytes) -> None:
                    try:
                        hb.write(data)
                    except (BrokenPipeError, ConnectionResetError) as gone:
                        raise _ClientHungUp() from gone
                progressive = responses.ProgressiveMessage(
                    deliver, lambda text: massage.stream_leak_start(text, rlog),
                    massage.STREAM_HOLDBACK, 0)
            try:
                comp, _indic = self._produce_completion(body, rlog, sess_key, progressive)
            except UpstreamError as e:
                rlog.emit("response.error", level="error", error=str(e))
                hb.write(responses._event("response.failed",
                    {"response": {"id": resp_id, "status": "failed", "error": e.response_error}}))
                return
            except _ClientHungUp:
                raise   # the harness hung up while text left; the model's own resets are NOT this (they get a failed event)
            except Exception as e:  # noqa: BLE001 — the exact scope g4 died in, six times, silently:
                # a FileNotFoundError here killed the handler with no event and no response; codex
                # retried 5x into the void and exited the run. The harness gets a clean failed
                # event; cria's log gets the crash.
                rlog.emit("response.error", level="error", error=repr(e), traceback=traceback.format_exc())
                hb.write(responses._event("response.failed",
                    {"response": {"id": resp_id, "status": "failed", "error": {"message": f"cria internal error: {e}"}}}))
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
            try:
                for chunk in responses.body_events(comp, resp_id, model, banner,
                                                   show_reasoning=show_reasoning,
                                                   reasoning_transcript=reasoning_transcript,
                                                   start_index=start_index, extra_items=extra_items,
                                                   custom_tools=custom_tools, progressive=progressive):
                    hb.write(chunk)
            except responses.ProgressiveDivergence as e:
                # Words are already on the harness's screen and the finished answer no longer starts
                # with them: end with the retryable failure rather than show two different answers.
                rlog.emit("response.progressive_diverged", level="error", error=str(e))
                hb.write(responses.failed_event(resp_id, f"cria could not finish the streamed answer: {e}"))
                return
            except (BrokenPipeError, ConnectionResetError):
                raise
            except Exception as e:  # noqa: BLE001 — an item that cannot be built (a custom call with no string
                # input) left the stream open mid-item with no terminal event: a bare EOF the harness reads
                # as a user abort. The retryable failure is the one terminal event it can act on.
                rlog.emit("response.error", level="error", error=repr(e), traceback=traceback.format_exc())
                hb.write(responses.failed_event(resp_id, f"cria internal error: {e}"))
                return
            rlog.emit("response.sent", api="responses", stream=True, beats=hb.beats,
                      status_lines=len(status_lines))
        except (BrokenPipeError, ConnectionResetError, _ClientHungUp):
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

    def _respond_responses_buffered(self, body: dict, sess_key: str, rlog,
                                    custom_tools: frozenset[str] = frozenset()) -> None:
        try:
            comp, _indic = self._produce_completion(body, rlog, sess_key)
        except ImageUnavailable as e:
            rlog.emit("response.error", level="error", error=str(e))
            self._send_json(422, {"error": e.response_error})
            return
        except UpstreamError as e:
            rlog.emit("response.error", level="error", error=str(e))
            self._send_json(getattr(e, "code", None) or 502, {"error": e.response_error})
            return
        except Exception as e:  # noqa: BLE001 — never die silently (the g4 hole)
            rlog.emit("response.error", level="error", error=repr(e), traceback=traceback.format_exc())
            self._send_json(500, {"error": f"cria internal error: {e}"})
            return
        ind = self.server.cfg.indicators
        show_reasoning = ind.enabled and ind.reasoning
        reasoning_transcript = ind.enabled and ind.reasoning_transcript
        banner = self._compute_banner(comp, _indic, rlog)  # parity with the streaming path
        self._send_raw_json(json.dumps(responses.to_responses_json(
            comp, body.get("model", "") or "", show_reasoning=show_reasoning,
            reasoning_transcript=reasoning_transcript, banner=banner,
            custom_tools=custom_tools)).encode("utf-8"))
        rlog.emit("response.sent", api="responses", stream=False)

    def _send_raw_json(self, raw: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self._write(raw)

    # ------------------------------------------------------------------ util

    def _read_body(self) -> bytes:
        """The request body, exactly Content-Length bytes: refused up front when it is chunked (cria does
        not decode it), malformed, or larger than ``MAX_BODY_BYTES``; read under a total deadline."""
        if self.headers.get("Transfer-Encoding"):
            raise BodyRejected(411, "Transfer-Encoding is not supported: send the body with a Content-Length")
        lengths = {v.strip() for v in self.headers.get_all("Content-Length") or ["0"]}
        if len(lengths) > 1:   # RFC 9110 §8.6: conflicting lengths are a framing error (identical duplicates are one)
            raise BodyRejected(400, f"conflicting Content-Length headers: {sorted(lengths)!r}")
        declared = lengths.pop() or "0"
        if not (declared.isascii() and declared.isdigit()):
            raise BodyRejected(400, f"invalid Content-Length: {declared!r}")
        length = int(declared)
        if length > MAX_BODY_BYTES:
            raise BodyRejected(413, f"request body too large: {length} bytes declared, the limit is {MAX_BODY_BYTES}")
        deadline = time.monotonic() + BODY_DEADLINE_SECONDS
        chunks: list[bytes] = []
        remaining = length
        try:
            while remaining:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError
                self.connection.settimeout(left)
                chunk = self.rfile.read1(min(remaining, 1 << 20))
                if not chunk:
                    raise BodyRejected(400, f"request body ended after {length - remaining} of {length} declared bytes")
                chunks.append(chunk)
                remaining -= len(chunk)
        except TimeoutError:
            raise BodyRejected(408, f"request body not received within {BODY_DEADLINE_SECONDS:g}s") from None
        finally:
            self.connection.settimeout(None)
        return b"".join(chunks)

    def _read_json_body(self, *, retain_raw: bool = False) -> dict | tuple[dict, bytes]:
        raw = self._read_body()
        if not raw:
            raise ValueError("empty body")
        try:
            obj = json.loads(raw)
        except RecursionError:
            raise ValueError("JSON nested too deeply") from None
        if not isinstance(obj, dict):
            raise ValueError("body must be a JSON object")
        return (obj, raw) if retain_raw else obj

    def _refuse_body(self, e: ValueError) -> None:
        """Answer a body that could not be used: a BodyRejected carries its own status (and ends the
        connection when bytes were left unread); any other ValueError is a 400 invalid-JSON-body."""
        if isinstance(e, BodyRejected):
            self.close_connection = e.close
            self._send_json(e.status, {"error": str(e)})
        else:
            self._send_json(400, {"error": f"invalid JSON body: {e}"})

    def _send_json(self, code: int, obj: dict) -> None:
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self._write(raw)

    def _write(self, raw: bytes) -> None:
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _incoming_ctx_tokens(body: dict, rlog=None) -> int:
    """Observation only: chars/4 of the whole INCOMING request (the harness's conversation PLUS the
    tools schema), logged as `ctx.estimate`. This is NOT what is reported to the harness — it counts
    cria's own completion-gate plumbing, which the model never sees, and omits cria's own coder
    prompt, which it does. Reported usage is the model-visible size (`modelview.visible_tokens`;
    `Loop.visible_context_tokens` on the loop path). Logs the msg-vs-tools breakdown."""
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


def _report_context_usage(completion: dict, ctx_tokens: int, rlog, *,
                          reply_estimate: int | None = None) -> None:
    """Report estimated continuing context at L1-L5, not generation consumption.

    Input remains the shared pre-floor model-visible estimate. Output is the
    public/history-projected reply, captured before synthetic lowering by callers.
    Native usage/details remain separate, unchanged; no private token count is
    inferred or subtracted. L0 and native Chat streaming retain their contracts.
    Final-wire fitting remains independent of the harness's compaction decision.
    """
    if ctx_tokens <= 0:
        return
    usage = modelview.continuing_usage(completion, ctx_tokens, reply_estimate=reply_estimate)
    completion["usage"] = usage
    rlog.emit("usage.context_reported", input_tokens=ctx_tokens,
              output_tokens=usage['completion_tokens'], context_estimate=usage['context_estimate'],
              native_usage=usage['native_usage'])
