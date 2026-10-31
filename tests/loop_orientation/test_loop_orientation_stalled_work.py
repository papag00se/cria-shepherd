"""Stalled work is detected from typed facts (refusals, repeated writes, an unchanged red) and answered with facts only."""
import copy
import json
from dataclasses import replace

import pytest
from cria import groundedaction as ga, loop, stalledwork as sw
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401

ACTION = "a call that was actually refused"

def observation(calls=(), *, refused=0, unlanded=(), sanctioned=(), log=None):
    facts = sw.ObservationFacts(tuple(sw.ForwardedCall(*c) for c in calls), refused, ACTION,
                                frozenset(unlanded), frozenset(sanctioned))
    return sw.ObservationInput(lambda: facts, log or Log())

def author_service(calls, *, text="a vetted action", checks="exact failure", visible=True, superseded="", dictation=None):
    """The real grounded-action engine over a scripted reasoner transport (text=None answers ON_TRACK)."""
    def chat(body, log):
        calls.append(body)
        prompt = body["messages"][0]["content"]
        answer = "SUPPORTED" if "SUPPORTED" in prompt else ("ON_TRACK" if text is None else text)
        if prompt.rstrip().endswith("DICTATES or DESCRIBES."):
            answer = dictation
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": answer}}]}).encode()
    public = {"guard_ground_truth", "workspace_inventory"}
    facts = ga.EvidenceServices(**{n: getattr(loop, n if n in public else "_" + n)
                                   for n in ga.EvidenceServices.__annotations__})
    engine = ga.GroundedActions(facts, ga.ProviderServices(loop.summarize, loop._judge_completion))
    history = [{"role": "user", "content": "ORIGINAL TASK"},
               {"role": "assistant", "tool_calls": [{"id": "c", "type": "function", "function": {
                   "name": "read_file", "arguments": '{"path":"cart.go"}'}}]},
               {"role": "tool", "tool_call_id": "c", "content": "func Total() int { return 0 }"}]
    seat = ga.AuthorInput(chat, None, None, ga.ActionEvidence(original_task="ORIGINAL TASK", last_gate_flag=checks),
                          {"messages": history}, Log(), "refusal")
    return sw.AuthorServices("ORIGINAL TASK", lambda: checks, lambda _: superseded, lambda _: visible,
                             loop._checks_ran_before, engine, seat, seat.log)

def settle(state, author, truth="exact checker bytes"):
    """Admit a real pending probe for the latched trigger, then settle its returned reading."""
    pending = sw.DEFINITION.admit(sw.AdmissionInput(lambda: {"id": "probe"}, Log(), lambda: (state.repeat_count, ACTION)), state)
    order = []
    result = sw.DEFINITION.settle(sw.ReturnedProbeInput(
        pending.probe, lambda: order.append("recorded"), lambda: truth, author, Log()), state)
    return result, order

def test_a_refusal_arms_a_nomination_that_admission_confirms_or_withdraws():
    """Arming keeps this completion's writes out of the window; a confirmed fire consumes it. run07: a withdrawn
    nomination (refusals aged out) burned the cooldown and blocked an eligible 3-refusal window for 11 calls."""
    def armed(count):
        state = sw.State(recent_writes=["a"] * 4, recent_write_ids=list("wxyz"))
        out = sw.observe(observation((("new", "a"), ("later", "a")), refused=count), state)
        assert (out.trigger, state.redirect_due, state.recent_writes, state.spin_due) == (
            sw.Trigger.REFUSAL, True, ["a"] * 4, False)
        return state

    state, log = armed(5), Log()
    out = sw.admit(sw.AdmissionInput(lambda: {"id": "p"}, log, lambda: (5, ACTION)), state)
    assert out.status is sw.Status.PENDING and not state.recent_writes and not state.redirect_due
    state = armed(3)
    stamp = state.blocked_fired_seq
    again = copy.deepcopy(state)                                  # the cooldown keeps a fired window from re-arming at once
    again.redirect_due = False
    assert sw.observe(observation((("c2", None),), refused=3), again).status is sw.Status.NO_OP
    log = Log()
    out = sw.admit(sw.AdmissionInput(lambda: pytest.fail("no probe"), log, lambda: (2, ACTION)), state)
    assert out.status is sw.Status.NO_OP and not state.redirect_due and log.kinds() == ["loop.refusals_withdrawn"]
    assert state.blocked_fired_seq == stamp - sw.REFUSAL_WINDOW and state.recent_writes == ["a"] * 4

