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

import shlex
from dataclasses import dataclass, field

from . import proberun
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
