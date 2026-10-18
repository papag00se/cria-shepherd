"""Repository-check lifecycle; check evidence is NEVER whole-task or step approval.

The optional policy owns admission, cadence, pending correlation, bounded survey/
rewrite recovery and result settlement. Probe planning/transport/parsing, shell
schemas, raw result reading and shared progress measurement are foundations.
EvidenceServices.read/error/raw/progress bind the ACTUAL existing read_gate,
gate_error_text, _read_tool_result and track_gate_progress implementations (or
those same functions relocated by integration), not old guard policy callbacks.
Runner and module judgments are separately selected authorities, in that order.
Foundation events keep their original untagged identity; only policy events claim
this selected assist. Selection is task-stable while a probe is pending. The state protocol aliases the
existing session fields; do not keep a second check-state mirror alongside it.
"""
from dataclasses import dataclass
from enum import Enum
import json
from typing import Callable, Protocol
import uuid

from . import participation, probegate, proberun, prompts
from .assistcontract import Policy, Reference
from .shelltool import find_shell_tool, shell_args, with_time_budget, tool_declares_time_budget

GATE_EVERY_CODER_TURNS = 15
MAX_PROBE_REISSUES = 2


class Log(Protocol):
    def emit(self, event: str, **fields) -> None: ...


class State(Protocol):
    coder_turns: int
    periodic_probe: bool
    periodic_replan_done: bool
    awaiting_probe: bool
    done_probe: bool
    probe_call_id: str
    probe_reissues: int
    probe_poll_reissues: int
    gate_plan: probegate.GatePlan | None
    gate_helpers_ready: bool
    gate_replan_required: bool
    gate_fresh: bool
    last_gate_ran: bool
    last_gate_red: bool
    last_gate_participation: participation.ParticipationReport | None
    last_gate_testless: bool
    last_gate_skipped: int
    tests_passed_high: dict[str, int]
    last_regression: tuple[str, int, int] | None


class Driver(Enum):
    TASK = "task"
    STEP = "step"


class Trigger(Enum):
    PERIODIC = "periodic"
    REQUESTED = "requested"


class Status(Enum):
    NOT_SELECTED = "not-selected"
    NOT_DUE = "not-due"
    UNAVAILABLE = "unavailable"
    PENDING = "pending"
    OBSERVED = "observed"
    SILENT = "silent"


class PendingKind(Enum):
    CHECK = "check"
    PAGE = "page"
    SURVEY_REPLAN = "survey-replan"
    REISSUE = "reissue"
    REWRITE_POLL = "rewrite-poll"


@dataclass(frozen=True)
class Result:
    status: Status
    call: dict | None = None
    text: str | None = None
    outcome: probegate.GateOutcome | None = None
    # Presentation belongs to the driver; these are the existing human notes.
    note: str = ""
    pending_kind: PendingKind | None = None


@dataclass(frozen=True)
class Input:
    body: dict
    log: Log
    engagement: int  # explicit actual rung; a level-4 binding must not imply periodic admission
    workspace_root: str | None = None
    driver: Driver = Driver.TASK
    trigger: Trigger = Trigger.PERIODIC
    steer: str | None = None
    rewritten: bool = False
    step: int | None = None


class PlanBuilder(Protocol):
    def __call__(self, workspace: str, session: str, log: Log, *,
                 poll_wait_s: float, helpers_ready: bool) -> probegate.GatePlan: ...


@dataclass(frozen=True)
class ProbeServices:
    extract_cwd: Callable[[list[dict]], str | None]
    plan: PlanBuilder = probegate.plan_gate
    call_id: Callable[[], str] = lambda: "call_" + uuid.uuid4().hex[:16]


@dataclass(frozen=True)
class EvidenceServices:
    raw: Callable[[list[dict], str], str]
    read: Callable[[probegate.GatePlan | None, str, Log], probegate.GateOutcome]
    error: Callable[[probegate.GateOutcome], str]
    # Shared factual progress/write bookkeeping, not F44's author/admit/vet policy.
    progress: Callable[[str, list[dict] | None], None]


@dataclass(frozen=True)
class JudgmentServices:
    runner: Callable[[probegate.GateOutcome], str | None] = lambda outcome: None
    module: Callable[[probegate.GateOutcome], str | None] = lambda outcome: None


def _event(source: Input, event: str, **fields) -> None:
    source.log.emit(event, assist_id=DEFINITION.policy.id, family_id=DEFINITION.policy.family_id, **fields)


