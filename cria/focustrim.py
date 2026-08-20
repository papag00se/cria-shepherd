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

from . import dedup, denial, jsontext
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


def _call_mutates(tc: dict) -> bool:
    """The tool call could have CHANGED the workspace — so cria may not tell the coder that
    repeating it is pointless. Delegates to `shelltool.writes_something`, the one owner of that
    question (#23); see its docstring for the run this cost."""
    from . import shelltool
    fn = tc.get("function") or {}
    args = fn.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    cmd = ""
    if isinstance(args, dict):
        for k in ("command", "cmd", "script", "input"):
            v = args.get(k)
            if v:
                cmd = v if isinstance(v, str) else json.dumps(v)
                break
    return shelltool.writes_something(str(fn.get("name") or ""), cmd)


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
                #
                # AND NEVER FOLD A CALL THAT CHANGED SOMETHING. The note this fold emits says the
                # call "has told you everything it can — repeating it will return that same result",
                # which is a statement about a READER. Walked on cycle 4 cell 14
                # (`cart-billing-go x ternary-bonsai`, 15% useful): it landed on a repeated
                # `write_file` and then on a `sed -i`, and the coder concluded the only thing the
                # note supports — "the write_file tool seems to be caching the old content", "the
                # sed command is not working because the file content seems to be cached" — and
                # moved every later write into `python3 <<'PYEOF'` heredocs, where cria's syntax
                # floor cannot see them. A swallowed `\t` made `taxed` into `axed` and bash ate the
                # struct tags. The cell's famous typo is an artifact of a write cria drove it to.
                if cid is not None and not _call_is_gate(tc) and not _call_mutates(tc):
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
        # WHICH ADVICE DEPENDS ON WHETHER THE CALL WORKED. The note tells the model the call "has
        # told you everything it can. Read what it already returned above" — true of a call that
        # SUCCEEDED and is being repeated pointlessly, and false and harmful of one that failed:
        # a failed call told it nothing, and there is no answer above to read. Measured on the
        # six-language battery, where the guard sent a model to re-read an error as though it were
        # the result it wanted. Same guard, two failure modes, two different true sentences.
        out.append({"role": "user",
                    "content": prompts.render(
                        "trim_repeat_collapsed_failed" if _repeat_failed(messages, repeated[-1])
                        else "trim_repeat_collapsed", n=len(repeated), tried=label)})
        rep.squashed_runs += 1
    return out, rep


def _repeat_failed(messages: list[dict], call_id: str) -> bool:
    """Did the repeated call come back as a failure rather than an answer?

    Conservative on purpose: a refusal cria itself authored, an empty body, or a nonzero exit
    reported by the lowered command. Anything else is treated as a real result, so the guard's
    original wording stands wherever it was already true."""
    for m in messages:
        if m.get("role") != "tool" or m.get("tool_call_id") != call_id:
            continue
        body = str(m.get("content") or "")
        if not body.strip() or denial.is_denied(body):
            return True
        for line in body.splitlines():
            s = line.strip()
            if s.startswith("EXIT:") and s[5:].strip() not in ("0", ""):
                return True
        return False
    return False


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


