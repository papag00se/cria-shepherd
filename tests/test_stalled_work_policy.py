"""Offline staged stalled-work policy. Measurements and author/vet are fake services.

This proves source behavior/selection, not production hook coverage or efficacy.
"""
import copy
from dataclasses import replace

from cria import stalledwork as sw


class Log:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def observation(calls=(), *, refused=0, unlanded=(), sanctioned=(), records=None, log=None):
    facts = sw.ObservationFacts(tuple(sw.ForwardedCall(*call) for call in calls),
                                refused, "a call that was actually refused",
                                frozenset(unlanded), frozenset(sanctioned))
    # Assembly records shared facts before selecting F44, never inside observe.
    if records is not None:
        records.append("registered")
    return sw.ObservationInput(lambda: facts, log or Log())


def fallback(count, action, truth):
    return f"Measured refusal count={count}; action={action}; exact checks={truth}"


def measured(count, action="a call that was actually refused"):
    """The admission-time refusal window this test means. Production measures it with the same
    owner the observation used (``loop._refusals_in_window`` over the inbound history)."""
    return lambda: (count, action)


def unmeasured():
    """Admission must not measure refusals when no refusal latch is set."""
    def forbidden():
        raise AssertionError("admission measured refusals without a refusal latch")
    return forbidden


def admit(state, *, call=None, author=None, record=None, truth="exact check output", log=None,
          refusals=None):
    source = sw.AdmissionInput(lambda: call, log or Log(), refusals or unmeasured())
    result = sw.DEFINITION.admit(source, state)
    if result.probe is None:
        return result
    returned = sw.ReturnedProbeInput(result.probe,
                                    lambda: record.append("recorded") if record is not None else None,
                                    lambda: truth, author, log or Log())
    return sw.DEFINITION.settle(returned, state)


def author_service(calls, *, checks="exact failure", visible=True, superseded="", text="a vetted action"):
    from stalled_work_fixtures import engine, seat
    from cria import loop
    author_seat = seat(text, checks=checks, calls=calls)
    return sw.AuthorServices("ORIGINAL TASK", lambda: checks, lambda value: superseded,
                             lambda value: visible, loop._checks_ran_before,
                             engine(), author_seat, author_seat.log)


def delivered(state, result):
    assert result.steer is not None
    assert state.last_delivered is None or state.last_delivered is not result.steer
    out = sw.DEFINITION.acknowledge(state, result.steer)
    assert out.status is sw.Status.DELIVERED
    assert state.last_delivered is result.steer and state.pending_steer is None


def test_refusal_observation_flushes_whole_completion_and_does_not_double_arm_spin():
    state, records, log = sw.State(), [], Log()
    state.recent_writes, state.recent_write_ids = ["a"] * 4, [str(i) for i in range(4)]
    result = sw.DEFINITION.execute(observation((("new", "a"), ("later", "a")),
                                              refused=5, records=records, log=log), state)
    assert result.status is sw.Status.ARMED and result.trigger is sw.Trigger.REFUSAL
    assert state.action_seq == 1 and state.repeat_count == 5
    # None of this completion's writes accrue and spin cannot arm beside the refusal. The window is
    # NOT cleared yet: arming is a nomination, and only a fire admission confirms consumes the window
    # (a withdrawn nomination keeps it; tests/test_review_adversarial_ontrack_admission.py).
    assert state.recent_writes == ["a"] * 4 and not state.spin_due
    assert records == ["registered"]
    assert log.events == [("loop.refusals", {"steer": "refusals", "step": None, "count": 5,
                                           "action": "a call that was actually refused"})]
    assert state == sw.State(recent_writes=["a"] * 4, recent_write_ids=[str(i) for i in range(4)],
                             action_seq=1, blocked_fired_seq=1, repeat_count=5,
                             repeat_action="a call that was actually refused", redirect_due=True)
    admitted = sw.DEFINITION.admit(sw.AdmissionInput(lambda: {"id": "probe"}, log,
                                   lambda: (5, "a call that was actually refused")), state)
    assert admitted.status is sw.Status.PENDING and admitted.trigger is sw.Trigger.REFUSAL
    # The confirmed fire consumes the whole window, so the writes before it cannot re-trip spin.
    assert not state.recent_writes and not state.recent_write_ids and not state.spin_due
    assert state.blocked_fired_seq == 1 and not state.redirect_due