def _shell_call(source: Input, services: ProbeServices, tool: dict, command: str) -> dict:
    return {"id": services.call_id(), "type": "function", "function": {
        "name": tool["name"], "arguments": json.dumps(with_time_budget(tool, shell_args(tool, command)))}}


def compose(source: Input, state: State, services: ProbeServices) -> dict | None:
    """Shared construction support, not an independently selectable assist.

    Same plan_gate and schema/time-budget libraries as guard_gate_op. No executor,
    local workspace reads, or fabricated '.' root. Explicit callers own arming.
    """
    tool = find_shell_tool(source.body.get("tools"))
    if tool is None:
        return None
    root = source.workspace_root or services.extract_cwd(source.body.get("messages", [])) or ""
    if root == ".":
        root = ""
    wait = probegate.GATE_POLL_WAIT_LONG_S if tool_declares_time_budget(tool) else probegate.GATE_POLL_WAIT_S
    try:
        plan = services.plan(root, getattr(state, "web_session", "") or "", source.log,
                             poll_wait_s=wait, helpers_ready=state.gate_helpers_ready)
    except OSError as error:
        source.log.emit("loop.gate_error", level="warn", error=str(error))
        state.gate_plan = None
        return None
    state.gate_plan = plan
    state.gate_replan_required = False
    return _shell_call(source, services, tool, plan.script)


def admit(source: Input, state: State, services: ProbeServices) -> Result:
    periodic = source.trigger is Trigger.PERIODIC
    if source.engagement < (5 if periodic else 4):
        return Result(Status.NOT_SELECTED)
    if periodic:
        # Step scheduling precedes the experimental step critic, ignores rewrite,
        # and uses truthiness of the parked nudge. Task scheduling follows task
        # review, requires no steer at all, and excludes the rewrite turn.
        blocked = bool(source.steer) if source.driver is Driver.STEP else source.steer is not None or source.rewritten
        if blocked or state.coder_turns < GATE_EVERY_CODER_TURNS:
            return Result(Status.NOT_DUE)
        state.coder_turns = 0  # also reset when no shell/plan is available
    call = compose(source, state, services)
    if call is None:
        return Result(Status.UNAVAILABLE)
    if periodic:
        state.awaiting_probe = state.periodic_probe = True
        state.periodic_replan_done = False
        state.probe_call_id = call["id"]
        _event(source, "loop.periodic_gate", steer="periodic-gate", plan_off=source.workspace_root is None)
    return Result(Status.PENDING, call, note="periodic check-in — running the repo's checks" if periodic else "",
                  pending_kind=PendingKind.CHECK)


def observe_acting_turn(state: State, *, acting: bool, selected: bool = True) -> None:
    """Call at the existing forwarded tool-call event, once per acting coder turn.

    Not a drive counter, number of calls, probe turn or experimental step clock.
    """
    if selected and acting:
        state.coder_turns += 1


def replan(source: Input, state: State, services: ProbeServices, *, periodic: bool = False) -> Result:
    if not state.gate_replan_required or (periodic and state.periodic_replan_done):
        return Result(Status.NOT_DUE)
    if periodic:
        state.periodic_replan_done = True  # bounded even if compose raises/has no shell
    call = compose(source, state, services)
    if call is None:
        state.gate_replan_required = False
    _event(source, "loop.gate_replan_after_survey", available=call is not None)
    if periodic:
        if call is not None:
            state.periodic_probe = state.awaiting_probe = True
            state.probe_call_id = call["id"]
        _event(source, "loop.periodic_replan_after_survey", available=call is not None)
    return Result(Status.PENDING if call else Status.UNAVAILABLE, call,
                  pending_kind=PendingKind.SURVEY_REPLAN if call else None)


