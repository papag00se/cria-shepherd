"""Adversarial-review regressions for the settled-ON_TRACK answer (1576951f) and refusal admission
re-measurement (70c5d258).

1576951f made the steer author's ON_TRACK a typed answer that delivers nothing. Two readings of the
token still turned a judgment of STUCK into that silence:

* THE RECOVERY QUESTION OVERLOADED THE WORD. ``steer_reasoning_recover.txt`` told the reasoner to
  answer ON_TRACK both when its thinking concluded the coder is progressing AND when it concluded the
  coder is stuck but named no action. Real case, 20260823T225511 calls 0089/0090 (refusal guard): the
  author answered ON_TRACK, its thinking said "The coder seems to be stuck in a loop of re-verifying
  everything that has already been verified", and the recovery's own reasoning ended "That's stuck.
  But no action. So ON_TRACK." The parent delivered the refusal redirect; 1576951f delivered nothing.
  "Stuck without an action" now has its own POSITIVE word, UNSETTLED (#21), which keeps the floor.
* A TRAILING TOKEN SETTLED WHATEVER CAME ABOVE IT. ``_read_reply`` answered on_track for any reply
  whose last line is the token; with no separate reasoning channel ``reasoning_of`` IS the reply, so
  the dispute check never ran. "<directive>\\nON_TRACK" and "The coder is stuck ...\\nON_TRACK" were
  silenced. The trailing token now counts only when essentially nothing else is above it.

70c5d258 withdraws a refusal nomination that admission numerically disproves (run07). The withdrawn
nomination still behaved as a fire: it kept the cooldown stamp (a genuinely eligible window right
after it could not arm for 11 calls), it had already flushed the wheel-spin write window, and it left
no event beside the ``loop.refusals`` it was armed with (#12).

Production seats only: ``loop.guard_probe_steer`` / ``Loop.drive`` with scripted transports, plus the
policy's own observe/admit for the write-window case. No model, network, GPU or service.
"""
import io
import json

import pytest

from cria import bodykeys, denial, loop, prompts, stalledwork as sw
from stalled_work_fixtures import engine, seat, _Log
from test_loop import _Rlog
from test_on_track_is_an_answer_not_a_failure import (FLOOR_REFUSAL, FLOOR_SPIN, TRIGGERS, TRUTH,
                                                      _reply, _settle)
from test_refusal_admission_freshness import prepare, probe_spy, returned
from test_stalled_work_production_binding import SESSION, acting


def _floor(trigger):
    return FLOOR_REFUSAL if trigger is sw.Trigger.REFUSAL else FLOOR_SPIN


# Verbatim from ~/.cria/calls/20260823T225511-01a03256-4aec-7743-a2de-981e6a96caeb/
# 0089-reasoner.reasoning.txt (its content was exactly "ON_TRACK"); the last paragraph trips the
# answer-versus-thinking dispute check.
THINKING_0089 = (
    "5. The compilation passes (`mvn compile` succeeds), the code runs correctly on both test files, "
    "and results are deterministic across multiple runs.\n\n"
    "6. The last check from repo-checks says \"no error-class problems\" in the current edits.\n\n"
    "The coder seems to be stuck in a loop of re-verifying everything that has already been verified. "
    "They keep reading the same file sections, running the same checks, and claiming they need to "
    "verify things again.\n")


# --- the recovery question: "stuck without an action" is its own positive word -------------------

def test_the_recovery_prompt_gives_stuck_without_an_action_its_own_positive_word():
    text = prompts.render("steer_reasoning_recover", reasoning="THINKING")
    assert "never settled on a concrete action, reply ON_TRACK" not in text
    assert "never settled on a concrete action" in text and "\nUNSETTLED\n" in text
    assert "or the single word UNSETTLED" in text and "NOT_" not in text  # positive tokens only (#21)


@pytest.mark.parametrize("recovery", ["UNSETTLED", "**UNSETTLED**",
                                      "The thinking concluded stuck but named nothing.\nUNSETTLED"],
                         ids=["bare", "markdown", "after-prose"])
@pytest.mark.parametrize("trigger", TRIGGERS)
def test_a_recovery_that_settles_stuck_without_an_action_keeps_the_floor(trigger, recovery):
    steer, asked, rlog, gs = _settle(trigger, [_reply("ON_TRACK", THINKING_0089), _reply(recovery)])
    assert asked == ["reasoner", "steer-recover"]
    assert "loop.steer_answer_contradicted" in rlog.kinds()
    assert "loop.steer_recover_unsettled" in rlog.kinds()
    assert steer is not None and _floor(trigger) in steer and TRUTH in steer
    assert "loop.stalled_on_track" not in rlog.kinds() and "loop.steer_on_track" not in rlog.kinds()
    assert gs.stalled_steer is not None and not gs.stalled_steer.authored


