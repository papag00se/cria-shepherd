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

import re
import shlex
from dataclasses import dataclass, field

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
# Per-probe wall-clock bound — codex-local's COMPLETION_PROBE_TIMEOUT (45 s per probe).
COMPLETION_PROBE_TIMEOUT_S = 45.0


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


def clean_gate_output(raw: str) -> str | None:
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
    for sid, body in split_sections(raw).items():
        if sid == "git":          # the changed-files hash is a signal for cria, noise for the model
            continue
        text, code = proberun.scrape_exit(body)
        # The EXIT sentinel is the reliable signal (the composed probe always prints it). A launch
        # failure (125/126/127) or timeout (124) means the check did NOT complete — never a code error
        # to "fix", never a pass. Sniffing text for "no such file" would misread a real error that just
        # mentions it (a FileNotFoundError, a missing #include) as couldn't-run.
        if code in proberun.LAUNCH_FAILURE_EXIT_CODES or code == proberun.TIMEOUT_EXIT_CODE:
            could_not_run = True
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
    if findings:                    # a check RAN and found a real error-class problem — foreground it
        return ("⟦cria:checks⟧ the repo's own checks report these error-class problems — fix them at "
                "the reported line:\n" + "\n".join(findings[:40]))
    if failed_no_detail:            # ran, exited non-zero, no usable output → a failure with no location
        return ("⟦cria:checks⟧ one of the repo's own checks FAILED but printed no location cria could "
                "parse — run it yourself and read the actual error before continuing. Not done.")
    if could_not_run:               # couldn't launch/timed out → cria's own setup gap; stay neutral
        # NOT a pass (never claim clean), NOT a fix request (the model can't fix cria's absent tool),
        # NOT a specific confession — just a non-actionable placeholder so the model relies on itself.
        return "⟦cria:checks⟧ the automatic checks produced no usable result this turn — no signal either way."
    return ("⟦cria:checks⟧ the repo's own checks that ran reported no error-class problems. That does "
            "not verify behaviour or mean the task is done — if you know something is still wrong, keep "
            "fixing it with a targeted edit.")


def clean_gate_results(messages: list) -> list:
    """Rewrite raw gate-probe tool results (in the model's view) to the cleaned summary. Idempotent;
    a re-run over already-clean messages leaves them untouched. Non-gate messages pass through."""
    out = []
    for m in messages:
        if isinstance(m, dict):
            is_tool = m.get("role") == "tool" or m.get("type") == "function_call_output"
            key = "content" if m.get("content") is not None else "output"
            c = m.get(key)
            if is_tool and isinstance(c, str) and SECTION_PREFIX in c:
                cleaned = clean_gate_output(c)
                if cleaned is not None:
                    out.append({**m, key: cleaned})
                    continue
        out.append(m)
    return out


def interpret_gate(plan: GatePlan, result_text: str) -> GateOutcome:
    """Replay the harness's gate output through the ported interpreters."""
    sections = split_sections(result_text)
    if not sections:
        return GateOutcome(ran=False)
    out = GateOutcome(ran=True)

    results = []
    for i, c in enumerate(plan.candidates):
        body = sections.get(f"probe-{i}")
        if body is None:
            continue  # never ran (script cut short) → no result; absence never blocks
        raw, code = proberun.scrape_exit(body)
        results.append(proberun.interpret_probe_output(
            c, " ".join(c.command), raw, code, COMPLETION_PROBE_TIMEOUT_S))
    out.report = ProbeReport(project_type=[], selected=list(plan.candidates), results=results)

    out.git_state = sections.get("git", "").strip().splitlines()[-1].strip() if sections.get("git") else ""
    return out
