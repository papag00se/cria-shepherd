"""Harness-agnostic context floor — cria's own guarantee that every request fits the
local model's window, no matter what connects to it.

cria is an OpenAI-compatible proxy fronting a fixed-window local model. WHATEVER agent
harness is on the other side (Codex, Claude, Aider, …) may hand cria a large tool
schema plus a conversation that grows without bound. cria cannot rely on the harness to
compact — many can't, and it isn't cria's to configure. So cria enforces the window
itself, here, on the final outbound body, operating on nothing but ``{messages, tools}``.

Four levers, in order (cheapest / most-lossless first), mirroring codex-local's
``enforce_token_budget`` (docs/spec/compaction-reference.md, content-reduce.md):

1. **Bound the tool SCHEMA.** The tool schema is a fixed per-request cost the model pays
   before it reads a single message — and some harnesses ship a huge one (e.g. 127
   connector tools ≈ 34K tokens, 67% of a 48K window). When it exceeds a fraction of the
   budget, cria truncates the free-text *descriptions* (function + parameter), keeping
   every tool callable (name, parameter names/types/required/enum untouched), so the
   conversation isn't crowded out. A fat tool list can't eat the whole window.
2. **Tool-aware message budget.** What's left after the (now-bounded) tool schema is the
   conversation's budget: ``window − reserve − tool_schema_tokens``.
3. **Bound oversized tool OUTPUTS.** A single giant tool result (a web_fetch page, a
   file read) is reduced via :mod:`cria.content_reduce` before any turn is dropped —
   shrinking one output is far less lossy than deleting a whole exchange.
4. **Drop oldest turns.** If it still doesn't fit, the oldest droppable turns go,
   preserving the system prelude and the active turn (the last user message onward),
   and never orphaning a ``tool`` result from the ``assistant`` tool-call it answers.

Deterministic, stdlib-only, no LLM. The token estimate is chars/4 inflated by a safety
factor (code/JSON render heavier than the estimate); we budget against the inflated
figure so the real rendered prompt lands under the window.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import bodykeys
from . import toolargs
from .content_reduce import content_reduce, digest_reduce, est_tokens

# The synthesized state note that REPLACES dropped turns (spirit of trim/state_extract): instead of
# silently deleting the oldest turns, keep a deterministic record of what they DID that still matters.
_COMPACTED_MARK = "⟦ctx:compacted⟧"
# Tags a tool result the floor REDUCED in place. content_reduce is lossy, so the model must be
# able to tell a shortened result from a verbatim one.
_REDUCED_MARK = "⟦ctx:reduced⟧"
# The stand-in note preserves a content_reduce()d digest of each dropped turn — not just the filenames
# it modified — so a dropped test-failure/error output survives as a SUMMARY rather than vanishing. The
# digests together occupy at most this share of the message budget (split across the dropped turns, each
# with a per-turn floor) so the stand-in note can't itself blow the window. content_reduce is lossless-
# first and guarded (never a blind slice); a turn whose content it can't summarize under budget is
# disclosed as omitted, never re-embedded verbatim (that would defeat the drop).
_NOTE_DIGEST_FRACTION = 0.25
_MIN_NOTE_DIGEST_TOKENS = 256   # total floor: even a tight budget leaves room for a real summary
_MIN_PER_TURN_TOKENS = 64       # per-turn floor: each digested turn gets at least this much room
# ...but a stand-in may never cost as much as what it stands in for. A share of the BUDGET alone let a
# note re-embed a whole dropped turn verbatim whenever that turn fit under the per-turn allowance, so
# the drop saved nothing (measured: a 1,215-token turn dropped, a 1,244-token note inserted — the
# transcript ENDED UP LARGER). The floor then read "still over budget" and escalated to lever 5,
# deleting the model's most recent turns for no gain: 350 turns + 736 protected messages destroyed in
# one 30-minute run, over_budget declared 60 times. Every drop must net at least (1 - this) of what it
# removed, and the drop loops count the same bound against the budget instead of discovering it after.
_NOTE_MAX_SHARE_OF_DROPPED = 0.6   # every drop nets at least 40% of what it removed. Tighter starves
                                   # the digest: a fetched HTML page — the biggest thing these
                                   # transcripts drop — compresses about 2x, and a 0.4 share would
                                   # reject it and lose the page's substance to buy back 20% more.
_NOTE_FRAME_TOKENS = 48         # the note's own header/file-list overhead, counted with its digests
# Tools whose target file a dropped turn MODIFIED — a durable fact worth keeping across the drop.
_WRITE_TOOL_NAMES = ("write_file", "edit_file", "apply_patch", "str_replace_editor",
                     "create_file", "text_editor")

# Anchors the floor must NOT silently trim: the completion-briefing envelope a follow-up re-reads
# FROM history, cria's ground-truth gate output the coder must read to fix a step, the synthesized-state
# note that stands in for dropped turns, and — crucially — self-compaction's OWN preservation anchors:
# the pinned north-star task (⟦ctx:task⟧) and the rolling summary (⟦ctx:rollup⟧) it emits are role:"user"
# turns OUTSIDE the last-user active span, so without this they read as the oldest droppable turns and
# the floor deletes the very things selfcompact ran to preserve (re-digesting the rollup into a
# summary-of-a-summary — the task-inversion selfcompact exists to prevent). Plus the ⟦ctx:continuation⟧
# reframe lead. Literals mirror loop.BRIEFING_OPEN / probegate.SECTION_PREFIX / selfcompact.SUMMARY_MARKER
# / selfcompact.TASK_MARKER / loop.CONTINUATION_MARKER — contextfloor is low-level and imports none (avoids
# a cycle); a test asserts they stay in sync.
_PROTECT_MARKERS = ("⟦ctx:briefing⟧", "___CRIA_GATE_", _COMPACTED_MARK,
                    "⟦ctx:rollup⟧", "⟦ctx:task⟧", "⟦ctx:facts⟧", "⟦ctx:continuation⟧")


def _has_protect_marker(m: dict) -> bool:
    t = _msg_text(m)
    return any(mk in t for mk in _PROTECT_MARKERS)

# Real rendered tokens exceed the chars/4 estimate for code/JSON/tool-arg-heavy transcripts.
# This is the DEFAULT inflation before the density is measured; the caller passes a LEARNED
# per-model ratio (cria.tokenratio, updated from real usage) as `safety` once it knows better.
# 1.8 matches codex-local's DEFAULT_SAFETY_FACTOR — chars/4 undercounts by ~1.8x on typical
# agent traffic, more on base64/code (learned up to 3.5x).
SAFETY_FACTOR = 1.8
# Generation budget reserved when the request does not cap its own output. The prompt
# must leave room for the model's reply inside the same window (llama.cpp n_ctx covers
# prompt + generation).
DEFAULT_GEN_RESERVE = 4096
# Lever 5 keeps this many trailing messages when forced to drop inside the protected span —
# the active work (the newest tool call/result pairs) survives even a hard overflow.
OVERFLOW_KEEP_TAIL = 8
# Never trim the conversation below this estimate — the active turn must survive even
# when tool schemas are pathologically large; if it still won't fit, that's surfaced,
# not hidden.
MIN_MSG_BUDGET = 512
# The tool schema may occupy at most this fraction of the estimate budget before cria
# starts truncating its descriptions. Half leaves at least half the budget for the
# system prompt + conversation, which the model actually reasons over.
MAX_TOOL_FRACTION = 0.5
# Description-length caps tried, longest first, until the tool schema fits its budget.
# 0 = drop the description entirely (name + parameter structure still identify the tool).
_DESC_CAPS = (400, 240, 140, 80, 40, 0)


@dataclass
class FloorReport:
    applied: bool = False
    window: int = 0
    reserve: int = 0
    tool_tokens: int = 0
    tool_tokens_before: int = 0
    tools_compressed: int = 0
    msg_tokens_before: int = 0
    msg_tokens_after: int = 0
    outputs_reduced: int = 0
    turns_dropped: int = 0
    protected_dropped: int = 0  # lever 5: turns dropped INSIDE the protected span (last resort)
    orphans_removed: int = 0
    over_budget: bool = False  # even after every lever the request still won't fit — surfaced loudly
    fields: dict = field(default_factory=dict)

    def as_event(self) -> dict:
        return {
            "window": self.window, "reserve": self.reserve, "tool_tokens": self.tool_tokens,
            "tool_tokens_before": self.tool_tokens_before, "tools_compressed": self.tools_compressed,
            "msg_before": self.msg_tokens_before, "msg_after": self.msg_tokens_after,
            "outputs_reduced": self.outputs_reduced, "turns_dropped": self.turns_dropped,
            "protected_dropped": self.protected_dropped,
            "orphans_removed": self.orphans_removed, "over_budget": self.over_budget,
        }


def _msg_text(m: dict) -> str:
    """The token-bearing text of a message: content (str or content-parts) plus any
    tool-call arguments (JSON schemas/args are real tokens too)."""
    parts: list[str] = []
    c = m.get("content")
    if isinstance(c, str):
        parts.append(c)
    elif isinstance(c, list):
        for p in c:
            if isinstance(p, dict):
                parts.append(p.get("text") or p.get("content") or "")
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function") or {}
        a = fn.get("arguments")
        parts.append(a if isinstance(a, str) else json.dumps(a or ""))
        parts.append(fn.get("name") or "")
    return "".join(parts)


def _msgs_tokens(messages: list[dict]) -> int:
    return sum(est_tokens(_msg_text(m)) for m in messages)


def content_text(messages, tools) -> str:
    """The token-bearing text of a whole request (message contents + tool-call args + tool
    schema) — the exact basis the floor's chars/4 estimate is built on, so a real /tokenize of
    THIS string yields a density ratio the floor can apply directly as its safety factor."""
    parts = [_msg_text(m) for m in (messages if isinstance(messages, list) else [])]
    if tools:
        parts.append(json.dumps(tools))
    return "".join(parts)


def est_total(messages: list[dict], tools) -> int:
    """The chars/4 estimate of a whole request (messages + tools schema) — the cheap gate for
    'is this big enough to bother measuring the real token count?'."""
    return est_tokens(content_text(messages, tools))


def _sniff_content_type(s: str) -> str | None:
    """Best-effort MIME for a tool output (chat tool results carry no content-type)."""
    t = s.lstrip()[:64].lower()
    if t.startswith("{") or t.startswith("["):
        return "application/json"
    if t.startswith("<!doctype html") or t.startswith("<html") or "<body" in t[:64]:
        return "text/html"
    return None


def fit(messages: list[dict], tools, *, window: int, reserve: int,
        safety: float = SAFETY_FACTOR) -> tuple[list[dict], object, FloorReport]:
    """Return ``(messages, tools, report)`` reshaped to fit ``window`` (accounting for the
    ``tools`` schema and a generation ``reserve``). Pure — does not mutate the inputs;
    reduced/dropped messages and compressed tools are new objects. ``safety`` inflates the
    chars/4 estimate to approximate real tokens; the caller raises it (via a real /tokenize
    measurement) for dense base64/code requests where chars/4 badly underestimates."""
    rep = FloorReport(window=window, reserve=reserve)
    if not isinstance(messages, list) or not messages or window <= 0:
        rep.tool_tokens = rep.tool_tokens_before = est_tokens(json.dumps(tools)) if tools else 0
        return messages, tools, rep

    safety = max(1.0, safety)
    # A reserve at/above the window zeroes (or negates) the prompt budget → the whole conversation
    # gets trimmed to the floor and STILL reports over budget. Bound it so at least MIN_MSG_BUDGET of
    # real window is left for the prompt (a harness may send max_tokens ≥ window, and reserve_for
    # falls back to max_tokens). Reflect the effective reserve in the report.
    reserve = max(0, min(reserve, window - MIN_MSG_BUDGET))
    rep.reserve = reserve
    # Budget in ESTIMATE space: real ≈ est × safety must fit window − reserve.
    target_est = int((window - reserve) / safety)
    rep.tool_tokens_before = est_tokens(json.dumps(tools)) if tools else 0
    rep.msg_tokens_before = _msgs_tokens(messages)

    # --- Lever 1: bound the tool schema so it can't crowd out the conversation. ---
    if tools and rep.tool_tokens_before > int(target_est * MAX_TOOL_FRACTION):
        tools, rep.tools_compressed = _compress_tools(tools, int(target_est * MAX_TOOL_FRACTION))
    tool_tokens = est_tokens(json.dumps(tools)) if tools else 0
    rep.tool_tokens = tool_tokens

    # --- Lever 2: what's left is the conversation budget. ---
    msg_budget = target_est - tool_tokens
    if msg_budget < MIN_MSG_BUDGET:
        msg_budget = MIN_MSG_BUDGET  # keep the active turn even if tools are pathological

    fits_at_start = rep.msg_tokens_before <= msg_budget and not rep.tools_compressed
    work = list(messages)
    if rep.msg_tokens_before > msg_budget:
        # --- Lever 3: reduce the bulkiest tool OUTPUTS before deleting any turn. ---
        work, rep.outputs_reduced = _reduce_tool_outputs(work, msg_budget)
        # --- Lever 4: drop oldest droppable turns until it fits. ---
        if _msgs_tokens(work) > msg_budget:
            work, rep.turns_dropped = _drop_oldest(work, msg_budget)
        # --- Integrity: never leave a tool result orphaned from its assistant call. ---
        work, rep.orphans_removed = _strip_orphan_tools(work)

    rep.msg_tokens_after = _msgs_tokens(work)
    over = (rep.msg_tokens_after + tool_tokens) * safety > (window - reserve)
    if over:
        # --- Lever 5 (LAST RESORT, ported from codex-local §27 drop_to_fit): the PROTECTED span
        # itself is over budget. That happens on long agentic conversations whose last USER
        # message sits near the top — "protect last-user→end" then protects nearly everything,
        # and levers 3-4 have almost nothing to work with (observed live: 259 messages, 171
        # trimmable tokens, a guaranteed llama 400 retried forever = "not connecting"). Sending a
        # known-doomed request helps no one: drop the OLDEST turns INSIDE the protected span —
        # always keeping system messages, the last user message (the request), and the most
        # recent tail — then re-strip orphans.
        msg_budget = max(target_est - tool_tokens, MIN_MSG_BUDGET)
        work, rep.protected_dropped = _drop_protected_overflow(work, msg_budget)
        work, more_orphans = _strip_orphan_tools(work)
        rep.orphans_removed += more_orphans
        rep.msg_tokens_after = _msgs_tokens(work)
        over = (rep.msg_tokens_after + tool_tokens) * safety > (window - reserve)
    rep.applied = not fits_at_start
    # Honest signal: if even the last resort couldn't make it fit (system + request + minimal
    # tail alone exceed the window), surface it rather than pretend.
    rep.over_budget = over
    return work, tools, rep


def _compress_tools(tools, budget_est: int) -> tuple[list, int]:
    """Bound the tool SCHEMA to ``budget_est`` estimated tokens by truncating free-text
    descriptions (function + parameter), longest cap first until it fits. Every tool stays
    callable: name, parameter names/types/required/enum are untouched. Returns
    ``(tools, n_compressed)``. Harness-agnostic — a harness that ships verbose connector
    schemas doesn't get to eat the whole window."""
    if est_tokens(json.dumps(tools)) <= budget_est:
        return tools, 0
    for cap in _DESC_CAPS:
        out = [_cap_descriptions(t, cap) for t in tools]
        if est_tokens(json.dumps(out)) <= budget_est or cap == _DESC_CAPS[-1]:
            n = sum(1 for a, b in zip(tools, out) if a != b)
            return out, n
    return tools, 0


