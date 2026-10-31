"""Stage contracts and real-driver equivalence, with synthetic wire replies only."""
import copy
import json
from dataclasses import dataclass, replace
from typing import Callable

from cria.assistcontract import Policy

import pytest

from cria import assistruntime, loop, participation, probediscovery
from cria.completionreview import (DEFINITION, ReviewInput, ReviewResult, ReviewStatus,
                                   ReviewTrigger, record_satisfaction)
from cria.config import AssistConfig, Config, RoutingConfig
from test_executable_assist_pilots import Log
from test_whole_task_review_boundaries import TASK, driver_fixture, gate_reply
from test_c10_module_state_reset import _candidate


def request(trigger, calls, log, *, answer=(False, "missing", "do work"), task=TASK):
    def history():
        calls.append("history")
        return "measured actions"
    def checks():
        calls.append("checks")
        return "\nmeasured checks"
    def judge(task, evidence):
        calls.append((task, evidence))
        return answer
    return ReviewInput(trigger, task, history, checks, judge, loop.VerdictNudge, log)


@pytest.mark.parametrize("trigger", list(ReviewTrigger))
@pytest.mark.parametrize("satisfied", [False, True])
def test_selected_owner_composes_once_and_records_the_authoritative_transition(trigger, satisfied):
    state = loop.GuardState(pending_done="held claim", pending_done_parts=("held review",))
    calls, log = [], Log()
    out = assistruntime.DEFAULT.review(request(trigger, calls, log,
        answer=(satisfied, "measured answer", "correction")), state)
    assert calls == ["history", "checks", (TASK, "measured actions\nmeasured checks")]
    assert out.status is (ReviewStatus.APPROVED if satisfied else ReviewStatus.REJECTED)
    assert (out.reason, out.action) == ("measured answer", "correction")
    assert state.latest_satisfaction is satisfied and state.latest_satisfaction_evidence == out.reason
    assert state.pending_done == ("held claim" if satisfied else "")
    assert state.pending_done_parts == (("held review",) if satisfied else ())
    assert log.events == [("loop.task_review", dict(assist_id=DEFINITION.policy.id,
        family_id=DEFINITION.policy.family_id, trigger=trigger.value, satisfied=satisfied,
        status=out.status.value))]


def test_unknown_original_claim_records_negative_without_judging_or_gathering():
    state = loop.GuardState(pending_done="stale", pending_done_parts=("stale",))
    calls, log = [], Log()
    result = assistruntime.DEFAULT.review(request(ReviewTrigger.CLAIM, calls, log, task=""), state)
    assert result.status is ReviewStatus.UNKNOWN_TASK and not calls
    assert state.latest_satisfaction is False and not state.pending_done_parts and not state.pending_done


@pytest.mark.parametrize("level,trigger", [(3, t) for t in ReviewTrigger] + [(4, ReviewTrigger.SCHEDULED)])
def test_unselected_stage_is_no_detection_no_services_no_state_no_events(level, trigger):
    state = loop.GuardState(latest_satisfaction=False, pending_done="held", pending_done_parts=("held",))
    before = copy.deepcopy(vars(state))
    calls, log = [], Log()
    result = assistruntime.AssistRuntime.select(level=level).review(request(trigger, calls, log), state)
    assert result.status is ReviewStatus.NOT_SELECTED and not result.approved
    assert vars(state) == before and calls == [] and log.events == []


def test_reactive_requirement_errors_at_selection_and_configuration_boundaries():
    for level in (4, 5):
        with pytest.raises(ValueError, match="required for reactive"):
            assistruntime.AssistRuntime.select(level=level, disabled=(DEFINITION.policy.id,))
        with pytest.raises(ValueError, match="required for reactive"):
            Config(routing=RoutingConfig(engagement_level=level), assists=AssistConfig(disabled=(DEFINITION.policy.id,)))
    assert DEFINITION.policy.id not in assistruntime.AssistRuntime.select(level=3,
        disabled=(DEFINITION.policy.id,)).selected
    with pytest.raises(ValueError, match="Unknown whole-task review trigger"):
        request("invented", [], Log())
    with pytest.raises(ValueError, match="Invalid whole-task review outcome"):
        ReviewResult(True)
    with pytest.raises(ValueError, match="preserve its registered"):
        replace(assistruntime.DEFAULT, task_review=replace(DEFINITION,
            policy=replace(DEFINITION.policy, triggers=(("scheduled", 4),))))


