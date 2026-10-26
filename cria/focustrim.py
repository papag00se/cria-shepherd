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

  B. FOLD PROVEN REFUSALS — only a call whose unambiguously paired result carries the lowering's
     authoritative refusal outcome may be folded. Native, successful and unknown results stay in
     place regardless of their words or exit status. Read observations, typed reports and unapplied
     edit recovery stay in place too. The last `_SPAM_KEEP` refusals survive as ordinary pairs;
     earlier pairs are carried WHOLE in a labelled historical record, not replaced with an invented
     verdict about their usefulness. A refused call can still return useful evidence.

Both drop tool calls and their paired results as UNITS, so no `tool` result is ever orphaned from
its `assistant` tool_call (the one hard constraint in the OpenAI/Responses message format). Neither
mutates its input — a new list is returned — so it is safe to apply to a framed body while the
history cria's detectors read stays intact. Runs BEFORE the context floor, so the floor budgets the
already-focused view.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Callable, NamedTuple

from . import bodykeys, dedup, denial, editrecovery, jsontext, toolargs
from . import probegate, proberun, prompts, research, shelltool
from .assistcontract import Policy, Reference
from .memoryeffects import Effect, MessageEffect

# cria's OWN ground-truth gate probe tags its output with these section markers. Such a probe
# exits NON-ZERO by design (a failing check is the signal), so it trips the fail signatures — but it
# is not a model dead-end: squashing it removes the exact ground truth cria injected and, worse,
# folds it into a note that tells the model "don't repeat these". It must survive the squash.
_GATE_MARKER = probegate.SECTION_PREFIX

# Rule B keeps recent proven refusals as native pairs and folds older ones only
# when at least two pairs can be folded. Native/unknown results never qualify.
_SPAM_KEEP = 2

# Legacy write-outcome classification below is separate from Rule B. Rule B
# consults neither these body regexes nor the read-tool exemptions: it consumes
# only the canonical paired refusal outcome and preserves every native result.
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


# Legacy name-only API compatibility set. Read-only operations carry file DATA;
# write/edit members report outcomes and do NOT gain that exemption. The shared
# read/write/shell classifiers below make that distinction before reading words.
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


def _is_failure(content, tool_name: str = "", *, arguments=None, landed: bool = False) -> bool:
    """``landed``: the call's own program reported (typed record, `denial.landed`) that this write landed — a confirmed
    write is never a failure whatever words its result contains."""
    if not isinstance(content, str):
        return False
    # Status and payload usefulness are independent. Preserve the public hard
    # status contract even for readers; hard failures are retained by the trim.
    if any(p.search(content) for p in _HARD_FAIL_SIGNATURES):
        return True
    # Only READ-ONLY file operations return file DATA. Write/edit operations
    # report mutation outcomes, not the submitted content; a path alone cannot
    # make their failure reports into data. Preserve the legacy name-only API
    # for known readers, and require the shared path shape for other families.
    mutates = shelltool.is_write_tool_name(tool_name)
    if (not mutates and not shelltool.is_shell_tool_name(tool_name)
            and shelltool.is_read_tool_name(tool_name)
            and (tool_name in _FILE_TOOLS or tool_name in research._READ_TOOLS
                 or (shelltool.is_file_tool_name(tool_name) and toolargs.tool_path(arguments)))):
        return False
    if any(p.search(content) for p in _SUCCESS_MARKERS):
        return False   # the tool exited 0 / returned 2xx → a success whose body just mentions "not found"
    if mutates:
        # The typed landed fact: a filename containing failure words does not turn a confirmed write into a failed one.
        if landed:
            return False
    if _is_a_payload(content):
        return False   # a service's own structured answer: the phrase is DATA, not a verdict
    return any(p.search(content) for p in _SOFT_FAIL_SIGNATURES)


