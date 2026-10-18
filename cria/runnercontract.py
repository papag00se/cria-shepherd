"""Reanchor a failed declared JS test runner after one definitive judgment.

Probe discovery/results, workspace observations, transcript cleanup and the
closed-question reader remain shared foundations. This policy never executes a
runner or edits its interface. Its transient state remembers definitive judgments,
not delivery: a later driver may still replace the returned guidance. New tasks,
forks and durable reconstruction receive a fresh state, as the old GuardState
signature did. There are no owned pending harness effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from . import probediscovery, proberun, prompts
from .assistcontract import Policy, Reference
from .classify import JUDGE_MAX_TOKENS


class EventLog(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


class ClosedJudge(Protocol):
    def __call__(self, question: str, *, phase: str, max_tokens: int,
                 retry_off: bool) -> str: ...


class GateFacts(Protocol):
    report: proberun.ProbeReport | None


@dataclass
class RunnerState:
    signature: str = ''

    def reset(self) -> None:
        self.signature = ''


class RunnerStatus(Enum):
    NOT_SELECTED = 'not-selected'
    NOT_APPLICABLE = 'not-applicable'
    REPEATED = 'repeated'
    WITHHELD = 'withheld'
    ON_TRACK = 'on-track'
    STEER = 'steer'


@dataclass(frozen=True)
class RunnerResult:
    status: RunnerStatus
    steer: str | None = None

    def __post_init__(self):
        if not isinstance(self.status, RunnerStatus):
            raise ValueError('Unknown runner-contract outcome')
        if self.status is RunnerStatus.STEER:
            if not isinstance(self.steer, str) or not self.steer.strip():
                raise ValueError('Runner reanchoring requires its concrete guidance')
        elif self.steer is not None:
            raise ValueError('A silent runner judgment cannot carry guidance')


@dataclass(frozen=True)
class RunnerInput:
    outcome: GateFacts
    checks: Callable[[], str]
    node_modules: Callable[[], bool | None]
    evidence: Callable[[], tuple[str, str]]  # pinned task and cleaned session
    ask: ClosedJudge | None
    log: EventLog


def failed_declared_runner(outcome: GateFacts) -> str:
    """Read declared interface + selected JS test + matching nonzero exit facts.

    Keep selected order and the existing display-command reader. Failure prose,
    package names, dependency APIs and proposed actions do not decide admission.
    """
    report = getattr(outcome, 'report', None)
    if report is None:
        return ''
    results = {result.command: result for result in (report.results or [])}
    for candidate in report.selected or []:
        if not (getattr(candidate, 'declared_interface', False)
                and getattr(candidate, 'kind', None) is probediscovery.ProbeKind.Test
                and getattr(candidate, 'ecosystem', None) is probediscovery.Ecosystem.JsTs):
            continue
        command = proberun.display_command(candidate.command)
        result = results.get(command)
        if result is not None and result.exit_code not in (None, 0):
            return command
    return ''


def judge_runner_contract(source: RunnerInput, state: RunnerState) -> RunnerResult:
    runner = failed_declared_runner(source.outcome)
    if not runner or source.ask is None:
        return RunnerResult(RunnerStatus.NOT_APPLICABLE)
    checks = source.checks()
    signature = '\n'.join((runner, checks))
    if signature == state.signature:
        return RunnerResult(RunnerStatus.REPEATED)
    node_modules = source.node_modules()
    # Existing exact factual wording; unknown must never become absence. The
    # reasoner, not a deterministic action/keyword rule, judges the task contract.
    node_modules_fact = {
        True: 'node_modules is present in the surveyed workspace.',
        False: 'node_modules is absent from the surveyed workspace.',
        None: 'Whether node_modules is present is not known from the workspace survey.',
    }[node_modules]
    task, session = source.evidence()
    question = prompts.render('runner_reset_judge_user', task=task or '(no task recovered)',
                              runner=runner, node_modules=node_modules_fact,
                              checks=checks, session=session)
    answer = source.ask(prompts.load('runner_reset_judge') + '\n\n' + question,
                        phase='runner-reset', max_tokens=JUDGE_MAX_TOKENS, retry_off=False)
    verdict = answer.strip().upper()
    identity = dict(assist_id=DEFINITION.policy.id, family_id=DEFINITION.policy.family_id)
    if verdict not in ('RESET', 'ON_TRACK'):
        source.log.emit('loop.runner_reset', applied=False, runner=runner,
                        verdict=answer.strip()[:40], **identity)
        return RunnerResult(RunnerStatus.WITHHELD)
    # Both exact answers settle the unchanged fact set, even if later caller
    # framing replaces the effect. Unknown answers and exceptions settle nothing.
    state.signature = signature
    if verdict == 'ON_TRACK':
        source.log.emit('loop.runner_reset', applied=False, runner=runner,
                        verdict=verdict, **identity)
        return RunnerResult(RunnerStatus.ON_TRACK)
    source.log.emit('loop.runner_reset', applied=True, runner=runner,
                    node_modules=node_modules, **identity)
    return RunnerResult(RunnerStatus.STEER,
                        prompts.render('runner_reset', runner=runner, checks=checks))


@dataclass(frozen=True)
class RunnerDefinition:
    policy: Policy
    execute: Callable[[RunnerInput, RunnerState], RunnerResult]


DEFINITION = RunnerDefinition(
    Policy('declared-js-runner-reanchor', 'dependency-contract-result', 5, family_id='F47',
           prompts=('runner_reset_judge', 'runner_reset_judge_user', 'runner_reset'),
           state='task/session-local definitive runner/check signature; reset on new task/fork/durable restore; no pending effects',
           services=('parsed-gate-outcome', 'checker-output', 'workspace-directory-fact',
                     'cleaned-task-and-session', 'closed-judge'),
           hooks=(Reference('cria/loop.py', 'guard_periodic_result'),
                  Reference('cria/loop.py', 'Loop._verify_after_probe'),
                  Reference('cria/loop.py', 'Loop._drive_single_item')),
           regressions=(Reference('tests/test_runner_contract_policy.py',
                                  'test_complete_judgment_keeps_checker_contract_and_settles_only_exact_answers'),
                        Reference('tests/test_runner_contract_policy.py',
                                  'test_disabled_stage_never_constructs_input_or_observes_state')),
           migrated=False),
    judge_runner_contract)


def run_selected(definition: RunnerDefinition | None, source: Callable[[], RunnerInput],
                 state: RunnerState) -> RunnerResult:
    """The selected result-stage hook; selection precedes all evidence gathering.

    The runtime owner supplies the authoritative selected definition/replacement,
    or None. There is no default-selection fallback or independent selector here.
    """
    if definition is None:
        return RunnerResult(RunnerStatus.NOT_SELECTED)
    result = definition.execute(source(), state)
    if not isinstance(result, RunnerResult):
        raise ValueError('Runner-contract replacement must return RunnerResult')
    return result