def test_five_writes_to_one_path_trip_a_wheel_spin_unless_corrected_sanctioned_or_aged_out():
    """Unlanded writes are corrected out of the streak; a sanctioned rewrite never counts; non-writes age the window."""
    state, log = sw.State(), Log()
    sw.observe(observation(tuple((f"e{i}", "a") for i in range(5))), state)       # a batch earns one turn's credit
    assert not state.spin_due and state.spin_recheck == "a"
    sw.observe(observation(unlanded=("e0", "e1", "e2"), log=log), state)          # three never landed
    assert state.recent_writes == ["a", "a"] and log.kinds() == ["loop.write_streak_corrected"]
    for i in range(3):
        result = sw.observe(observation(((f"l{i}", "a"),)), state)
    assert (result.status, result.trigger, state.spin_path) == (sw.Status.ARMED, sw.Trigger.WHEEL_SPIN, "a")
    batched = sw.State()
    sw.observe(observation(tuple((str(i), "a") for i in range(5))), batched)    # a batch earns one turn's credit...
    assert sw.observe(observation(), batched).trigger is sw.Trigger.WHEEL_SPIN  # ...rechecked once results return
    sanctioned = sw.State()
    for i in range(5):
        sw.observe(observation(((str(i), "a"),), sanctioned=("a",)), sanctioned)
    assert not sanctioned.spin_due
    aged = sw.State()
    for i in range(4):
        sw.observe(observation(((f"w{i}", "a"),)), aged)
    for i in range(15):                                          # a 15-call window: the old writes age out
        sw.observe(observation(((f"r{i}", None),)), aged)
    assert sw.observe(observation((("w", "a"),)), aged).status is sw.Status.NO_OP

@pytest.mark.parametrize("state,floor", [
    (sw.State(redirect_due=True, repeat_count=3, repeat_action="refused action"),
     "3 of your recent calls were refused, so none of them ran"),
    (sw.State(spin_due=True, spin_path="a"), "you have rewritten `a` repeatedly"),
], ids=["refusal", "wheel-spin"])
def test_without_a_shell_the_floor_states_only_the_measured_fact(state, floor):
    """No check could run: the steer says what was measured (counts, the path) and claims no diagnosis."""
    out = sw.admit(sw.AdmissionInput(lambda: None, Log(), lambda: (3, "refused action")), state)
    assert out.status is sw.Status.STEER and floor in out.steer.text
    assert not out.steer.authored and not out.steer.grounded and state.pending_steer is out.steer

def test_settlement_records_the_reading_before_the_author_and_a_directive_carries_the_envelope():
    state = sw.State(redirect_due=True, spin_due=True, repeat_count=4)
    result, order = settle(state, author_service([]))
    assert order == ["recorded"] and not state.spin_due          # refusal supersedes the pending spin
    assert result.steer.text == "a vetted action" and result.steer.authored and result.steer.redirect_envelope

@pytest.mark.parametrize("trigger_state", [sw.State(redirect_due=True, repeat_count=3),
                                           sw.State(spin_due=True, spin_path="cart.go")], ids=["refusal", "spin"])
def test_an_on_track_answer_delivers_nothing_but_no_answer_keeps_the_facts(trigger_state):
    """ornith1.5_9b / Java 01a168cb: the coder had already corrected a refused command and the author said ON_TRACK; the
    refusal floor ("Choose a DIFFERENT next action") was delivered anyway and the coder ruminated 8,244 tokens.
    ON_TRACK is an ANSWER; only an author that returned nothing falls back to the exact ground truth."""
    twin, third = replace(trigger_state), replace(trigger_state)
    on_track, _ = settle(trigger_state, author_service([], text=None))
    assert on_track.status is sw.Status.ON_TRACK and on_track.steer is None and trigger_state.pending_steer is None
    silent, _ = settle(twin, author_service([], text=""))
    assert silent.steer.author_status is sw.Status.WITHHELD and "exact checker bytes" in silent.steer.text
    assert not silent.steer.authored
    unread, _ = settle(third, None, truth="")                       # an unreadable probe is never read as clean
    assert unread.status is sw.Status.STEER and not unread.steer.grounded