def transport(source: Input, state: State, services: ProbeServices, evidence: EvidenceServices,
              *, call_id: str = "") -> Result:
    """Required checked-page transport support, usable independently of selection.

    Existing probegate owns bytes, digest, deadline, refusal/UNKNOWN and cleanup.
    Never interpret a still-pending page, and never manufacture a clean result.
    """
    plan = state.gate_plan
    if plan is None or not plan.transport_required:
        return Result(Status.NOT_DUE)
    raw = evidence.raw(source.body.get("messages", []), call_id or state.probe_call_id)
    status = probegate.ingest_transport(plan, raw)
    state.gate_helpers_ready = plan.helpers_ready
    if status not in ("pending", "running"):
        if status == "unknown":
            source.log.emit("gate.transport_unknown", level="warn", reason=plan.transport_error,
                            received=len(plan.transport_data), total=plan.transport_total)
        return Result(Status.OBSERVED)
    command = probegate.continue_transport_command(plan)
    tool = find_shell_tool(source.body.get("tools"))
    if not command or tool is None:
        probegate.fail_transport(plan, "the harness no longer offers a shell for the next page")
        source.log.emit("gate.transport_unknown", level="warn", reason=plan.transport_error,
                        received=len(plan.transport_data), total=plan.transport_total)
        return Result(Status.OBSERVED)
    call = _shell_call(source, services, tool, command)
    state.probe_call_id = call["id"]
    source.log.emit("gate.transport_running" if status == "running" else "gate.transport_page",
                    received=len(plan.transport_data), total=plan.transport_total)
    return Result(Status.PENDING, call, pending_kind=PendingKind.PAGE)


def poll_after_rewrite(source: Input, state: State, services: ProbeServices) -> dict | None:
    plan = state.gate_plan
    if (plan is None or not plan.transport_required or plan.transport_complete or plan.transport_error
            or state.probe_poll_reissues >= MAX_PROBE_REISSUES):
        return None
    command = probegate.continue_transport_command(plan)
    tool = find_shell_tool(source.body.get("tools"))
    if not command or tool is None:
        return None
    call = _shell_call(source, services, tool, command)
    state.probe_call_id = call["id"]
    state.awaiting_probe = True
    state.probe_poll_reissues += 1
    _event(source, "gate.transport_poll_after_rewrite", attempt=state.probe_poll_reissues,
           received=len(plan.transport_data), total=plan.transport_total)
    return call


def reissue(source: Input, state: State, services: ProbeServices, evidence: EvidenceServices) -> Result:
    """Task/guard recovery. STEP-periodic readers historically do not reissue.

    Drivers retain their explicit ordering: task reissue → transport → periodic
    result; STEP-periodic transport → result (no rewrite reissue). Nonperiodic
    step readers retain their own presentation and terminal counter settlement.
    """
    if source.driver is Driver.STEP and state.periodic_probe:
        return Result(Status.NOT_DUE)
    if not (state.done_probe or state.awaiting_probe):
        return Result(Status.NOT_DUE)
    if evidence.raw(source.body.get("messages", []), state.probe_call_id).strip():
        if source.driver is Driver.TASK:
            state.probe_reissues = state.probe_poll_reissues = 0
        return Result(Status.OBSERVED)
    if not source.rewritten:
        return Result(Status.NOT_DUE)
    call = poll_after_rewrite(source, state, services)
    if call is not None:
        return Result(Status.PENDING, call, note="receiving complete check output (history was compacted)",
                      pending_kind=PendingKind.REWRITE_POLL)
    if state.probe_reissues >= MAX_PROBE_REISSUES:
        return Result(Status.UNAVAILABLE)
    call = compose(source, state, services)
    if call is None:
        return Result(Status.UNAVAILABLE)
    state.probe_call_id = call["id"]
    state.probe_reissues += 1
    fields = {"step": source.step} if source.driver is Driver.STEP else {"plan_off": source.workspace_root is None}
    if source.driver is Driver.STEP:
        state.awaiting_probe = True
    _event(source, "loop.probe_reissued", attempt=state.probe_reissues, **fields)
    return Result(Status.PENDING, call, note="re-running checks (history was compacted)",
                  pending_kind=PendingKind.REISSUE)


def record(source: Input, state: State, outcome: probegate.GateOutcome, findings: str,
           evidence: EvidenceServices) -> None:
    """Single shared check-state settlement; F44 progress bookkeeping stays shared."""
    state.last_gate_ran = bool(outcome.ran)
    state.last_gate_participation = outcome.participation
    state.gate_replan_required = bool(outcome.replan_after_survey)
    if outcome.transport_unknown:
        state.gate_fresh = False
        return
    if state.gate_replan_required:
        state.gate_fresh = False
        source.log.emit("loop.gate_survey_only", level="info")
        return
    if not outcome.ran:
        state.gate_fresh = True
        return
    if findings:
        state.last_gate_red = True
        state.gate_fresh = False
        evidence.progress(findings, source.body.get("messages"))
        return
    if probegate.gate_is_partial(outcome):
        source.log.emit("loop.gate_partial", level="warn", missing=len(outcome.unran), checks=outcome.unran[:6])
        state.gate_fresh = True
        return
    state.last_gate_red = False
    state.gate_fresh = True
    state.last_gate_testless = not proberun.gate_ran_tests(outcome.report)
    state.last_gate_skipped = proberun.gate_skipped_count(outcome.report)
    evidence.progress("", source.body.get("messages"))


