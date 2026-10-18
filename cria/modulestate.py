"""One session-local judgment per unchanged failed Go test observation.

Only definitive judgments are remembered. State is transient: reset for a new
session/task and on durable session reconstruction; never copy it to a fork.
No probe or pending harness effect is owned by this policy.
"""
from dataclasses import dataclass
from enum import Enum
import json
from typing import Callable, Protocol

from . import probediscovery, proberun, prompts
from .assistcontract import Policy


@dataclass
class ModuleState:
    signature: str = ""


class Judgment(Enum):
    NOT_APPLICABLE = "not-applicable"
    REPEATED = "repeated"
    WITHHELD = "withheld"
    ON_TRACK = "on-track"
    STEER = "steer"


@dataclass(frozen=True)
class ModuleResult:
    judgment: Judgment
    steer: str | None = None

    def __post_init__(self):
        if not isinstance(self.judgment, Judgment):
            raise ValueError("Unknown periodic judgment outcome")
        if self.judgment is Judgment.STEER:
            if not isinstance(self.steer, str) or not self.steer.strip():
                raise ValueError("A steering judgment requires its concrete effect")
        elif self.steer is not None:
            raise ValueError("A withheld or silent judgment cannot carry a steer")


class CheckOutcome(Protocol):
    report: proberun.ProbeReport | None


class EventLog(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


@dataclass(frozen=True)
class ModuleInput:
    outcome: CheckOutcome
    # Lazy shared evidence; not gathered on disabled, irrelevant or repeated input.
    checks: Callable[[], str]
    evidence: Callable[[], tuple[str, str]]  # exact task and scrubbed session
    ask: Callable[[str], str] | None
    log: EventLog


def judge_module_state(source: ModuleInput, state: ModuleState) -> ModuleResult:
    report = getattr(source.outcome, "report", None)
    if report is None or source.ask is None:
        return ModuleResult(Judgment.NOT_APPLICABLE)
    results = {result.command: result for result in report.results or []}
    failed = []
    for candidate in report.selected or []:
        command = proberun.display_command(candidate.command)
        result = results.get(command)
        if (getattr(candidate, "ecosystem", None) is probediscovery.Ecosystem.Go
                and getattr(candidate, "kind", None) is probediscovery.ProbeKind.Test
                and result is not None and getattr(result, "exit_code", None) not in (None, 0)):
            failed.append((command, result.exit_code))
    if not failed:
        return ModuleResult(Judgment.NOT_APPLICABLE)
    checks = source.checks()
    signature = json.dumps([failed, checks], sort_keys=True)
    if signature == state.signature:
        return ModuleResult(Judgment.REPEATED)
    task, session = source.evidence()
    question = prompts.render("module_state_judge_user", TASK=task or "(no task recovered)",
                              TESTS="\n".join(f"{command} exited {code}" for command, code in failed),
                              CHECKS=checks, SESSION=session)
    answer = source.ask(prompts.load("module_state_judge") + "\n\n" + question)
    verdict = answer.strip().upper()
    if verdict not in ("REANCHOR", "ON_TRACK"):
        source.log.emit("loop.module_state", applied=False, verdict=answer.strip()[:40])
        return ModuleResult(Judgment.WITHHELD)
    state.signature = signature
    source.log.emit("loop.module_state", applied=verdict == "REANCHOR", verdict=verdict,
                    tests=[command for command, _code in failed],
                    assist_id=DEFINITION.policy.id, family_id=DEFINITION.policy.family_id)
    if verdict == "ON_TRACK":
        return ModuleResult(Judgment.ON_TRACK)
    return ModuleResult(Judgment.STEER, prompts.render("module_state_reset", CHECKS=checks))


@dataclass(frozen=True)
class ModuleDefinition:
    policy: Policy
    execute: Callable[[ModuleInput, ModuleState], ModuleResult]


DEFINITION = ModuleDefinition(
    Policy("go-module-state-judgment", "periodic-check-result", 5, family_id="F47",
           prompts=("module_state_judge", "module_state_judge_user", "module_state_reset"),
           state="session-local; reset on new task/fork/durable restore; no pending effects",
           services=("parsed-gate-outcome", "checker-output", "scrubbed-session", "closed-judge")),
    judge_module_state)
