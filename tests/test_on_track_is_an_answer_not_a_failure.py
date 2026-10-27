"""An author's ON_TRACK is an ANSWER; only an author that gave no answer gets the canned floor.

INCIDENT (ornith1.5_9b / Java, session 01a168cb, calls 0074-0078, 2026-10-23). Three of the coder's
calls had been refused; at call 0074 it had already rerun the refused command, corrected, and it
succeeded. The steer author answered ON_TRACK, its thinking was checked and the recovery answered
ON_TRACK again. Settlement still handed the coder the refusal floor: "Continuing down this line will
not change the outcome ... the most recent action of that kind was: <the prefix of the command that
had just succeeded> ... Choose a DIFFERENT next action". The coder ruminated 8,244 reasoning tokens
and was aborted. The cause: ``GroundedActions.author`` returned ``None`` for ON_TRACK, the same value
as a cut, ruminating or vetted-away author, so ``stalledwork.settle`` could not tell an answer from
no answer and delivered ``authored or <floor>`` (#4: no deterministic fallback behind a reasoner).
38 such ON_TRACK answers (30 refusal, 8 wheel-spin) drew a canned floor across ~/.cria/logs.

Silence loses no fact: the probe's own result still reaches the coder as its separate checks
message, and each refused call keeps its own refusal result. Controls keep every floor for an author
that could NOT answer, a genuine directive, and the positive-token rule (#21).

Driven through the production seat ``loop.guard_probe_steer`` with the canonical runtime, the real
author/recovery/vet, and a scripted reasoner transport; no executor, network or model.
"""
from __future__ import annotations

import json

import pytest

from cria import assistruntime, loop, stalledwork
from cria.loop import GuardState
from cria.probegate import GateOutcome

TRUTH = "cart.go:3: undefined: Total"
REFUSED = 'exec_command {"cmd":"time java -cp target/classes pipeline.Importer > /tmp/out.txt"}'
FLOOR_REFUSAL = "Continuing down this line will not change the outcome"
FLOOR_SPIN = "you have rewritten `cart.go` repeatedly"


class _Report:
    results, selected = [], []


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def _reply(content, reasoning=None, finish="stop"):
    msg = {"role": "assistant", "content": content}
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    return {"choices": [{"finish_reason": finish, "message": msg}]}


PROGRESSING = "Every recent turn advances; it recovered from the refusals by writing under tmp/."
STUCK = "The coder is stuck in a loop and needs help; we must write a directive."


def _settle(trigger, replies, *, truth=TRUTH):
    """Admit a real pending probe, return its result, settle it through the production seat.

    ``replies`` are the reasoner transport's answers in call order (author, then recovery /
    vetting questions). Returns (steer text or None, the reasoner phases asked, rlog, gs)."""
    from tests.test_loop import _admit_guard_probe
    gs = GuardState()
    gs.gate_plan = object()
    gs.probe_call_id = "probe-1"
    gs.spin_path = "cart.go"
    gs.repeat_count, gs.repeat_action = 3, REFUSED
    body = {"messages": [{"role": "user", "content": "Make the importer faster."},
                         {"role": "tool", "tool_call_id": gs.probe_call_id, "content": "gate output"}]}
    rlog, asked, queue = _Rlog(), [], list(replies)

    def chat(request, log):
        asked.append(log.phase)
        assert queue, f"unexpected reasoner call in phase {log.phase!r}"
        return json.dumps(queue.pop(0)).encode()

    def author(condition, owner, observed, actual_body, log):
        return loop._stalled_author(owner, actual_body, log, chat, None,
                                    condition=condition, outcome=observed)

    real_read, real_truth = loop.read_gate, loop.guard_ground_truth
    loop.read_gate = lambda plan, probe, log: GateOutcome(ran=True, report=_Report())
    loop.guard_ground_truth = lambda outcome: truth
    try:
        with assistruntime.bound(assistruntime.AssistRuntime.select()):
            _admit_guard_probe(gs, body, rlog, redirect=trigger is stalledwork.Trigger.REFUSAL)
            steer = loop.guard_probe_steer(gs, body, rlog, author=author, step=None)
    finally:
        loop.read_gate, loop.guard_ground_truth = real_read, real_truth
    assert gs.stalled_probe is None  # the reading is consumed whatever is delivered
    return steer, asked, rlog, gs


TRIGGERS = [stalledwork.Trigger.REFUSAL, stalledwork.Trigger.WHEEL_SPIN]


# --- the incident: a settled ON_TRACK answer delivers nothing --------------------------------------

@pytest.mark.parametrize("trigger", TRIGGERS)
@pytest.mark.parametrize("truth", [TRUTH, ""])
def test_an_on_track_answer_its_thinking_agrees_with_delivers_nothing(trigger, truth):
    steer, asked, rlog, gs = _settle(trigger, [_reply("ON_TRACK", PROGRESSING)], truth=truth)
    assert steer is None and gs.stalled_steer is None
    assert asked == ["reasoner"]  # no recovery question: nothing in the thinking disputes it
    assert ("loop.stalled_on_track", {"step": None, "condition": trigger.value,
                                      "grounded": bool(truth)}) in rlog.events
    assert "loop.redirect" not in rlog.kinds() and "loop.spin_probe_result" not in rlog.kinds()