def test_unlanded_correction_and_batched_results_precede_wheel_spin_admission():
    state, log = sw.State(), Log()
    # A batch only earns one turn's credit until returned results are known.
    batch = tuple((f"edit{i}", "a") for i in range(5))
    first = sw.DEFINITION.execute(observation(batch), state)
    assert first.status is sw.Status.NO_OP and state.spin_recheck == "a"
    assert state == sw.State(recent_writes=["a"] * 5, recent_write_ids=[f"edit{i}" for i in range(5)],
                             spin_recheck="a", action_seq=5)
    second = sw.DEFINITION.execute(observation(unlanded=("edit0", "edit1", "edit2"), log=log), state)
    assert second.status is sw.Status.NO_OP and state.recent_writes == ["a", "a"]
    assert log.events[0] == ("loop.write_streak_corrected", {"level": "info", "dropped": 3})
    for i in range(3):
        result = sw.DEFINITION.execute(observation(((f"later{i}", "a"),), log=log), state)
    assert result.status is sw.Status.ARMED and result.trigger is sw.Trigger.WHEEL_SPIN
    assert state.spin_path == "a" and not state.recent_writes
    assert state == sw.State(action_seq=8, spin_path="a", spin_due=True)
    assert log.events == [("loop.write_streak_corrected", {"level": "info", "dropped": 3}),
                          ("loop.wheel_spinning", {"steer": "wheel-spin", "step": None, "path": "a", "writes": 5})]


def test_successful_same_turn_batch_is_rechecked_once_results_return():
    state = sw.State()
    sw.DEFINITION.execute(observation(tuple((str(i), "a") for i in range(5))), state)
    result = sw.DEFINITION.execute(observation(), state)
    assert result.status is sw.Status.ARMED and state.spin_due
    assert state.spin_recheck == "" and state.recent_writes == []


def test_nonwrites_age_the_window_and_sanctioned_rewrites_do_not_trigger():
    state = sw.State()
    for i in range(5):
        sw.DEFINITION.execute(observation(((str(i), "a"),), sanctioned=("a",)), state)
    assert not state.spin_due
    for i in range(sw.WRITE_WINDOW):
        sw.DEFINITION.execute(observation(((f"read{i}", None),)), state)
    result = sw.DEFINITION.execute(observation((("fresh", "a"),)), state)
    assert result.status is sw.Status.NO_OP and state.recent_writes.count("a") == 1


def test_refusal_admission_supersedes_spin_and_settlement_records_before_author():
    state, order, calls = sw.State(redirect_due=True, spin_due=True, repeat_count=4), [], []
    author = author_service(calls)
    actual = author.engine.providers.summarize
    def run(*args, **kwargs):
        if kwargs.get("phase") == "reasoner":
            order.append("author/vet")
        return actual(*args, **kwargs)
    author.engine.providers = replace(author.engine.providers, summarize=run)
    # The inbound window still holds the 4 refusals that armed it.
    source = sw.AdmissionInput(lambda: {"id": "probe"}, Log(), measured(4))
    pending = sw.DEFINITION.admit(source, state)
    assert pending.status is sw.Status.PENDING and not state.redirect_due and not state.spin_due
    assert sw.DEFINITION.admit(source, state).probe is pending.probe
    result = sw.DEFINITION.settle(sw.ReturnedProbeInput(
        pending.probe, lambda: order.append("recorded"), lambda: "exact checker bytes",
        author, Log()), state)
    assert order == ["recorded", "author/vet"]
    assert result.steer.text == "a vetted action" and result.steer.redirect_envelope
    assert result.steer.author_status is sw.Status.STEER
    assert not state.pending_probe
    delivered(state, result)