def passing_test_regression(state: State, report) -> str:
    now = probegate.gate_passing_by_command(report)
    if not now:
        return ""
    highs = getattr(state, "tests_passed_high", None)
    highs = dict(highs) if isinstance(highs, dict) else {}
    worst = None
    for command, passed in now.items():
        was = highs.get(command, 0)
        if passed < was and (worst is None or was - passed > worst[1] - worst[2]):
            worst = command, was, passed
        highs[command] = max(was, passed)
    state.tests_passed_high = highs
    if worst is None:
        return ""
    state.last_regression = worst
    return prompts.render("tests_regressed", was=str(worst[1]), now=str(worst[2]))


def periodic_result(source: Input, state: State, evidence: EvidenceServices,
                    judgments: JudgmentServices) -> Result:
    if not state.periodic_probe:
        return Result(Status.NOT_DUE)
    state.periodic_probe = state.awaiting_probe = False
    raw = evidence.raw(source.body.get("messages", []), state.probe_call_id)
    outcome = evidence.read(state.gate_plan, raw, source.log)
    error = evidence.error(outcome)
    _event(source, "loop.periodic_gate_result", ran=outcome.ran, spoke=bool(error))
    fresh = state.gate_fresh
    record(source, state, outcome, error, evidence)
    state.gate_fresh = fresh  # never pre-satisfy a later done claim
    if error:
        reset = judgments.runner(outcome)
        if reset:
            return Result(Status.OBSERVED, text=reset, outcome=outcome)
        reset = judgments.module(outcome)
        if reset is not None:
            return Result(Status.OBSERVED, text=reset, outcome=outcome)
    if not error and outcome.ran:
        lost = passing_test_regression(state, outcome.report)
        if lost:
            command, high, now = state.last_regression
            _event(source, "loop.tests_regressed", level="warn", command=command, high=high, now=now)
            return Result(Status.OBSERVED, text=prompts.render("periodic_gate", truth=lost), outcome=outcome)
    return Result(Status.OBSERVED if error else Status.SILENT,
                  text=prompts.render("periodic_gate", truth=error) if error else None, outcome=outcome)


def completion_result(source: Input, state: State, evidence: EvidenceServices) -> Result:
    """Objective checks only. None text means no checker veto, NOT task approval."""
    raw = evidence.raw(source.body.get("messages", []), state.probe_call_id)
    outcome = evidence.read(state.gate_plan, raw, source.log)
    findings = evidence.error(outcome)
    record(source, state, outcome, findings, evidence)
    if outcome.transport_unknown:
        return Result(Status.OBSERVED, text=prompts.load("probe_transport_unknown"), outcome=outcome)
    if not outcome.ran:
        _event(source, "loop.gate", plan_off=True, blocked=False, gate_ran=False,
               replan_after_survey=bool(outcome.replan_after_survey))
        return Result(Status.SILENT, outcome=outcome)
    return Result(Status.OBSERVED if findings else Status.SILENT, text=findings or None, outcome=outcome)


class ReplanHook(Protocol):
    def __call__(self, source: Input, state: State, services: ProbeServices, *,
                 periodic: bool = False) -> Result: ...


@dataclass(frozen=True)
class ResumeHooks:
    # Required policy composition from the same selected Definition, not facts.
    reissue: Callable[[Input, State, ProbeServices, EvidenceServices], Result]
    replan: ReplanHook


def _resume_result(result: Result, allowed: tuple[Status, ...]) -> Result:
    if not isinstance(result, Result):
        raise TypeError("repository-check hook must return Result")
    if not isinstance(result.status, Status) or result.status not in allowed:
        raise ValueError("repository-check hook returned an invalid status")
    if result.status is Status.PENDING:
        if not isinstance(result.call, dict) or not result.call:
            raise ValueError("pending repository-check result requires a nonempty call")
    elif result.call is not None:
        raise ValueError("nonpending repository-check result cannot carry a call")
    return result