def _is_a_payload(content: str) -> bool:
    """Is this the tool's structured RESULT rather than its report of what happened?

    A deletion keyed on a phrase deletes whatever contains the phrase. `{"error":"route_not_found",
    "docs":"https://…/routes"}` is a live API answering — the exact hint the model needs — and it was
    read as a dead end and squashed into a "tried this" note. Whether a body PARSES as JSON is
    structural and needs no vocabulary: a service that answers in JSON is answering (#R7)."""
    text = (content or "").strip()
    if not text or text[0] not in "{[":
        return False
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


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

    Conservative on purpose: a refusal cria itself authored, or a nonzero exit reported by the
    lowered command. Anything else is treated as a real result, so the guard's original wording
    stands wherever it was already true.

    AN EMPTY BODY IS AN ANSWER, NOT A FAILURE — and it used to be counted as one. An empty file, a
    grep that matched nothing, a command that printed nothing: each is a fact the coder asked for and
    got. Walked on orders-api-py x nemotron-elastic 1787270062: `orders/__init__.py` is 0 bytes,
    `read_file` returned it correctly, and cria answered

        [you have now made this exact call 12 times and it FAILED the same way every time … Repeating
        it will fail the same way. It has not answered the question, so do not read its result as the
        answer: use a different tool, or fix what made it fail, before asking again.]

    The model obeyed it literally for twelve turns — "Maybe the file exists but empty? Let's try to
    view it" — and, pushed by "use a different tool", called `view_image` on a `.py` file. It escaped
    only by shelling out to `cat`, which printed the same nothing, at which point it believed the
    emptiness. Twelve of 146 turns, and a false fact in the one seat built to break loops (#5b).

    This is the same class as `selfcompact`'s "an empty line in a program's output is a value"
    (e6a3626), one module over. The repeat guard still fires on the REPETITION — that part was never
    wrong — it just no longer calls the answer a failure."""
    for m in messages:
        if m.get("role") != "tool" or m.get("tool_call_id") != call_id:
            continue
        body = str(m.get("content") or "")
        if denial.refused(m):
            return True
        # THE EXIT SENTINEL, READ THE ONE WAY IT IS WRITTEN. This scanned top-down for a literal
        # "EXIT:" of its own — so a program that PRINTED that string ("EXIT:1" in a log line, a test
        # name, a here-doc) was read as the shell's own exit code, and the first one won over the
        # real one at the bottom. `proberun` owns the sentinel and already reads it bottom-up for
        # exactly that reason; there is no second parser and no second spelling to keep in step.
        _, code = proberun.scrape_exit(body)
        return code not in (0, None)
    return False


def _squash_failures(messages: list[dict]) -> tuple[list[dict], TrimReport]:
    """Rule B — losslessly fold older proven refusals, never classify result prose.

    A command's nonzero status does not establish that its output is useless; neither
    do failure-looking phrases or a quoted exit line. Only the existing refusal and
    pairing owners can establish that a call did not run. Even then its entire answer
    survives: refusal bodies may carry genuine evidence. No new tool-name exceptions,
    native status parser or model judgment is needed.
    """
    paired = denial.paired_results(messages)
    failed: list[tuple[int, int, dict]] = []  # (assistant_idx, result_idx, tool_call), in order
    i, n = 0, len(messages)
    while i < n - 1:
        tc = _single_call(messages[i])
        nxt = messages[i + 1]
        if (tc is not None and paired.get(tc.get("id")) is nxt
                and denial.refused(nxt)
                # Keep evidence-bearing/recovery carriers at their native positions.
                # A damaged observation is UNKNOWN, not permission to fold its bytes.
                and bodykeys.READ_OBSERVATION not in nxt
                and bodykeys.RESULT_REPORT not in nxt
                and bodykeys.PAYLOAD_BOUNDARY not in nxt
                and not _is_gate_probe(tc, nxt)):
            failed.append((i, i + 1, tc))
            i += 2
        else:
            i += 1
    if len(failed) - _SPAM_KEEP < 2:
        return messages, TrimReport()  # fewer than 2 stale failures — not worth collapsing to a note

    drop = failed[:-_SPAM_KEEP]
    remove = {idx for a, r, _tc in drop for idx in (a, r)}
    # Preserve each complete public call/result, including assistant prose, exact
    # argument spelling and multiline output. Private producer hints are not prose
    # and must not leak into the model-facing historical record. The existing label
    # asserts ONLY the proven fact: these calls did not run, not that their answers
    # were empty, superseded or worthless. The context floor alone owns any later
    # pressure-driven reduction of this record.
    # Fold each pair at its original position. Combining scattered refusals into
    # one later record would move their evidence across intervening real results.
    label = prompts.load("work_log_denied").strip()
    notes = {a: label + "\n" + json.dumps(
                [{k: v for k, v in messages[idx].items() if k not in bodykeys.ALL} for idx in (a, r)],
                ensure_ascii=False)
             for a, r, _tc in drop}
    rep = TrimReport(dropped_calls=len(drop), dropped_msgs=len(drop) * 2, squashed_runs=1)

    out: list[dict] = []
    for idx, m in enumerate(messages):
        if idx in notes:
            out.append({"role": "user", "content": notes[idx]})
        if idx in remove:
            continue
        out.append(m)
    return out, rep


class SupersededWriteNotice(NamedTuple):
    """Producer-only identity of a notice and the exact historical pairs it promises.

    A JSON hint or marker-looking quote is not this in-process provenance. The
    immutable byte-identity digests survive framing copies without retaining
    mutable references or duplicating the source payload. A tuple remains JSON
    serializable for existing focused-view callers; a round-tripped JSON list
    deliberately has no producer authority.
    """
    text: str
    count: int
    paths: tuple[str, ...]
    replacements: tuple[tuple[str, str, str | None], ...]


def superseded_pair_identity(call: dict, result: dict | None) -> tuple[str, str | None]:
    """Exact call (including argument spelling) and paired output, not a landing judgment."""
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()
    return (digest(call), digest(result.get("content")) if result is not None else None)


def _terminal_positions(messages: list[dict]) -> dict:
    """call id -> message index of its result, for every call whose PAIRED result carries a TERMINAL proof: the write program itself
    reported it landed, or cria proved it changed nothing (`denial.landed_call_ids` / `denial.unlanded_call_ids`, over
    `denial.paired_results`). A reply merely ARRIVING proves nothing: a lowered command that yielded ("still running"), a cut or
    unframed result, or an `uncertain`/unknown one leaves the write possibly still executing, so it can neither be ordered before
    another call nor stand as the file's content. ONE owner for every happens-before question in this module and `selfcompact`."""
    terminal = denial.landed_call_ids(messages) | denial.unlanded_call_ids(messages)
    position = {id(m): n for n, m in enumerate(messages)}
    return {cid: position[id(m)] for cid, m in denial.paired_results(messages).items() if cid in terminal}


def _result_id(m: dict):
    """The call id a tool result answers — under either spelling `denial.paired_results` resolves."""
    return m.get("tool_call_id") or m.get("call_id")


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
    # A WRITE THAT NEVER REACHED DISK IS NOT THE NEWEST VERSION OF ANYTHING. `last` used to record
    # every write-shaped call, refusals included, so a REJECTED write became the "surviving" copy
    # and the real one before it was dropped — the model then held cria's rejection placeholder
    # where the file's text should be, which is exactly the destruction the removal rule above
    # exists to prevent. Walked on `feed-pipeline-java x nemotron-elastic` 20260820T103857 call
    # 0054: the coder's `pom.xml` write was refused as malformed XML, and the note still told it
    # "what is on disk is what you last wrote" about `pom.xml`.
    # ONLY A WHOLE-FILE WRITE SUPERSEDES, and it supersedes everything BEFORE it.
    #
    # Two sides, and the old rule had neither right. The superseding call has to replace the file
    # outright: an `edit_file` changes part of one and is not a version of it, so a 500-character
    # edit was deleting a 3,000-character `write_file` of the same path while the note below still
    # said "The newest version of each of those files is still here in full. Nothing was lost."
    # Reproduced before the fix. The superseded call, on the other hand, can be any write — once a
    # later whole-file write lands, every earlier call to that path is historical, edits included.
    #
    # So `last` indexes the last WHOLE-FILE write per path, and a call is superseded when it sits
    # strictly before it. An edit AFTER the last whole-file write is the newest change to that file
    # and survives. `toolargs.write_target` is the one owner of the distinction — there were three
    # implementations with three different tool-name lists (#23).
    failed = _failed_write_ids(messages)
    # THE SUPERSEDING WRITE MUST BE PROVEN LANDED (`denial.landed_call_ids`, the one typed accessor): an unknown, `uncertain`
    # or merely-quoted-confirmation result is not "what is on disk", and dropping an earlier copy on its strength would
    # delete the only version the model can still read.
    landed_ids = denial.landed_call_ids(messages)
    landed = [(i, p) for i, m in enumerate(messages)
              if isinstance(m, dict) and m.get("role") == "assistant"
              for tc in (m.get("tool_calls") or [])
              if (pw := toolargs.write_target(tc))[1] and (p := pw[0])
              and tc.get("id") not in failed and tc.get("id") in landed_ids]
    # THE CANDIDATE UNIVERSE IS EVERY FILE THE SESSION TRIED TO WRITE, whatever became of the attempt. The identity decides which
    # spellings could name the same file; building it from the landed writes alone dropped a real rival (a write whose result
    # was cut, unknown, uncertain or unanswered) and a relative spelling then folded onto the one landed absolute path — deleting a
    # payload that was still current while the note said "Nothing was lost". Outcomes decide what each write may CLAIM, never which
    # files exist. An AMBIGUOUS relative spelling (a suffix of two or more of them) is an unknown file: it does not supersede
    # anything, and it is never itself dropped, because deleting its only copy is the harm.
    key = _path_identity([p for m in messages if isinstance(m, dict) and m.get("role") == "assistant"
                          for tc in (m.get("tool_calls") or []) if (p := toolargs.write_path(tc))])
    last: dict = {}
    for i, path in landed:
        if not key.candidates(path):
            last[key(path)] = i
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
    # REMOVAL IS BY OCCURRENCE, NOT BY ID MEMBERSHIP, AND ONLY FOR A WRITE THAT PROVABLY FINISHED BEFORE ITS REPLACEMENT WAS SENT.
    # The removal below deletes every call and every result carrying a dropped id, so an id shared by two calls would take an
    # UNRELATED write with the superseded one; and a write that has not been answered (or whose answer arrives only after the
    # replacement was dispatched) may still execute AFTER it — dispatch order is not execution order — so deleting it would
    # destroy the only record of what the disk will hold. `denial.paired_results` (the one pairing owner: exactly one call, exactly
    # one result, the result after the call, under `tool_call_id` or `call_id`) is therefore the only pairing authority — and a
    # result that merely ARRIVED is not completion: a lowered command's reply may be "still running", cut, unframed or uncertain.
    # A call is removable only when its own PAIRED result carries a TERMINAL proof (`_terminal_positions`: proven landed, or
    # proven to have changed nothing) and sits BEFORE the message that carries the superseding write. Everything else stays,
    # with its result.
    result_at = _terminal_positions(messages)

    def removable(cid, superseder_at: int) -> bool:
        return bool(cid) and result_at.get(cid, superseder_at) < superseder_at

    superseded = [(tc.get("id"), p) for i, m in enumerate(messages)
                  if isinstance(m, dict) and m.get("role") == "assistant"
                  for tc in (m.get("tool_calls") or [])
                  if (p := toolargs.write_path(tc)) and i < last.get(key(p), -1) and not key.candidates(p)
                  and tc.get("id") not in failed and removable(tc.get("id"), last.get(key(p), -1))
                  and _payload_chars(tc) >= _STUB_MIN_CHARS]
    drop_ids = {i for i, _ in superseded}
    drop_ids.discard(None)
    if not drop_ids:
        return messages, 0
    # THE NOTE NAMES WHAT IT DROPPED, not every file the session ever wrote. `paths` was rendered
    # from `last` — the full write target list — so a note reporting ONE removal listed four files,
    # and asserted "what is on disk is what you last wrote" about files nothing had touched since.
    # Same walk, same call 0054.
    dropped_paths = sorted({key(p) for i, p in superseded if i in drop_ids})
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
        elif role == "tool" and _result_id(m) in drop_ids:
            continue                          # orphaned result of a dropped call (answered under `tool_call_id` OR `call_id`)
        else:
            out.append(m)
    # SAY IT HAPPENED, once, in cria's own marked channel — never in an argument slot. The model is
    # otherwise shown a history in which writes it made are simply absent, and a weak model reading
    # that concludes the file was never written and starts again (the disown-your-own-work failure
    # the re-orientation seat exists for).
    if dropped:
        answers = {_result_id(m): m for m in messages
                   if isinstance(m, dict) and m.get("role") == "tool"}
        replacements = []
        for path in dropped_paths:
            # Same selection as the deletion owner above; never infer a success from
            # English or promote an unanswered call to a landed write.
            candidates = [tc for tc in messages[last[path]].get("tool_calls") or []
                          if toolargs.write_target(tc)[1]
                          and key(toolargs.write_path(tc)) == path and tc.get("id") not in failed]
            tc = candidates[-1]
            call_text, answer_text = superseded_pair_identity(tc, answers.get(tc.get("id")))
            replacements.append((path, call_text, answer_text))
        text = prompts.render("superseded_writes_dropped", count=str(dropped),
                              paths=prompts.named_list(dropped_paths))
        out.append({"role": "user",
                    # THE REMAINDER IS NAMED. `paths` was cut at six with no marker, so a note could
                    # read "9 earlier write(s) removed … : a, b, c, d, e, f" and the model had no
                    # way to learn which files the missing bytes belonged to. The two units in the
                    # sentence are deliberate — N writes were removed, ACROSS these files — and the
                    # count stays a count of calls.
                    "content": text,
                    bodykeys.SUPERSEDED_WRITES: SupersededWriteNotice(
                        text, dropped, tuple(dropped_paths), tuple(replacements))})
    return (out if dropped else messages), dropped


def _path_identity(paths: list[str]):
    """A function folding the spellings of ONE file onto a single key — for grouping, not for I/O.

    ONE FILE UNDER TWO NAMES IS TWO FILES TO A dict, and that is how the superseded-write rule lost
    the file it existed for. Walked on `feed-pipeline-java x nemotron-elastic` 20260820T103857: the
    coder wrote `Importer.java` seven times by absolute path and once, at call 0043, as
    `src/main/java/pipeline/Importer.java` — the tool accepts both and they land on the same inode.
    Keyed on the raw string, the relative write and the absolute writes never superseded each other,
    so the biggest payload in the session went unfolded and cria's own note listed the file twice in
    one sentence, which reads as two different files that both changed (#5b).

    RESOLVED BY SHAPE, because cria cannot resolve it by path: the working directory is the
    HARNESS's, not cria's, so `abspath` here would anchor to the wrong root and invent a file that
    does not exist. A relative path folds onto an absolute one when it is a component-wise SUFFIX of
    it — `src/main/java/pipeline/Importer.java` under `/w/src/main/java/pipeline/Importer.java`.

    AMBIGUITY DOES NOT FOLD. When a relative spelling suffixes two different absolute paths, cria
    cannot know which was meant, so it stays its own key: the cost of not folding is a duplicate the
    model can still read, and the cost of folding wrongly is deleting a file's only copy. Safe null
    over a guess (#1).

    NOT FOLDING IS NOT A PROOF OF "DIFFERENT FILE". For a grouping (a duplicate the model can still read) it is the safe default;
    for any claim that says what is on disk it is UNKNOWN: the harness's cwd decides which absolute path an ambiguous relative
    spelling names, and cria cannot read it. The returned identity says so: ``identity.candidates(p)`` is the tuple of absolute
    keys an AMBIGUOUS relative spelling could name (empty for every spelling that resolved or has no rival). Callers that
    only group ignore it; callers that make a claim must not claim about any file in it."""
    absolute = sorted({p for p in paths if os.path.isabs(p)})
    out: dict[str, str] = {}
    rivals: dict[str, tuple] = {}
    for p in paths:
        if p in out:
            continue
        norm = os.path.normpath(p)
        if os.path.isabs(p):
            out[p] = norm
            continue
        tail = os.sep + norm.lstrip(os.sep)
        hits = [a for a in absolute if os.path.normpath(a).endswith(tail)]
        out[p] = os.path.normpath(hits[0]) if len(hits) == 1 else norm
        if len(hits) > 1:
            rivals[p] = tuple(sorted({os.path.normpath(a) for a in hits}))

    class _Identity:
        def __call__(self, p):
            return out.get(p, os.path.normpath(p))

        @staticmethod
        def candidates(p):
            return rivals.get(p, ())

    return _Identity()


def _failed_write_ids(messages: list[dict]) -> set[str]:
    """Correlated mutation failures, including native reports and owned refusals.

    Supersession must reject failed writes independently of whether soft-failure
    trimming ran first. Keep structural refusal handling even without a call;
    interpret native reports only with their actual write/edit operation.
    """
    calls = {tc.get("id"): tc.get("function") or {}
             for m in messages if isinstance(m, dict) and m.get("role") == "assistant"
             for tc in m.get("tool_calls") or []
             if shelltool.is_write_tool_name(str((tc.get("function") or {}).get("name") or ""))}
    ids: set[str] = set()
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "tool" or not _result_id(m):
            continue
        body = str(m.get("content") or "")
        fn = calls.get(_result_id(m))
        if (denial.unlanded(m)
                or (fn is not None and _is_failure(body, fn.get("name") or "",
                                                  arguments=fn.get("arguments"), landed=denial.landed(m)))):
            ids.add(_result_id(m))
    return ids


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


# `_write_path` LIVED HERE AND WAS THE FOURTH COPY of "which tool call writes, and to what". It had
# no caller — `_drop_superseded_writes` moved to `toolargs.write_target`, whose own comment records
# there having been "three implementations with three different tool-name lists (#23)" — and this
# one was left behind with a four-name list of its own.


# Below this a payload is not worth a pointer — the stub would be as long as the thing it replaces.
_STUB_MIN_CHARS = 400


def superseded_writes_truth(messages: list[dict]) -> list[dict]:
    """Settle producer-authenticated promises ONLY on the final surviving body.

    Reads and edits cannot stand in for a promised historical whole-write pair.
    The driver must run this after floor, argument and evidence transforms, before
    role concatenation. Removing selection cannot make an existing notice truthful.
    """
    notices = []
    for i, m in enumerate(messages):
        hint = m.get(bodykeys.SUPERSEDED_WRITES) if isinstance(m, dict) else None
        if (isinstance(hint, SupersededWriteNotice)
                and m.get("role") == "user" and m.get("content") == hint.text):
            notices.append((i, m, hint))
    if not notices:
        return messages
    answers = {_result_id(m): m for m in messages
               if isinstance(m, dict) and m.get("role") == "tool"}
    pairs = {superseded_pair_identity(tc, answers.get(tc.get("id")))
             for m in messages if isinstance(m, dict) and m.get("role") == "assistant"
             for tc in m.get("tool_calls") or [] if tc.get("id") in answers}
    out = None
    for i, m, hint in notices:
        missing = [path for path, call, answer in hint.replacements
                   if answer is None or (call, answer) not in pairs]
        if not missing:
            continue
        text = prompts.render("superseded_writes_unavailable", count=str(hint.count),
                              paths=prompts.named_list(hint.paths),
                              missing=prompts.named_list(missing))
        if out is None:
            out = list(messages)
        out[i] = {**m, "content": text}
    return out if out is not None else messages


@dataclass(frozen=True)
class FocusDefinition:
    policy: Policy
    # The existing supersession count is a call count, not a failure-run count.
    execute: Callable[[list[dict]], tuple[list[dict], TrimReport | int]]
    settle: Callable[[list[dict]], list[dict]] | None = None


@dataclass(frozen=True)
class FocusInput:
    messages: list[dict]


@dataclass(frozen=True)
class FocusResult:
    messages: list[dict]
    report: TrimReport
    effect: Effect
    applied_ids: tuple[str, ...] = ()
    # Producer notices remain in messages; no copied payload or global pending store.
    pending_settlement: tuple[SupersededWriteNotice, ...] = ()
    superseded_calls: int = 0
    stage_reports: tuple[tuple[str, TrimReport], ...] = ()


def focus(source: FocusInput, definitions: tuple[FocusDefinition, ...] | None = None) -> FocusResult:
    """Run selected focus decisions in declared order; empty selection is exact bypass.

    Replacement definitions use the same typed stage contract. Validation of IDs,
    levels and dependencies belongs to the shared runtime, not a second selector.
    """
    stages = FOCUS_STAGE if definitions is None else definitions
    messages = source.messages
    if not stages or not isinstance(messages, list):
        return FocusResult(messages, TrimReport(), Effect.NO_OP)
    total = TrimReport()
    applied = []
    superseded = 0
    stage_reports = []
    for definition in stages:
        out, report = definition.execute(messages)
        if isinstance(report, int):
            superseded += report
            report = TrimReport(squashed_runs=report)
        stage_reports.append((definition.policy.id, report))
        if report.applied:
            applied.append(definition.policy.id)
            messages = out
            total.dropped_calls += report.dropped_calls
            total.dropped_msgs += report.dropped_msgs
            total.squashed_runs += report.squashed_runs
    pending = (tuple(m[bodykeys.SUPERSEDED_WRITES] for m in messages
                     if isinstance(m, dict) and isinstance(m.get(bodykeys.SUPERSEDED_WRITES),
                                                         SupersededWriteNotice))
               if any(d.settle is not None for d in stages) else ())
    return FocusResult(messages, total, Effect.REDUCED if applied else Effect.NO_OP,
                       tuple(applied), pending, superseded, tuple(stage_reports))


DUPLICATES = FocusDefinition(
    Policy("focus-duplicate-pairs", "coder-focus", 3, family_id="F69",
           prompts=("trim_repeat_collapsed", "trim_repeat_collapsed_failed"),
           services=("paired-tool-history",),
           hooks=(Reference("cria/loop.py", "Loop._prepare_coder_context"),
                  Reference("cria/loop.py", "Loop._work_item"),
                  Reference("cria/loop.py", "Loop._drive_single_item"),
                  Reference("cria/server.py", "CriaHandler._focus_trim")),
           regressions=(Reference("tests/test_context_memory_migration.py", "test_focus_order_selection_and_replacement_are_real_execution"),
                        Reference("tests/test_context_memory_migration.py", "test_disabled_focus_does_not_scan_history"),
                        Reference("tests/test_context_memory_migration.py", "test_real_focus_keeps_different_outputs_mutations_and_hard_failures"),
                        Reference("tests/test_common_context_preparation.py", "test_absent_context_selection_never_runs_optional_leaf_detection")),
           migrated=False), _collapse_duplicates)
FAILURES = FocusDefinition(
    Policy("focus-soft-failure-history", "coder-focus", 3, family_id="F73",
           prompts=("work_log_denied",), services=("paired-tool-history",),
           hooks=(Reference("cria/loop.py", "Loop._prepare_coder_context"),
                  Reference("cria/loop.py", "Loop._work_item"),
                  Reference("cria/loop.py", "Loop._drive_single_item"),
                  Reference("cria/server.py", "CriaHandler._focus_trim")),
           regressions=(Reference("tests/test_context_memory_migration.py", "test_focus_order_selection_and_replacement_are_real_execution"),
                        Reference("tests/test_context_memory_migration.py", "test_disabled_focus_does_not_scan_history"),
                        Reference("tests/test_focustrim.py", "ErrorSquashTests.test_squashes_a_run_of_distinct_failures_keeping_recent"),
                        Reference("tests/test_focustrim.py", "HardFailKeptTests.test_hard_failures_are_never_squashed"),
                        Reference("tests/test_common_context_preparation.py", "test_absent_context_selection_never_runs_optional_leaf_detection")),
           migrated=False), _squash_failures)
SUPERSESSION = FocusDefinition(
    Policy("superseded-write-history", "coder-focus", 3, family_id="F73",
           prompts=("superseded_writes_dropped", "superseded_writes_unavailable"),
           state="producer notice in framed messages; settle exact pairs at final wire; no durable state",
           services=("paired-tool-history", "final-surviving-messages"),
           hooks=(Reference("cria/loop.py", "Loop._prepare_coder_context"),
                  Reference("cria/loop.py", "Loop._work_item"),
                  Reference("cria/loop.py", "Loop._drive_single_item"),
                  Reference("cria/server.py", "CriaHandler._focus_trim"),
                  Reference("cria/upstream.py", "Upstream._prep")),
           regressions=(Reference("tests/test_context_memory_migration.py", "test_supersession_producer_and_final_settlement_have_one_definition"),
                        Reference("tests/test_c21_superseded_preservation_wire.py", "test_real_floor_pressure_qualifies_the_missing_write_not_the_later_source"),
                        Reference("tests/test_c21_superseded_preservation_wire.py", "test_refused_newest_never_displaces_landed_content_or_rejected_bytes"),
                        Reference("tests/test_common_context_preparation.py", "test_absent_context_selection_never_runs_optional_leaf_detection")),
           migrated=False),
    _drop_superseded_writes, superseded_writes_truth)
# One order shared by the whole-stage compatibility API and the typed entry.
FOCUS_STAGE = (DUPLICATES, FAILURES, SUPERSESSION)


def settle_focus(source: FocusInput,
                 definitions: tuple[FocusDefinition, ...] | None = None) -> MessageEffect:
    """Settle selected producer obligations at Upstream._prep, never before fit.

    Use the same task-stable selection that produced the view. Selection cannot
    change while notices are pending. This only qualifies claims; it does not
    restore removed writes or infer landed state from replacement prose.
    """
    messages = source.messages
    count = 0
    for definition in FOCUS_STAGE if definitions is None else definitions:
        if definition.settle is None:
            continue
        out = definition.settle(messages)
        if out is not messages and out != messages:
            count += 1
            messages = out
    return MessageEffect(messages, Effect.SETTLED if count else Effect.NO_OP, count)


def trim(messages: list[dict]) -> tuple[list[dict], TrimReport]:
    """Legacy whole-stage API; drivers can migrate to focus() without changing bytes.

    Preserve historical aggregate counters; the typed API also exposes superseded
    call counts independently rather than hiding ownership in a failure-run tally.
    """
    result = focus(FocusInput(messages))
    # The legacy aggregate excludes duplicate-repeat notices from squashed_runs;
    # preserve it exactly. Typed consumers can read each authoritative stage's
    # report rather than reconstructing counts from the rendered note.
    duplicate_notices = sum(report.squashed_runs for ident, report in result.stage_reports
                            if ident == DUPLICATES.policy.id)
    return result.messages, TrimReport(result.report.dropped_calls, result.report.dropped_msgs,
                                      result.report.squashed_runs - duplicate_notices)