def test_no_shell_refusal_and_wheel_spin_keep_existing_distinct_floors():
    refusal = sw.State(redirect_due=True, repeat_count=3, repeat_action="refused action")
    log = Log()
    out = admit(refusal, log=log, refusals=measured(3, "refused action"))
    text = ("Continuing down this line will not change the outcome — 3 of your recent calls were refused, "
            "so none of them ran, and the most recent action of that kind was: refused action. "
            "Choose a DIFFERENT next action and take it now via a tool call.")
    expected = sw.Steer(text, "refusal guard", sw.Trigger.REFUSAL)
    assert out == sw.Result(sw.Status.STEER, sw.Trigger.REFUSAL, steer=expected)
    assert refusal == sw.State(repeat_count=3, repeat_action="refused action", pending_steer=expected)
    assert refusal.pending_steer is out.steer and not out.steer.redirect_envelope and not out.steer.authored
    assert log.events == [("loop.redirect", {"step": None, "canned": True, "chars": len(text)})]
    spin = sw.State(spin_due=True, spin_path="a")
    log = Log()
    out = admit(spin, log=log)
    text = ("you have rewritten `a` repeatedly; the repo's checks could not run here. Stop rewriting it — "
            "re-read the step and verify a DIFFERENT part of the work before touching that file again.")
    expected = sw.Steer(text, "wheel-spin guard", sw.Trigger.WHEEL_SPIN)
    assert out == sw.Result(sw.Status.STEER, sw.Trigger.WHEEL_SPIN, steer=expected)
    assert spin == sw.State(spin_path="a", pending_steer=expected) and spin.pending_steer is out.steer
    assert out.steer.source == "wheel-spin guard" and not out.steer.grounded
    assert log.events == [("loop.spin_probe_result", {"step": None, "canned": True})]


def test_unknown_probe_is_recorded_but_never_becomes_clean_or_completion():
    state, records = sw.State(spin_due=True, spin_path="a"), []
    result = admit(state, call={"id": "unknown"}, truth="", record=records)
    assert records == ["recorded"]
    assert result.status is sw.Status.STEER and not result.steer.grounded
    assert result.steer.author_status is sw.Status.NO_OP
    assert state.pending_probe is None and state.last_delivered is None


def test_withheld_author_preserves_exact_ground_truth_not_a_new_diagnosis():
    # An author that returned NOTHING (not one that answered ON_TRACK) keeps the factual floor.
    calls, state = [], sw.State(spin_due=True, spin_path="a")
    result = admit(state, call={"id": "p"}, truth="compiler: exact negative evidence",
                   author=author_service(calls, text=""))
    assert len(calls) == 2 and "ORIGINAL TASK" in str(calls[0])  # the shared summarizer retries an empty reply once
    assert result.steer.author_status is sw.Status.WITHHELD
    assert not result.steer.authored and "compiler: exact negative evidence" in result.steer.text
    expected = sw.Steer("you have rewritten `a` repeatedly; ground truth from the repo's own checks:\n"
                        "compiler: exact negative evidence", "wheel-spin guard", sw.Trigger.WHEEL_SPIN,
                        grounded=True, author_status=sw.Status.WITHHELD)
    assert result == sw.Result(sw.Status.STEER, sw.Trigger.WHEEL_SPIN, steer=expected)
    assert state.pending_steer is result.steer and state.pending_probe is None


def test_same_checks_get_one_second_look_then_reattach_without_inference():
    state, calls = sw.State(), []
    author = author_service(calls, visible=False)
    for _ in range(3):
        result = sw.DEFINITION.progress(sw.ProgressInput("same check", 2, author, Log()), state)
        delivered(state, result)
    assert len(calls) == 4 and state.same_checks_relooked
    assert result.steer.checks_reattached and "same check" in result.steer.text
    assert result.steer.text != "a vetted action"
    # Actual changed facts rearm, not a new phase name or detector trigger.
    result = sw.DEFINITION.progress(sw.ProgressInput("changed check", 3, author, Log()), state)
    assert len(calls) == 6 and not state.same_checks_relooked
    assert "changed check" in str(calls[-2])