@pytest.mark.parametrize("synthetic", [False, True])
def test_real_driver_executes_replacement_and_never_the_default_judge(monkeypatch, synthetic):
    seen = []
    def execute(source, state):
        seen.append((source.trigger, state))
        record_satisfaction(state, False, "replacement rejected")
        return ReviewResult(ReviewStatus.REJECTED, "replacement rejected")
    runtime = replace(assistruntime.DEFAULT, task_review=replace(DEFINITION, execute=execute))
    driver, session, body, frames = driver_fixture(synthetic=synthetic, scheduled=True, reasoner=lambda *_: b'{}')
    driver._ctx.pilot_runtime = runtime
    monkeypatch.setattr(loop, "judge_satisfaction", lambda *_a, **_k: pytest.fail("default judge executed"))
    driver.drive(body, "sid:review", None, Log())
    assert seen == [(ReviewTrigger.SCHEDULED, session)]
    assert len(frames) == 1 and session.latest_satisfaction_evidence == "replacement rejected"


def test_invalid_replacement_result_is_rejected_before_release():
    runtime = replace(assistruntime.DEFAULT, task_review=replace(DEFINITION, execute=lambda *_: True))
    with pytest.raises(ValueError, match="return ReviewResult"):
        runtime.review(request(ReviewTrigger.CLAIM, [], Log()), loop.GuardState())


class Reasoner:
    def __init__(self, outcome, *, required="REQUIRED"):
        self.outcome = outcome
        self.required = required
        self.calls = []
    def __call__(self, body, log):
        phase = getattr(log, "phase", "")
        self.calls.append((phase, copy.deepcopy(body)))
        if phase == "test-participation-requirement":
            content = self.required
        elif phase == "test-e2e-requirement":
            content = "NOT_REQUIRED"
        elif self.outcome == "unreadable":
            content = ""
        else:
            content = json.dumps({"satisfied": self.outcome == "positive", "reason": ""})
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": content}}]}).encode()


def add_evidence(kind, session, body):
    if kind in ("dropped", "model", "unknown"):
        summary = "Prior work says the artifact exists."
        origin = loop._HandoffOrigin(summary, "measured ledger", kind == "dropped")
        messages = [{"role": "user", "content": loop._COMPACTION_MARKER + "\n" + summary}]
        reframed, changed = loop.reframe_compaction(messages, origin=origin if kind != "unknown" else None)
        assert changed
        # The next real drive sees the already-reframed retained history, not a
        # just-rewritten opportunity (whose cadence is intentionally blocked).
        body["messages"] += reframed
        session.handoff_origin = origin if kind != "unknown" else None
    elif kind == "refused":
        body["messages"] += [{"role": "assistant", "tool_calls": [{"id": "denied", "type": "function",
            "function": {"name": "run_command", "arguments": '{"command":"echo requested"}'}}]},
            {"role": "tool", "tool_call_id": "denied", "content": "Rejected by user"}]
    elif kind in ("required-test", "test-not-required"):
        report = participation.report([participation.observe(
            _candidate(probediscovery.ProbeKind.SyntaxCheck, ["node", "--check", "index.js"]), "", 0)])
        assert report.support("test") is participation.Support.UNKNOWN
        session.last_gate_participation = report
        session.gate_fresh = False
    elif kind == "actions":
        body["messages"] += [{"role": "assistant", "tool_calls": [{"id": "inspect", "type": "function",
            "function": {"name": "run_command", "arguments": '{"command":"echo inspection"}'}}]},
            {"role": "tool", "tool_call_id": "inspect", "content": "inspection: established fact"}]