def _drop_superseded_writes(messages: list[dict]) -> tuple[list[dict], int]:
    """A write payload that a LATER write to the same path replaced is carried once, as a pointer.

    THE MODEL WAS LOOKING AT SIX COPIES OF ITS OWN FILE. Measured on the targeted post-fix re-run of
    `rust-toml-cli x ternary-bonsai`: it rewrote a 6.6 KB `main.rs` whole, five times, each version
    99.1–99.9% identical to the one before — and every copy stayed verbatim in the working tail. The
    prompt went **5,223 tokens at the first write to 21,009 at the last**, and 33,103 bytes of that
    is six near-identical versions of one file. It then synthesised a sixth that introduced the type
    error the run died on: `.get(key)` had been right at three earlier rewrites and became
    `.get(key.to_string())` at the last.

    Nothing folded them because nothing could. `_collapse_duplicates` needs the calls to be
    byte-identical, and these differ by about 1%. `selfcompact` has exactly the right rule already —
    `write_stub_superseded`, keyed on PATH and not on content — but it only runs over the compacted
    middle, and these all sat in the verbatim tail after it.

    Only SUPERSEDED copies are stubbed; the newest write to each path stays whole, because that one
    is what is on disk. #5 names this exception in its own words: "repeated content may appear once
    with a pointer to the original"."""
    last: dict = {}
    for i, m in enumerate(messages):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            path = _write_path(tc)
            if path:
                last[path] = i
    if not last:
        return messages, 0
    # THE WHOLE CALL GOES, NOT THE INSIDE OF ITS ARGUMENT. This used to replace the payload with an
    # elision stub — `[elided 8031 chars — an EARLIER version of X, replaced by a later write…]` —
    # and leave the call in place. That put cria's own prose in the exact slot where file content
    # lives, in the model's own history, and on `feed-pipeline-java x qwen35` (2026-08-19) call 0095
    # the coder copied it forward as the content of a NEW write. javac answered
    # `Importer.java:[1,20] illegal character: '\u2014'` — the em dash in cria's sentence — and the
    # model's own reasoning read "The file got corrupted with placeholder text." A 357-line file
    # became one line of cria's note; recovery was `git checkout` to the seed, and everything built
    # since was lost.
    #
    # Operator, 2026-08-19: "There is not supposed to be any elision. It's all or nothing." So the
    # superseded call and its result are REMOVED, the way `_collapse_duplicates` already removes a
    # folded call, and one note says it happened. Nothing is left behind that can be read as content,
    # because nothing is left behind.
    drop_ids = {tc.get("id") for i, m in enumerate(messages)
                if isinstance(m, dict) and m.get("role") == "assistant"
                for tc in (m.get("tool_calls") or [])
                if (p := _write_path(tc)) and last.get(p) != i and _payload_chars(tc) >= _STUB_MIN_CHARS}
    drop_ids.discard(None)
    if not drop_ids:
        return messages, 0
    out, dropped = [], 0
    for m in messages:
        role = m.get("role") if isinstance(m, dict) else None
        if role == "assistant" and m.get("tool_calls"):
            kept = [tc for tc in m["tool_calls"] if tc.get("id") not in drop_ids]
            n = len(m["tool_calls"]) - len(kept)
            if not n:
                out.append(m)
                continue
            dropped += n
            if not kept and not str(m.get("content") or "").strip():
                continue                      # emptied → the whole assistant turn goes
            out.append({**m, "tool_calls": kept})
        elif role == "tool" and m.get("tool_call_id") in drop_ids:
            continue                          # orphaned result of a dropped call
        else:
            out.append(m)
    # SAY IT HAPPENED, once, in cria's own marked channel — never in an argument slot. The model is
    # otherwise shown a history in which writes it made are simply absent, and a weak model reading
    # that concludes the file was never written and starts again (the disown-your-own-work failure
    # the re-orientation seat exists for).
    if dropped:
        out.append({"role": "user",
                    "content": prompts.render("superseded_writes_dropped", count=str(dropped),
                                              paths=", ".join(sorted(last)[:6]))})
    return (out if dropped else messages), dropped


def _payload_chars(tc: dict) -> int:
    """The size of the biggest write-payload argument on this call — 0 when it carries none.

    The size test is what keeps a one-line edit in the history: dropping every superseded call
    regardless of size would throw away the small, cheap ones that cost nothing to keep and that
    show the model the shape of what it has been doing."""
    fn = tc.get("function") or {}
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        return 0
    if not isinstance(args, dict):
        return 0
    return max((len(v) for k, v in args.items()
                if k in ("content", "contents", "new_string", "patch", "old_string")
                and isinstance(v, str)), default=0)


def _write_path(tc: dict) -> str:
    """The path a write-ish tool call targets, or ""."""
    fn = tc.get("function") or {}
    if fn.get("name") not in ("write_file", "create_file", "edit_file", "apply_patch"):
        return ""
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        return ""
    return str((args or {}).get("path") or (args or {}).get("file_path") or "") if isinstance(args, dict) else ""


# Below this a payload is not worth a pointer — the stub would be as long as the thing it replaces.
_STUB_MIN_CHARS = 400


def trim(messages: list[dict]) -> tuple[list[dict], TrimReport]:
    """Focus the outbound view. Returns (messages, report) — the SAME list object (no copy) when
    nothing is trimmed."""
    if not isinstance(messages, list):
        return messages, TrimReport()
    out, rep_a = _collapse_duplicates(messages)
    out, rep_b = _squash_failures(out)
    out, superseded = _drop_superseded_writes(out)
    rep_b = TrimReport(dropped_calls=rep_b.dropped_calls, dropped_msgs=rep_b.dropped_msgs,
                       squashed_runs=rep_b.squashed_runs + superseded)
    total = TrimReport(
        dropped_calls=rep_a.dropped_calls + rep_b.dropped_calls,
        dropped_msgs=rep_a.dropped_msgs + rep_b.dropped_msgs,
        squashed_runs=rep_b.squashed_runs,
    )
    return (out if total.applied else messages), total