@pytest.mark.parametrize("trigger", TRIGGERS)
def test_a_recovery_that_settles_progressing_still_delivers_nothing(trigger):
    # The 01a168cb 0075/0076 incident is a genuine "progressing" recovery; it stays silent.
    steer, asked, rlog, _gs = _settle(trigger, [_reply("ON_TRACK", THINKING_0089), _reply("ON_TRACK")])
    assert asked == ["reasoner", "steer-recover"]
    assert steer is None and "loop.stalled_on_track" in rlog.kinds()
    assert "loop.steer_recover_unsettled" not in rlog.kinds()


@pytest.mark.xfail(strict=True, reason=(
    "Undecidable from the reply: the captured 0090 recovery answered ON_TRACK under the OLD prompt, "
    "where that word also meant 'stuck without an action'. The bytes are identical to a genuine "
    "'progressing' answer (01a168cb 0076), and the only disambiguator is the recovery's private "
    "reasoning, which cria must not judge lexically (#8). Under the current prompt the same case "
    "answers UNSETTLED (test above)."))
@pytest.mark.parametrize("trigger", TRIGGERS)
def test_captured_0090_bytes_under_the_old_prompt_cannot_be_told_from_progressing(trigger):
    recovery_0090 = _reply("ON_TRACK", "The thinking says 'stuck in a loop of re-verifying'. "
                                       "That's stuck. But no action. So ON_TRACK.")
    steer, _asked, _rlog, _gs = _settle(trigger, [_reply("ON_TRACK", THINKING_0089), recovery_0090])
    assert steer is not None and _floor(trigger) in steer


# --- a trailing token settles ON_TRACK only when nothing substantive is above it ------------------

@pytest.mark.parametrize("content", [
    "The coder is stuck in a loop and needs help; it keeps re-running the refused command.\nON_TRACK",
    "Read cart.go before the next edit.\nON_TRACK",
    "Read cart.go before the next edit.\n\n**ON_TRACK**",
], ids=["inline-stuck-then-token", "directive-then-token", "directive-then-bold-token"])
@pytest.mark.parametrize("trigger", TRIGGERS)
def test_substance_above_a_trailing_token_is_not_a_settled_on_track(trigger, content):
    steer, asked, rlog, _gs = _settle(trigger, [_reply(content)])
    assert asked == ["reasoner"]
    assert steer is not None and _floor(trigger) in steer, rlog.kinds()
    assert "loop.stalled_on_track" not in rlog.kinds()


@pytest.mark.parametrize("content", ["ON_TRACK", "ON_TRACK.", "**ON_TRACK**", "> ON_TRACK",
                                     "Verdict:\nON_TRACK", "\n\nON_TRACK\n"],
                         ids=["bare", "period", "bold", "quote", "short-label", "blank-lines"])
def test_a_bare_trailing_token_still_settles_on_track(content):
    steer, _asked, rlog, _gs = _settle(sw.Trigger.REFUSAL, [_reply(content)])
    assert steer is None and "loop.stalled_on_track" in rlog.kinds()


# --- a withdrawn refusal nomination spends nothing a fire would -----------------------------------

PROBE = {"id": "owned-probe", "type": "function",
         "function": {"name": "exec_command", "arguments": '{"cmd":"probe"}'}}


@pytest.mark.parametrize("synthetic", [False, True])
def test_a_withdrawn_nomination_does_not_spend_the_refusal_cooldown(monkeypatch, synthetic):
    """run07 shape: armed at sequence 1, withdrawn at admission (2 refusals left). The coder's next
    call is refused, so the SAME 12-call window holds 3 refusals again and must arm."""
    driver, state, body, posted, first, log = prepare(monkeypatch, synthetic)
    replies = iter([acting("keep-working"), acting("third")])
    owner = driver._ctx.coder_chat.__self__
    original = owner._receive_open

    def transport(request, **options):
        if request.full_url.endswith("/v1/chat/completions"):
            posted.append(json.loads(request.data))
            return io.BytesIO(json.dumps(next(replies)).encode())
        return original(request, **options)
    monkeypatch.setattr(owner, "_receive_open", transport)
    returned(body, first)                               # the recovery call ran; oldest refusal aged out
    nominations = probe_spy(monkeypatch, PROBE)
    second = driver.drive(body, SESSION, None, log)     # withdrawn: no probe requested
    assert nominations == [] and not state.redirect_due
    withdrawn = [f for k, f in log.events if k == "loop.refusals_withdrawn"]
    assert len(withdrawn) == 1 and withdrawn[0]["count"] == 2, withdrawn
    body["messages"] += [second["choices"][0]["message"],
                         {"role": "tool", "tool_call_id": "keep-working", "content": "refused",
                          bodykeys.RESULT_OUTCOME: denial.REFUSED}]
    assert loop._refusals_in_window(body["messages"])[0] == sw.REFUSAL_THRESHOLD
    driver.drive(body, SESSION, None, log)              # observation of this forward sees 3 refused
    assert state.redirect_due and state.repeat_count == sw.REFUSAL_THRESHOLD, (
        f"action_seq={state.action_seq} blocked_fired_seq={state.blocked_fired_seq}")
    assert [k for k, _ in log.events].count("loop.refusals") == 2