def test_unchanged_checks_get_one_second_look_then_come_back_verbatim_not_re_diagnosed():
    state, calls = sw.State(), []
    author = author_service(calls, checks="same check", visible=False)
    for _ in range(3):
        result = sw.progress(sw.ProgressInput("same check", 2, author, Log()), state)
        sw.acknowledge(state, result.steer)
    assert len(calls) == 4 and state.same_checks_relooked          # authored once, one second look, then none
    assert result.steer.checks_reattached and "same check" in result.steer.text
    assert sw.progress(sw.ProgressInput("fresh red", 1, author, Log()), sw.State()).status is sw.Status.NO_OP   # one round is not a stall
    sw.progress(sw.ProgressInput("changed check", 3, author, Log()), state)
    assert len(calls) == 6 and not state.same_checks_relooked      # changed facts re-arm the author
    seen = sw.State()                                              # checks already in the coder's context: stay silent
    for _ in range(3):
        result = sw.progress(sw.ProgressInput("same", 2, author_service([]), Log()), seen)
        sw.acknowledge(seen, result.steer)
    assert result.steer.author_status is sw.Status.WITHHELD and result.steer.text == "same"
    stale = sw.State(steered_checks_text="old", same_checks_relooked=True)
    sw.progress(sw.ProgressInput("old", 2, author_service([], superseded="a newer coder run"), Log()), stale)
    assert stale.steered_checks_text == "" and not stale.same_checks_relooked

def test_pending_steer_suspends_detection_and_only_the_exact_delivery_acknowledges():
    state = sw.State(redirect_due=True, repeat_count=3)
    out = sw.admit(sw.AdmissionInput(lambda: None, Log(), lambda: (3, ACTION)), state)
    boom = sw.ObservationInput(lambda: pytest.fail("pending intervention measured again"), Log())
    assert sw.observe(boom, state).status is sw.Status.PENDING
    assert sw.acknowledge(state, replace(out.steer)).status is sw.Status.NO_OP and state.last_delivered is None
    facts = sw.ObservationFacts((sw.ForwardedCall("first", None),), 0, "", sequence_start=100)
    offered = sw.ObservationInput(lambda: facts, Log(), offered_steer=out.steer)   # first compliance is observed...
    assert sw.observe(offered, state).status is sw.Status.NO_OP and state.pending_steer is out.steer
    assert state.recent_write_ids == ["first"] and state.last_delivered is None    # ...but never acknowledged
    assert sw.acknowledge(state, out.steer).status is sw.Status.DELIVERED and state.pending_steer is None

def test_a_stale_ticket_touches_nothing_and_a_step_advance_keeps_the_check_authority():
    state = sw.State(pending_probe=sw.PendingProbe(sw.Trigger.WHEEL_SPIN, {"id": "owned"}), repeat_count=4,
                     recent_writes=["a"], recent_write_ids=["i"], spin_due=True, spin_path="a", redirect_due=True,
                     steered_checks_text="current", blocked_fired_seq=10)
    no = lambda: pytest.fail("a service was called")
    stale = sw.ReturnedProbeInput(sw.PendingProbe(sw.Trigger.REFUSAL, {"id": "other"}), no, no, None, Log())
    assert sw.settle(stale, state).status is sw.Status.NO_OP
    assert sw.reset_step(state).status is sw.Status.RESET
    assert not (state.recent_writes or state.spin_due or state.redirect_due)
    assert (state.steered_checks_text, state.repeat_count, state.blocked_fired_seq) == ("current", 4, 10)

HEADER = "[GROUND TRUTH — the repo own checks fail] " + "shared diagnostic framing " * 8

def test_a_shared_check_header_is_not_proof_that_a_finding_is_visible():
    """Two different failures share one preamble; only the exact findings (even inside a larger message) count."""
    wanted = HEADER + "\n$ build — source/a:4: required symbol absent"
    other = HEADER + "\n$ build — source/b:9: a different failure"
    assert not loop._checks_already_visible({"messages": [{"role": "tool", "content": other}]}, wanted)
    assert loop._checks_already_visible({"messages": [{"role": "user", "content": "framing\n" + wanted + "\nend"}]}, wanted)

@pytest.mark.parametrize("ruling,delivered", [("DICTATES", False), ("DESCRIBES", True)])
def test_a_directive_ruled_to_dictate_invented_code_is_withheld_whole_never_restated(ruling, delivered):
    """run07 (ornith-java, refusal guard): the author named a design and a restater kept only the purpose clause, which
    the coder then built. A directive ruled DICTATES is withheld; the exact check facts are all the coder is told."""
    calls = []
    authored = "Replace the failing call with `parser.parse_all(rows)` and verify the build."
    result, _ = settle(sw.State(spin_due=True, spin_path="a"), author_service(calls, text=authored, dictation=ruling))
    assert result.steer.authored is delivered
    assert ("parser.parse_all(rows)" in result.steer.text) is delivered
    assert "exact checker bytes" in result.steer.text or delivered
    assert not any("Restate it so it says" in c["messages"][0]["content"] for c in calls)
