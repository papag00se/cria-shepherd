"""Focus-trim — a per-call OUTBOUND context-shaping pass.

cria keeps the FULL conversation for its own detection (repetition guards read the model's
completions, compaction detection reads the conversation root — neither is affected by this), but a
small model drowns in its own repeated failed tool calls: the PyHandle spiral was wall-to-wall
`cat …: No such file` / `find … lambdas` pairs, the model re-reading its own dead ends and
re-deciding to repeat them. This trims what the MODEL sees so it stays focused on current state.

Two rules, applied in order:

  A. COLLAPSE EXACT DUPLICATES — a tool call with the same (name, canonicalized arguments, AND
     result content) appearing more than once is reduced to its LAST occurrence. The OUTPUT is part
     of the key: a `cat config` run before vs after an edit returns DIFFERENT content, so BOTH are
     kept (the earlier output is never lost to a silent collapse). Only a byte-identical re-run —
     same command AND same result — collapses, subsuming an exact re-read of a file whose content
     did not change.

  B. SQUASH SOFT ERROR-SPAM — soft-failed actions (an assistant turn with one tool call whose result
     is a dead-end LOOKUP: file-not-found, command-not-found, a bare "not found" with no explicit
     success) are collapsed once there are more than `_SPAM_KEEP` of them: the last `_SPAM_KEEP`
     survive, all EARLIER ones are removed wherever they sit, and one note names everything that was
     tried. They need NOT be consecutive — a dead-end lookup is noise whether it flails in a spree or
     is scattered across the session. HARD failures (the tool itself exited non-zero — a failing
     pytest / build / live-test) are NEVER squashed: their output carries the traceback / assertion /
     error the coder needs to fix the problem, so every one is kept IN FULL, in place. Successful
     actions are always kept too.

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

from . import dedup, jsontext
from . import probegate, prompts

# cria's OWN ground-truth gate probe tags its output with these section markers. Such a probe
# exits NON-ZERO by design (a failing check is the signal), so it trips the fail signatures — but it
# is not a model dead-end: squashing it removes the exact ground truth cria injected and, worse,
# folds it into a note that tells the model "don't repeat these". It must survive the squash.
_GATE_MARKER = probegate.SECTION_PREFIX

# Error-spam squash tuning. Squash only once there are MORE than _SPAM_KEEP SOFT-failed actions (so
# a couple of dead-end lookups are left alone); the most recent _SPAM_KEEP soft failures always
# survive (a live dead-end the model is fixing is never removed, even across intervening successes).
# HARD failures (non-zero exit) are exempt entirely — see _is_hard_failure — never dropped.
_SPAM_KEEP = 2

# HARD failures — the tool itself exited non-zero. Unambiguous dead ends.
_HARD_FAIL_SIGNATURES = [
    re.compile(r"exited with code [1-9]", re.I),   # Codex exec: "Process exited with code 1"
    re.compile(r"\bexit code [1-9]", re.I),
]
# SOFT failures — content phrases that USUALLY mean a dead end (a missing file, a bad command). But
# they also appear in the BODY of a SUCCESSFUL call: a live-API curl that exits 0 and returns
# {"error":"route_not_found", "docs":"…"} carries the exact hint the model needs. So a soft phrase is
# only a failure when the tool did NOT explicitly succeed — otherwise squashing it (into a "don't
# repeat these" note) throws away a real result and steers the model away from re-querying the API.
_SOFT_FAIL_SIGNATURES = [
    re.compile(r"no such file or directory", re.I),
    re.compile(r"command not found", re.I),
    re.compile(r"\bnot found\b", re.I),
]
# Explicit success markers the exec / lowered-web_fetch envelopes always print. Their presence means
# the TOOL succeeded, so a soft phrase in the content is data, not a failure.
_SUCCESS_MARKERS = [
    re.compile(r"exited with code 0\b", re.I),
    re.compile(r"\bHTTP 2\d\d\b"),
]


@dataclass
class TrimReport:
    dropped_calls: int = 0    # duplicate/failed tool_calls removed
    dropped_msgs: int = 0     # messages removed (emptied assistant turns, squashed failed actions)
    squashed_runs: int = 0    # error-spam runs collapsed to a note

    @property
    def applied(self) -> bool:
        return self.dropped_calls > 0 or self.dropped_msgs > 0 or self.squashed_runs > 0


def _fingerprint(tc: dict) -> tuple[str, str]:
    """(name, normalized-arguments) — JSON args are canonicalized (key order / whitespace
    insensitive); non-JSON falls back to the stripped string."""
    fn = tc.get("function") or {}
    name = str(fn.get("name", ""))
    args = fn.get("arguments")
    try:
        parsed = jsontext.loads(args) if isinstance(args, str) else args
        norm = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        norm = str(args).strip()
    return name, norm


def _single_call(m: dict) -> dict | None:
    """The lone tool_call of an assistant turn that made exactly one — else None."""
    tcs = m.get("tool_calls") or []
    return tcs[0] if m.get("role") == "assistant" and len(tcs) == 1 else None


# The FILE tools. Their result is a PAYLOAD (a file's bytes, a directory listing, "Wrote <path>"),
# never a lookup envelope — so a soft phrase inside one is the user's own source code, not a dead end.
# Walked on ada-handles_nemotron-elastic_codex_pon_1785888803 calls 0159-0165: the coder's resolver
# raises `ValueError("Handle not found or no holder address")`, so EVERY read_file of it, and every
# ⟦ctx:edit⟧ recovery dump carrying its exact bytes, matched `\bnot found\b` and was squashed into a
# note reading "each returned nothing usable (a dead-end lookup: not found / no match / empty
# result) … don't repeat these". The sibling test file, whose source lacks the phrase, was never
# folded once — same tool, same session, same directory. The coder was left unable to see the file it
# was editing, guessed its old_string from a deleted memory eight calls running, and at 0162 answered
# cria's "Read what it already returned above" by FABRICATING the file and writing it to disk.
_FILE_TOOLS = frozenset({"read_file", "write_file", "edit_file", "list_dir", "view_image"})


# The harness exec envelope stamps fields that differ on EVERY run of the same command — a fresh
# `Chunk ID: <hex>`, a wall time, a token count. Keying a duplicate group on the raw result text
# therefore means two BYTE-IDENTICAL re-runs of one command never share a key, and rule A can never
# fire for exec_command at all. Walked on ada-handles_nemotron-elastic_codex_pon_1785360304: the
# coder ran `sed -n '607,680p'` on the same file seven times inside one prompt and
# `grep -n "#/components/schemas/Handle"` a dozen more, ~30 KB of byte-identical output per prompt,
# and no duplicate collapse and no repetition notice ever fired across the whole run.
#
# The table of what counts as per-run noise now lives in dedup.volatile_key — ONE owner, because
# probegate's gate repeat-collapse was failing the same way on a different shape (object addresses,
# runner durations) and two answers to "is this the same thing again?" is one too many.
_result_key = dedup.volatile_key


def _is_failure(content, tool_name: str = "") -> bool:
    if not isinstance(content, str):
        return False
    if any(p.search(content) for p in _HARD_FAIL_SIGNATURES):
        return True
    if any(p.search(content) for p in _SUCCESS_MARKERS):
        return False   # the tool exited 0 / returned 2xx → a success whose body just mentions "not found"
    if tool_name in _FILE_TOOLS:
        return False   # a file payload: the phrase is the file's content, not the tool's verdict
    return any(p.search(content) for p in _SOFT_FAIL_SIGNATURES)


def _is_hard_failure(content) -> bool:
    """The tool itself exited NON-ZERO (matches a HARD signature). Unlike a soft dead-end lookup, its
    output carries the traceback / assertion / build error the coder needs to fix the problem — so it
    is exempt from the error-spam squash and kept in full, never folded into a 'tried' note."""
    return isinstance(content, str) and any(p.search(content) for p in _HARD_FAIL_SIGNATURES)


def _call_is_gate(tc: dict) -> bool:
    """The tool call is cria's own gate probe — its command carries the ___CRIA_GATE_ marker."""
    args = (tc.get("function") or {}).get("arguments") or ""
    args = args if isinstance(args, str) else json.dumps(args)
    return _GATE_MARKER in args


