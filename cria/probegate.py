"""The completion gate's transport: compose ONE shell script the HARNESS runs, then
re-interpret its output through the ported probe modules — cria owns no executors.

The gate is CONGRUENT across ecosystems (operator direction): there is no privileged
per-language floor anymore. ``proberun.select_completion_probes`` returns one ranked
candidate list — tier-0 parse/compile checks for every language present (compileall,
node --check, php -l, ruby -c by file presence; cargo check / go build / tsc /
mvn-gradle compile / dotnet build / mix compile via their ecosystems' tier≤1
candidates) plus the top-ranked probe and the top TEST probe. This module:

* :func:`plan_gate` — select the candidates (READ-ONLY workspace inspection) and
  compose one marker-delimited script: each candidate via
  :func:`cria.proberun.compose_probe_command` (timeout-bounded, output-capped,
  EXIT-sentineled), plus a ``git status`` snapshot for the changed-files signal. The
  plan REMEMBERS what it composed so interpretation doesn't re-inspect a
  possibly-changed world.
* :func:`interpret_gate` — split the harness's result into sections and map each onto
  the upstream ProbeResult contract (:func:`cria.proberun.interpret_probe_output`):
  timeout → 124, launch failure → 127/"command not found", findings via the per-tool
  parsers (tier-0 checks included — every ecosystem's parse floor yields file:line).

A result with NO section markers means the script never ran (harness declined,
old-format response, tool error): ``GateOutcome.ran`` is False and the caller keeps
the pre-existing don't-wedge semantics instead of inventing a verdict.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from dataclasses import dataclass, field

from . import dirguard, dedup, jsontext
from . import probediscovery, probeparse, prompts, proberun

# Leading ``path:line[:col][:]`` location prefix a linter prints before the diagnostic. Stripping it
# lets probeparse.is_advisory's ANCHORED style-code check (``^W###``/``E###``…) fire on a raw gate
# line — its phrase check is substring so it already works either way.
_LOC_PREFIX = re.compile(r"^\S.*?:\d+(?::\d+)?:?\s+")

from .proberun import ProbeReport
# runner_tally lives in probeparse now (it parses runner OUTPUT, and the tally must be taken at
# parse time while the raw text still exists). Re-exported so existing callers are unmoved.
from .probeparse import COMPILES_FIRST, runner_and_tally, runner_tally  # noqa: F401

# Marker line delimiting each section of the composed script's output. The id after the
# prefix names the section ("probe-0", "git"). Chosen to never collide with tool output.
SECTION_PREFIX = "___CRIA_GATE_"
SECTION_SUFFIX = "___"
# Section carrying the untracked paths the probes themselves created — cria's own litter, listed by the
# harness's shell and removed by :func:`sweep_litter` on cria's side. A signal for cria, never the model.
LITTER_SECTION = "litter"
# Per-probe wall-clock bound. Was 45 s (codex-local's COMPLETION_PROBE_TIMEOUT), which is fine for a
# syntax floor and far too short for what this gate actually selects: a full test suite, a cold
# `cargo check`, a `tsc` build. That is not merely a slow gate — `completion_block_nudge` fails CLOSED
# on a timed-out hard-failure probe, so a repo whose tests take a minute is permanently
# un-completable: every round re-nudges with "TIMEOUT after 45s" and no edit can ever clear it.
COMPLETION_PROBE_TIMEOUT_S = 240.0


@dataclass
class GatePlan:
    """Everything :func:`interpret_gate` needs to replay the output faithfully."""

    workspace: str
    script: str = ""
    candidates: list = field(default_factory=list)  # selected ProbeCandidates, in section order
    # Test-naming conventions cria searched by and found nothing for (probediscovery.undiscoverable_tests).
    # Computed with the selection, so the clean-gate render reads a fact instead of re-walking the tree.
    untested: list = field(default_factory=list)
    # The subdirectory every real probe had to be run in, when NONE of them could run at the
    # workspace root — "" in the ordinary case. See :func:`_checks_ran_elsewhere`.
    ran_in: str = ""
    # cria-facing observations about the PLAN itself (not about the repo) — currently only the
    # shared-budget floor. Never shown to the model; it is a note for the log and the operator.
    notes: list = field(default_factory=list)


@dataclass
class GateOutcome:
    ran: bool = False  # False → no markers came back; keep don't-wedge semantics
    report: ProbeReport | None = None
    git_state: str = ""  # `git status --porcelain | sha1sum` — changed-files signal
    unran: list = field(default_factory=list)  # selected checks whose section never came back — a GAP,
    #                                            not a pass: without this, a truncated gate read clean
    refused: str = ""  # the harness REFUSED to run the gate (sandbox policy) — its own words, for the log
    swept: list = field(default_factory=list)  # untracked paths the probes created, removed by sweep_litter


def _marker(section_id: str) -> str:
    return f"{SECTION_PREFIX}{section_id}{SECTION_SUFFIX}"


def _checks_ran_elsewhere(workspace: str, candidates: list) -> str:
    """The ONE subdirectory every real check had to run in, or "" — a fact straight off the plan.

    Cycle 4 cell 6, rust-toml-cli x gemma4, a from-scratch task: the model ran `cargo new toml-cli`
    and built a complete, working Rust project inside `toml-cli/`. cria's own gate cd'd into that
    folder for four of its five probes, they all passed, the gate went GREEN, the completion critic
    approved and the session exited normally. The verifier runs `cargo` at the working directory and
    found no `Cargo.toml`: **0 of 4**, on a cell that had scored 4/4 for three cycles running.

    cria was holding the fact the whole time — `working_dir=toml-cli` on every probe it composed —
    and never said it. This is not a judgement about layout (a monorepo puts manifests in
    subdirectories on purpose and is right to); it is the plan read back. It fires only when NO real
    check could run at the root, which is the case where the directory the harness handed the model
    contains no buildable project at all.

    The syntax floor is excluded: it walks files and always runs at the root, so counting it would
    make this permanently silent."""
    if not (workspace or "").strip():
        return ""            # `abspath("")` is the CWD, which would report cria's own directory
    root = os.path.abspath(workspace)
    dirs = set()
    for c in candidates:
        if c.kind is probediscovery.ProbeKind.SyntaxCheck:
            continue                       # walks the tree from the root by construction
        d = os.path.abspath(str(getattr(c, "working_dir", "") or root))
        dirs.add(os.path.relpath(d, root))
    if not dirs or "." in dirs or len(dirs) != 1:
        return ""                          # something ran at the root, or they disagree → say nothing
    where = dirs.pop()
    # A path that climbs OUT of the workspace is not a subdirectory of it, and naming it would point
    # the coder somewhere it is not working.
    return "" if where.startswith("..") or os.path.isabs(where) else where


def plan_gate(workspace: str) -> GatePlan:
    """Inspect the workspace read-only and compose the gate script.

    Selection is re-run on EVERY gate (like upstream's ``discover`` per gate run):
    the repo's shape changes as the coder works — a pyproject.toml written in step 2
    must make pytest discoverable by step 3's gate.

    ``workspace`` empty → a MINIMAL gate (git snapshot only, no cd): cria couldn't learn
    the workspace path, so it must not discover against its OWN cwd (that once composed a
    probe over cria's repo itself). The harness's shell already runs in the workspace, so
    the git leg still lands; the checks just abstain (digest says none ran)."""
    plan = GatePlan(workspace=workspace)
    if workspace:
        plan.candidates = proberun.select_completion_probes(workspace)
        plan.untested = probediscovery.undiscoverable_tests(workspace)
        # …and the other half of the same question. `undiscoverable_tests` reports test files a
        # runner will NOT see; this reports test files a runner WOULD see in a project where no test
        # command was composed at all. Both end in the same clean-branch qualifier, because the coder
        # needs the same thing from either: to know that a green gate ran no tests.
        if not any(c.kind is probediscovery.ProbeKind.Test for c in plan.candidates):
            plan.untested += probediscovery.tests_with_no_command(workspace)
        plan.ran_in = _checks_ran_elsewhere(workspace, plan.candidates)

    parts: list[str] = [f"cd {shlex.quote(workspace)} || exit 97"] if workspace else []
    # THE GATE MUST NOT LEAVE STATE BEHIND. It runs the repo's own tests in the LIVE workspace, and a
    # test that writes — a database file, a fixture, an output artifact — leaves that behind for the
    # next gate to trip over. cria then reports a failure it manufactured itself, under the strongest
    # header it has. Measured on the six-language battery: a leftover orders.db from one gate run
    # made the next run's schema assertions fail, and the coder was sent to debug cria's litter.
    #
    # Principle 7 already says cria never pollutes the user's workspace; running tests there is the
    # one place it did. The fix is bounded and needs no per-language knowledge: record the untracked
    # files before the probes, and remove exactly the ones that appeared during them. Tracked files
    # are never touched, and with no git the whole thing abstains rather than guessing.
    #
    # The REMOVAL happens on cria's side (:func:`sweep_litter`), not in this script. A `rm` here is
    # not merely inelegant — the Codex sandbox HARD-REJECTS the whole exec ("rm -f style commands are
    # not permitted"), so an `rm` in the cleanup killed EVERY gate in EVERY language, and the gate
    # abstained silently because a rejected exec returns no probe sections. writeproxy.py:801 records
    # the same sandbox rejection breaking every web_search. cria composes read-only shell; when
    # something must be deleted, cria deletes it itself, under the dirguard's bounds.
    if workspace:
        parts.append("__cria_pre=$(git status --porcelain 2>/dev/null | sed -n 's/^?? //p' | sort)")
    # ONE RESULT, SHARED BUDGET. Every probe below writes into the same shell result, and the bound
    # that decides whether the model ever sees it is applied to that whole result — so the per-probe
    # cap has to be this plan's share of it, not a constant. When each probe carried the full
    # whole-result budget the gate reliably overran and was discarded, and cria then read its own
    # refusal as the probe output. See proberun.probe_output_budget.
    section_cap, fits = proberun.probe_output_budget(len(plan.candidates))
    if not fits:
        # Say it rather than starve the sections silently (#5b): the plan is asking one result to
        # carry more than it can, and a reader of the log should see that, not a mysteriously
        # clipped check.
        plan.notes.append(f"gate plan has {len(plan.candidates)} probes sharing one result; "
                          f"each section floored at {section_cap} bytes")
    for i, c in enumerate(plan.candidates):
        parts.append(f"echo {_marker(f'probe-{i}')}")
        parts.append(proberun.compose_probe_command(c, COMPLETION_PROBE_TIMEOUT_S, cap=section_cap))
        if c.kind is probediscovery.ProbeKind.Test:
            # Remember THIS probe's exit code for the offline leg below. compose_probe_command
            # leaves it in __cria_ec, which the next probe overwrites, so it is captured here under
            # a name of its own.
            parts.append("__cria_test_ec=$__cria_ec")
    # The OFFLINE re-run of the test probe — see proberun.offline_probe_command.
    # Emitted last among the probes so a failure here can never mask a real check result.
    test_c = next((c for c in plan.candidates
                   if c.kind is probediscovery.ProbeKind.Test), None)
    offline = proberun.offline_probe_command(test_c, COMPLETION_PROBE_TIMEOUT_S) if test_c else ""
    if offline:
        parts.append(f"echo {_marker('offline')}")
        parts.append(offline)
    if workspace:
        # Exactly what the probes created, LISTED for cria to remove. The files present now that were
        # not present before; anything git tracks never appears in this list at all.
        parts.append(f"echo {_marker(LITTER_SECTION)}")
        parts.append("__cria_post=$(git status --porcelain 2>/dev/null | sed -n 's/^?? //p' | sort)")
        # POSIX sh only — no process substitution. The harness's shell is not guaranteed to be bash,
        # and a bashism here would fail silently and leave the litter behind.
        parts.append('if [ -z "$__cria_pre" ]; then __cria_new=$__cria_post; '
                     'else __cria_new=$(printf \'%s\\n\' "$__cria_post" | grep -vxF "$__cria_pre"); fi')
        parts.append('printf \'%s\\n\' "$__cria_new"')
    parts.append(f"echo {_marker('git')}")
    # Changed-files signal: one line summarizing the working tree (porcelain is stable);
    # hashing keeps it tiny and diffable across gate runs. Absent git → empty (no signal).
    parts.append("git status --porcelain 2>/dev/null | sha1sum 2>/dev/null | cut -d' ' -f1")
    plan.script = "\n".join(parts)
    return plan


def split_sections(text: str) -> dict[str, str]:
    """Marker-delimited output → {section_id: body}. Unknown text before the first
    marker is ignored (harness banners etc.)."""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(SECTION_PREFIX) and stripped.endswith(SECTION_SUFFIX):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = stripped[len(SECTION_PREFIX):-len(SECTION_SUFFIX)]
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


_DELIM_PAIRS = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}
_UNMATCHED_RE = re.compile(r"^(.+?):(\d+):.*?\bunmatched\b.*?['\"]([()\[\]{}])")
# Any finding that NAMES a position: `path:LINE[:COL]: …` (pyflakes/compileall style) or
# `path: … (at line LINE, column COL)` (tomllib style).
_FLAGGED_LINE_RE = re.compile(r"^(.+?):(\d+)(?::\d+)?:")
_AT_LINE_RE = re.compile(r"^(.+?): .*\(at line (\d+), column \d+\)")


def _paths_written_after(messages: list, start: int) -> "frozenset[str]":
    """Basenames of files a LANDED write/edit touched in messages after ``start``.

    The newest gate result is re-annotated at every prompt build, and "the flagged line on disk" is
    read at render time — so a check that ran before an edit gets stamped with the post-edit line.
    Walked on mellum2 1786196176 (0036/0045/0054): pyflakes said line 42 col 61 has `requests`;
    cria's own quote of disk line 42 showed a line with no `requests` — a self-contradictory anchor,
    three times, because the file moved under the still-newest gate. The write ledger in the same
    message list says exactly which files moved; their findings keep the checker's line, unquoted."""
    from cria import selfcompact
    calls: dict = {}
    changed = set()
    for m in messages[start + 1:]:
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") in ("write_file", "edit_file"):
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    continue
                path = str((args or {}).get("path") or (args or {}).get("file_path") or "")
                if path and tc.get("id"):
                    calls[tc["id"]] = os.path.basename(path)
        if m.get("role") == "tool" or m.get("type") == "function_call_output":
            tid = m.get("tool_call_id") or m.get("call_id")
            c = m.get("content") if m.get("content") is not None else m.get("output")
            if tid in calls and isinstance(c, str) and selfcompact.write_landed(c):
                changed.add(calls[tid])
    return frozenset(changed)


def _with_delimiter_facts(findings: list[str], plan, annotate: bool = True,
                          changed_paths: "frozenset[str]" = frozenset()) -> list[str]:
    """For an unmatched-delimiter finding, append ONE counted fact: the flagged line's actual
    on-disk bytes plus how many openers and closers it holds. Code counts, the model applies —
    a small model provably cannot (run 0729-gemma4: 137 calls failing to remove one ')', its own
    steer author miscounting too). The fact PRESCRIBES NOTHING (operator: cria cannot know whether
    the fix is deleting the extra closer or adding a missing opener). When the flagged line's
    counts BALANCE, the imbalance lives on another line — a single-line count would mislead, so
    stay silent (state the fact or be silent)."""
    import os
    from pathlib import Path
    out: list[str] = []
    workspace = getattr(plan, "workspace", "") or ""
    for f in findings:
        out.append(f)
        if not workspace:
            continue
        m = _UNMATCHED_RE.match(f)
        if m:
            path, line_no, d = m.group(1), int(m.group(2)), m.group(3)
            p = Path(path) if os.path.isabs(path) else Path(workspace) / path
            try:
                line = p.read_text(errors="replace").splitlines()[line_no - 1]
            except (OSError, IndexError):
                continue
            opener = d if d in "([{" else _DELIM_PAIRS[d]
            closer = _DELIM_PAIRS[opener]
            n_open, n_close = line.count(opener), line.count(closer)
            if n_open == n_close:
                continue
            out.append(f"  counted fact: line {line_no} on disk is `{line.strip()}` — it contains "
                       f"{n_open} '{opener}' and {n_close} '{closer}'.")
            continue
        # GENERAL case (walked on run 1785904860, ~call 0045): a finding that names a POSITION
        # without quoting the line invites the model to GUESS the line's text — the checker said
        # `pyproject.toml: Invalid value (at line 20, column 9)` and the model edited against an
        # invented `build-backend = "python3"` that was never on disk or in context. Quote the
        # flagged line's real bytes. Same contract as the counted fact: state the fact or be
        # silent (missing file/line → silent; line already quoted in the finding → silent),
        # and PRESCRIBE NOTHING.
        if not annotate:
            continue        # HISTORY — see clean_gate_results; the quote would be read from a
                            # file that has moved on since these findings were produced.
        m = _FLAGGED_LINE_RE.match(f) or _AT_LINE_RE.match(f)
        if not m:
            continue
        path, line_no = m.group(1), int(m.group(2))
        if os.path.basename(path) in changed_paths:
            continue        # the file moved since this check ran — quoting today's line under
                            # yesterday's finding manufactures the contradiction; the finding stands
        p = Path(path) if os.path.isabs(path) else Path(workspace) / path
        # ONLY inside the workspace. An absolute finding can name a stdlib frame
        # (/usr/lib/python3.12/unittest/mock.py:956 in a pytest traceback), and quoting it back
        # presents CPython internals as "a line the repo's own checks flagged" — under a header
        # telling the coder to fix what each one names. Walked: ~10 such annotations per checks
        # block, each duplicating the traceback line printed directly beneath it.
        try:
            if workspace and not p.resolve().is_relative_to(Path(workspace).resolve()):
                continue
        except (OSError, ValueError):
            continue
        try:
            line = p.read_text(errors="replace").splitlines()[line_no - 1]
        except (OSError, IndexError):
            continue
        text = line.strip()
        if not text or text in f:      # nothing to quote, or the finding already shows it
            continue
        if _EXCEPTION_FINDING.search(f):
            # A RAISE SITE IS NOT A DEFECT SITE. This annotation is correct for a LINTER, where the
            # flagged line IS the problem, and actively misleading for a runtime exception, where it
            # is merely where the program stopped — the cause is upstream, in the value that reached
            # it. Under a header ordering the coder to "resolve exactly what it names", quoting the
            # raise site points at the one line that is usually fine. Measured on the six-language
            # battery: the coder rewrote the assertion line repeatedly while the bad value came from
            # a default argument three functions away. cria cannot justify the pointer, so it does
            # not make it (#5b, and #3 — silence over noise).
            continue
        out.append(f"  the flagged line on disk — line {line_no}: `{text[:200]}`")
    return out


# A finding produced by a program CRASHING rather than by a checker inspecting code. Matched on the
# shapes runtimes actually print — an exception class name, a traceback frame, an assertion report —
# not on one language's phrasing.
_EXCEPTION_FINDING = re.compile(
    r"(?im)^\s*(?:Traceback|Exception in thread|goroutine \d+)|\bpanic:"
    r"|\b[A-Z]\w*(?:Error|Exception)\b"
    r"|\bassertion failed\b|\bAssertionError\b|\bpanicked at\b"
    r"|\bat [\w.$]+\([\w.]+\.(?:java|kt|scala):\d+\)")


def _line_on_disk(finding: str, workspace: str) -> "str | None":
    """The on-disk text of the line a ``path:LINE…`` finding flags, or None. Feeds probeparse's
    F811 discriminator (def/class shadow = real bug; import rebinding = advisory) — the file
    access the pure predicate can't do itself."""
    import os
    from pathlib import Path
    m = _FLAGGED_LINE_RE.match(finding)
    if not m or not workspace:
        return None
    path, line_no = m.group(1), int(m.group(2))
    p = Path(path) if os.path.isabs(path) else Path(workspace) / path
    try:
        return p.read_text(errors="replace").splitlines()[line_no - 1]
    except (OSError, IndexError):
        return None


def _is_hard_failure(plan, sid: str) -> bool:
    """Is section ``sid`` a probe whose non-zero exit is a REAL failure regardless of how its output
    looks? Test / typecheck / build — `plan.candidates` is in section order, so probe-N is candidate N.
    Unknown plan or unparseable id → False (keep the advisory-clean lint behaviour)."""
    # `kind` is a FIELD, not a method. Calling it raised TypeError on every probe, and TypeError was
    # in this function's own `except`, so it swallowed its own defect and returned False forever —
    # proved by executing it: a Test candidate, whose kind IS in _HARD_FAILURE_KINDS, answered False.
    #
    # What that turned off: the branch that reports a non-zero exit as a real failure REGARDLESS of
    # how its output looks. With it dead, a build that fails only on warnings-shaped output — a
    # `-Werror` compile, `#![deny(warnings)]`, `noUnusedLocals` — was summarised to the model as
    # clean, which is the fail-open on missing ground truth (#13) this file exists to prevent.
    #
    # It hid because a DIFFERENT function of the same name in focustrim.py is tested and correct, so
    # the name looked covered.
    #
    # TypeError is deliberately no longer caught: nothing here legitimately raises it, and catching it
    # is what let the bug live.
    try:
        idx = int(sid.split("-", 1)[1])
        kind = plan.candidates[idx].kind
    except (AttributeError, IndexError, ValueError):
        return False
    return kind in proberun._HARD_FAILURE_KINDS


def clean_gate_output(raw: str, plan: "GatePlan | None" = None, *, annotate: bool = True,
                      changed_paths: "frozenset[str]" = frozenset()) -> str | None:
    """A raw gate-probe RESULT → a compact, error-class-only summary for the MODEL to read.

    The raw result is cria's internal gate protocol wrapped in the harness's exec noise:
    ``___CRIA_GATE_probe-N___`` section markers, ``EXIT:<n>`` sentinels, a git-hash section, and a
    ``Chunk ID / Process exited / …`` wrapper. Shown verbatim (and PROTECTED from trimming) it buried
    the one real error under plumbing AND leaked advisory lint (``imported but unused``) the model then
    chased — even though the gate DIGEST already filters those. This strips all of it and, keying on the
    RELIABLE per-section EXIT code (not fragile text sniffing), reports one honest state: error-class
    findings; a check that FAILED with no parseable location; checks that could NOT run (launch failure
    / timeout — cria's own setup gap, a neutral non-signal, never a pass); or the checks that ran found
    nothing (framed "no error-class problems", explicitly NOT "done"). Returns ``None`` when ``raw`` is
    not a gate result (untouched)."""
    if SECTION_PREFIX not in (raw or ""):
        return None
    workspace = getattr(plan, "workspace", "") or ""
    stranded_findings: list[str] | None = None   # scanned at most once, only on a zero-tests signal
    findings: list[str] = []
    seen: set[str] = set()
    could_not_run = False
    failed_no_detail = False
    saw_probe = False
    timed_out_output: list[str] = []
    _sections = split_sections(raw)
    for sid, body in _sections.items():
        if sid in ("git", LITTER_SECTION):  # cria's own bookkeeping — signal for cria, noise for the model
            continue
        # The offline re-run is an INSTRUMENT READING, not a check. It is the same suite with the
        # network taken away, so on a genuinely live suite it is SUPPOSED to fail — and this loop
        # would have scraped that failure into the findings and told the coder to go fix passing
        # tests (the false-red class, from the very leg built to expose a false green). Its exit
        # code reaches exactly one reader: _offline_fact. Skipping it also keeps a namespace-less
        # box honest — an empty section can no longer set could_not_run and wedge the whole gate.
        if sid == "offline":
            continue
        saw_probe = True
        text, code = proberun.scrape_exit(body)
        # The EXIT sentinel is the reliable signal (the composed probe always prints it). A launch
        # failure (125/126/127) or timeout (124) means the check did NOT complete — never a code error
        # to "fix", never a pass. Sniffing text for "no such file" would misread a real error that just
        # mentions it (a FileNotFoundError, a missing #include) as couldn't-run.
        if code in proberun.LAUNCH_FAILURE_EXIT_CODES:
            could_not_run = True    # never launched → there is nothing it could have printed
            continue
        if code is None:
            # The section header arrived but its EXIT sentinel never did: the HARNESS returned (its
            # yield window / output cap) while the check was still running — observed live: a 10s
            # exec yield cut the composed gate mid-pytest ("Process running with session ID …"), and
            # this section previously contributed NOTHING, so a lint-green gate read CLEAN while the
            # tests never finished (the vacuous-green shape). A missing sentinel can ONLY mean a cut
            # stream — the script echoes EXIT:$? unconditionally, so even a missing tool prints 127.
            # Same treatment as a timeout: never a pass, partial output kept as context not findings.
            could_not_run = True
            if text.strip():
                timed_out_output.append(text.strip())
            continue
        if code == proberun.TIMEOUT_EXIT_CODE:
            # A timeout is NOT a launch failure: the command RAN and may already have printed the real
            # error before it stalled. The state stays "couldn't run" (never a pass, and its lines must
            # NOT be scraped as error-class findings — post-timeout output is mostly noise, the false-red
            # class), but what it DID print is kept as CONTEXT rather than discarded.
            could_not_run = True
            if text.strip():
                timed_out_output.append(text.strip())
            continue
        # pytest exit 5 = no tests collected (a fresh/testless project). The runner ran fine and had
        # nothing to assess — a benign non-signal. Skip the section so its "no tests ran" line isn't
        # scraped as an error-class finding AND it doesn't set failed_no_detail; the OTHER probes that
        # ran decide the gate's verdict. saw_probe stays True, so a pytest-only gate reads clean-ish
        # ("checks that ran reported no problems"), never "one of the checks FAILED".
        #
        # UNLESS the disk says otherwise. Measured on maple run 2 (1785973706): a 19KB pytest suite
        # named `pytest_da_resolvers.py` — a name pytest's pattern cannot collect — so "no tests ran"
        # for the run's final 30 minutes while real tests sat on disk, and the benign rule kept the
        # gate silent. Same discriminator shape as F811: keep the benign default, read the disk to
        # tell the testless project from the mis-named suite; a stranded test file is a stated,
        # checkable, error-class fact (the files, the runner, its naming rule). The detector is the
        # ONE existing owner (probediscovery's convention table — the g20 mechanism), not a second
        # scanner. Also applied to a PASSING test section whose runner said it collected nothing
        # (go's "[no test files]" exits 0) — a green built on zero tests plus a stranded suite is
        # the same false green.
        if proberun.is_no_tests_collected(code, output=text) or \
                (code == 0 and _zero_tests_marker(text)):
            if stranded_findings is None:
                stranded_findings = probediscovery.stranded_test_sentences(workspace) \
                    if workspace else []
            if stranded_findings:
                findings.extend(f for f in stranded_findings if f not in seen)
                seen.update(stranded_findings)
            continue
        # A check that PASSED (exit 0) has, by definition, no error-class problem — its stdout is NOT a
        # diagnosis. Linters/typecheckers print nothing on success, but pytest prints "…. [100%]\nN
        # passed", go test prints "ok", etc. — and the raw-line scraper below would harvest those as
        # "findings" and hand the model "fix them at the reported line: 4 passed" (a false-red that told
        # the model to fix a GREEN suite ~20 times). Skip a passing section entirely; the exit code is
        # the reliable signal (kept: a None code — sentinel lost, unknown — still gets scraped, never
        # silently swallowed).
        if code == 0:
            continue
        had_content = False
        section_findings: list[str] = []
        prev_kept = ""   # consecutive-repeat collapse only — see the note at the append below
        for ln in text.splitlines():
            s = ln.strip()
            if not s or s.startswith(proberun.PROBE_EXIT_SENTINEL):   # blank / EXIT:<n> sentinel
                continue
            had_content = True
            # advisory either as a whole line (phrase/prefix forms) or once the location prefix is
            # stripped (bare style code like `foo.py:80:1: E501 …`) — unused-import / style, filtered.
            # For an F811 redefinition the flagged line on disk is the discriminator (def/class
            # shadow = real bug, kept; import rebinding = cleanliness, dropped) — only F811 pays
            # the disk read.
            flagged = (_line_on_disk(s, workspace)
                       if probeparse.F811_PHRASE in s.lower() else None)
            if (probeparse.is_advisory(s, flagged)
                    or probeparse.is_advisory(_LOC_PREFIX.sub("", s), flagged)):
                continue
            # KEEP THE LINE AS THE CHECKER WROTE IT. `s` is the stripped copy — fine for deciding
            # whether to keep a line, wrong to SHIP, because cria ships this block under "each is the
            # checker's OWN message". De-indenting and globally de-duplicating destroys the source
            # echo in a traceback: pytest prints the failing function's body, and a `}` or `)` on its
            # own line is both indentation-bearing AND a repeat of one seen earlier, so it is deleted
            # twice over.
            #
            # Walked on ada-handles_fabliq_codex_pon_1785721353. A reader fed the real pytest output
            # through this function and reproduced cria's exact call-0185 bytes, including:
            #
            #     'total_handles': total_handles
            # except requests.exceptions.RequestException as e:      <- the closing } is GONE
            #
            # The file parses cleanly; `compileall` exited 0 in that same gate. cria manufactured
            # "handle_resolver.py has a syntax error — missing a closing parenthesis", restated it in
            # every prompt for 45 straight calls, and the coder copied the DE-INDENTED text into
            # edit_file old_strings that could never match. Two earlier walks named this their top
            # fix. Dedupe on the stripped form; emit the original.
            #
            # CONSECUTIVE-ONLY, not global — the same walk family, one organ deeper. A GLOBAL `seen`
            # deletes a line because an IDENTICAL line appeared in a DIFFERENT failure block, and two
            # failures that share an assertion are not duplicates: they are two facts. Walked on
            # ada-handles_nemotron-elastic_codex_pon_1785360304 calls 0152/0153/0155, where pytest
            # reported two failing tests whose bodies share `self.assertIsNotNone(result[...])` and
            # `E  AssertionError: unexpectedly None`. Both lines were printed for test_goose and
            # therefore DELETED from test_papagoose, so the coder was handed
            # `test_resolve_handle.py:24: AssertionError` with no assertion and no reason under a
            # header promising "each is the checker's OWN message". The same global rule also ate a
            # docstring's closing `\"\"\"`. Collapsing a line repeated back-to-back is still worth
            # doing (that is the spam this was built for); collapsing across blocks is data loss.
            if s != prev_kept:
                prev_kept = s
                section_findings.append(ln.rstrip())
        findings.extend(section_findings)
        # a check that exited NON-ZERO but printed NOTHING usable (empty output) still FAILED — don't
        # let it read as clean. If it printed only advisory lines (had_content, no findings), that's an
        # advisory-clean lint exit, NOT a failure — so keying on had_content avoids the footgun.
        if code not in (0, None) and not had_content:
            failed_no_detail = True
        # A non-zero exit whose output is ALL advisory-shaped is an advisory-clean LINT exit (don't send
        # the model chasing style) — but for a TEST/TYPECHECK/BUILD probe it is a real failure whose
        # diagnostics merely look advisory: -Werror, deny(warnings), tsc noUnusedLocals. Reporting that
        # as "no error-class problems" is a false green on a build that did not build. The probe KIND is
        # the grounded distinction, and it is in the plan cria already holds.
        elif code not in (0, None) and not section_findings and _is_hard_failure(plan, sid):
            failed_no_detail = True
    if not saw_probe:               # git-only gate (empty/no-code repo) → NO check ran → not a pass
        could_not_run = True
    findings = _with_delimiter_facts(findings, plan, annotate, changed_paths)
    if findings:                    # a check RAN and found a real error-class problem — foreground it
        # Show EVERY error-class finding — a 40-line clip once hid findings 41+, so the model "fixed"
        # what it saw and claimed done while real errors remained invisible. The context floor
        # (contextfloor.fit) is the one window-aware place a truncation may happen, and only when the
        # physical window forces it — never a blind per-site clip here.
        # NOT "the smallest change that clears it". When the failure is a real defect, the smallest
        # change that CLEARS it is to stop the check asking. Walked on
        # ada-handles_mellum2_codex_poff_1785714194: at 0029 pytest reported `AssertionError: 0 not
        # greater than 0` — a true signal that the deliverable was wrong — and the coder rewrote its
        # own assertion to `assertEqual(result["total_handles"], 0)`. The test then certified the bug
        # and the run shipped green. The phrase landed twice in that one run.
        return ("⟦ctx:checks⟧ the repo's own checks report these error-class problems — each is the "
                "checker's OWN message and the line it flagged; resolve what each one names with the "
                "smallest change that makes it actually work. If a test failed, fix what the test "
                "caught — changing the test so it stops asking is not a fix:\n" + "\n".join(findings))
    if failed_no_detail:            # ran, exited non-zero, no usable output → a failure with no location
        return ("⟦ctx:checks⟧ one of the repo's own checks FAILED but printed no parseable location — "
                "run it yourself and read the actual error before continuing. Not done.")
    if could_not_run and timed_out_output:
        # It ran, stalled, and printed something first — hand that over verbatim, labelled for what it
        # is, instead of only "no signal either way".
        return (CHECKS_MARKER + " a check did not finish (timed out) — no verdict either way. It printed "
                "this before it was stopped:\n" + "\n".join(timed_out_output))
    if could_not_run:               # couldn't launch/timed out → cria's own setup gap; stay neutral
        # NOT a pass (never claim clean), NOT a fix request (the model can't fix cria's absent tool),
        # NOT a specific confession — just a non-actionable placeholder so the model relies on itself.
        return "⟦ctx:checks⟧ the automatic checks produced no usable result — no signal either way."
    # Report the clean result as a FACT — no "but this doesn't mean it's correct / doesn't mean done"
    # hedge. That caveat is unactionable doubt (it names nothing to fix) and a weak model latches onto
    # it and spirals; completion is guarded by the actual gate + satisfaction check, not by nagging the
    # coder that a green check might still be wrong. (Operator directive, twice.)
    clean = "⟦ctx:checks⟧ the repo's own checks that ran reported no error-class problems."
    # ...but "the checks reported no problems" is half a sentence when NO test ran. g20 (gemma4,
    # ada-handles) returned exactly this line fifty-four times over a project whose unittest classes
    # sat inside resolve_handle.py — unmatched by any naming convention, so no test probe was ever
    # selected — and the completion judge approved on it. The qualifier is a fact about cria's own
    # check (what it looked for, what it found), never a claim that this task needs tests; it stops
    # the moment a matching file exists. Only on the CLEAN branch: where real findings exist the coder
    # has concrete work, and this would be noise on top of it.
    # Keyed on the FILES, not on whether a test command was invoked. A Go project with go.mod and no
    # *_test.go DOES get `go test ./...` — which exits 0 saying "no test files", so the gate reads
    # clean and says nothing. Same vacuous green as g20's Python, reached the other way round. The
    # absence of a test file is the fact either way, and it needs no runner output parsing (cria has
    # no Go/PHP/Ruby toolchain to have verified those strings against).
    untested = list(getattr(plan, "untested", None) or []) if plan is not None else []
    if untested:
        clean += " " + prompts.render("no_tests_found", findings=" ".join(untested))
    # WHERE the checks had to run, when none of them could run where the coder is working. A green
    # gate over a project the working directory does not contain is the most expensive green there
    # is — see _checks_ran_elsewhere for the cell it cost.
    if getattr(plan, "ran_in", ""):
        clean += " " + prompts.render("checks_ran_elsewhere", where=plan.ran_in)
    # A suite that passes with the network blocked never touched the API it claims to test. FACT,
    # not verdict (principle 8) — plenty of tasks have no network in them, and which it is here is
    # the judge's call. Only on the CLEAN branch: with real findings the coder already has work.
    offline = _offline_fact(_sections, plan)
    if offline:
        clean += " " + offline
    return clean


# The runner-said-nothing-ran shapes, per supported runner — consulted only to decide whether the
# stranded-test disk scan is worth asking for; the scan result, not the marker, is the finding.
_ZERO_TESTS_MARKERS = ("no tests ran", "[no test files]", "no tests found")


def gate_passing_tests(report: ProbeReport) -> int:
    """Tool-reported PASSING-test count across this report's Test-kind probes, or -1 when no runner
    printed a tally it recognises.

    Sibling of :func:`gate_ran_tests` and :func:`gate_skipped_count`, and read from the same place:
    the runner's own summary line, via ``runner_tally``, which normalizes twelve runners
    to ``Nf/Np``. -1 rather than 0 for "no tally", so a caller can tell "the runner said nothing"
    from "the runner said zero" — the distinction the completion gate's whole vacuous-green family
    turns on.
    """
    if report is None:
        return -1
    kinds = proberun._kind_by_command(report)
    total, seen = 0, False
    for r in report.results:
        if kinds.get(r.command) is not probediscovery.ProbeKind.Test or r.timed_out:
            continue
        m = re.match(r"(\d+)f/(\d+)p$", r.tally or "")
        if m:
            total += int(m.group(2))
            seen = True
    return total if seen else -1


def _offline_fact(sections: dict, plan: "GatePlan | None" = None) -> str:
    """One sentence when the test suite passes with the network taken away — else "".

    TWO signals, and cria only says as much as it has.

    The EXIT CODES gate it. Every test runner on earth exits 0 on pass and non-zero on fail, so exit
    codes read `go test` and `cargo test` — 3 of the suite's 5 task families — exactly as well as
    pytest. That is what let the block go language-agnostic without a tally format per ecosystem.

    The PASSED COUNTS decide how much can be claimed. Exit codes alone are not enough to say "nothing
    in them reaches the real service", because a live test can SKIP instead of fail when the service
    is gone — a two-line try/except that leaves the exit code at 0. Reproduced against a real gate:
    six tests green online, `5 passed, 1 skipped` offline, both exit 0, and the sentence asserted
    that no test touches the service while one of them was hitting it. Operator caught the same hole
    from the other end ("we don't know that all tests are network tests"). So: counts readable on
    both sides and EQUAL → the strong sentence; readable and DIFFERENT → silence, because coverage
    changed and cria cannot tell which half is the truth; not readable → the weaker sentence, which
    claims only what the exit code established.

    ONLY when the suite was GREEN online. Two runs that both FAIL say nothing about mocking — the
    suite is just failing, and on a box with no outbound network the two agree trivially. Caught
    end-to-end while building this: a genuinely live test failed on both sides, the results matched,
    and the draft told the judge the suite never touches the service. That is the false fact rule 5b
    forbids, produced by the very check built to expose one.

    Silent unless cria established it. No offline section (the kernel refused the namespace, so no
    block was applied), no plan to say WHICH probe was the test, a missing sentinel, or any non-zero
    on either side — each one says nothing rather than guess."""
    off = sections.get("offline")
    if not off:
        return ""
    # WHICH probe was the test is a fact the plan holds; without it cria will not guess. The offline
    # leg is composed from this same candidate, so the index is exact, not a search over sections.
    idx = next((i for i, c in enumerate(getattr(plan, "candidates", None) or [])
                if c.kind is probediscovery.ProbeKind.Test), None)
    if idx is None:
        return ""
    online = sections.get(f"probe-{idx}")
    if not online:
        return ""
    online_text, online_code = proberun.scrape_exit(online)
    offline_text, offline_code = proberun.scrape_exit(off)
    if online_code != 0 or offline_code != 0:
        return ""
    on_tally, off_tally = runner_tally(online_text), runner_tally(offline_text)
    if on_tally and off_tally:
        if on_tally != off_tally:
            return ""      # a test stepped aside offline — cria cannot claim the suite is self-contained
        return prompts.render("tests_pass_offline", tally=on_tally)
    return prompts.render("tests_pass_offline_uncounted")


def _zero_tests_marker(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _ZERO_TESTS_MARKERS)


CHECKS_MARKER = "⟦ctx:checks⟧"
CHECKS_REPEAT_NOTE = (CHECKS_MARKER + " (same result as a later check below — omitted here so the same "
                      "finding isn't repeated across turns)")


def _checks_payload(m) -> tuple[str, str] | None:
    """(key, text) when ``m`` is a ⟦ctx:checks⟧ tool result, else None."""
    if not isinstance(m, dict):
        return None
    key = "content" if m.get("content") is not None else "output"
    c = m.get(key)
    return (key, c) if isinstance(c, str) and c.startswith(CHECKS_MARKER) else None


_NO_SIGNAL_CHECK = "no usable result"   # the ⟦ctx:checks⟧ non-signal — nothing to act on

# Gate SCAFFOLDING lines (from plan_gate): the section-marker echoes, the git-status|sha1sum changed-files
# fingerprint, and the ``cd <ws> || exit 97`` guard. Pure plumbing the model never authored and can't act
# on — stripped from the COMMAND side so the coder's view isn't flooded with the gate's own machinery.
_GATE_MARKER_ECHO = re.compile(r"^\s*echo\s+.*" + re.escape(SECTION_PREFIX))
_GATE_GIT_FP = re.compile(r"^\s*git status --porcelain.*sha1sum")
_GATE_CD_GUARD = re.compile(r"^\s*cd\s+.*\|\|\s*exit\s+97\s*$")
# The litter bookkeeping (pre/post untracked snapshot). Named for the three variables that appear
# ONLY there — the probe wrapper uses __cria_out/_ec/_n, so a real probe line can never match.
_GATE_LITTER = re.compile(r"__cria_(?:pre|post|new)\b")


# The capture wrapper `proberun.compose_probe_command` builds, reduced to the command inside it.
# Deliberately anchored on the SHAPE (`$(timeout … <argv> </dev/null 2>&1)`) rather than on cria's
# variable names, so a rename cannot silently turn this back off.
_GATE_WRAPPER = re.compile(
    r"""(?x)^\s*(?:cd\s+\S+\s+&&\s+)?          # the cd guard, when present
        \w+=\$\(\s*timeout\s+(?:-k\s+\S+\s+)?\S+\s+   # __x_out=$(timeout [-k GRACE] LIMIT
        (?P<cmd>.+?)\s*</dev/null\s*2>&1\s*\);           # …the real command…
        .*$""")


def _strip_gate_plumbing(cmd: str) -> str:
    """Drop cria's gate scaffolding from a composed gate command, keeping only the real probe commands
    (pytest/lint) the model might care about. Returns '' when nothing but scaffolding remains.

    IT NOW DOES WHAT IT SAYS. It dropped whole LINES matching four scaffolding patterns — but the
    capture wrapper is ONE line with the real command inside it, so every probe line rode through
    complete: `cd /tmp/… && __cria_out=$(timeout -k 5 240 pytest -q </dev/null 2>&1); __cria_ec=$?;
    …; printf 'EXIT:%d\n' "$__cria_ec"`. Measured on one day of real prompts: 131,946 occurrences of
    cria's own variable names across 1,433 coder prompts — 6.1% of every byte cria sent the coder and
    31.6% of the worst single prompt.

    Three harms, one cause. Three different models COPIED the wrapper back into their own commands
    (21 responses, 5 sessions; one reproduced the whole four-probe script including the offline leg),
    and the copy always exits 0 because its last statement is a `printf`. The repetition detector's
    fingerprint drowned: the boilerplate contributes ~35 shared words against a real command's 1–4,
    so `cat main.go` matched `mv cart.go .` — three live fires, each costing a probe and a reasoned
    redirect. And the steer author's transcript, defanged precisely so there is "nothing a model can
    COPY", carried 557 characters of runnable shell per call.

    Rules 17 and 5b: the model never sees the token, and never sees an idiom that lies about its own
    exit status."""
    out = []
    for ln in cmd.splitlines():
        if (_GATE_MARKER_ECHO.match(ln) or _GATE_GIT_FP.match(ln)
                or _GATE_CD_GUARD.match(ln) or _GATE_LITTER.search(ln)):
            continue
        m = _GATE_WRAPPER.match(ln)
        out.append(m.group("cmd") if m else ln)
    return "\n".join(ln for ln in out if ln.strip()).strip()


def _strip_command_plumbing(m: dict) -> dict:
    """If an assistant tool call carries a gate-scaffolded command, rewrite the command in place to drop
    the plumbing (markers/git-sha/cd-guard). Shape-preserving: str ``cmd`` or list ``command``."""
    tcs = m.get("tool_calls")
    if not tcs:
        return m
    changed = False
    new_tcs = []
    for tc in tcs:
        fn = tc.get("function") or {}
        raw = fn.get("arguments")
        if isinstance(raw, str) and SECTION_PREFIX in raw:
            try:
                a = jsontext.loads(raw)
            except (ValueError, TypeError):
                a = None
            if isinstance(a, dict):
                for field in ("cmd", "command"):
                    v = a.get(field)
                    if isinstance(v, str) and SECTION_PREFIX in v:
                        a[field] = _strip_gate_plumbing(v)
                    elif isinstance(v, list):
                        joined = "\n".join(str(x) for x in v)
                        if SECTION_PREFIX in joined:
                            a[field] = [_strip_gate_plumbing(joined)]
                tc = {**tc, "function": {**fn, "arguments": json.dumps(a)}}
                changed = True
        new_tcs.append(tc)
    return {**m, "tool_calls": new_tcs} if changed else m


def clean_gate_results(messages: list, plan: "GatePlan | None" = None) -> list:
    """Rewrite raw gate-probe tool results (in the model's view) to the cleaned summary. Idempotent;
    a re-run over already-clean messages leaves them untouched. Non-gate messages pass through.

    Also STRIPS the gate's command-side plumbing (the ``echo ___CRIA_GATE_…``/``git status|sha1sum``/
    ``cd||exit 97`` scaffolding the coder never authored), DROPS non-signal ⟦ctx:checks⟧ turns entirely
    (with their command call, so nothing orphans — a "no usable result this turn" is pure noise), and

    COLLAPSES repeats: when the same cleaned ⟦ctx:checks⟧ payload appears more than once (a gate finding
    that recurs unchanged across turns — e.g. the identical ImportError the model kept hitting), keep only
    the most recent full copy and shorten the earlier identical ones to a one-line back-reference. The
    model stops re-reading the same error N times (which reinforced its fixation)."""
    out = []
    drop_ids: set = set()          # tool_call ids whose result we dropped → drop the calling turn too
    last_gate = max((i for i, m in enumerate(messages)
                     if isinstance(m, dict)
                     and (m.get("role") == "tool" or m.get("type") == "function_call_output")
                     and isinstance(m.get("content") or m.get("output"), str)
                     and SECTION_PREFIX in (m.get("content") or m.get("output"))), default=-1)
    for i, m in enumerate(messages):
        if isinstance(m, dict):
            is_tool = m.get("role") == "tool" or m.get("type") == "function_call_output"
            key = "content" if m.get("content") is not None else "output"
            c = m.get(key)
            if is_tool and isinstance(c, str) and SECTION_PREFIX in c:
                # ANNOTATE ONLY THE NEWEST GATE RESULT. This function re-renders every gate result
                # in the history on EVERY prompt build, and the disk quote is read at render time —
                # so a finding produced five calls ago gets stamped with whatever that line says
                # NOW. Walked three times independently on maple-preview 1785994846: the same
                # `test_resolve_adam.py:54` was annotated `mock_get.assert_called_once_with(` at
                # call 0027, `self.assertEqual(result["address"], "tz1KqTp…")` at 0031, and
                # `f"{API_BASE_URL}/handles/go.handle",` at 0032 — with byte-identical MagicMock ids
                # proving the checks never re-ran in between. The coder read a stale failure carrying
                # a freshly-wrong quote, concluded its landed fix had not landed, un-fixed a correct
                # assertion and re-applied an import it already had. Three calls, on a 15-minute wall.
                # The guard was added the same morning (bdd68bc) to stop the model GUESSING at an
                # unquoted line; on a file that has moved it manufactures the guess instead.
                cleaned = clean_gate_output(c, plan, annotate=(i == last_gate),
                                            changed_paths=_paths_written_after(messages, i)
                                            if i == last_gate else frozenset())
                if cleaned is not None:
                    if _NO_SIGNAL_CHECK in cleaned:   # no signal → drop the result AND its command turn
                        tid = m.get("tool_call_id") or m.get("call_id")
                        if tid:
                            drop_ids.add(tid)
                        continue
                    out.append({**m, key: cleaned})
                    continue
            if m.get("role") == "assistant" and m.get("tool_calls"):
                m = _strip_command_plumbing(m)
        out.append(m)
    if drop_ids:  # remove the assistant call(s) whose only result was a dropped no-signal gate probe
        out = [m for m in out if not (isinstance(m, dict) and m.get("role") == "assistant"
               and m.get("tool_calls") and len(m["tool_calls"]) == 1
               and (m["tool_calls"][0].get("id") in drop_ids))]
    # Keyed on dedup.volatile_key, NOT the raw payload. Two renderings of the same finding differ by
    # per-run noise the finding does not depend on, and keying on bytes meant the collapse never
    # fired for them. mellum2 1786051505 carried `resolve_handle_and_test.py:92: undefined name
    # 'pytest'` THREE times in one coder prompt — on a file the coder had since cut to 7 lines, so it
    # was hunting a line that no longer existed — and the three copies differed only by a
    # `<urllib.request.Request object at 0x…>` address and `in 0.36s` vs `in 0.28s`.
    last_of: dict[str, int] = {}
    for i, m in enumerate(out):
        p = _checks_payload(m)
        if p is not None:
            last_of[dedup.volatile_key(p[1])] = i
    if any(idx != last_of[dedup.volatile_key(_checks_payload(out[idx])[1])]
           for idx, m in enumerate(out) if _checks_payload(m) is not None):
        for i, m in enumerate(out):
            p = _checks_payload(m)
            if p is not None and last_of[dedup.volatile_key(p[1])] != i:
                out[i] = {**m, p[0]: CHECKS_REPEAT_NOTE}
    return out


# A harness that REFUSES to run the gate at all (sandbox policy, no shell, a rejected verb) returns no
# section markers, which interpret_gate correctly reads as "nothing ran" — correct, and completely
# silent. cria then loses its single largest assist on every turn with nothing in the log to say so.
# These are the phrases a refusal carries; matching one turns the silence into one operator-facing warn.
_REFUSAL_PHRASES = (
    "not permitted",
    "rejected:",
    "is not allowed",
    "permission denied",
    "operation not permitted",
    "sandbox",
)


def refusal_reason(result_text: str) -> str:
    """The harness's own words for why it would not run the gate — '' if it doesn't look like a refusal.

    Only consulted when NO section came back: a gate that ran and merely failed is not a refusal."""
    text = (result_text or "").strip()
    if not text:
        return ""
    low = text.lower()
    if not any(p in low for p in _REFUSAL_PHRASES):
        return ""
    # The useful part is the harness's reason, not the multi-kilobyte echo of the script it refused.
    for phrase in _REFUSAL_PHRASES:
        i = low.find(phrase)
        if i >= 0:
            return " ".join(text[max(0, i - 80):i + 160].split())
    return ""


def sweep_litter(plan: GatePlan, sections: dict) -> list[str]:
    """Remove the untracked files the gate's OWN probes created. Returns what was removed.

    The list comes from the harness's shell (git's ``??`` set, before minus after); the removal happens
    here so cria never composes a destructive command — the Codex sandbox rejects the whole exec when it
    sees one, which silently killed every gate (see :func:`plan_gate`).

    Bounded three ways, because this deletes files: git must call the path UNTRACKED (a tracked file can
    never appear), the path must resolve INSIDE the workspace (no absolute paths, no ``..``, no following
    a symlink out), and any failure is skipped rather than escalated. Nothing here guesses."""
    body = (sections or {}).get(LITTER_SECTION)
    root = getattr(plan, "workspace", "") or ""
    if not body or not root:
        return []
    removed: list[str] = []
    for rel in (ln.strip() for ln in body.splitlines()):
        # ONE OWNER for "does this path leave the workspace". This used to be a hand-rolled
        # realpath-the-parent dance here, correct but private, while writeproxy asked dirguard a
        # LEXICAL version of the same question and the two disagreed on a symlink pointing out.
        # Both answers were right for their caller and neither had a name, so execcheck and
        # planner_tools — which also act in the workspace — checked nothing at all.
        if not rel or os.path.isabs(rel) or dirguard.escapes_workspace(rel, root):
            continue
        target = os.path.join(os.path.realpath(root), rel)
        try:
            if os.path.islink(target) or os.path.isfile(target):
                os.unlink(target)
            elif os.path.isdir(target):
                shutil.rmtree(target)
            else:
                continue
        except OSError:
            continue
        removed.append(rel)
    return removed


def interpret_gate(plan: GatePlan, result_text: str) -> GateOutcome:
    """Replay the harness's gate output through the ported interpreters."""
    sections = split_sections(result_text)
    # Before anything else: take back what the probes left behind. Runs even when the gate FAILED —
    # a suite that errors halfway still wrote its fixtures, and the next gate would inherit them.
    swept = sweep_litter(plan, sections)
    # ran is TRUE only if an actual check section came back — NOT just the always-present git snapshot.
    # An empty / no-code repo yields zero candidates, so plan_gate composes a git-ONLY script; treating
    # that as "ran" made guard_ground_truth emit a clean "no error-class problems" verdict when NO check
    # actually ran. No probe-* section → ran=False → silence, not a false pass.
    if not any(k.startswith("probe-") for k in sections):
        return GateOutcome(ran=False, refused=refusal_reason(result_text))
    out = GateOutcome(ran=True, swept=swept)

    results = []
    for i, c in enumerate(plan.candidates):
        body = sections.get(f"probe-{i}")
        if body is None:
            # Never ran — the script was cut short (harness truncation) or the section never came back.
            # Absence must not BLOCK, but it must not read as CLEAN either: `results` silently became a
            # subset of `selected`, and nothing downstream said a check was missing, so a truncated gate
            # looked like a passing one. Record the gap so the digest can report it.
            out.unran.append(proberun.display_command(c.command))
            continue
        raw, code = proberun.scrape_exit(body)
        results.append(proberun.interpret_probe_output(
            c, proberun.display_command(c.command), raw, code, COMPLETION_PROBE_TIMEOUT_S))
    out.report = ProbeReport(project_type=[], selected=list(plan.candidates), results=results)

    out.git_state = sections.get("git", "").strip().splitlines()[-1].strip() if sections.get("git") else ""
    return out
