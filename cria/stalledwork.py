"""Grounded stalled-work intervention: one owner across every lifecycle stage.

No loop import, executor or private copy of a gate/parser/reader. Drivers supply
shared facts and provider transport; groundedaction owns actual author/recovery/
vet decisions. Integration removes the old loop bodies and author suppression
prelude; running both would double-consume evidence.

Shared gate progress, write-result tracking and transport remain foundations.
They may be observed by completion even when this intervention is not selected.
The state below is task/session local, transient on reconstruction, and never
copied to another task/fork. Selection is stable while a probe/steer is pending.
"""
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Protocol

from . import checkmotion, prompts, groundedaction
from .assistcontract import Policy, Reference
from .writeobservation import ForwardedCall

REFUSAL_THRESHOLD = 3
REFUSAL_WINDOW = 12
WRITE_THRESHOLD = 5
WRITE_WINDOW = WRITE_THRESHOLD * 3
STALL_ROUNDS = 2


class Trigger(Enum):
    REFUSAL = "refusal"
    WHEEL_SPIN = "wheel_spin"
    PROGRESS_STALL = "thrash"


class Status(Enum):
    NOT_SELECTED = "not-selected"
    NO_OP = "no-op"
    ARMED = "armed"
    PENDING = "pending"
    STEER = "steer"
    # The author answered ON_TRACK (groundedaction.Verdict.ON_TRACK): an answer, not a failure.
    ON_TRACK = "on-track"
    WITHHELD = "withheld"
    DELIVERED = "delivered"
    RESET = "reset"