@pytest.mark.parametrize("trigger", TRIGGERS)
def test_the_incident_shape_on_track_reconfirmed_by_recovery_delivers_nothing(trigger):
    # 01a168cb 0075/0076: the answer was ON_TRACK, its thinking tripped the contradiction check,
    # and the recovery question answered ON_TRACK again.
    steer, asked, rlog, gs = _settle(trigger, [_reply("ON_TRACK", STUCK), _reply("ON_TRACK")])
    assert steer is None and gs.stalled_steer is None
    assert asked == ["reasoner", "steer-recover"]
    assert "loop.steer_answer_contradicted" in rlog.kinds()
    assert "loop.stalled_on_track" in rlog.kinds()


# --- controls: an author that could NOT answer keeps its existing floor -----------------------------

@pytest.mark.parametrize("reply", [
    _reply(""),                                   # nothing at all
    _reply("NOT_STUCK", PROGRESSING),             # legacy negated token is not a verdict (#21)
    _reply("The coder is not ON_TRACK.", PROGRESSING),   # negated sentinel
    _reply('{"path": "cart.go"}'),                # an argument blob, not an answer
    _reply("First read cart.go. Then run the tests."),   # structural refusal: two actions
], ids=["empty", "not-stuck", "negated", "json", "two-actions"])
@pytest.mark.parametrize("trigger", TRIGGERS)
def test_an_author_with_no_answer_keeps_the_existing_floor(trigger, reply):
    steer, _asked, rlog, _gs = _settle(trigger, [reply])
    floor = FLOOR_REFUSAL if trigger is stalledwork.Trigger.REFUSAL else FLOOR_SPIN
    assert steer is not None and floor in steer and TRUTH in steer
    assert "loop.stalled_on_track" not in rlog.kinds()


@pytest.mark.parametrize("recovery", [_reply(""), _reply("NOT_STUCK")], ids=["empty", "not-stuck"])
@pytest.mark.parametrize("trigger", TRIGGERS)
def test_an_on_track_its_own_thinking_disputes_and_recovery_cannot_settle_keeps_the_floor(trigger, recovery):
    # An empty recovery is retried once by the shared summarizer; it stays empty.
    steer, asked, rlog, _gs = _settle(trigger, [_reply("ON_TRACK", STUCK), recovery, recovery])
    floor = FLOOR_REFUSAL if trigger is stalledwork.Trigger.REFUSAL else FLOOR_SPIN
    assert asked[:2] == ["reasoner", "steer-recover"]
    assert steer is not None and floor in steer
    assert "loop.stalled_on_track" not in rlog.kinds()


def test_a_cut_author_reply_keeps_the_existing_floor_even_if_it_reads_on_track():
    # A first pass cut at the cap cannot have its thinking checked; the retry's ON_TRACK is undecided.
    steer, asked, rlog, _gs = _settle(stalledwork.Trigger.REFUSAL,
                                      [_reply("ON_TRACK", STUCK, finish="length"), _reply("ON_TRACK")])
    assert asked == ["reasoner", "reasoner-noreason"]
    assert steer is not None and FLOOR_REFUSAL in steer
    assert "loop.stalled_on_track" not in rlog.kinds()


# --- controls: a genuine directive is still delivered -----------------------------------------------

@pytest.mark.parametrize("trigger", TRIGGERS)
def test_a_genuine_directive_is_still_delivered(trigger):
    steer, _asked, rlog, _gs = _settle(trigger, [_reply("Read cart.go before the next edit.")])
    assert steer is not None and "Read cart.go before the next edit." in steer
    assert FLOOR_REFUSAL not in steer and FLOOR_SPIN not in steer
    assert "loop.stalled_on_track" not in rlog.kinds()


@pytest.mark.parametrize("trigger", TRIGGERS)
def test_an_on_track_whose_recovery_names_an_action_delivers_that_action(trigger):
    steer, asked, _rlog, _gs = _settle(trigger, [_reply("ON_TRACK", STUCK),
                                                 _reply("Read cart.go before the next edit.")])
    assert asked[:2] == ["reasoner", "steer-recover"]
    assert steer is not None and "Read cart.go before the next edit." in steer


# --- the periodic check-in keeps its own baseline truth (unchanged) ---------------------------------

def test_periodic_progress_still_inserts_its_own_check_truth_after_on_track():
    from stalled_work_fixtures import engine, seat
    author_seat = seat("ON_TRACK", checks=TRUTH)
    services = stalledwork.AuthorServices("ORIGINAL TASK", lambda: TRUTH, lambda value: "",
                                          lambda value: True, loop._checks_ran_before,
                                          engine(), author_seat, author_seat.log)
    out = stalledwork.DEFINITION.progress(stalledwork.ProgressInput(TRUTH, 2, services, _Rlog()),
                                          stalledwork.State())
    assert out.steer.text == TRUTH and not out.steer.authored
    assert out.steer.author_status is stalledwork.Status.ON_TRACK