def _observe(state, log, calls, refused):
    return sw.observe(sw.ObservationInput(lambda: sw.ObservationFacts(
        tuple(calls), refused, "read_file {}"), log), state)


def _admit(state, log, count):
    return sw.admit(sw.AdmissionInput(lambda: PROBE, log, lambda: (count, "read_file {}")), state)


def _write(i, path="a.py"):
    return sw.ForwardedCall(f"w{i}", path)


def test_a_withdrawn_nomination_keeps_the_write_window_and_the_next_landed_write_trips_spin():
    state, log = sw.State(), _Log()
    for i in range(4):
        _observe(state, log, [_write(i)], 0)
    _observe(state, log, [sw.ForwardedCall("r", None)], sw.REFUSAL_THRESHOLD)
    assert state.redirect_due and state.recent_writes == ["a.py"] * 4
    assert _admit(state, log, 2).status is sw.Status.NO_OP and not state.redirect_due
    assert state.recent_writes == ["a.py"] * 4
    _observe(state, log, [_write(4)], 2)
    assert state.spin_due and state.spin_path == "a.py"


def test_a_confirmed_fire_consumes_the_write_window_and_keeps_its_cooldown_stamp():
    state, log = sw.State(), _Log()
    for i in range(4):
        _observe(state, log, [_write(i)], 0)
    _observe(state, log, [sw.ForwardedCall("r", None)], sw.REFUSAL_THRESHOLD)
    stamp = state.blocked_fired_seq
    result = _admit(state, log, sw.REFUSAL_THRESHOLD)
    assert result.status is sw.Status.PENDING and result.probe.trigger is sw.Trigger.REFUSAL
    assert state.recent_writes == [] and state.recent_write_ids == []
    assert state.blocked_fired_seq == stamp
    assert "loop.refusals_withdrawn" not in [k for k, _ in log.events]


def test_withdrawal_is_an_event_and_restores_eligibility_without_a_second_fire():
    state, log = sw.State(), _Log()
    _observe(state, log, [sw.ForwardedCall("r", None)], sw.REFUSAL_THRESHOLD)
    _admit(state, log, 2)
    assert [k for k, _ in log.events] == ["loop.refusals", "loop.refusals_withdrawn"]
    assert log.events[-1][1] == {"step": None, "count": 2}
    # The window admission just measured (2) cannot re-arm; the next refused call can.
    assert _observe(state, log, [sw.ForwardedCall("x", None)], 2).status is sw.Status.NO_OP
    assert _observe(state, log, [sw.ForwardedCall("y", None)], 3).status is sw.Status.ARMED


# --- known limitation, outside this change's ownership ---------------------------------------------

@pytest.mark.xfail(strict=True, reason=(
    "Same class, not fixed here: the same-checks suppression returns WITHHELD, which settlement turns "
    "into the canned refusal floor even after the author answered ON_TRACK for those exact checks. "
    "Remembering that answer needs a new task-state field aliased by loop._StalledWorkView, and "
    "cria/loop.py is owned by another change in flight."))
def test_unchanged_checks_after_on_track_answers_do_not_draw_the_canned_floor():
    state, log = sw.State(), _Log()
    author_seat = seat(None, checks=TRUTH)          # the author answers ON_TRACK every time
    services = sw.AuthorServices("ORIGINAL TASK", lambda: TRUTH, lambda v: "", lambda v: True,
                                 loop._checks_ran_before, engine(), author_seat, author_seat.log)
    statuses = []
    for i in range(3):
        state.repeat_count, state.repeat_action = 3, "exec_command {}"
        ticket = state.pending_probe = sw.PendingProbe(sw.Trigger.REFUSAL, {"id": f"p{i}"})
        statuses.append(sw.DEFINITION.settle(sw.ReturnedProbeInput(
            ticket, lambda: None, lambda: TRUTH, services, log), state).status)
        state.pending_steer = None
    assert statuses == [sw.Status.ON_TRACK] * 3