@pytest.mark.parametrize("outcome", ["positive", "negative", "unreadable"])
@pytest.mark.parametrize("evidence", ["actions", "dropped", "model", "unknown", "refused",
                                      "required-test", "test-not-required"])
def test_full_judge_bodies_events_and_review_state_match_through_both_real_drivers(outcome, evidence):
    seen = []
    for synthetic in (False, True):
        reasoner = Reasoner(outcome, required="NOT_REQUIRED" if evidence == "test-not-required" else "REQUIRED")
        driver, session, body, frames = driver_fixture(synthetic=synthetic, scheduled=True, reasoner=reasoner)
        add_evidence(evidence, session, body)
        log = Log()
        out = driver.drive(body, "sid:review", None, log)
        approved = outcome == "positive" and evidence != "required-test"
        assert session.latest_satisfaction is approved
        assert session.satisfaction_last_drive == 1 and session.drive_count == 1
        assert session.done_probe is approved and bool(session.pending_done_parts) is approved
        assert len(frames) == (0 if approved else 1)
        assert out["choices"][0]["message"].get("tool_calls")
        review_events = [(k, v) for k, v in log.events if k in ("loop.task_review", "loop.satisfaction_check")]
        assert [k for k, _ in review_events] == ["loop.task_review", "loop.satisfaction_check"]
        assert review_events[0][1]["trigger"] == ReviewTrigger.SCHEDULED.value
        assert review_events[1][1]["satisfied"] is approved
        task_bodies = [b for phase, b in reasoner.calls if phase in ("satisfaction", "satisfaction-noreason")]
        assert len(task_bodies) == (2 if outcome == "unreadable" else 1)
        encoded = json.dumps(task_bodies[0], ensure_ascii=False)
        assert TASK in encoded
        if evidence == "actions":
            assert "inspection: established fact" in encoded
        if evidence in ("dropped", "model", "unknown"):
            assert "Prior work says the artifact exists." in encoded
            source = loop.prompts.load("satisfaction_source_" + ("unknown" if evidence == "unknown" else evidence))
            wire_text = '\n\n'.join(m.get("content", "") for m in task_bodies[0]["messages"])
            assert source.strip() in wire_text
        if evidence == "refused":
            assert "Rejected by user" in encoded
        if evidence in ("required-test", "test-not-required"):
            assert "unknown" in encoded.lower()
        common = [(k, {field: value for field, value in v.items() if field != "plan_off"}) for k, v in review_events]
        seen.append((reasoner.calls, common, session.latest_satisfaction, session.latest_satisfaction_evidence,
                     session.pending_done_parts, session.completion_checks))
    assert seen[0] == seen[1], "whole-task question or authoritative transition drifted between drivers"


@pytest.mark.parametrize("synthetic", [False, True])
@pytest.mark.parametrize("mode", ["red", "stale", "unknown"])
def test_pending_probe_cannot_release_on_red_stale_or_unknown_gate(monkeypatch, synthetic, mode):
    driver, session, body, frames = driver_fixture(synthetic=synthetic, scheduled=True, reasoner=lambda *_: b'{}')
    monkeypatch.setattr(loop, "judge_satisfaction", lambda *_a, **_k: (True, "reviewed", ""))
    log = Log()
    driver.drive(body, "sid:review", None, log)
    pending_id = session.probe_call_id
    reply = gate_reply(session, body, red=mode == "red")
    if mode == "stale":
        # A real pending transport still exists: rewrite recovery must poll THAT
        # transport, not trust a tool result for an unrelated older gate.
        pending_plan = session.gate_plan
        from cria import probegate
        pending_plan.transport_required = True
        pending_plan.transport_path = "/tmp/synthetic-harness-spool"
        reply["messages"][-1]["tool_call_id"] = "older-id"
        reply["messages"] = [{"role": "user", "content": loop._COMPACTION_MARKER + "\nPrior actions retained."},
                             reply["messages"][-1]]
        result = driver.drive(reply, "sid:review", None, log)
        assert session.done_probe and session.probe_call_id != pending_id
        assert session.pending_done_parts == ("reviewed",)
        assert session.gate_plan is pending_plan
    elif mode == "unknown":
        from cria import probegate
        session.gate_plan.transport_required = True
        session.gate_plan.transport_openerless_streak = probegate.GATE_OPENERLESS_MAX - 1
        reply["messages"][-1]["content"] = "unreadable transport payload"
        result = driver.drive(reply, "sid:review", None, log)
        assert not session.done_probe and not session.pending_done_parts
        assert not session.last_gate_ran
    else:
        result = driver.drive(reply, "sid:review", None, log)
        assert not session.done_probe and not session.pending_done_parts
        assert session.last_gate_red
    assert result["choices"][0]["message"].get("tool_calls")
    assert driver._store.get("sid:review") is session


