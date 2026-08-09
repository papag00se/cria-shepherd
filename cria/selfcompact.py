"""Plan-off self-compaction — cria manages its OWN context, on its own side.

On a long plan-off (direct-coder) session the harness may never compact, so the coder's
history grows unbounded (observed: 331 messages / ~35K tokens). The context floor keeps it
UNDER the window by DROPPING the oldest turns — which loses the information. Self-compaction
instead SUMMARIZES the old middle into one rolling briefing (reasoner-generated), so the
coder gets a lean, information-PRESERVING view: [system] + anchors + [rollup summary] +
a small verbatim band + the recent tail.

Everything is measured in TOKENS, not message count — the real constraint is the context
window, and a few huge file reads matter more than many tiny turns (the same currency the
floor uses). Structure kept every turn:
  - the leading system message (cria's coder framing),
  - any ANCHOR message (a ⟦ctx:briefing⟧ handoff / a ___CRIA_GATE_ ground truth) — verbatim,
  - ONE ⟦ctx:rollup⟧ summary of the old middle,
  - a small VERBATIM band of old-but-not-yet-folded turns (bounded by RECOMPACT_TOKENS),
  - the recent tail up to KEEP_TAIL_TOKENS verbatim (the live working set).

The summary is THROTTLED: re-generated only when the unfolded band grows past RECOMPACT_TOKENS,
not every turn (one reasoner call amortized over many turns). Boundary splits (an edge landing
between an assistant tool_call and its result) are cleaned by the floor's existing
_strip_orphan_tools downstream — self-compaction runs BEFORE the floor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import jsontext, probegate, prompts
from .content_reduce import est_tokens

# Tunables in TOKENS. TRIGGER is operator-tunable via [context] trigger_compaction; the rest are
# code constants (they don't vary by environment).
TRIGGER_TOKENS_DEFAULT = 16384   # start compacting a plan-off view once it exceeds this many tokens
KEEP_TAIL_TOKENS = 6000          # keep the most recent turns verbatim, up to this many tokens
BOUNDARY_KEEP_TAIL_TOKENS = 0    # at a verified STEP BOUNDARY keep NO verbatim tail — the completed step's raw
#                                  turns fold ENTIRELY into the rollup. Nothing is lost: the NEXT step rides in
#                                  the caller's authoritative system message, the original task is pinned
#                                  (⟦ctx:task⟧), the API's real endpoint/fields are anchored, and the rollup
#                                  carries the rest. A verbatim tail here would only re-introduce the finished
#                                  step's distracting signals — the exact thing folding at a boundary clears.
#                                  (Without this, force only lowered the TRIGGER; the completed step stayed
#                                  verbatim in the 6000-tok tail and the view GREW step over step — observed
#                                  live: +14KB / ~350 lines between step 1 and step 2.)
RECOMPACT_TOKENS = 4000          # re-summarize only after the unfolded band grows this much (throttle)
REFOLD_TOKENS = 6000             # when the ACCUMULATED rolling summary itself exceeds this, fold it once
#                                  (rollup-of-a-rollup, deliberately RARE — see the refold tier in compact())
SUMMARY_MARKER = "⟦ctx:rollup⟧"     # tags the injected summary — floor-protected + identifiable
TASK_MARKER = "⟦ctx:task⟧"          # tags the pinned original-task header — the session's north star
FACTS_MARKER = "⟦ctx:facts⟧"        # tags the DURABLE fetch ledger (url→status→endpoints) the loop re-injects
                                    # from cria's own session memory, so the coder keeps the real endpoints it
                                    # already fetched even after the HARNESS compacts the raw result out of its
                                    # own history — else it re-fetches to rediscover them (370-call spec loop).
# (⟦ctx:search⟧ lived here and is gone. It tagged ONE denial — a suppressed search-results read — and
#  the general case is every call cria refuses: cria.denial.DENIED_MARKER now marks all of them, at
#  the sites that decide to refuse. Two markers for one idea is one to keep in sync.)
# cria-SURFACED spec-shape markers — the [API endpoints …] / [response shape …] blocks a web_fetch result
# carries (mirror webfetch.ROUTES_MARKER / SHAPE_MARKER; a test asserts sync). They hold the API's REAL
# endpoint paths + response field names — EXTERNAL ground truth the coder must code against, NOT its own
# mutable identifiers. Anchored so compaction keeps them VERBATIM and the summarizer (which deliberately
# drops identifier names) NEVER folds them — else the exact fields vanish and the coder guesses
# (resolved_addresses → a made-up "cardano_address"), which is a live failure mode.
_SPEC_ROUTES_MARKER = "[API endpoints ("
_SPEC_SHAPE_MARKER = "[response shape —"
# Anchor markers whose messages are ALWAYS kept verbatim — AND, critically, excluded from the
# summarizer input, so cria's OWN prior briefings never become a rollup-of-a-rollup (each round
# summarizing the last round's summary is how a transient hallucination hardened into authoritative
# "Treat this as done" misdirection that inverted the task). ⟦ctx:continuation⟧ (loop's harness-
# compaction reframe) is one such cria-authored summary and MUST be here for the same reason as
# ⟦ctx:briefing⟧. Mirrors loop.BRIEFING_OPEN / loop.CONTINUATION_MARKER / probegate.SECTION_PREFIX
# + webfetch.ROUTES_MARKER / SHAPE_MARKER (selfcompact is low-level; a test asserts sync).
_ANCHOR_MARKERS = ("⟦ctx:briefing⟧", "⟦ctx:continuation⟧", "___CRIA_GATE_", SUMMARY_MARKER, TASK_MARKER,
                   FACTS_MARKER, _SPEC_ROUTES_MARKER, _SPEC_SHAPE_MARKER)


@dataclass
class CompactState:
    summary: str = ""      # the current rolling summary text
    covered: int = 0       # message INDEX the summary represents up to (throttle reference)


def _text(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c if isinstance(c, str) else ""


def _msg_tokens(m: dict) -> int:
    t = _text(m)
    for tc in m.get("tool_calls") or []:
        t += " " + str((tc.get("function") or {}).get("arguments") or "")
    return est_tokens(t)


def has_anchor(m: dict) -> bool:
    """Public alias — the harness-compaction path in server.py needs the same exclusion this
    module has always applied to its own summarizer input, and reaching into a private name is how
    two copies of a rule drift apart."""
    return _has_anchor(m)


def _has_anchor(m: dict) -> bool:
    t = _text(m)
    return any(mk in t for mk in _ANCHOR_MARKERS)


def _tail_start(messages: list[dict], head_end: int, budget_tokens: int) -> int:
    """The lowest index i (> head_end) such that messages[i:] fits in ``budget_tokens`` — i.e. the
    recent verbatim working set. Keeps at least one message."""
    acc = 0
    i = len(messages)
    while i > head_end + 1:
        t = _msg_tokens(messages[i - 1])
        if acc + t > budget_tokens:
            break
        acc += t
        i -= 1
    return i


# cria's OWN edit-recovery steer (editrecovery.EDIT_MARK — mirrored literal, a test asserts sync).
# Its body is a whole-file "EXACT current content on disk" snapshot that goes STALE by design: the
# live mechanism re-injects the CURRENT content whenever it fires again. Fed whole into the
# summarizer, a weak model preserves it verbatim — measured across 295 rollups: 27 carried a
# fossilized copy, and one prompt (0728-m14 call 0281) held TWO conflicting "EXACT content" claims,
# the rollup's stale one beside the live one. In summarizer INPUT the steer is represented by its
# HEADLINE only — the event survives ("cria provided the file's content after N failed edits"), the
# perishable payload does not.
_EDIT_MARK = "⟦ctx:edit⟧"


def msg_digest(m: dict) -> str:
    """A compact one-line rendering of a message for a summarization transcript: its text plus any
    tool call as ``name(args…)``. Shared by both paths so the rollup input is built the same way."""
    parts = []
    t = _text(m)
    if t.strip():
        if t.lstrip().startswith(_EDIT_MARK):
            t = t.lstrip().splitlines()[0]  # headline only — see _EDIT_MARK above
        parts.append(t)
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function") or {}
        parts.append(f"{fn.get('name', '?')}({str(fn.get('arguments', ''))})")
    return " ".join(p for p in parts if p)


def serialize(messages: list[dict], defang: bool = False) -> str:
    """The transcript span → one string fed to a model.

    ``defang`` renders the same facts with nothing a model can COPY. Measured over 717 reasoner
    calls in the captures: a prompt demonstrating 0-9 tool-call/output shapes was answered by
    imitating one 1% of the time, 10-29 3%, 30-59 **8%**. The worst case shipped: mellum2
    1786302864 call 0060 was shown tool-call syntax 50 times and tool OUTPUT blocks 24 times, and
    answered with a fabricated `exec_command(...)` plus an invented `Chunk ID`, wall time, exit
    code and `addr1q…` address — which cria then delivered to the coder as a steer, in cria's voice.

    The default rendering is the copyable one: `name({"arg": …})` is a complete template for how to
    open a call, and the harness's `Chunk ID: / Wall time: / Process exited with code / Output:`
    envelope is a complete template for how to fake its result. Defanged, a call reads
    `the coder ran a shell command: pytest -q` and a result reads `→ failed, exit 1: …` — same
    facts, no syntax to continue.

    This is the lesson cria already recorded for the compaction path ("a weak model continues the
    pattern and answers with a tool call, whatever the system prompt says", cria/server.py), where
    the fix was to FLATTEN the history. This path was already flat and still failed, because
    flattening kept the syntax. Flattening was necessary and not sufficient.

    Opt-in, and currently taken only by the steer-author path — the one the 717-call measurement
    covers. The summarizer keeps the verbatim rendering until the same base rate is taken for it
    (#15)."""
    if not defang:
        return "\n".join(f"{m.get('role')}: {msg_digest(m)}" for m in messages)
    out = []
    for i, m in enumerate(messages, 1):
        line = _defanged_line(m)
        if line:
            out.append(f"[{i:02d}] {line}")
    return "\n".join(out)


# The harness's exec envelope, whose shape is the thing a model copies when it fakes a result.
# `Process exited with code N` is stripped WITH the rest even though the code itself is kept — the
# defanged line already states it as `→ exit N`, so leaving the original both duplicates the fact
# and preserves the exact phrase a model copies when it fabricates a result.
_ENVELOPE = re.compile(r"(?im)^\s*(?:Chunk ID|Wall time|Original token count|Output)\s*:.*$"
                       r"|Process exited with code\s+\d+")
_EXIT = re.compile(r"(?i)Process exited with code\s+(\d+)")


def _defanged_line(m: dict) -> str:
    """One transcript entry as PROSE — the facts a supervisor needs, with no copyable syntax."""
    role = m.get("role")
    text = _text(m).strip()
    calls = m.get("tool_calls") or []
    if calls:
        bits = []
        for tc in calls:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            try:
                d = jsontext.loads(args) if isinstance(args, str) else (args or {})
            except (ValueError, TypeError, AttributeError):
                d = {}
            detail = "; ".join(f"{k}={str(v)[:160]}" for k, v in d.items()) if isinstance(d, dict) \
                else str(args)[:160]
            bits.append(f"the coder called {fn.get('name', '?')} — {detail}" if detail
                        else f"the coder called {fn.get('name', '?')}")
        return " / ".join(bits)
    if role == "tool":
        exit_m = _EXIT.search(text)
        body = _ENVELOPE.sub("", text).strip()
        head = f"→ exit {exit_m.group(1)}" if exit_m else "→ result"
        return f"{head}: {' '.join(body.split())[:400]}" if body else head
    if not text:
        return ""
    who = {"user": "the task/context said", "assistant": "the coder said",
           "system": "the frame said"}.get(role, f"{role} said")
    return f"{who}: {' '.join(text.split())[:400]}"


def compaction_request(messages: list[dict]) -> str:
    """The compactor's user message: the cleaned transcript, then cria's ask LAST.

    ONE owner, because having two was the bug. A model obeys the last instruction it reads, so a
    transcript whose final line is the coder's live step ("produce the corrected FULL file in a
    single write_file call") gets obeyed instead of summarized. `da35f4e` fixed that on the harness
    path in server.py; the self-compaction path in loop.py kept the old order and kept failing, and
    on run 20260801T161949 its compactor emitted `write_file({"path": …` and degenerated to
    `v5v5v5…` until the token cap, after which cria adopted a hallucinated unittest file as the
    session summary and the coder believed it.

    Fixing the sibling by copying the two lines would have left a third place to forget. Both callers
    now compose the request here."""
    return (serialize(probegate.clean_gate_results(messages))
            + "\n\n" + prompts.load("compact_closing_ask"))


def _summary_msg(summary: str) -> dict:
    # This rolls up MID-work turns (the work is NOT necessarily finished) — unlike the loop's
    # completion compaction, which summarizes genuinely-done work. So it must NOT stamp "treat this as
    # done": that blanket done-assertion drove premature completion and suppressed re-doing needed work
    # (the model coasted to "done" over an unresolved pyproject blocker; a summary saying "I fetched the
    # spec" made it skip re-fetching). Frame it truthfully as CONTEXT, and defer to the live results:
    # anything unfinished/failing/blocked still needs doing.
    # NB: do NOT promise verbatim turns "below". At a verified step boundary the tail budget is
    # BOUNDARY_KEEP_TAIL_TOKENS = 0, so this summary is the LAST message and nothing follows it — the
    # old wording sent the model to look for ground truth that was not there, and the one thing it
    # then had was the summary it had just been told not to trust. Defer to the live workspace, which
    # is always there, instead of to a position in the transcript.
    return {"role": "user", "content": (
        f"{SUMMARY_MARKER} Summary of your earlier turns this session (older turns were elided to keep "
        f"you focused). Use it as CONTEXT so you don't re-derive what you already worked out — but it "
        f"is a summary, NOT a statement that the task is done: anything it describes as unfinished, "
        f"failing, or blocked still needs doing. Where a real tool result or the files on disk "
        f"disagree with it, those are the ground truth — read them rather than trusting this:\n{summary}")}


def _task_msg(task: str) -> dict:
    return {"role": "user", "content": (
        f"{TASK_MARKER} Your ORIGINAL task for this session — keep it as your north star and do NOT "
        f"drift onto tangential work; everything below serves THIS:\n{task}")}


FILES_MARKER = "⟦ctx:files⟧"        # tags the post-compaction workspace files list (caller-supplied)

# --- Rollup echo-guard. The summarizer input is built by serialize() in a FRAME cria authors
# ("role: text", the harness exec envelope, think tags). A weak compactor ECHOES that frame instead
# of summarizing (measured: 20/295 rollups carried raw "Chunk ID" plumbing; p90 rollup 17K, max
# 29.8K). Lines matching cria's OWN frame are BY CONSTRUCTION echo, not summary prose — dropping
# them is deterministic housekeeping of cria's own artifacts, never a judgment on model prose.
_FRAME_ECHO_RE = re.compile(
    r"^(?:(?:system|user|assistant|tool):\s"      # serialize()'s role prefix
    r"|Chunk ID:|Wall time:|Process exited with code|Original token count:"  # exec envelope
    r"|</?think>\s*$"                             # leaked think tags
    r"|<\|im_start\|>|<\|im_end\|>)")          # raw template markers


# A line long enough that matching cria's own ask verbatim cannot be coincidence. Short lines
# ("Do this.", a bare heading) can legitimately collide; a full sentence cannot.
_ECHO_MIN_CHARS = 40


def _ask_sentences(ask: str) -> list[str]:
    """cria's own instruction, split into comparable sentences."""
    out = []
    for raw in re.split(r"(?<=[.!?])\s+|\n", ask or ""):
        t = " ".join(raw.split())
        if len(t) >= _ECHO_MIN_CHARS:
            out.append(t)
    return out


def strip_frame_echo(summary: str, ask: str = "") -> str:
    """Drop summarizer-output lines that echo cria's own serialization frame (see _FRAME_ECHO_RE) or,
    when ``ask`` is given, cria's own INSTRUCTION text. Returns the cleaned summary; a summary that
    was ALL echo comes back empty, and compact() then fails safe exactly as it does on an empty
    summary (fold nothing, keep every turn verbatim).

    The instruction clause is measured, not anticipated. Run 20260801T161949 (mellum2, ada-handles,
    0/4): the compactor at call 0062 produced a briefing that was mostly cria's own ask quoted back
    at itself, and cria injected it whole. Counted in the coder's prompt at 0063 — 68,914 characters,
    of which the continuation block was 54,274 (79%):

        "Do not emit a tool/function call"  x145
        "What you should say instead"       x47

    Both are cria's words, from selfcompact_summary.txt. The coder read them and said so — *"This is
    contradictory. The continuation says 'fix search_handles' which IS writing code. The continuation
    also says 'Do not write code.'"* — and emitted no tool call. It never fully recovered: at 0084,
    twenty calls later, the coder's own answer to the user still ENDED with that block, and the same
    text reappears verbatim at 0089 and 0207. Every compaction after the first collapsed the same
    way (0087, 0118, 0161, 0204).

    cria composed the ask, so this needs no judgment: a line of the "summary" that is cria's own
    sentence is not a summary of anything."""
    drop = _ask_sentences(ask)
    kept = []
    for ln in summary.splitlines():
        t = ln.strip()
        if _FRAME_ECHO_RE.match(t):
            continue
        flat = " ".join(t.split())
        if len(flat) >= _ECHO_MIN_CHARS and any(d in flat or flat in d for d in drop):
            continue
        kept.append(ln)
    return "\n".join(kept).strip()


# --- Older write-args → on-disk references (operator's design, run 0728-m14: post-compaction the
# coder does not need file CONTENT in old turns — the disk + the files list + read_file carry it;
# only the LAST tool call keeps its full arguments). Applies ONLY to the model's OWN write arguments
# (content it emitted, now durably on disk) — tool RESULTS the model read are never touched
# (never-truncate). Mirrors writeproxy's write-tool names; a test asserts sync.
_WRITE_TOOL_NAMES = ("write_file", "edit_file")
_WRITE_ARG_KEYS = ("content", "new_string")
_STUB_MIN_CHARS = 400


# A write that landed confirms in one of two shapes: the raw heredoc token (writeproxy._WROTE,
# pre-render) or the model-facing render of prompts/write_confirm ("Wrote <path>") that transcripts
# actually carry. Anything else — an ⟦ctx:editfail⟧ report, a denial, an error — did NOT reach
# disk. Kept in sync with both owners by tests.
_WROTE_HEAD = "⟦ctx:wrote⟧"


def write_landed(result_text: str) -> bool:
    head = prompts.render("write_confirm", path="").strip()
    t = result_text.lstrip()
    return _WROTE_HEAD in result_text or (bool(head) and t.startswith(head))


def _stub_write_args(m: dict, landed=None) -> dict:
    """A COPY of message ``m`` with big write-tool argument bodies replaced by an elision stub.

    ``landed`` maps tool_call_id -> bool (the paired tool result confirmed the write). The on-disk
    stub is a CLAIM — "this exact content is on disk" — and stamping it on a refused edit states a
    false fact (rule 5b): walked on mellum2 1786196176, call 0182's refused new_string was elided as
    "on disk", two reasoner prompts repeated it, and the 0144 steer told the coder the fix had
    landed. A refused write gets the refused stub; an UNKNOWN outcome (no paired result in the span)
    keeps the full text rather than risk either claim. Returns ``m`` unchanged when nothing
    qualifies."""
    changed = False
    new_calls = []
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw = fn.get("arguments") or ""
        if fn.get("name") not in _WRITE_TOOL_NAMES:
            new_calls.append(tc); continue
        try:
            args = json.loads(raw)
        except ValueError:
            new_calls.append(tc); continue
        if not isinstance(args, dict):
            new_calls.append(tc); continue
        path = str(args.get("path") or args.get("file_path") or "?")
        outcome = (landed or {}).get(tc.get("id"))
        if outcome is None:
            new_calls.append(tc); continue      # no paired result → no claim in either direction
        stub_key = "write_stub" if outcome else "write_stub_refused"
        touched = False
        for key in _WRITE_ARG_KEYS:
            v = args.get(key)
            if isinstance(v, str) and len(v) >= _STUB_MIN_CHARS:
                args[key] = prompts.fill(prompts.load_map("compact_view")[stub_key],
                                         chars=str(len(v)), path=path)
                touched = True
        if touched:
            changed = True
            new_calls.append({**tc, "function": {**fn, "arguments": json.dumps(args)}})
        else:
            new_calls.append(tc)
    return {**m, "tool_calls": new_calls} if changed else m


def _write_outcomes(msgs: list[dict]) -> dict:
    """tool_call_id -> did the paired tool result confirm the write reached disk."""
    landed: dict = {}
    for m in msgs:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "tool" or m.get("type") == "function_call_output":
            tid = m.get("tool_call_id") or m.get("call_id")
            c = m.get("content") if m.get("content") is not None else m.get("output")
            if tid and isinstance(c, str):
                landed[tid] = write_landed(c)
    return landed


def stub_old_write_args(msgs: list[dict]) -> list[dict]:
    """Post-compaction view of a message span: every write-tool call OLDER than the last tool-call
    turn gets its big argument bodies replaced by an elision stub — the on-disk reference for a
    write that landed, the refused form for one that did not; the LAST tool-call turn keeps its
    full arguments (the live working set). Copies — never mutates the caller's messages."""
    last_tc = max((i for i, m in enumerate(msgs) if m.get("tool_calls")), default=None)
    landed = _write_outcomes(msgs)
    return [m if (i == last_tc or not m.get("tool_calls")) else _stub_write_args(m, landed)
            for i, m in enumerate(msgs)]


def compact(messages: list[dict], summarize, state: CompactState, *,
            trigger_tokens: int = TRIGGER_TOKENS_DEFAULT, keep_tail_tokens: int = KEEP_TAIL_TOKENS,
            recompact_tokens: int = RECOMPACT_TOKENS, pinned_task: str = "", force: bool = False,
            boundary_keep_tail_tokens: int = BOUNDARY_KEEP_TAIL_TOKENS,
            files_list: str = "", refold=None,
            refold_tokens: int = REFOLD_TOKENS, rlog=None) -> tuple[list[dict], CompactState, bool]:
    """Return (messages, state, applied?). ``summarize(list[dict]) -> str`` folds the old middle into
    a briefing (injected so this is testable without a model). No-op (same list) at/below the token
    trigger, or when there is no middle to compact (the recent tail already spans everything).

    ``force`` (the plan loop passes it at a STEP BOUNDARY) both lowers the trigger AND shrinks the kept tail
    to ``boundary_keep_tail_tokens`` (0 by default → NO verbatim tail) — so the just-verified step's work
    folds ENTIRELY into the ⟦ctx:rollup⟧ (it IS the working-set tail, which a mere trigger drop left verbatim,
    so the view grew step over step). Nothing is lost at a boundary: the next step rides in the caller's
    system message, ``pinned_task`` re-anchors the original task, and anchored messages — a surfaced spec's
    real endpoint/fields (_SPEC_*_MARKER) and cria's own briefings — survive folding VERBATIM. (A boundary
    therefore REQUIRES the caller to pass ``pinned_task``, or the task would fold with the rest.)

    ``pinned_task`` (the conversation's ROOT task, supplied by the caller — it alone can detect the
    task past the harness env-context/reframe) is re-emitted verbatim as a ⟦ctx:task⟧ header on every
    compacted view. Without it the task — a plain user message with no anchor marker — falls into the
    summarizable middle and ERODES across rounds (round 2's rollup summarizes round 1's rollup), which
    is how a plan-off session lost its goal and drifted onto tangential build/deploy work. Pinning it
    keeps the north star authoritative and immune to summary degradation."""
    # At a STEP BOUNDARY keep only a SMALL verbatim tail (boundary_keep_tail_tokens) so the just-finished
    # step's work FOLDS into the rollup; otherwise keep the full working-set tail. force also lowers the
    # trigger so a boundary compacts even below the size trigger (but never a trivial view that fits the tail).
    eff_keep_tail = boundary_keep_tail_tokens if force else keep_tail_tokens
    threshold = eff_keep_tail if force else trigger_tokens
    if sum(_msg_tokens(m) for m in messages) <= threshold:
        return messages, state, False
    head_end = 1 if messages and messages[0].get("role") == "system" else 0
    tail_start = _tail_start(messages, head_end, eff_keep_tail)
    if tail_start <= head_end:
        return messages, state, False

    band_tokens = (sum(_msg_tokens(m) for m in messages[state.covered:tail_start])
                   if head_end <= state.covered <= tail_start else None)
    if not state.summary or band_tokens is None or band_tokens >= recompact_tokens:
        # TRULY ROLLING (operator-driven, first 27B): summarize only the NEW band — the turns past
        # what the existing summary already covers — and APPEND the increment. The old shape
        # re-summarized the ENTIRE middle every round into one REPLACING summary, which (a) squeezed
        # a whole session's folded history into one output budget (the squeeze the operator called
        # ridiculous — it saturated exactly when the session was long enough to need it most), and
        # (b) re-paid the full summarization wall-clock every round (13+ min observed at ~7 tok/s).
        # Incremental: each increment is bounded by the summarizer's output cap, the TOTAL summary
        # grows with the session, and earlier increments are never re-generated. When ``covered`` is
        # unusable (compaction state lost / indices shifted), fall back to the whole middle — the
        # old behavior, correct just slower.
        lo = state.covered if (state.summary and band_tokens is not None) else head_end
        summarizable = [m for m in messages[lo:tail_start] if not _has_anchor(m)]
        if summarizable:
            fresh = strip_frame_echo(summarize(summarizable), prompts.load("selfcompact_summary"))
            # An EMPTY summary must NEVER be adopted. ``summarize`` returns "" on a failed/empty compactor
            # call (it happens — a reasoning model can burn its budget thinking and emit no content), and
            # taking it would advance ``covered`` to tail_start: every folded turn replaced by a rollup
            # header with nothing under it. At a step BOUNDARY (keep NO tail) that is the whole session's
            # work history destroyed by one bad model call — the exact undetectable lie never-truncate
            # exists to prevent. Fail SAFE: fold nothing, keep every turn verbatim, and let the context
            # floor (the one lossless window-fit point) size the request.
            if not fresh.strip():
                return messages, state, False
            combined = (state.summary + "\n\n" + fresh) if (state.summary and lo > head_end) else fresh
            # REFOLD TIER (operator: append-only just moves the unbounded growth into the summary —
            # over a long session the accumulated increments would themselves overtake the window,
            # and the rollup is anchor-protected so nothing else ever shrinks it). When the
            # accumulated summary crosses REFOLD_TOKENS, fold IT once via ``refold``. This is the
            # rollup-of-a-rollup the old code rightly feared — but the fear was doing it EVERY round
            # (compounding degradation); at a ~3× increment threshold it happens once per ~6K summary
            # tokens, bounding degradation to a handful of generations across a whole session. A
            # failed/empty refold keeps the un-refolded text (fail-safe: too long beats gone).
            if refold is not None and est_tokens(combined) >= refold_tokens:
                folded = strip_frame_echo(refold(combined), prompts.load("selfcompact_refold"))
                if folded.strip():
                    combined = folded
            state = CompactState(summary=combined, covered=tail_start)

    covered = max(head_end, min(state.covered, tail_start))
    # Kept verbatim, never elided — but IDENTICAL copies collapse to the first. Each ⟦ctx:denied⟧
    # reply to a repeated whole-spill read re-embeds the spec digest, and the digest contains the
    # _SPEC_*_MARKERs, so every copy classified as an anchor: nemotron-nano 1786243834 carried the
    # same 7,216-char denial SIX times in one 61K step frame (the prompt the coder answered with
    # prose instead of a write). The anchor guarantee is ONE verbatim surviving copy; byte-identical
    # repeats add zero information and drown the frame for a small model.
    anchors, dup_anchors = _dedup_identical([m for m in messages[head_end:covered] if _has_anchor(m)])
    if dup_anchors and rlog is not None:
        # Every sibling dedup in cria emits its count (context.ledger_dedup, context.focus_trim,
        # context.deorphaned); a silent drop makes a future misfire invisible in the run log.
        rlog.emit("context.anchor_dedup", dropped=dup_anchors)
    band = messages[covered:tail_start]                                   # old-but-unfolded, verbatim
    # The pinned task leads the compacted view (right after cria's system prompt) so the north star is
    # the first thing the coder reads — never summarized, re-emitted fresh from the caller each turn.
    task = [_task_msg(pinned_task)] if pinned_task.strip() else []
    # The caller-supplied FILES LIST (operator's design): the compacted view carries what EXISTS —
    # names + sizes — not the bytes; read_file is the road back to any content. Refreshed each
    # compaction (any prior copy is filtered out of every kept segment above via _not_stale_files).
    files = ([{"role": "user", "content": files_list}] if files_list.strip() else [])
    working = band + messages[tail_start:]
    working = stub_old_write_args([m for m in working if not _is_files_msg(m)])
    anchors = [m for m in anchors if not _is_files_msg(m)]
    # NO summary, NO rollup header. The empty-summary guard above covers the case where the compactor
    # ANSWERED with nothing; this covers the other way in — a middle made entirely of anchored messages
    # leaves nothing summarizable, `summarize` is never called, and `state.summary` is still "". The
    # header was emitted anyway: a paragraph telling the coder this is its summary of earlier turns and
    # to read the disk where the summary disagrees, followed by nothing. cria asserting a record exists
    # when it holds none, in the message that IS the record.
    rollup = [_summary_msg(state.summary)] if state.summary.strip() else []
    out = messages[:head_end] + task + files + anchors + rollup + working
    return out, state, True


def _dedup_identical(msgs: list[dict]) -> tuple[list[dict], int]:
    """Identical anchor messages collapse to the first occurrence → ``(kept, dropped_count)``.
    Order and bytes of every distinct message are untouched.

    The key is :func:`msg_digest`, which covers the tool CALL as well as the text. Keying on text
    alone would fold two anchors that differ only in their tool_calls, and the survivor's sibling
    call would vanish from the view entirely — anchors are excluded from the summarizer input, so
    nothing downstream would carry it. (Prevalence of that shape today: zero across 17,912 captured
    coder bodies — no anchor message carries tool_calls at all. Keyed correctly anyway, because the
    cost is one function call and the failure is silent.)

    Exact match only: two renderings of the same fact are NOT the same message, and deciding they
    mean the same thing would be a judgment this function must not make."""
    seen: set[str] = set()
    out, dropped = [], 0
    for m in msgs:
        key = msg_digest(m)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        out.append(m)
    return out, dropped


def _is_files_msg(m: dict) -> bool:
    """A previously injected ⟦ctx:files⟧ list — stale the moment a newer one exists; filtered so
    exactly ONE (the fresh one) rides each compacted view."""
    c = m.get("content")
    return isinstance(c, str) and c.lstrip().startswith(FILES_MARKER)