def _is_gate_probe(tc: dict, result: dict) -> bool:
    """cria's own ground-truth gate probe (its command/result carries the ___CRIA_GATE_ markers).
    Exempt from the failure-squash: it is the ground truth, not a dead end to remove."""
    return _call_is_gate(tc) or _GATE_MARKER in str(result.get("content") or "")


def _tried_label(tc: dict) -> str:
    """A short 'exec_command(cat /x)' label for the squash note's list of what was tried."""
    fn = tc.get("function") or {}
    name = str(fn.get("name", ""))
    args = fn.get("arguments")
    try:
        d = jsontext.loads(args) if isinstance(args, str) else args
        detail = d.get("cmd") or d.get("command") or d.get("path") or json.dumps(d, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        detail = str(args)
    # Full command text — a model can't recognize (and so can't avoid retrying) a command shown as
    # "python -m pytest tests/really/long/pa…". The whole label rides in the squash note.
    return f"{name}({str(detail)})"


def _collapse_duplicates(messages: list[dict]) -> tuple[list[dict], TrimReport]:
    """Rule A — collapse duplicate tool calls to their LAST occurrence. The key is (name, canonical
    arguments, AND result content): a command re-run with DIFFERENT output (e.g. `cat config` before
    vs after an edit) is NOT a duplicate, so both are kept and no earlier output is lost. Only a
    byte-identical re-run — same args AND same result — collapses."""
    # Map each tool_call id → its result content so identical args with DIFFERING output stay
    # distinct. Missing result → "" (two argless-identical calls with no result collapse harmlessly;
    # a present-vs-missing result differs → both kept).
    result_by_id: dict[str, str] = {}
    for m in messages:
        if m.get("role") == "tool":
            rid = m.get("tool_call_id")
            if rid is not None:
                result_by_id[rid] = str(m.get("content") or "")

    occ: dict[tuple[str, str, str], list[str]] = {}
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                cid = tc.get("id")
                # Never fold cria's OWN gate probe into a dup group — two identical gate scripts
                # would collapse and drop an earlier probe+result pair cria depends on (same class
                # as the failure-squash exemption).
                if cid is not None and not _call_is_gate(tc):
                    name, norm = _fingerprint(tc)
                    occ.setdefault((name, norm, _result_key(result_by_id.get(cid, ""))), []).append(cid)
    drop_ids = {cid for cids in occ.values() if len(cids) > 1 for cid in cids[:-1]}
    if not drop_ids:
        return messages, TrimReport()

    # THE LAST CALL REPEATED ITSELF — say so, don't just delete the evidence.
    #
    # When the group whose duplicates are being collapsed is the one the model just made, this
    # collapse is silently destructive in the one way that matters: the conversation GREW by an
    # identical call and an identical result, this rule removes the older copy, and the rendered
    # body comes out BYTE-IDENTICAL to the one sent a moment ago. A temperature-0 model handed a
    # constant is a deterministic function — it returns the same call again, necessarily. cria then
    # counts those repeats and steers the coder for "repeating the same action without changing
    # anything", which it did not choose to do: cria deleted the only evidence that it already had.
    #
    # MEASURED over the whole capture set (2026-08-03): 76 of 118 runs (64%) sent a coder the
    # byte-identical prompt twice in a row, 344 calls in all — every one a guaranteed-identical
    # answer. Walked on ada-handles_fabliq_codex_pon_1785801960 calls 0015/0016: same prompt md5,
    # same 682-char reasoning, same tool call, then `loop.repetition` at count 3 and a supervisor
    # directive telling the coder to stop repeating the fetch.
    #
    # So the note is not decoration — it is the difference between the model being told what it did
    # and being asked the same question again. This mirrors what rule B has always done for the
    # failures it folds away (`trim_error_squash`); rule A collapsing in silence was the asymmetry.
    # Only for the group that ends at the FINAL tool call: an old duplicate deep in the history is
    # genuinely stale and folding it away is what this rule is for (#3 — silence over noise).
    last_call_id = None
    for m in reversed(messages):
        if m.get("role") == "assistant" and (m.get("tool_calls") or []):
            last_call_id = (m["tool_calls"][-1] or {}).get("id")
            break
    repeated = next((cids for cids in occ.values()
                     if len(cids) > 1 and cids[-1] == last_call_id and last_call_id is not None), None)

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
    if repeated is not None:
        label = next((_tried_label(tc) for m in messages if m.get("role") == "assistant"
                      for tc in (m.get("tool_calls") or []) if tc.get("id") == repeated[-1]), "")
        out.append({"role": "user",
                    "content": prompts.render("trim_repeat_collapsed",
                                              n=len(repeated), tried=label)})
        rep.squashed_runs += 1
    return out, rep


def _squash_failures(messages: list[dict]) -> tuple[list[dict], TrimReport]:
    """Rule B — collapse stale SOFT-failed actions (position-independent). Keep the last _SPAM_KEEP
    soft failures (a live dead-end the model is fixing survives even across intervening successes);
    remove every earlier soft failure wherever it sits, and replace them with ONE note naming what
    was tried. HARD failures (non-zero exit — a failing pytest / build / live-test) are NEVER a
    squash candidate: their output carries the traceback / assertion the coder needs, so they are
    kept in full, in place. Successful actions are always kept. An 'action' is an assistant turn with
    one tool call immediately followed by its (failing) result."""
    failed: list[tuple[int, int, dict]] = []  # (assistant_idx, result_idx, tool_call), in order
    i, n = 0, len(messages)
    while i < n - 1:
        tc = _single_call(messages[i])
        nxt = messages[i + 1]
        if (tc is not None and nxt.get("role") == "tool"
                and nxt.get("tool_call_id") == tc.get("id")
                and _is_failure(nxt.get("content"), str((tc.get("function") or {}).get("name") or ""))
                and not _is_hard_failure(nxt.get("content"))  # hard fail carries diagnostics — keep in full
                and not _is_gate_probe(tc, nxt)):  # never squash cria's own ground-truth probe
            failed.append((i, i + 1, tc))
            i += 2
        else:
            i += 1
    if len(failed) - _SPAM_KEEP < 2:
        return messages, TrimReport()  # fewer than 2 stale failures — not worth collapsing to a note

    drop = failed[:-_SPAM_KEEP]  # every failure except the most recent _SPAM_KEEP
    remove = {idx for a, r, _tc in drop for idx in (a, r)}
    note_at = drop[-1][0]  # the last removed failure's position → the note sits just before the kept ones
    tried = "; ".join(_tried_label(tc) for _a, _r, tc in drop)
    note = prompts.render("trim_error_squash", n=len(drop), tried=tried)  # full list — don't elide squashed attempts
    rep = TrimReport(dropped_calls=len(drop), dropped_msgs=len(drop) * 2, squashed_runs=1)

    out: list[dict] = []
    for idx, m in enumerate(messages):
        if idx == note_at:
            out.append({"role": "user", "content": note})
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
    out, rep_b = _squash_failures(out)
    total = TrimReport(
        dropped_calls=rep_a.dropped_calls + rep_b.dropped_calls,
        dropped_msgs=rep_a.dropped_msgs + rep_b.dropped_msgs,
        squashed_runs=rep_b.squashed_runs,
    )
    return (out if total.applied else messages), total