def _cap_descriptions(obj, cap: int):
    """Deep-copy ``obj`` (a tool schema) with every ``description`` string truncated to
    ``cap`` chars (``cap == 0`` drops it). Structure and all non-description fields intact."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "description" and isinstance(v, str):
                if cap <= 0:
                    continue
                out[k] = v if len(v) <= cap else v[:cap] + "…"
            else:
                out[k] = _cap_descriptions(v, cap)
        return out
    if isinstance(obj, list):
        return [_cap_descriptions(x, cap) for x in obj]
    return obj


def ensure_tool_integrity(messages: list[dict]) -> tuple[list[dict], int]:
    """UNCONDITIONAL last-mile guarantee that the message list is valid for a STRICT chat template — run
    on EVERY request, not only when the floor REDUCES. A ``tool`` result whose issuing ``assistant``
    tool-call is absent is an ORPHAN the template rejects (observed: HTTP 400 every turn, poisoning the
    whole run). Self-compaction creates exactly this WITHOUT any reduction: it folds the assistant
    tool-call into the ⟦ctx:rollup⟧ but keeps the anchored ground-truth gate result (a ``tool`` message)
    — so a request that comfortably FITS the window still ships an orphan and _strip_orphan_tools (which
    runs only inside the over-budget reduction) never sees it.

    Rather than DROP the orphan (it may be cria's own gate/ground-truth result), CONVERT it to a ``user``
    message: the content survives, the invalid tool↔assistant pairing does not. Also prune a DANGLING
    assistant tool-call whose result is absent (the other direction). Returns (messages, n_repaired)."""
    live_calls = {tc["id"] for m in messages if m.get("role") == "assistant"
                  for tc in (m.get("tool_calls") or []) if tc.get("id")}
    out, n = [], 0
    for m in messages:
        if m.get("role") == "tool" and m.get("tool_call_id") and m["tool_call_id"] not in live_calls:
            out.append({"role": "user", "content": m.get("content") if m.get("content") is not None else ""})
            n += 1
            continue
        out.append(m)
    live_results = {m["tool_call_id"] for m in out if m.get("role") == "tool" and m.get("tool_call_id")}
    final = []
    for m in out:
        tcs = m.get("tool_calls") if m.get("role") == "assistant" else None
        if tcs:
            surviving = [tc for tc in tcs if not tc.get("id") or tc["id"] in live_results]
            if len(surviving) != len(tcs):
                n += len(tcs) - len(surviving)
                if not surviving and not (m.get("content") or "").strip():
                    continue
                m = {k: v for k, v in m.items() if k != "tool_calls"}
                if surviving:
                    m["tool_calls"] = surviving
        final.append(m)
    return final, n


def _reduce_tool_outputs(messages: list[dict], msg_budget: int) -> tuple[list[dict], int]:
    """Shrink bulky ``tool`` outputs via content_reduce until the transcript fits or nothing
    bulky remains. Only touches role==tool messages. OLDEST-first: the tool result the model is
    acting on THIS turn is the highest-indexed tool message — reducing it truncates the very
    content the current step depends on, so stale outputs are sacrificed before the freshest one
    (was largest-first, which reduced the current file read before any old web_fetch dump)."""
    total = _msgs_tokens(messages)
    if total <= msg_budget:
        return messages, 0
    # (index, est size), tool outputs only, in conversation order → oldest reduced first.
    sized = [(i, est_tokens(_msg_text(m))) for i, m in enumerate(messages) if m.get("role") == "tool"]
    out = list(messages)
    reduced = 0
    for i, sz in sized:
        if total <= msg_budget:
            break
        if sz < 256:  # not worth reducing a small output
            continue
        m = out[i]
        if _has_protect_marker(m):  # never truncate cria's own ground-truth gate output
            continue
        content = m.get("content")
        text = content if isinstance(content, str) else _msg_text(m)
        # Aim this output at a share of the remaining budget, not below a usable floor.
        cap = max(256, msg_budget // 4)
        new_text = content_reduce(text, _sniff_content_type(text), cap)
        if est_tokens(new_text) < sz:
            # LABEL it. content_reduce is genuinely lossy (prose function words dropped, JSON string
            # values rewritten), and this swapped the result in with no marker — the model read a
            # transformed tool result as the verbatim one, with no way to tell. Prefer a labelled
            # reduction over a silent one.
            out[i] = {**m, "content": _REDUCED_MARK + " " + new_text}
            total = total - sz + est_tokens(new_text)
            reduced += 1
    return out, reduced


# The harness's environment/instructions preamble — a user-role turn that is NOT the task. Mirrors
# selfcompact.is_env_context; contextfloor imports nothing (see _PROTECT_MARKERS above) and a test
# asserts the two stay in sync.
_ENV_PREAMBLE = ("<environment_context>", "<user_instructions>")


def _is_env_preamble(m: dict) -> bool:
    t = _msg_text(m)
    return any(tok in t for tok in _ENV_PREAMBLE)


def _protected_mask(messages: list[dict]) -> list[bool]:
    """True where a message must NOT be dropped: every system message, the active turn — the last
    user message through the end of the list — and THE FIRST REAL USER TURN, which is the task.

    THE TASK USED TO BE DROPPABLE, and it was dropped. The active span is "the last user message
    onward", so the task is covered only while nothing follows it — and cria itself injects user-role
    turns after it: the reasoned steer and focus-trim's two notes. The moment one lands, the task
    becomes the OLDEST droppable turn and the floor deletes it first. Measured across one day's real
    sessions: 53 of 1,475 coder prompts shipped with no task in them, in 8 of 22 sessions; 15 traced
    to cria's own steer and 12 to focus-trim's notes. In one, the model's only standing instruction
    was the steer: it reasoned "use float64 instead of decimal" and edited the test to undo the
    decimal work the task had asked for.

    ⟦ctx:task⟧ is already in _PROTECT_MARKERS, but self-compaction only emits it once it fires, and
    the floor starts dropping at a far lower budget than self-compaction triggers at — so on the
    plan-off path the raw task carries no marker for most of a session. This protects it structurally
    instead, with no marker and nothing added to what the model reads.

    The harness's `<environment_context>` preamble is a user turn and is NOT the task, so it is
    skipped; that is the same distinction selfcompact.is_env_context draws."""
    n = len(messages)
    last_user, first_task = -1, -1
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            last_user = i
            if first_task < 0 and not _is_env_preamble(m):
                first_task = i
    prot = [False] * n
    if first_task >= 0:
        prot[first_task] = True
    for i, m in enumerate(messages):
        if m.get("role") in ("system", "developer"):
            prot[i] = True
        if last_user >= 0 and i >= last_user:
            prot[i] = True
        if _has_protect_marker(m):  # the briefing / gate anchor — don't drop it from under a reference
            prot[i] = True
    # PAIR protection (M18): a MARKER-protected tool RESULT and its issuing assistant tool_call are a
    # UNIT. A gate result whose shell command carries the marker, but whose assistant call does not, would
    # else have its call dropped by _drop_oldest and then be discarded by _strip_orphan_tools as an orphan
    # (defeating the protection; a dangling call is also rejected by strict templates). Propagate MARKER
    # protection across the pair — but ONLY marker protection: an active-turn/system result whose call is
    # an old, huge message must still be droppable (its orphan is then cleaned up), so those aren't linked.
    call_at: dict = {}     # tool_call_id -> index of the assistant msg that issued it
    result_at: dict = {}   # tool_call_id -> index of the tool msg that answered it
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            if tc.get("id"):
                call_at[tc["id"]] = i
        if m.get("tool_call_id"):
            result_at[m["tool_call_id"]] = i
    for cid, ai in call_at.items():
        ri = result_at.get(cid)
        if ri is None:
            continue
        if _has_protect_marker(messages[ri]):
            prot[ai] = True   # a marker-protected RESULT → keep its issuing call (else the result orphans)
        if _has_protect_marker(messages[ai]):
            prot[ri] = True   # a marker-protected CALL → keep its result (else the call dangles)
    return prot


def _drop_protected_overflow(messages: list[dict], msg_budget: int) -> tuple[list[dict], int]:
    """Last resort when the PROTECTED span alone is over budget: drop its oldest turns,
    never touching (a) system/developer messages, (b) the last user message — the request
    being answered, (c) the trailing OVERFLOW_KEEP_TAIL messages — the active work. Drops
    from the oldest end of the span until the estimate fits or nothing droppable remains.
    Protect-marked messages (the compacted-note summary, the briefing, the gate anchor) are
    dropped LAST — they are the summary standing in for everything already dropped, so losing
    one is the worst kind of loss; only sacrifice one when nothing unmarked remains to drop and
    the window still doesn't fit (fit must be guaranteed or the model errors on every call)."""
    work = list(messages)
    dropped = 0
    dropped_tokens = 0
    removed: list[dict] = []
    # The stand-in note this lever appends counts against the budget too — dropping to exactly the
    # budget and THEN adding a note leaves the request over, which is how a "last resort" ended up
    # firing on nearly every request of a long run.
    while _msgs_tokens(work) + _note_cost_bound(dropped_tokens, msg_budget) > msg_budget:
        last_user = -1
        for i, m in enumerate(work):
            if m.get("role") == "user":
                last_user = i
        tail_start = max(len(work) - OVERFLOW_KEEP_TAIL, 0)
        def _droppable(i, m):
            return i > last_user and i < tail_start and m.get("role") not in ("system", "developer")
        # Prefer an unmarked victim; fall back to a protect-marked one only if nothing else is left.
        victim = next((i for i, m in enumerate(work)
                       if _droppable(i, m) and not _has_protect_marker(m)), None)
        if victim is None:
            # Only protect-marked turns are left. Sacrificing one is the worst loss there is (it is the
            # summary standing in for everything already gone), so pay it ONLY when it actually buys the
            # fit: if dropping every remaining droppable turn STILL leaves the request over budget, the
            # anchors would be destroyed for nothing. Stop instead and let over_budget say so honestly.
            remaining = [i for i, m in enumerate(work) if _droppable(i, m)]
            freed = sum(est_tokens(_msg_text(work[i])) for i in remaining)
            if not remaining or (_msgs_tokens(work) - freed
                                 + _note_cost_bound(dropped_tokens + freed, msg_budget)) > msg_budget:
                break
            victim = remaining[0]
        if victim is None:
            break  # only the irreducible core remains
        dropped_tokens += est_tokens(_msg_text(work[victim]))
        removed.append(work.pop(victim))
        dropped += 1
    if removed:
        # DISCLOSE the removal, exactly as _drop_oldest does. This lever silently popped whole turns —
        # including protect-marked anchors when nothing else was droppable — so the model's history had
        # holes in it with nothing to say so. The note goes where the gap IS: drops always start just
        # after the last surviving user turn (the request), so it reads in chronological place rather
        # than displacing the task at the head.
        at = len(work)
        for i, m in enumerate(work):
            if m.get("role") == "user":
                at = i + 1
        work.insert(at, _compacted_note(removed, dropped, msg_budget))
    return work, dropped


def _drop_oldest(messages: list[dict], msg_budget: int) -> tuple[list[dict], int]:
    """Drop oldest droppable messages (not system, not the active turn) until the transcript fits
    the budget or nothing droppable remains — but SYNTHESIZE their durable state (the files they
    modified) into a protected note in their place, so a long overflowing session doesn't lose track
    of what exists on disk (spirit of trim/state_extract — deterministic, no LLM).

    The note is part of the result, so it is part of the arithmetic: stop when the survivors PLUS the
    note fit, not when the survivors alone do (see ``_note_cost_bound``)."""
    prot = _protected_mask(messages)
    keep = [True] * len(messages)
    total = _msgs_tokens(messages)
    dropped = 0
    dropped_tokens = 0
    for i, m in enumerate(messages):
        if total + _note_cost_bound(dropped_tokens, msg_budget) <= msg_budget:
            break
        if prot[i]:
            continue
        size = est_tokens(_msg_text(m))
        total -= size
        dropped_tokens += size
        keep[i] = False
        dropped += 1
    kept = [m for i, m in enumerate(messages) if keep[i]]
    if dropped:
        note = _compacted_note([m for i, m in enumerate(messages) if not keep[i]], dropped, msg_budget)
        kept = _insert_after_leading_system(kept, note)
    return kept, dropped


def _modified_files(msgs: list[dict]) -> list[str]:
    """Deduped paths of files that the given (dropped) assistant turns WROTE/EDITED — the fact that
    survives the drop even though the content doesn't."""
    out: list[str] = []
    for m in msgs:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if (fn.get("name") or "") in _WRITE_TOOL_NAMES:
                p = toolargs.tool_path(toolargs.parse_args(fn.get("arguments")))
                if p and p not in out:
                    out.append(p)
    return out


def _note_cost_bound(dropped_tokens: int, msg_budget: int) -> int:
    """The most the stand-in note may cost, given how much was dropped for it.

    ONE definition shared by the drop loops (which must stop early enough to leave room for it) and by
    the note builder (which must honour it) — so the two cannot disagree, which is exactly how the
    floor used to end up bigger than it started."""
    if dropped_tokens <= 0:
        return 0
    of_budget = max(_MIN_NOTE_DIGEST_TOKENS, int(msg_budget * _NOTE_DIGEST_FRACTION))
    of_dropped = int(dropped_tokens * _NOTE_MAX_SHARE_OF_DROPPED)
    return min(of_budget, of_dropped) + _NOTE_FRAME_TOKENS


_REPEAT_SUFFIX = "   [identical result, {n} times in a row]"


def _collapse_repeats(digests: list[tuple[int, str]]) -> list[str]:
    """Consecutive identical digests folded into ONE, with the count stated.

    Repeating a byte-identical result N times is not a summary of anything — it costs N times the
    context to say what one copy plus a number says exactly. This is lossless: nothing is reworded,
    nothing is cut, and the count is on the line.

    Measured on run 20260801T225200 (zaya1). One compaction note ran to 22,149 characters across 117
    bullets of which **25 were distinct** — the single line

        {"error":"route_not_found","message":"Route not found: /info", ...}

    appeared **89 times**, and repeated bullets were 42% of the note's characters. The model had
    emitted the same failing curl in a loop; cria then replayed the identical failure back at it 89
    times."""
    out: list[str] = []
    run_text, run_n = None, 0
    for _, d in digests:
        if d == run_text:
            run_n += 1
            continue
        if run_text is not None:
            out.append(run_text + (_REPEAT_SUFFIX.format(n=run_n) if run_n > 1 else ""))
        run_text, run_n = d, 1
    if run_text is not None:
        out.append(run_text + (_REPEAT_SUFFIX.format(n=run_n) if run_n > 1 else ""))
    return out


def _compacted_note(dropped_msgs: list[dict], dropped: int, msg_budget: int) -> dict:
    """The synthesized stand-in for the dropped turns: a content_reduce()d digest of what each turn
    CONTAINED (so a dropped test-failure/error output survives as a summary, not just a filename) plus
    the full list of files those turns modified. Digests are lossless-first (content_reduce, never a
    blind slice) and bounded BOTH by a share of the budget and by a share of what was dropped, so the
    note can neither blow the window nor cost as much as the turns it replaces."""
    parts = [f"{_COMPACTED_MARK} {dropped} earlier turn(s) were compacted to fit the context window."]

    # Per-turn digests. The digests together may occupy at most the same bound the drop loops budgeted
    # for (share of the budget AND share of what was dropped); split it across the dropped turns, each
    # with a per-turn floor so a digest stays usable — but never a floor larger than the whole bound.
    note_budget = max(0, _note_cost_bound(sum(est_tokens(_msg_text(m)) for m in dropped_msgs),
                                          msg_budget) - _NOTE_FRAME_TOKENS)
    per_turn = min(max(_MIN_PER_TURN_TOKENS, note_budget // max(dropped, 1)), note_budget)
    digests: list[tuple[int, str]] = []
    spent = 0
    omitted = 0
    # Newest-dropped first so a tight budget spends on the turns adjacent to the surviving active span
    # (most relevant to the current step); reassembled into chronological order for reading.
    for idx in range(len(dropped_msgs) - 1, -1, -1):
        text = _msg_text(dropped_msgs[idx]).strip()
        if not text:
            continue  # nothing to summarize (e.g. a bare tool-call frame) — not a loss to disclose
        if spent >= note_budget:
            omitted += 1
            continue
        # digest_reduce, NOT content_reduce: a dropped turn can be the TASK or cria's own
        # instruction, and the prose tier deletes function words. See digest_reduce.
        digest = digest_reduce(text, _sniff_content_type(text), per_turn).strip()
        # Keep the digest only if it FITS the remaining note budget. content_reduce is lossless-first:
        # asked for `per_turn` it returns the best it can honestly do, which for ordinary prose is the
        # text nearly unchanged — so a cap it merely aims at is not a cap. The budget check is the
        # enforcement, and it is what makes "the note costs less than what it replaces" true rather
        # than aspirational. A turn that won't fit is disclosed as omitted, never re-embedded whole
        # (its file, if it wrote one, still survives via the file list below).
        cost = est_tokens(digest)
        if digest and spent + cost <= note_budget:
            digests.append((idx, digest))
            spent += cost
        else:
            omitted += 1
    if digests:
        digests.sort(key=lambda p: p[0])  # chronological
        parts.append("Summary of what those turns contained:")
        parts.extend("• " + d for d in _collapse_repeats(digests))
    if omitted:
        parts.append(f"(+{omitted} further compacted turn(s) whose content could not be summarized here.)")

    files = _modified_files(dropped_msgs)
    if files:
        parts.append("Files modified in them (still on disk — re-read one if you need its current "
                     "contents): " + ", ".join(files) + ".")
    return {"role": "user", "content": "\n".join(parts)}


def _insert_after_leading_system(msgs: list[dict], note: dict) -> list[dict]:
    """Place the synthesized note right after the leading run of system/protected messages, so it
    stands at the head of the (now-compacted) conversation body."""
    i = 0
    while i < len(msgs) and (msgs[i].get("role") in ("system", "developer") or _has_protect_marker(msgs[i])):
        i += 1
    return msgs[:i] + [note] + msgs[i:]


def _strip_orphan_tools(messages: list[dict]) -> tuple[list[dict], int]:
    """Remove orphans a drop left behind, in BOTH directions — strict chat templates reject either. (1) a
    ``tool`` result whose issuing ``assistant`` tool-call was dropped; and (M18) (2) an ``assistant``
    tool-call whose ``tool`` result was dropped — a DANGLING call is just as invalid. Pruning is by
    tool_call id, so a multi-call assistant keeps the calls whose results survived."""
    live_calls: set = set()
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                if tc.get("id"):
                    live_calls.add(tc["id"])
    kept, removed = [], 0
    for m in messages:  # (1) drop results whose call didn't survive
        if m.get("role") == "tool" and m.get("tool_call_id") and m["tool_call_id"] not in live_calls:
            removed += 1
            continue
        kept.append(m)
    live_results = {m["tool_call_id"] for m in kept
                    if m.get("role") == "tool" and m.get("tool_call_id")}
    out = []
    for m in kept:  # (2) prune assistant tool_call entries whose result didn't survive
        tcs = m.get("tool_calls") if m.get("role") == "assistant" else None
        if tcs:
            surviving = [tc for tc in tcs if not tc.get("id") or tc["id"] in live_results]
            if len(surviving) != len(tcs):
                removed += len(tcs) - len(surviving)
                if not surviving and not (m.get("content") or "").strip():
                    continue  # the assistant turn was ONLY dead tool_calls → drop the whole message
                m = {k: v for k, v in m.items() if k != "tool_calls"}
                if surviving:
                    m["tool_calls"] = surviving
        out.append(m)
    return out, removed


def reserve_for(body: dict) -> int:
    """Generation budget to hold back from the window for this request's own reply — the
    INPUT/output split of a fixed window (llama.cpp ``n_ctx`` covers prompt + generation).

    Precedence (codex-local's two-knob split — see ``Role``):
      1. ``cria_output_reserve`` — the role's explicit input-side reserve. This is the intended
         lever for file-writing roles: generous, and INDEPENDENT of ``max_tokens``. Because it
         wins here, an overflow-driven re-trim reserves the SAME generous output room every time —
         the codex-local subtlety (reserve output room via output_reserve, never via the usually-
         unset hard cap, which would leave 0 room and re-truncate immediately).
      2. ``max_tokens`` — fallback only: a request that self-caps its output at N needs exactly N
         of room, so reserve exactly that (no more — over-reserving would trim input needlessly).
      3. ``DEFAULT_GEN_RESERVE`` — nothing specified. Note an UNSET hard cap never means 0 reserve."""
    def _pos_int(v) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 0
        return v if v > 0 else 0

    return _pos_int(body.get(bodykeys.OUTPUT_RESERVE)) or _pos_int(body.get("max_tokens")) or DEFAULT_GEN_RESERVE