def resume(source: Input, state: State, services: ProbeServices, evidence: EvidenceServices,
           judgments: JudgmentServices, hooks: ResumeHooks) -> Result:
    """Pending periodic lifecycle, preserving task-vs-step reader ordering."""
    if not state.periodic_probe:
        return Result(Status.NOT_DUE)
    if source.driver is Driver.TASK:
        recovered = _resume_result(hooks.reissue(source, state, services, evidence),
            (Status.NOT_DUE, Status.OBSERVED, Status.PENDING, Status.UNAVAILABLE))
        if recovered.call is not None:
            return recovered
    page = transport(source, state, services, evidence)
    if page.call is not None:
        if source.driver is Driver.STEP:
            state.awaiting_probe = True
        return page
    result = periodic_result(source, state, evidence, judgments)
    if not result.text:
        followup = _resume_result(hooks.replan(source, state, services, periodic=True),
            (Status.NOT_DUE, Status.PENDING, Status.UNAVAILABLE))
        if followup.call is not None:
            return followup
    return result


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[[Input, State, ProbeServices], Result]
    resume: Callable[[Input, State, ProbeServices, EvidenceServices, JudgmentServices, ResumeHooks], Result]
    observe: Callable[..., None]
    completion: Callable[[Input, State, EvidenceServices], Result]
    replan: Callable[..., Result]
    reissue: Callable[[Input, State, ProbeServices, EvidenceServices], Result]


DEFINITION = Definition(Policy(
    "repository-check-lifecycle", "repository-checks", 4, family_id="F40", triggers=(("periodic", 5),),
    prompts=("periodic_gate", "probe_transport_unknown", "tests_regressed"),
    state="existing task/session probe id/plan, helper readiness, periodic flags/cadence/replan/reissue counters, check mirror and per-command passing highs; fresh session on a new task",
    services=("probe-plan", "shell-schema", "raw-tool-result", "gate-reader", "checker-findings", "shared-progress", "selected-runner-judgment", "selected-module-judgment"),
    hooks=tuple(Reference("cria/loop.py", name) for name in (
        "guard_gate_op", "guard_gate_replan_after_survey", "guard_periodic_replan_after_survey", "guard_gate_transport",
        "guard_periodic_gate", "guard_periodic_result", "guard_gate_verdict", "record_gate_state", "guard_probe_reissue",
        "passing_test_regression",
        "Loop._work_item", "Loop._verify_after_probe", "Loop._drive_single_item")),
    regressions=tuple(Reference("tests/test_repository_check_policy.py", name) for name in (
        "test_admission_matches_current_periodic_owner", "test_periodic_result_matches_current_owner",
        "test_shared_settlement_matches_current_owner", "test_task_and_step_rewrite_order",
        "test_disabled_and_replacement_do_not_touch_unselected_state")), migrated=False),
    admit, resume, observe_acting_turn, completion_result, replan, reissue)
DEFINITIONS = (DEFINITION,)


@dataclass(frozen=True)
class Selected:
    definition: Definition | None

    def admit(self, source: Callable[[], Input], state: State, services: Callable[[], ProbeServices]) -> Result:
        if self.definition is None:
            return Result(Status.NOT_SELECTED)
        return self.definition.execute(source(), state, services())

    def resume(self, source: Callable[[], Input], state: State, services: Callable[[], ProbeServices],
               evidence: Callable[[], EvidenceServices], judgments: Callable[[], JudgmentServices]) -> Result:
        if self.definition is None:
            return Result(Status.NOT_SELECTED)
        return self.definition.resume(source(), state, services(), evidence(), judgments(),
                                      ResumeHooks(self.definition.reissue, self.definition.replan))

    def replan(self, source: Callable[[], Input], state: State, services: Callable[[], ProbeServices],
               *, periodic: bool = False) -> Result:
        if self.definition is None:
            return Result(Status.NOT_SELECTED)
        return self.definition.replan(source(), state, services(), periodic=periodic)

    def reissue(self, source: Callable[[], Input], state: State, services: Callable[[], ProbeServices],
                evidence: Callable[[], EvidenceServices]) -> Result:
        if self.definition is None:
            return Result(Status.NOT_SELECTED)
        return self.definition.reissue(source(), state, services(), evidence())

    def observe(self, state: State, *, acting: bool) -> None:
        if self.definition is not None:
            self.definition.observe(state, acting=acting)

    def completion(self, source: Callable[[], Input], state: State, evidence: Callable[[], EvidenceServices]) -> Result:
        if self.definition is None:
            return Result(Status.NOT_SELECTED)
        return self.definition.completion(source(), state, evidence())
