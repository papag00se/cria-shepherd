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
import re
import shlex
from dataclasses import dataclass, field

from . import jsontext
from . import probeparse, proberun

# Leading ``path:line[:col][:]`` location prefix a linter prints before the diagnostic. Stripping it
# lets probeparse.is_advisory's ANCHORED style-code check (``^W###``/``E###``…) fire on a raw gate
# line — its phrase check is substring so it already works either way.
_LOC_PREFIX = re.compile(r"^\S.*?:\d+(?::\d+)?:?\s+")

from .proberun import ProbeReport

# Marker line delimiting each section of the composed script's output. The id after the
# prefix names the section ("probe-0", "git"). Chosen to never collide with tool output.
SECTION_PREFIX = "___CRIA_GATE_"
SECTION_SUFFIX = "___"
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


@dataclass
class GateOutcome:
    ran: bool = False  # False → no markers came back; keep don't-wedge semantics
    report: ProbeReport | None = None
    git_state: str = ""  # `git status --porcelain | sha1sum` — changed-files signal
    unran: list = field(default_factory=list)  # selected checks whose section never came back — a GAP,
    #                                            not a pass: without this, a truncated gate read clean


def _marker(section_id: str) -> str:
    return f"{SECTION_PREFIX}{section_id}{SECTION_SUFFIX}"


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

    parts: list[str] = [f"cd {shlex.quote(workspace)} || exit 97"] if workspace else []
    for i, c in enumerate(plan.candidates):
        parts.append(f"echo {_marker(f'probe-{i}')}")
        parts.append(proberun.compose_probe_command(c, COMPLETION_PROBE_TIMEOUT_S))
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


def _is_hard_failure(plan, sid: str) -> bool:
    """Is section ``sid`` a probe whose non-zero exit is a REAL failure regardless of how its output
    looks? Test / typecheck / build — `plan.candidates` is in section order, so probe-N is candidate N.
    Unknown plan or unparseable id → False (keep the advisory-clean lint behaviour)."""
    try:
        idx = int(sid.split("-", 1)[1])
        kind = plan.candidates[idx].kind()
    except (AttributeError, IndexError, ValueError, TypeError):
        return False
    return kind in proberun._HARD_FAILURE_KINDS


def clean_gate_output(raw: str, plan: "GatePlan | None" = None) -> str | None:
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
    findings: list[str] = []
    seen: set[str] = set()
    could_not_run = False
    failed_no_detail = False
    saw_probe = False
    timed_out_output: list[str] = []
    for sid, body in split_sections(raw).items():
        if sid == "git":          # the changed-files hash is a signal for cria, noise for the model
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
        if proberun.is_no_tests_collected(code, output=text):
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
        for ln in text.splitlines():
            s = ln.strip()
            if not s or s.startswith(proberun.PROBE_EXIT_SENTINEL):   # blank / EXIT:<n> sentinel
                continue
            had_content = True
            # advisory either as a whole line (phrase/prefix forms) or once the location prefix is
            # stripped (bare style code like `foo.py:80:1: E501 …`) — unused-import / style, filtered
            if probeparse.is_advisory(s) or probeparse.is_advisory(_LOC_PREFIX.sub("", s)):
                continue
            if s not in seen:
                seen.add(s)
                section_findings.append(s)
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
    if findings:                    # a check RAN and found a real error-class problem — foreground it
        # Show EVERY error-class finding — a 40-line clip once hid findings 41+, so the model "fixed"
        # what it saw and claimed done while real errors remained invisible. The context floor
        # (contextfloor.fit) is the one window-aware place a truncation may happen, and only when the
        # physical window forces it — never a blind per-site clip here.
        return ("⟦ctx:checks⟧ the repo's own checks report these error-class problems — each is the "
                "checker's OWN message and the line it flagged; resolve what each one names with the "
                "smallest change that clears it:\n" + "\n".join(findings))
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
    return "⟦ctx:checks⟧ the repo's own checks that ran reported no error-class problems."


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


def _strip_gate_plumbing(cmd: str) -> str:
    """Drop cria's gate scaffolding from a composed gate command, keeping only the real probe commands
    (pytest/lint) the model might care about. Returns '' when nothing but scaffolding remains."""
    kept = [ln for ln in cmd.splitlines()
            if not (_GATE_MARKER_ECHO.match(ln) or _GATE_GIT_FP.match(ln) or _GATE_CD_GUARD.match(ln))]
    return "\n".join(ln for ln in kept if ln.strip()).strip()


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
    for m in messages:
        if isinstance(m, dict):
            is_tool = m.get("role") == "tool" or m.get("type") == "function_call_output"
            key = "content" if m.get("content") is not None else "output"
            c = m.get(key)
            if is_tool and isinstance(c, str) and SECTION_PREFIX in c:
                cleaned = clean_gate_output(c, plan)
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
    last_of: dict[str, int] = {}
    for i, m in enumerate(out):
        p = _checks_payload(m)
        if p is not None:
            last_of[p[1]] = i
    if any(idx != last_of[_checks_payload(out[idx])[1]]  # some earlier duplicate exists
           for idx, m in enumerate(out) if _checks_payload(m) is not None):
        for i, m in enumerate(out):
            p = _checks_payload(m)
            if p is not None and last_of[p[1]] != i:
                out[i] = {**m, p[0]: CHECKS_REPEAT_NOTE}
    return out


def interpret_gate(plan: GatePlan, result_text: str) -> GateOutcome:
    """Replay the harness's gate output through the ported interpreters."""
    sections = split_sections(result_text)
    # ran is TRUE only if an actual check section came back — NOT just the always-present git snapshot.
    # An empty / no-code repo yields zero candidates, so plan_gate composes a git-ONLY script; treating
    # that as "ran" made guard_ground_truth emit a clean "no error-class problems" verdict when NO check
    # actually ran. No probe-* section → ran=False → silence, not a false pass.
    if not any(k.startswith("probe-") for k in sections):
        return GateOutcome(ran=False)
    out = GateOutcome(ran=True)

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