@pytest.mark.parametrize("synthetic", [False, True])
def test_l4_real_driver_bypasses_scheduled_review_without_consuming_cadence(monkeypatch, synthetic):
    driver, session, body, frames = driver_fixture(synthetic=synthetic, scheduled=True, reasoner=lambda *_: b'{}')
    driver._ctx.pilot_runtime = assistruntime.AssistRuntime.select(level=4)
    monkeypatch.setattr(loop, "judge_satisfaction", lambda *_a, **_k: pytest.fail("L5 scheduled review ran at L4"))
    log = Log()
    driver.drive(body, "sid:review", None, log)
    assert frames and session.satisfaction_last_drive == -1 and session.latest_satisfaction is None
    assert not any(k == "loop.task_review" for k, _ in log.events)


@pytest.mark.parametrize("outcome", ["positive", "negative", "unreadable"])
@pytest.mark.parametrize("evidence", ["actions", "dropped", "refused", "required-test"])
def test_reactive_real_drivers_use_the_same_question_but_keep_their_release_and_retry_owners(outcome, evidence):
    seen = []
    for synthetic in (False, True):
        reasoner = Reasoner(outcome, required="REQUIRED" if evidence == "required-test" else "NOT_REQUIRED")
        driver, session, body, frames = driver_fixture(synthetic=synthetic, reasoner=reasoner)
        driver._ctx.pilot_runtime = assistruntime.AssistRuntime.select(level=4)
        add_evidence(evidence, session, body)
        session.pending_done = "held success"
        session.probe_call_id = "probe-result"
        if synthetic:
            session.done_probe = True
        else:
            session.plan.items[0].done = True
            session.completion_probe_id = session.probe_call_id
        body = gate_reply(session, body)
        log = Log()
        result = driver.drive(body, "sid:review", None, log)
        approved = outcome == "positive" and evidence != "required-test"
        assert session.latest_satisfaction is approved
        assert not session.done_probe and not session.pending_done_parts
        if not approved:
            assert not session.pending_done
        judgments = [(p, b) for p, b in reasoner.calls if p in ("satisfaction", "satisfaction-noreason")]
        rounds = 1 if approved or synthetic else loop.MAX_COMPLETION_CHECKS
        assert len(judgments) == rounds * (2 if outcome == "unreadable" else 1)
        events = [v for k, v in log.events if k == "loop.task_review"]
        assert len(events) == rounds and all(v["satisfied"] is approved for v in events)
        trigger = ReviewTrigger.CLAIM if synthetic else ReviewTrigger.PLAN_EXHAUSTED
        assert all(v["trigger"] == trigger.value for v in events)
        if synthetic and not approved:
            assert result["choices"][0]["message"].get("tool_calls") and len(frames) == 1
            assert driver._store.get("sid:review") is session
        else:
            assert not result["choices"][0]["message"].get("tool_calls") and not frames
            assert driver._store.get("sid:review") is None
        if not synthetic and not approved:
            # The pre-existing bounded plan-exhausted escape is NOT an approval.
            assert session.completion_checks == loop.MAX_COMPLETION_CHECKS
            assert any(k == "loop.done_unverified" for k, _ in log.events)
        seen.append(judgments[:2 if outcome == "unreadable" else 1])
    assert seen[0] == seen[1], "reactive whole-task prompt/evidence drifted between release owners"