def test_visible_unchanged_checks_withhold_author_but_retain_periodic_truth():
    state, calls = sw.State(), []
    author = author_service(calls)
    for _ in range(3):
        result = sw.DEFINITION.progress(sw.ProgressInput("same", 2, author, Log()), state)
        delivered(state, result)
    assert len(calls) == 4
    assert result.steer.author_status is sw.Status.WITHHELD and result.steer.text == "same"


def test_superseded_check_facts_clear_suppression_without_changing_original_task():
    calls, state = [], sw.State(steered_checks_text="old", same_checks_relooked=True)
    author = author_service(calls, superseded="a newer real coder run")
    result = sw.DEFINITION.progress(sw.ProgressInput("old", 2, author, Log()), state)
    assert result.status is sw.Status.STEER
    assert len(calls) == 2 and "ORIGINAL TASK" in str(calls[0])
    assert state.steered_checks_text == "" and not state.same_checks_relooked


def test_all_disabled_stages_leave_pending_effects_state_and_services_untouched():
    def forbidden(*args):
        raise AssertionError("disabled lifecycle accessed a service")
    log = Log()
    ticket = sw.PendingProbe(sw.Trigger.REFUSAL, {"id": "p"})
    steer = sw.Steer("already pending", "refusal guard", sw.Trigger.REFUSAL)
    state = sw.State(pending_probe=ticket, pending_steer=steer, repeat_count=4)
    before = copy.deepcopy(state)
    outputs = [sw.DEFINITION.execute(sw.ObservationInput(forbidden, log), state, enabled=False),
               sw.DEFINITION.admit(sw.AdmissionInput(forbidden, log, forbidden), state, enabled=False),
               sw.DEFINITION.settle(sw.ReturnedProbeInput(ticket, forbidden, forbidden, None, log), state, enabled=False),
               sw.DEFINITION.progress(sw.ProgressInput("truth", 2, None, log), state, enabled=False),
               sw.DEFINITION.acknowledge(state, steer, enabled=False),
               sw.DEFINITION.reset_step(state, enabled=False)]
    assert all(out.status is sw.Status.NOT_SELECTED for out in outputs)
    assert state == before and not log.events
    assert state.pending_probe is ticket and state.pending_steer is steer


def test_pending_steer_suspends_new_detection_and_only_exact_delivery_acknowledges():
    state = sw.State(redirect_due=True, repeat_count=3)
    result = admit(state, refusals=measured(3))
    def forbidden():
        raise AssertionError("pending intervention started new detection")
    assert sw.DEFINITION.execute(sw.ObservationInput(forbidden, Log()), state).status is sw.Status.PENDING
    other = replace(result.steer)
    assert sw.DEFINITION.acknowledge(state, other).status is sw.Status.NO_OP
    assert state.last_delivered is None
    delivered(state, result)


def test_stale_probe_ticket_does_not_consume_other_owner_or_call_services():
    state = sw.State(pending_probe=sw.PendingProbe(sw.Trigger.WHEEL_SPIN, {"id": "owned"}))
    stale = sw.PendingProbe(sw.Trigger.REFUSAL, {"id": "unrelated"})
    def forbidden():
        raise AssertionError("unrelated probe was consumed")
    result = sw.DEFINITION.settle(sw.ReturnedProbeInput(stale, forbidden, forbidden, None, Log()), state)
    assert result.status is sw.Status.NO_OP and state.pending_probe.call["id"] == "owned"


