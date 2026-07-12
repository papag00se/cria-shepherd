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

from .content_reduce import content_reduce, est_tokens

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


def _reduce_tool_outputs(messages: list[dict], msg_budget: int) -> tuple[list[dict], int]:
    """Shrink the largest ``tool`` outputs (bulkiest first) via content_reduce until the
    transcript fits or nothing bulky remains. Only touches role==tool messages."""
    total = _msgs_tokens(messages)
    if total <= msg_budget:
        return messages, 0
    # index → estimated size, largest first, tool outputs only
    sized = sorted(
        ((i, est_tokens(_msg_text(m))) for i, m in enumerate(messages) if m.get("role") == "tool"),
        key=lambda t: t[1], reverse=True,
    )
    out = list(messages)
    reduced = 0
    for i, sz in sized:
        if total <= msg_budget:
            break
        if sz < 256:  # not worth reducing a small output
            continue
        m = out[i]
        content = m.get("content")
        text = content if isinstance(content, str) else _msg_text(m)
        # Aim this output at a share of the remaining budget, not below a usable floor.
        cap = max(256, msg_budget // 4)
        new_text = content_reduce(text, _sniff_content_type(text), cap)
        if est_tokens(new_text) < sz:
            out[i] = {**m, "content": new_text}
            total = total - sz + est_tokens(new_text)
            reduced += 1
    return out, reduced


def _protected_mask(messages: list[dict]) -> list[bool]:
    """True where a message must NOT be dropped: every system message, and the active
    turn — the last user message through the end of the list."""
    n = len(messages)
    last_user = -1
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            last_user = i
    prot = [False] * n
    for i, m in enumerate(messages):
        if m.get("role") in ("system", "developer"):
            prot[i] = True
        if last_user >= 0 and i >= last_user:
            prot[i] = True
    return prot


def _drop_protected_overflow(messages: list[dict], msg_budget: int) -> tuple[list[dict], int]:
    """Last resort when the PROTECTED span alone is over budget: drop its oldest turns,
    never touching (a) system/developer messages, (b) the last user message — the request
    being answered, (c) the trailing OVERFLOW_KEEP_TAIL messages — the active work. Drops
    from the oldest end of the span until the estimate fits or nothing droppable remains."""
    work = list(messages)
    dropped = 0
    while _msgs_tokens(work) > msg_budget:
        last_user = -1
        for i, m in enumerate(work):
            if m.get("role") == "user":
                last_user = i
        tail_start = max(len(work) - OVERFLOW_KEEP_TAIL, 0)
        victim = next((i for i, m in enumerate(work)
                       if i > last_user and i < tail_start
                       and m.get("role") not in ("system", "developer")), None)
        if victim is None:
            break  # only the irreducible core remains
        work.pop(victim)
        dropped += 1
    return work, dropped


def _drop_oldest(messages: list[dict], msg_budget: int) -> tuple[list[dict], int]:
    """Drop oldest droppable messages (not system, not the active turn) until the
    transcript fits the budget or nothing droppable remains."""
    prot = _protected_mask(messages)
    keep = [True] * len(messages)
    total = _msgs_tokens(messages)
    dropped = 0
    for i, m in enumerate(messages):
        if total <= msg_budget:
            break
        if prot[i]:
            continue
        total -= est_tokens(_msg_text(m))
        keep[i] = False
        dropped += 1
    return [m for i, m in enumerate(messages) if keep[i]], dropped


def _strip_orphan_tools(messages: list[dict]) -> tuple[list[dict], int]:
    """Remove any ``tool`` message whose ``tool_call_id`` is not produced by a surviving
    ``assistant`` tool-call — dropping an old assistant turn would otherwise leave its
    results orphaned, which strict chat templates reject."""
    live: set = set()
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                if tc.get("id"):
                    live.add(tc["id"])
    out, removed = [], 0
    for m in messages:
        if m.get("role") == "tool" and m.get("tool_call_id") and m["tool_call_id"] not in live:
            removed += 1
            continue
        out.append(m)
    return out, removed


def reserve_for(body: dict) -> int:
    """Generation budget to hold back from the window for this request's own reply — the
    INPUT/output split of a fixed window (llama.cpp ``n_ctx`` covers prompt + generation).

    Precedence (codex-local's two-knob split — see ``LocalRole``):
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

    return _pos_int(body.get("cria_output_reserve")) or _pos_int(body.get("max_tokens")) or DEFAULT_GEN_RESERVE