class Log(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


@dataclass(frozen=True)
class ObservationFacts:
    calls: tuple[ForwardedCall, ...]
    # Existing refusal-window measurement: tail of assistant call turns, not a
    # reconstructed text count or similarity detector. Description is refused too.
    refused_count: int
    last_refused: str
    unlanded_ids: frozenset[str] = frozenset()
    sanctioned_rewrites: frozenset[str] = frozenset()
    # Production owns the monotonic retained-call fact clock independently of
    # optional observation. This is the sequence BEFORE this actual call batch.
    # None preserves the standalone policy's historical local counter contract.
    sequence_start: int | None = None
    # The error sets of the coder's own check runs since the given write call (oldest first), read only
    # when five writes are about to trip: errors that were fixed and never came back are progress.
    check_outputs: Callable[[str], tuple[frozenset[str], ...]] | None = None


@dataclass(frozen=True)
class PendingProbe:
    trigger: Trigger
    call: dict


@dataclass(frozen=True)
class Steer:
    text: str
    source: str
    trigger: Trigger
    authored: bool = False
    grounded: bool = False
    # The existing driver's redirect envelope is not part of the authored action.
    redirect_envelope: bool = False
    author_status: Status = Status.NO_OP
    checks_reattached: bool = False


@dataclass
class State:
    recent_writes: list[str | None] = field(default_factory=list)
    recent_write_ids: list[str | None] = field(default_factory=list)
    spin_recheck: str = ""
    spin_path: str = ""
    spin_due: bool = False
    action_seq: int = 0
    blocked_fired_seq: int = -10_000
    repeat_action: str = ""
    repeat_count: int = 0
    redirect_due: bool = False
    pending_probe: PendingProbe | None = None
    pending_steer: Steer | None = None
    last_delivered: Steer | None = None
    # These record author attempts, not delivery or completion approval. Preserve
    # the one second look, then exact-check reattachment/silence contract.
    steered_checks_text: str = ""
    same_checks_relooked: bool = False


class StateAccess(Protocol):
    """Mutable lifecycle surface; production views reference their existing owner.

    This declares no storage or serialization. ``State`` remains the standalone
    implementation; a driver may provide an aliasing view of its task fields.
    Pending probe/steer values retain exact object identity across calls.
    """
    recent_writes: list[str | None]
    recent_write_ids: list[str | None]
    spin_recheck: str
    spin_path: str
    spin_due: bool
    action_seq: int
    blocked_fired_seq: int
    repeat_action: str
    repeat_count: int
    redirect_due: bool
    pending_probe: PendingProbe | None
    pending_steer: Steer | None
    last_delivered: Steer | None
    steered_checks_text: str
    same_checks_relooked: bool


@dataclass(frozen=True)
class Result:
    status: Status
    trigger: Trigger | None = None
    probe: PendingProbe | None = None
    steer: Steer | None = None


@dataclass(frozen=True)
class ObservationInput:
    # Shared write bookkeeping MUST already have run outside assist selection.
    # This lazy gather only reads facts; it must never repeat that bookkeeping.
    measure: Callable[[], ObservationFacts]
    log: Log
    step: int | None = None
    # Exact offered identity, not delivery credit. Permit first-compliance
    # validation before the caller publishes acknowledgement.
    offered_steer: Steer | None = None


def observe(source: ObservationInput, state: StateAccess, *, enabled: bool = True) -> Result:
    if not enabled:
        return Result(Status.NOT_SELECTED)
    if state.pending_steer is not None and state.pending_steer is not source.offered_steer:
        return Result(Status.PENDING, state.pending_steer.trigger, steer=state.pending_steer)
    facts = source.measure()
    # Refusals run first, so an armed refusal keeps this completion's writes out of the window;
    # admit flushes the window only when it confirms the fire.
    for ordinal, _call in enumerate(facts.calls, 1):
        if state.redirect_due or state.spin_due or state.pending_probe is not None:
            break
        if facts.sequence_start is None:
            state.action_seq += 1
            sequence = state.action_seq
        else:
            sequence = facts.sequence_start + ordinal
        if (facts.refused_count >= REFUSAL_THRESHOLD
                and sequence - state.blocked_fired_seq >= REFUSAL_WINDOW):
            state.blocked_fired_seq = sequence
            state.redirect_due = True
            # The write window is NOT cleared here: a nomination is not yet a fire. Accrual is frozen
            # while the latch is pending (both loops break on redirect_due, 6f1ab0a8), and admit
            # clears the window only when it confirms the fire; a withdrawn nomination keeps it.
            state.repeat_action, state.repeat_count = facts.last_refused, facts.refused_count
            source.log.emit("loop.refusals", steer="refusals", step=source.step,
                            count=facts.refused_count, action=facts.last_refused.strip()[:120]
                            + ("…" if len(facts.last_refused.strip()) > 120 else ""))
    if facts.unlanded_ids:
        kept = [(path, cid) for path, cid in zip(state.recent_writes, state.recent_write_ids)
                if cid is None or cid not in facts.unlanded_ids]
        dropped = len(state.recent_writes) - len(kept)
        if dropped:
            source.log.emit("loop.write_streak_corrected", level="info", dropped=dropped)
        state.recent_writes = [path for path, _ in kept]
        state.recent_write_ids = [cid for _, cid in kept]

    def armed(path):
        return (path is not None and not state.spin_due and not state.redirect_due
                and state.pending_probe is None and path not in facts.sanctioned_rewrites)

    def trip(path):
        state.spin_due, state.spin_path = True, path
        state.recent_writes, state.recent_write_ids = [], []
        state.spin_recheck = ""
        source.log.emit("loop.wheel_spinning", steer="wheel-spin", step=source.step,
                        path=path, writes=WRITE_THRESHOLD)

    def fire(path):
        # Five writes to one file are a wheel only while the checks keep naming the same fault. Errors
        # that were fixed (and none returned) across the runs since the window opened mean each edit
        # landed: the window restarts, so a later real spiral still needs five more writes.
        first = next((cid for p, cid in zip(state.recent_writes, state.recent_write_ids)
                      if p == path and cid), None)
        if first is not None and facts.check_outputs is not None:
            runs = facts.check_outputs(first)
            if checkmotion.moving(runs):
                state.recent_writes, state.recent_write_ids = [], []
                state.spin_recheck = ""
                source.log.emit("loop.wheel_spin_progress", level="info", path=path, runs=len(runs))
                return
        trip(path)

    pending = state.spin_recheck
    if pending:
        state.spin_recheck = ""
        if state.recent_writes.count(pending) >= WRITE_THRESHOLD and armed(pending):
            fire(pending)
    this_turn = {}
    for call in facts.calls:
        if state.redirect_due or state.spin_due or state.pending_probe is not None:
            break
        path = call.write_path
        state.recent_writes.append(path)
        state.recent_write_ids.append(call.call_id)
        del state.recent_writes[:-WRITE_WINDOW]
        del state.recent_write_ids[:-WRITE_WINDOW]
        if path is not None:
            this_turn[path] = this_turn.get(path, 0) + 1
            counted = state.recent_writes.count(path) - (this_turn[path] - 1)
            if counted >= WRITE_THRESHOLD and armed(path):
                fire(path)
            elif this_turn[path] > 1 and state.recent_writes.count(path) >= WRITE_THRESHOLD:
                state.spin_recheck = path
    trigger = Trigger.REFUSAL if state.redirect_due else Trigger.WHEEL_SPIN if state.spin_due else None
    return Result(Status.ARMED if trigger else Status.NO_OP, trigger)


@dataclass(frozen=True)
class AdmissionInput:
    # The existing gate planner/admission owns shell availability, workspace reach,
    # gate plan, transport and survey. None retains the existing no-shell behavior.
    admit_probe: Callable[[], dict | None]
    log: Log
    measure_refusals: Callable[[], tuple[int, str]]
    step: int | None = None


def _redirect(count: int, action: str, truth: str) -> str:
    # Existing refusal floor for an author that gave NO answer (or no reasoner at all). Never
    # after an ON_TRACK answer: that is the reasoner answering, and overriding it is #4's sin.
    if count > 1:
        observed = f"{count} of your recent calls were refused, so none of them ran"
    elif count:
        observed = "your last call was refused, so it did not run"
    else:
        observed = "you are not getting a new outcome from these actions"
    return prompts.render("redirect_canned", ground_truth=f"{truth}\n\n" if truth else "",
                          observed=observed, repeat_action=action)


def admit(source: AdmissionInput, state: StateAccess, *, enabled: bool = True) -> Result:
    if not enabled:
        return Result(Status.NOT_SELECTED)
    if state.pending_probe is not None:
        return Result(Status.PENDING, state.pending_probe.trigger, probe=state.pending_probe)
    if state.pending_steer is not None:
        return Result(Status.PENDING, state.pending_steer.trigger, steer=state.pending_steer)
    if state.redirect_due:
        # Observation used the history BEFORE the forwarded call returned. Keep its
        # latch until admission, then withdraw only when the SAME window no longer
        # meets its numeric threshold. A ran call is not evidence of recovery.
        count, last = source.measure_refusals()
        if count < REFUSAL_THRESHOLD:
            # NOTHING FIRED, so nothing the arm reserved for a fire is spent. The arm stamped the
            # cooldown at its own sequence S, which it could only do because the previous stamp was
            # <= S - REFUSAL_WINDOW; observe cannot re-arm while the latch is pending, so the stamp
            # is still S here, and S - REFUSAL_WINDOW is equivalent to the previous stamp for every
            # later sequence. Without this, run07's withdrawn nomination blocked a genuinely
            # eligible 3-refusal window for the next 11 calls.
            state.redirect_due = False
            state.blocked_fired_seq -= REFUSAL_WINDOW
            source.log.emit("loop.refusals_withdrawn", step=source.step, count=count)
        else:
            state.repeat_count, state.repeat_action = count, last
            # The fire is confirmed: it consumes the write window, so the coder's compliance
            # writes cannot re-trip a spin probe with the writes that preceded the redirect.
            state.recent_writes, state.recent_write_ids = [], []
    trigger = Trigger.REFUSAL if state.redirect_due else Trigger.WHEEL_SPIN if state.spin_due else None
    if trigger is None:
        return Result(Status.NO_OP)
    if trigger is Trigger.REFUSAL:
        state.redirect_due = state.spin_due = False  # refusal supersedes pending spin
    else:
        state.spin_due = False
    call = source.admit_probe()
    if call is not None:
        pending = state.pending_probe = PendingProbe(trigger, call)
        if trigger is Trigger.REFUSAL:
            source.log.emit("loop.redirect_probe", step=source.step)
        else:
            source.log.emit("loop.spin_probe", step=source.step, path=state.spin_path)
        return Result(Status.PENDING, trigger, probe=pending)
    if trigger is Trigger.REFUSAL:
        text = _redirect(state.repeat_count, state.repeat_action, "")
        steer = Steer(text, "refusal guard", trigger)
        source.log.emit("loop.redirect", step=source.step, canned=True, chars=len(text))
    else:
        text = prompts.render("spin_nogate", spin_path=state.spin_path)
        steer = Steer(text, "wheel-spin guard", trigger)
        source.log.emit("loop.spin_probe_result", step=source.step, canned=True)
    state.pending_steer = steer
    return Result(Status.STEER, trigger, steer=steer)


@dataclass(frozen=True)
class AuthorServices:
    original_task: str
    current_checks: Callable[[], str]
    superseded_by_coder_run: Callable[[str], str]
    checks_visible: Callable[[str], bool]
    checks_ran_before: Callable[[list[str]], str]
    engine: groundedaction.GroundedActions
    seat: groundedaction.AuthorInput
    log: Log
    # Task-aware drivers bind the shared task-review evidence/judgment/delivery seat.
    # Standalone action authors retain their distinct author/vet contract.
    review: Callable[[Trigger], "AuthorResult"] | None = None


@dataclass(frozen=True)
class AuthorResult:
    text: str | None
    status: Status
    reattached: bool = False


def _author(source: AuthorServices, state: StateAccess, trigger: Trigger, truth: str = "",
            stall_rounds: int = 0, *, actions: groundedaction.Definition) -> AuthorResult:
    if source.review is not None:
        return source.review(trigger)
    checks = truth.strip() or source.current_checks().strip()
    superseded = source.superseded_by_coder_run(checks)
    if superseded:
        source.log.emit("loop.steer_checks_stale", level="info", condition=trigger.value,
                        tally=superseded, head=source.engine.facts.clip(checks, 100))
        checks, truth = "", ""
    if checks and checks == state.steered_checks_text and not state.same_checks_relooked:
        state.same_checks_relooked = True
    elif checks and checks == state.steered_checks_text:
        if not source.checks_visible(checks):
            since = source.engine.facts.writes_since_last_gate(source.seat.body.get("messages", []))
            source.log.emit("loop.steer_checks_reattached", level="info", condition=trigger.value,
                            since=since, head=source.engine.facts.clip(checks, 100))
            text = prompts.render("steer_checks_repeat", findings=checks,
                                  seeded_test_rule=prompts.load("seeded_test_rule").strip(),
                                  since=source.checks_ran_before(since))
            return AuthorResult(text, Status.STEER, True)
        source.log.emit("loop.steer_same_checks", level="info", condition=trigger.value,
                        head=source.engine.facts.clip(checks, 100))
        return AuthorResult(None, Status.WITHHELD)
    if checks != state.steered_checks_text:
        state.same_checks_relooked = False
    state.steered_checks_text = checks
    facts = replace(source.seat.facts, original_task=source.original_task,
                    last_gate_flag=source.current_checks(),
                    recent_writes=tuple(state.recent_writes), repeat_count=state.repeat_count,
                    repeat_action=state.repeat_action, spin_path=state.spin_path,
                    gate_stall=stall_rounds or source.seat.facts.gate_stall,
                    write_threshold=WRITE_THRESHOLD)
    seat = replace(source.seat, facts=facts, condition=trigger.value, truth_text=truth)
    text = actions.author(source.engine, seat, definition=actions)
    if text is groundedaction.Verdict.ON_TRACK:
        return AuthorResult(None, Status.ON_TRACK)
    return AuthorResult(text, Status.STEER if text else Status.WITHHELD)


@dataclass(frozen=True)
class ReturnedProbeInput:
    ticket: PendingProbe
    # Parse and transport completion happen in the shared gate foundation. Record
    # it BEFORE any author/silence decision, including unknown/partial outcomes.
    record_reading: Callable[[], None]
    ground_truth: Callable[[], str]
    author: AuthorServices | None
    log: Log
    step: int | None = None


def settle(source: ReturnedProbeInput, state: StateAccess, *, enabled: bool = True,
           actions: groundedaction.Definition = groundedaction.DEFINITION) -> Result:
    if not enabled:
        return Result(Status.NOT_SELECTED)
    if state.pending_probe is None or source.ticket is not state.pending_probe:
        return Result(Status.NO_OP)
    source.record_reading()
    trigger = source.ticket.trigger
    state.pending_probe = None
    truth = source.ground_truth()
    author_result = (_author(source.author, state, trigger, actions=actions) if source.author is not None
                     else AuthorResult(None, Status.NO_OP))
    authored = author_result.text
    if author_result.status is Status.ON_TRACK:
        # THE AUTHOR ANSWERED, SO NOTHING IS DELIVERED. The floors below exist for an author that
        # could not answer; after ON_TRACK they overrode the trusted reasoner with "Choose a DIFFERENT
        # next action" / "Stop rewriting" (#4, #3). Nothing factual is lost by the silence: the probe's
        # own result reaches the coder as its separate checks message, and each refused call keeps its
        # own refusal result. Measured 2026-10-27 over ~/.cria/logs: 38 settled ON_TRACK answers (30
        # refusal, 8 wheel-spin) each drew a canned floor. ornith1.5_9b session 01a168cb call 0077 was
        # told "Continuing down this line will not change the outcome" on the first coder call after it
        # had rerun the refused command, corrected, successfully; it ruminated 8,244 tokens and was aborted.
        source.log.emit("loop.stalled_on_track", step=source.step, condition=trigger.value,
                        grounded=bool(truth))
        return Result(Status.ON_TRACK, trigger)
    if source.author is not None and source.author.review is not None and not authored:
        # An undecidable/suppressed focused review is silence, not a canned diagnosis.
        return Result(Status.WITHHELD, trigger)
    if trigger is Trigger.REFUSAL:
        text = authored or _redirect(state.repeat_count, state.repeat_action, truth)
        steer = Steer(text, "refusal guard", trigger, bool(authored), bool(truth),
                      source.author is None or source.author.review is None)
        source.log.emit("loop.redirect", step=source.step, chars=len(text))
    else:
        canned = (prompts.render("spin_ground_truth", spin_path=state.spin_path, truth=truth)
                  if truth else prompts.render("spin_no_truth", spin_path=state.spin_path))
        steer = Steer(authored or canned, "wheel-spin guard", trigger, bool(authored), bool(truth))
        source.log.emit("loop.spin_probe_result", step=source.step,
                        authored=bool(authored), grounded=bool(truth))
    steer = Steer(steer.text, steer.source, steer.trigger, steer.authored, steer.grounded,
                  steer.redirect_envelope, author_result.status, author_result.reattached)
    state.pending_steer = steer
    return Result(Status.STEER, trigger, steer=steer)


@dataclass(frozen=True)
class ProgressInput:
    truth: str
    stalled_rounds: int
    author: AuthorServices | None
    log: Log


def progress(source: ProgressInput, state: StateAccess, *, enabled: bool = True,
             actions: groundedaction.Definition = groundedaction.DEFINITION) -> Result:
    """Upgrade existing periodic truth only at its existing persistent-red trigger.

    The shared gate-progress recorder owns the streak and neutral unknown handling.
    This stage never starts a probe, declares completion or replaces a distinct
    runner/module-state judgment. Driver calls it at the existing periodic seat.
    """
    if not enabled:
        return Result(Status.NOT_SELECTED)
    if not source.truth or source.author is None or source.stalled_rounds < STALL_ROUNDS:
        return Result(Status.NO_OP)
    if state.pending_probe is not None or state.pending_steer is not None:
        return Result(Status.PENDING)
    authored = _author(source.author, state, Trigger.PROGRESS_STALL, source.truth,
                       source.stalled_rounds, actions=actions)
    text = authored.text
    source.log.emit("loop.thrash_diagnosed", plan_off=True, stall=source.stalled_rounds)
    if source.author.review is not None and not text:
        return Result(authored.status, Trigger.PROGRESS_STALL)
    steer = Steer(text or source.truth, "periodic check-in", Trigger.PROGRESS_STALL,
                  bool(text), True, author_status=authored.status, checks_reattached=authored.reattached)
    state.pending_steer = steer
    return Result(Status.STEER, Trigger.PROGRESS_STALL, steer=steer)


def acknowledge(state: StateAccess, steer: Steer, *, enabled: bool = True) -> Result:
    """Only the caller's actual coder-delivery boundary acknowledges its own steer."""
    if not enabled:
        return Result(Status.NOT_SELECTED)
    if state.pending_steer is not steer:
        return Result(Status.NO_OP)
    state.last_delivered, state.pending_steer = steer, None
    return Result(Status.DELIVERED, steer.trigger, steer=steer)


def reset_step(state: StateAccess, *, enabled: bool = True) -> Result:
    """Existing step advance clears the write window, not author/check authority."""
    if not enabled:
        return Result(Status.NOT_SELECTED)
    state.recent_writes, state.recent_write_ids = [], []
    state.spin_path, state.spin_due, state.redirect_due = "", False, False
    return Result(Status.RESET)


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[..., Result]
    admit: Callable[..., Result]
    settle_stage: Callable[..., Result]
    progress_stage: Callable[..., Result]
    acknowledge: Callable[..., Result]
    reset_step: Callable[..., Result]
    actions: groundedaction.Definition = groundedaction.DEFINITION

    def settle(self, source: ReturnedProbeInput, state: StateAccess, *, enabled: bool = True) -> Result:
        return self.settle_stage(source, state, enabled=enabled, actions=self.actions)

    def progress(self, source: ProgressInput, state: StateAccess, *, enabled: bool = True) -> Result:
        return self.progress_stage(source, state, enabled=enabled, actions=self.actions)


DEFINITION = Definition(
    Policy("grounded-stalled-work", "stalled-work-observation", 5, family_id="F44",
           prompts=("spin_nogate", "spin_ground_truth", "spin_no_truth", "redirect_canned",
                    "steer_checks_repeat", "steer_diagnose", "steer_triggers", "thrash_edits",
                    "automatic_check_request", "automatic_check_result",
                    "confirm_auth_claim", "ledger_dedup_note", "reasoner_coder_tools",
                    "steer_blames_the_service", "steer_checks_age", "steer_diagnose_user",
                    "steer_diagnostic_action", "steer_diagnostic_answer", "steer_diagnostic_grounding_above",
                    "steer_diagnostic_no_findings", "steer_diagnostic_no_grounding", "steer_diagnostic_no_refusals",
                    "steer_dictates_code", "steer_historical_author_request", "steer_reasoning_recover",
                    "steer_session_evidence", "steer_session_root", "seeded_test_rule"),
           state="State per session/task; transient on reconstruction; stable selection until pending effects settle",
           services=("forwarded-call-and-unlanded-write-facts", "shared-write-registry",
                     "required-retained-call-sequence", "exact-current-frame-offered-steer-identity",
                     "probe-admission-and-transport", "authoritative-gate-recording",
                     "exact-check-evidence", "reasoner-summarize-and-inspection-provider",
                     "shared-session-evidence-readers", "shared-workspace-and-ledger-facts"),
           hooks=(Reference("cria/loop.py", "Loop.drive"),
                  Reference("cria/loop.py", "_prepare_stalled_reply"),
                  Reference("cria/loop.py", "_settle_stalled_reply"),
                  Reference("cria/loop.py", "guard_intervene"),
                  Reference("cria/loop.py", "guard_probe_steer"),
                  Reference("cria/loop.py", "Loop._coder_turn_impl"),
                  Reference("cria/loop.py", "Loop._work_item"),
                  Reference("cria/loop.py", "Loop._verify_after_probe"),
                  Reference("cria/loop.py", "Loop._drive_single_item"),
                  Reference("cria/loop.py", "Loop._advance"),
                  Reference("cria/loop.py", "author_steer")),
           regressions=(Reference("tests/loop_orientation/test_loop_orientation_stalled_work.py", "test_a_refusal_arms_a_nomination_that_admission_confirms_or_withdraws"),
                        Reference("tests/loop_orientation/test_loop_orientation_stalled_work.py", "test_five_writes_to_one_path_trip_a_wheel_spin_unless_corrected_sanctioned_or_aged_out"),
                        Reference("tests/loop_orientation/test_loop_orientation_stalled_work.py", "test_settlement_records_the_reading_before_the_author_and_a_directive_carries_the_envelope"),
                        Reference("tests/loop_orientation/test_loop_orientation_stalled_work.py", "test_an_on_track_answer_delivers_nothing_but_no_answer_keeps_the_facts"),
                        Reference("tests/loop_orientation/test_loop_orientation_stalled_work.py", "test_unchanged_checks_get_one_second_look_then_come_back_verbatim_not_re_diagnosed"),
                        Reference("tests/loop_orientation/test_loop_orientation_stalled_work.py", "test_a_stale_ticket_touches_nothing_and_a_step_advance_keeps_the_check_authority"),
                        Reference("tests-before-reset-20261031:tests/test_grounded_action_policy.py", "test_generic_vet_preserves_real_guard_order_and_question_transcript"),
                        Reference("tests/loop_orientation/test_loop_orientation_stalled_work.py", "test_pending_steer_suspends_detection_and_only_the_exact_delivery_acknowledges"),
                        Reference("tests/gates_completion/test_gates_completion_history.py", "test_automatic_checks_reach_a_reasoner_as_observations_never_as_the_coders_actions"),
                        Reference("tests-before-reset-20261031:tests/test_steer_check_origin.py", "test_paged_gate_keeps_complete_checker_lines_and_unknown_stays_unknown"),
                        Reference("tests/loop_orientation/test_loop_orientation_steer_facts.py", "test_an_auth_requirement_the_evidence_does_not_show_is_asked_about_not_delivered"),
                        Reference("tests/loop_rest/test_loop_rest_scenario2_sw2_steer_author.py", "test_every_kind_of_reasoner_reply_is_delivered_or_withheld_with_its_reason_on_the_plain_path"),
                        Reference("tests/loop_rest/test_loop_rest_scenario2_sw2_steer_author.py", "test_an_on_track_answer_over_thinking_that_says_stuck_is_asked_again_once"),
                        Reference("tests/loop_rest/test_loop_rest_scenario2_sw2_steer_author.py", "test_each_rejection_reason_of_the_steer_funnel_names_its_guard_and_logs_it"),
                        Reference("tests-before-reset-20261031:tests/test_grounded_action_policy.py", "test_empty_structured_refusal_ledger_supersedes_stale_legacy_names"),
                        Reference("tests-before-reset-20261031:tests/test_grounded_action_policy.py", "test_shared_write_results_and_ids_survive_pending_steer_independent_of_selection"),
                        Reference("tests-before-reset-20261031:tests/test_grounded_action_policy.py", "test_replacing_source_author_definition_prevents_every_generation_and_vet_call"),
                        Reference("tests-before-reset-20261031:tests/test_grounded_action_policy.py", "test_replacing_source_vet_definition_is_honored_inside_full_intervention"),
                        Reference("tests-before-reset-20261031:tests/test_stalled_work_production_binding.py", "test_public_disabled_selection_does_not_arm_legacy_refusal_or_spin"),
                        Reference("tests-before-reset-20261031:tests/test_stalled_work_production_binding.py", "test_public_exact_observation_replacement_owns_the_only_detection"),
                        Reference("tests-before-reset-20261031:tests/test_stalled_work_production_binding.py", "test_public_periodic_progress_calls_same_selected_nested_author_and_vet"),
                        Reference("tests-before-reset-20261031:tests/test_stalled_work_production_binding.py", "test_public_returned_probe_requires_exact_ticket_and_matching_tool_result")),
           migrated=False),
    observe, admit, settle, progress, acknowledge, reset_step)
