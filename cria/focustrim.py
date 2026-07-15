"""Focus-trim — a per-call OUTBOUND context-shaping pass.

cria keeps the FULL conversation for its own detection (repetition guards read the model's
completions, compaction detection reads the conversation root — neither is affected by this), but a
small model drowns in its own repeated failed tool calls: the PyHandle spiral was wall-to-wall
`cat …: No such file` / `find … lambdas` pairs, the model re-reading its own dead ends and
re-deciding to repeat them. This trims what the MODEL sees so it stays focused on current state.

Two rules, applied in order:

  A. COLLAPSE EXACT DUPLICATES — a tool call with the same (name, canonicalized arguments) appearing
     more than once is reduced to its LAST occurrence (the freshest result: a `cat x` that failed
     then succeeded after an edit keeps the success). This also subsumes "superseded errors" (same
     command failed then succeeded) and exact re-reads of a file.

  B. SQUASH ERROR-SPAM — a consecutive RUN of failed actions (an assistant turn with one tool call
     whose result is an error: non-zero exit, file-not-found, command-not-found) of length ≥
     `_SPAM_THRESHOLD` is collapsed to its last `_SPAM_KEEP` actions plus one note naming what was
     tried. The recent failures survive (so the model won't repeat them or lose a live error); only
     the stale flailing tail is removed.

Both drop tool calls and their paired results as UNITS, so no `tool` result is ever orphaned from
its `assistant` tool_call (the one hard constraint in the OpenAI/Responses message format). Neither
mutates its input — a new list is returned — so it is safe to apply to a framed body while the
history cria's detectors read stays intact. Runs BEFORE the context floor, so the floor budgets the
already-focused view.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import prompts

# Error-spam squash tuning. A run must reach _SPAM_THRESHOLD failed actions before any are squashed,
# and the most recent _SPAM_KEEP always survive (so a live error the model needs is never removed).
_SPAM_THRESHOLD = 4
_SPAM_KEEP = 2

# Precise failure signatures — matched against a tool RESULT's content. Kept narrow on purpose (a
# bare "failed"/"error" appears in plenty of legitimate output); these are unambiguous dead ends.
_FAIL_SIGNATURES = [
    re.compile(r"exited with code [1-9]", re.I),   # Codex exec: "Process exited with code 1"
    re.compile(r"\bexit code [1-9]", re.I),
    re.compile(r"no such file or directory", re.I),
    re.compile(r"command not found", re.I),
    re.compile(r"\bnot found\b", re.I),
]


@dataclass
class TrimReport:
    dropped_calls: int = 0    # duplicate/failed tool_calls removed
    dropped_msgs: int = 0     # messages removed (emptied assistant turns, squashed failed actions)
    squashed_runs: int = 0    # error-spam runs collapsed to a note

    @property
    def applied(self) -> bool:
        return self.dropped_calls > 0 or self.dropped_msgs > 0 or self.squashed_runs > 0


def _clip(s: str, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _fingerprint(tc: dict) -> tuple[str, str]:
    """(name, normalized-arguments) — JSON args are canonicalized (key order / whitespace
    insensitive); non-JSON falls back to the stripped string."""
    fn = tc.get("function") or {}
    name = str(fn.get("name", ""))
    args = fn.get("arguments")
    try:
        parsed = json.loads(args) if isinstance(args, str) else args
        norm = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        norm = str(args).strip()
    return name, norm


def _single_call(m: dict) -> dict | None:
    """The lone tool_call of an assistant turn that made exactly one — else None."""
    tcs = m.get("tool_calls") or []
    return tcs[0] if m.get("role") == "assistant" and len(tcs) == 1 else None


def _is_failure(content) -> bool:
    return isinstance(content, str) and any(p.search(content) for p in _FAIL_SIGNATURES)


def _tried_label(tc: dict) -> str:
    """A short 'exec_command(cat /x)' label for the squash note's list of what was tried."""
    fn = tc.get("function") or {}
    name = str(fn.get("name", ""))
    args = fn.get("arguments")
    try:
        d = json.loads(args) if isinstance(args, str) else args
        detail = d.get("cmd") or d.get("command") or d.get("path") or json.dumps(d, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        detail = str(args)
    return f"{name}({_clip(str(detail), 60)})"


def _collapse_duplicates(messages: list[dict]) -> tuple[list[dict], TrimReport]:
    """Rule A — collapse exact-duplicate tool calls to their LAST occurrence."""
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


def _squash_error_runs(messages: list[dict]) -> tuple[list[dict], TrimReport]:
    """Rule B — collapse a consecutive run of failed single-call actions to its last _SPAM_KEEP,
    replacing the dropped tail-of-flailing with one note. An 'action' is an assistant turn with one
    tool call immediately followed by its (failing) result."""
    n = len(messages)
    spans: list[tuple[int, int, dict]] = []  # (assistant_idx, result_idx, tool_call)
    i = 0
    while i < n - 1:
        tc = _single_call(messages[i])
        nxt = messages[i + 1]
        if (tc is not None and nxt.get("role") == "tool"
                and nxt.get("tool_call_id") == tc.get("id") and _is_failure(nxt.get("content"))):
            spans.append((i, i + 1, tc))
            i += 2
        else:
            i += 1
    if not spans:
        return messages, TrimReport()

    # Group spans that are adjacent in the message list into runs.
    runs: list[list[tuple[int, int, dict]]] = []
    cur: list[tuple[int, int, dict]] = []
    for s in spans:
        if cur and s[0] == cur[-1][1] + 1:
            cur.append(s)
        else:
            if cur:
                runs.append(cur)
            cur = [s]
    if cur:
        runs.append(cur)

    remove: set[int] = set()
    notes: dict[int, str] = {}  # first-dropped-assistant-index → the squash note
    rep = TrimReport()
    for run in runs:
        if len(run) < _SPAM_THRESHOLD:
            continue
        drop = run[:-_SPAM_KEEP]
        for a, r, _tc in drop:
            remove.add(a)
            remove.add(r)
        rep.dropped_calls += len(drop)
        rep.dropped_msgs += len(drop) * 2  # each action is an assistant + a tool message
        rep.squashed_runs += 1
        tried = "; ".join(_tried_label(tc) for _a, _r, tc in drop)
        notes[drop[0][0]] = prompts.render("trim_error_squash", n=len(drop), tried=_clip(tried, 300))
    if not remove:
        return messages, TrimReport()

    out: list[dict] = []
    for idx, m in enumerate(messages):
        if idx in notes:
            out.append({"role": "user", "content": notes[idx]})
        if idx in remove:
            continue
        out.append(m)
    return out, rep


def trim(messages: list[dict]) -> tuple[list[dict], TrimReport]:
    """Focus the outbound view. Returns (messages, report) — the SAME list object (no copy) when
    nothing is trimmed."""
    if not isinstance(messages, list):
        return messages, TrimReport()
    out, rep_a = _collapse_duplicates(messages)
    out, rep_b = _squash_error_runs(out)
    total = TrimReport(
        dropped_calls=rep_a.dropped_calls + rep_b.dropped_calls,
        dropped_msgs=rep_a.dropped_msgs + rep_b.dropped_msgs,
        squashed_runs=rep_b.squashed_runs,
    )
    return (out if total.applied else messages), total
