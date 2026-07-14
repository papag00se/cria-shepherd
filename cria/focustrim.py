"""Focus-trim — a per-call OUTBOUND context-shaping pass.

cria keeps the FULL conversation for its own detection (repetition guards read the model's
completions, compaction detection reads the conversation root — neither is affected by this), but a
small model drowns in its own repeated failed tool calls: the PyHandle spiral was wall-to-wall
identical `cat …: No such file` / `find … lambdas` pairs, the model re-reading its own dead ends and
re-deciding to repeat them. This trims what the MODEL sees so it stays focused on current state.

v1 rule — collapse EXACT-duplicate tool calls: a tool call with the same (name, normalized
arguments) that appears more than once is reduced to its LAST occurrence (the freshest result — e.g.
a `cat x` that failed, then succeeded after an edit, keeps the success). Earlier duplicates are
dropped as call+result UNITS so no `tool` result is ever orphaned from its `assistant` tool_call
(the one hard correctness constraint in the OpenAI/Responses message format); an assistant message
left with no tool_calls and no text is dropped whole.

Never mutates its input — returns a new list — so it is safe to apply to a framed body while the
original history cria's detectors read stays intact. Runs BEFORE the context floor (contextfloor),
so the floor budgets against the already-focused view.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class TrimReport:
    dropped_calls: int = 0   # duplicate tool_calls removed
    dropped_msgs: int = 0    # assistant messages emptied and removed

    @property
    def applied(self) -> bool:
        return self.dropped_calls > 0 or self.dropped_msgs > 0


def _fingerprint(tc: dict) -> tuple[str, str]:
    """(name, normalized-arguments) — JSON args are canonicalized (key order / whitespace
    insensitive) so `cat x` and `cat  x` with reordered keys still match; non-JSON falls back to the
    stripped string."""
    fn = tc.get("function") or {}
    name = str(fn.get("name", ""))
    args = fn.get("arguments")
    try:
        parsed = json.loads(args) if isinstance(args, str) else args
        norm = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        norm = str(args).strip()
    return name, norm


def trim(messages: list[dict]) -> tuple[list[dict], TrimReport]:
    """Collapse exact-duplicate tool calls to their last occurrence. Returns (messages, report) —
    the SAME list object (no copy) when nothing is trimmed."""
    if not isinstance(messages, list):
        return messages, TrimReport()

    # Pass 1 — every tool_call id per fingerprint, in order. All but the LAST are dropped.
    occ: dict[tuple[str, str], list[str]] = {}
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                cid = tc.get("id")
                if cid is not None:
                    occ.setdefault(_fingerprint(tc), []).append(cid)
    drop_ids = {cid for cids in occ.values() if len(cids) > 1 for cid in cids[:-1]}
    if not drop_ids:
        return messages, TrimReport()

    # Pass 2 — rebuild, dropping the flagged tool_calls and their paired results as units.
    out: list[dict] = []
    rep = TrimReport()
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            kept = [tc for tc in m["tool_calls"] if tc.get("id") not in drop_ids]
            n = len(m["tool_calls"]) - len(kept)
            if not n:
                out.append(m)
                continue
            rep.dropped_calls += n
            if not kept and not str(m.get("content") or "").strip():
                rep.dropped_msgs += 1  # emptied → drop the whole assistant turn
                continue
            out.append({**m, "tool_calls": kept})
        elif role == "tool" and m.get("tool_call_id") in drop_ids:
            continue  # orphaned result of a dropped call
        else:
            out.append(m)
    return out, rep