def test_step_reset_and_new_task_do_not_reset_shared_or_other_authority():
    state = sw.State(recent_writes=["a"], recent_write_ids=["id"], spin_due=True,
                     spin_path="a", steered_checks_text="current", same_checks_relooked=True,
                     repeat_count=4, blocked_fired_seq=10, redirect_due=True)
    assert sw.DEFINITION.reset_step(state).status is sw.Status.RESET
    assert not state.recent_writes and not state.spin_path and not state.spin_due and not state.redirect_due
    assert state.steered_checks_text == "current" and state.same_checks_relooked
    assert state.repeat_count == 4 and state.blocked_fired_seq == 10
    new = sw.State()
    assert new.steered_checks_text == "" and new.blocked_fired_seq < 0
    assert not new.recent_writes and new.pending_probe is new.pending_steer is None


def test_exact_offered_identity_allows_observation_without_acknowledgement_or_counter_mutation():
    steer = sw.Steer('use the real checks', 'refusal guard', sw.Trigger.REFUSAL)
    for offered in (None, replace(steer), steer):
        measured = []
        state = sw.State(action_seq=17, pending_steer=steer)
        facts = sw.ObservationFacts((sw.ForwardedCall('first-compliance', None),), 0, '',
                                    frozenset(), frozenset(), sequence_start=100)
        def measure():
            measured.append('facts')
            return facts
        source = sw.ObservationInput(measure, Log(), offered_steer=offered)
        result = sw.DEFINITION.execute(source, state)
        assert state.pending_steer is steer and state.last_delivered is None and state.action_seq == 17
        if offered is steer:
            assert result.status is sw.Status.NO_OP and result.steer is None
            assert measured == ['facts'] and state.recent_writes == [None]
            assert state.recent_write_ids == ['first-compliance']
            delivery = sw.DEFINITION.acknowledge(state, steer)
            assert delivery.status is sw.Status.DELIVERED and state.last_delivered is steer
            assert state.pending_steer is None and state.recent_write_ids == ['first-compliance']
        else:
            assert result.status is sw.Status.PENDING and result.steer is steer
            assert measured == [] and state.recent_writes == state.recent_write_ids == []


def test_authoritative_batch_clock_uses_first_call_for_refusal_without_recounting_required_fact():
    state, log = sw.State(action_seq=51, blocked_fired_seq=38), Log()
    facts = sw.ObservationFacts((sw.ForwardedCall('one', 'a'), sw.ForwardedCall('two', 'a')),
                                5, 'actually refused', sequence_start=49)
    out = sw.DEFINITION.execute(sw.ObservationInput(lambda: facts, log), state)
    assert out.status is sw.Status.ARMED and out.trigger is sw.Trigger.REFUSAL
    assert state.action_seq == 51 and state.blocked_fired_seq == 50
    assert state.redirect_due and state.recent_writes == state.recent_write_ids == []
    assert log.events == [('loop.refusals', {'steer': 'refusals', 'step': None,
                                            'count': 5, 'action': 'actually refused'})]


def test_authoritative_batch_cooldown_can_expire_on_second_call_without_mutating_fact_clock():
    state, log = sw.State(action_seq=26, blocked_fired_seq=14), Log()
    facts = sw.ObservationFacts((sw.ForwardedCall('one', None), sw.ForwardedCall('two', None)),
                                3, 'last real refusal', sequence_start=24)
    out = sw.DEFINITION.execute(sw.ObservationInput(lambda: facts, log), state)
    assert out.status is sw.Status.ARMED and out.trigger is sw.Trigger.REFUSAL
    assert state.action_seq == 26 and state.blocked_fired_seq == 26
    assert log.events == [('loop.refusals', {'steer': 'refusals', 'step': None,
                                            'count': 3, 'action': 'last real refusal'})]


def test_definition_replacement_is_real_stage_execution_not_hidden_old_loop():
    state, calls = sw.State(), []
    def replaced(source, owned, *, enabled=True):
        calls.append((source, owned, enabled))
        return sw.Result(sw.Status.WITHHELD)
    definition = replace(sw.DEFINITION, execute=replaced)
    source = observation()
    assert definition.execute(source, state).status is sw.Status.WITHHELD
    assert calls == [(source, state, True)] and state == sw.State()