@pytest.mark.parametrize("synthetic", [False, True])
def test_registered_negative_without_guidance_cannot_release_a_held_completion(monkeypatch, synthetic):
    def withheld(source, state):
        record_satisfaction(state, False, "")
        return ReviewResult(ReviewStatus.REJECTED)
    driver, session, body, frames = driver_fixture(synthetic=synthetic, reasoner=lambda *_: b'{}')
    driver._ctx.pilot_runtime = replace(assistruntime.DEFAULT,
        task_review=replace(DEFINITION, execute=withheld))
    session.done_probe = True
    session.probe_call_id = "held-probe"
    session.pending_done = "held success"
    session.pending_done_parts = ("held scheduled approval",)
    session.latest_satisfaction = True
    body = gate_reply(session, body)
    monkeypatch.setattr(loop, "judge_satisfaction", lambda *_a, **_k: pytest.fail("default judge executed"))
    log = Log()
    result = driver.drive(body, "sid:review", None, log)
    assert result["choices"][0]["message"].get("tool_calls") and len(frames) == 1
    assert session.latest_satisfaction is False and not session.pending_done and not session.pending_done_parts
    assert not session.done_probe and driver._store.get("sid:review") is session
    wire_text = '\n\n'.join(str(m.get("content", "")) for m in frames[0]["messages"])
    assert "held success" not in wire_text and "held scheduled approval" not in wire_text
    assert loop.prompts.load("done_no_named_gap").strip() in wire_text


@dataclass(frozen=True)
class LocalInput:
    text: str


@dataclass(frozen=True)
class LocalDefinition:
    policy: Policy
    execute: Callable[[LocalInput], str]


def test_source_owned_typed_stages_select_replace_disable_and_keep_declared_order():
    called = []
    first = LocalDefinition(Policy("local-first", "local-preparation", 2, family_id="fixture",
        state="request-local"), lambda source: called.append("first") or source.text)
    second = LocalDefinition(Policy("local-second", "local-preparation", 3, family_id="fixture",
        state="request-local", dependencies=(first.policy.id,)),
        lambda source: called.append("second") or source.text.upper())
    registry = assistruntime.DEFINITIONS + (first, second)
    runtime = assistruntime.AssistRuntime.select(level=5, registrations=registry)
    assert runtime.bindings("local-preparation") == (first, second)
    assert runtime.selected == assistruntime.DEFAULT.selected + (first.policy.id, second.policy.id)
    # Merely selecting a stage invokes nothing. Its typed consumer owns the call.
    assert called == []
    assert tuple(d.execute(LocalInput("work")) for d in runtime.bindings("local-preparation")) == ("work", "WORK")
    assert called == ["first", "second"]
    swapped = replace(second, execute=lambda source: "replacement: " + source.text)
    runtime = replace(runtime, ordered_stages=(swapped, first))
    assert runtime.bindings("local-preparation") == (first, swapped)
    assert runtime.bindings("local-preparation")[1].execute(LocalInput("work")) == "replacement: work"
    assert assistruntime.AssistRuntime.select(level=2, registrations=registry).bindings("local-preparation") == (first,)
    assert assistruntime.AssistRuntime.select(level=5, registrations=registry,
        disabled=(first.policy.id, second.policy.id)).bindings("local-preparation") == ()
    with pytest.raises(ValueError, match="Disabled dependency"):
        assistruntime.AssistRuntime.select(level=5, registrations=registry, disabled=(first.policy.id,))
    with pytest.raises(ValueError, match="registered policy contract"):
        replace(runtime, ordered_stages=(first, replace(second, policy=replace(second.policy, family_id="changed"))))
    with pytest.raises(ValueError, match="Unregistered"):
        replace(assistruntime.DEFAULT, ordered_stages=(first,))
    with pytest.raises(ValueError, match="immutable"):
        replace(runtime, ordered_stages=[first, second])
