"""Public STEP review selection/observation contracts; fake providers, no task approval."""
import base64
import copy
import hashlib
import json
from dataclasses import replace

import pytest

from cria import assistruntime, completionconfirmation, completiondiagnosis, completionreview, livingplan, loop, probegate, stepreview as sp, wsview
from cria.config import Role
from cria.plan import Plan, PlanItem


TASK = "Write the report and its tests."
STEP = "Write report.md."
KEY = "sid:step-review-source"
TOOLS = [{"type": "function", "function": {"name": "exec_command", "parameters": {
    "type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}}]


class Log:
    def __init__(self):
        self.events = []

    def emit(self, name, **fields):
        self.events.append((name, fields))


def action(cid):
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": cid, "type": "function", "function": {
            "name": "exec_command", "arguments": json.dumps({"cmd": "printf work"})}}]}}]}


def fixture(runtime, *, acting_only=False, judge_done=False, workspace_root=None):
    # STEP selection is the subject; independently selected tail revision would ask other questions.
    runtime = replace(runtime, ordered_stages=tuple(definition for definition in runtime.ordered_stages
        if definition.policy.id != livingplan.DEFINITION.policy.id))
    coder_frames, reasoner_frames = [], []
    replies = [action("work-1"), {"choices": [{"message": {
        "role": "assistant", "content": "The report step is complete."}}]}, action("work-2")]

    def coder(body, log):
        coder_frames.append(copy.deepcopy(body))
        reply = action(f"work-{len(coder_frames)}") if acting_only else (
            replies.pop(0) if replies else action("more-work"))
        return json.dumps(reply).encode()

    def reasoner(body, log):
        reasoner_frames.append(copy.deepcopy(body))
        if getattr(log, "phase", "") == "confirm-applies":
            return json.dumps({"choices": [{"message": {"content": "YES"}}]}).encode()
        return json.dumps({"choices": [{"message": {"content": json.dumps({
            "done": judge_done, "reason": "", "proposed_fix": ""})}}]}).encode()

    session = loop.PlanSession(plan=Plan(id="review-source", task=TASK, created="now",
        items=[PlanItem(STEP), PlanItem("Write report tests.")]), workspace_root=workspace_root)
    store = loop.LoopStore()
    store.put(KEY, session)
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=coder,
        reasoner_chat=reasoner, reasoner_role=Role(name="reasoner", backend="local"),
        planner_enabled=True, pilot_runtime=runtime, runs_dir="", workspace_root=workspace_root,
        self_compact=False,
        focus_trim=False, satisfaction_check_start=0), store)
    body = {"messages": [{"role": "user", "content": TASK}], "tools": copy.deepcopy(TOOLS)}
    return driver, session, body, Log(), coder_frames, reasoner_frames


def claim_then_return_required_probe(driver, session, body, log):
    first = driver.drive(body, KEY, None, log)
    assert first["choices"][0]["message"]["tool_calls"][0]["id"] == "work-1"
    history = body["messages"] + [first["choices"][0]["message"],
        {"role": "tool", "tool_call_id": "work-1", "content": "work"}]
    claim = {**body, "messages": history}
    issued = driver.drive(claim, KEY, None, log)
    call = issued["choices"][0]["message"]["tool_calls"][0]
    assert call["id"] == session.probe_call_id and session.awaiting_probe
    # This is a harness refusal of the actual issued probe, not a fabricated clean result.
    returned = {**body, "messages": history + [issued["choices"][0]["message"],
        {"role": "tool", "tool_call_id": call["id"], "content": "sandbox refused command"}]}
    result = driver.drive(returned, KEY, None, log)
    return result, returned, call


def test_public_absent_step_review_keeps_current_step_without_unconditional_critic():
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True,
        disabled=(sp.DEFINITION.policy.id,))
    driver, session, body, log, frames, questions = fixture(runtime)
    result, returned, call = claim_then_return_required_probe(driver, session, body, log)
    assert questions == [], "absent STEP policy still ran the legacy unconditional critic"
    assert not session.plan.items[0].done and session.plan.items[0].note != "verified"
    assert session.latest_satisfaction is None and driver._store.get(KEY) is session
    assert result["choices"][0]["message"].get("tool_calls") and len(frames) == 3
    assert any(name == "loop.probe" for name, _ in log.events)
    assert returned["messages"][-1]["tool_call_id"] == call["id"]


def test_public_absent_scheduled_review_gathers_nothing_and_does_not_consume_cadence():
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True,
        disabled=(sp.DEFINITION.policy.id,))
    driver, session, body, log, frames, questions = fixture(runtime, acting_only=True)
    for _ in range(sp.STEP_CHECK_EVERY):
        result = driver.drive(body, KEY, None, log)
        assert result["choices"][0]["message"].get("tool_calls")
    assert questions == [], "absent scheduled STEP selection still ran the legacy critic"
    assert session.step_checked_drive == -1 and not session.periodic_observation
    assert not session.plan.items[0].done and session.latest_satisfaction is None
    assert len(frames) == sp.STEP_CHECK_EVERY


def test_public_exact_step_replacement_receives_real_claim_and_probe_evidence():
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True)
    definition = next(d for d in runtime.definitions if d.policy.id == sp.DEFINITION.policy.id)
    seen = []

    def execute(source):
        seen.append(source)
        return sp.StepResult(sp.StepStatus.REJECTED, "selected step repair", readable=True,
            effect=sp.StepEffect(sp.StepAction.RENUDGE, "selected step repair",
                                 verify_failures=1, critic_failures=1))

    replacement = replace(definition, execute=execute)
    runtime = replace(runtime, ordered_stages=tuple(
        replacement if d is definition else d for d in runtime.ordered_stages))
    driver, session, body, log, frames, questions = fixture(runtime)
    result, returned, call = claim_then_return_required_probe(driver, session, body, log)
    assert len(seen) == 1, "the public claim ignored the exact selected STEP executor"
    source = seen[0]
    assert source.step == STEP and source.original_task == TASK and source.key == KEY
    assert source.trigger is sp.StepTrigger.CLAIM and source.probe.transport_unknown
    assert not source.probe.pending and not source.probe.ran
    assert "selected step repair" in json.dumps(frames[-1]["messages"])
    assert questions == [] and not session.plan.items[0].done
    assert session.latest_satisfaction is None and result["choices"][0]["message"].get("tool_calls")
    assert driver._ctx.pilot_runtime.step_review.definition is replacement


@pytest.mark.parametrize("seat", ["confirmation", "diagnosis"])
def test_public_canonical_step_uses_exact_independently_selected_support(seat):
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True)
    original = (runtime.completion_confirmation if seat == "confirmation"
                else runtime.completion_diagnosis)
    calls = []

    def execute(request, services):
        calls.append((request, services))
        if seat == "confirmation":
            return completionconfirmation.Result(completionconfirmation.Status.REJECTED,
                reason="selected confirmation says keep working",
                authority=completionconfirmation.Authority.STEP)
        return completiondiagnosis.DiagnosisResult(completiondiagnosis.DiagnosisStatus.WITHHELD)

    replacement = replace(original, execute=execute)
    runtime = replace(runtime, ordered_stages=tuple(
        replacement if definition is original else definition for definition in runtime.ordered_stages))
    driver, session, body, log, frames, questions = fixture(runtime,
        judge_done=seat == "confirmation", workspace_root="/workspace/step-support")
    claim_then_return_required_probe(driver, session, body, log)
    assert len(calls) == 1 and calls[0][0].original_task == TASK
    if seat == "confirmation":
        assert calls[0][0].claim == STEP
        assert calls[0][0].authority is completionconfirmation.Authority.STEP
        assert calls[0][0].phase == "critic-confirm"
        assert driver._ctx.pilot_runtime.completion_confirmation is replacement
    else:
        assert calls[0][0].task == STEP and calls[0][0].phase == "critic-diagnosis"
        assert driver._ctx.pilot_runtime.completion_diagnosis is replacement
    # Unknown transport is not a red finding; the positive claim also asks applicability.
    assert len(questions) == (2 if seat == "confirmation" else 1)
    assert not session.plan.items[0].done
    assert session.latest_satisfaction is None and driver._store.get(KEY) is session


@pytest.mark.parametrize("scheduled", [False, True])
def test_public_absent_confirmation_is_no_brake_not_negative_step_review(scheduled):
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True,
        disabled=(completionconfirmation.DEFINITION.policy.id,))
    definition = runtime.step_review.definition
    results, inputs = [], []

    def execute(source):
        inputs.append(source)
        result = definition.execute(source)
        results.append(result)
        return result

    replacement = replace(definition, execute=execute)
    runtime = replace(runtime, ordered_stages=tuple(
        replacement if actual is definition else actual for actual in runtime.ordered_stages))
    driver, session, body, log, frames, questions = fixture(runtime,
        acting_only=scheduled, judge_done=True, workspace_root="/workspace/disabled-step-brake")
    if scheduled:
        for _ in range(sp.STEP_CHECK_EVERY):
            driver.drive(body, KEY, None, log)
    else:
        claim_then_return_required_probe(driver, session, body, log)
    assert len(results) == len(inputs) == 1 and len(questions) == 2
    assert driver._ctx.pilot_runtime.completion_confirmation is None
    assert driver._ctx.pilot_runtime.step_review.definition is replacement
    assert inputs[0].original_task == TASK
    assert results[0].status is (sp.StepStatus.UNOBSERVED if scheduled else sp.StepStatus.APPROVED)
    assert results[0].confirmation is None and results[0].review_done
    assert session.plan.items[0].done is (not scheduled)
    assert not session.periodic_observation and session.latest_satisfaction is None
    assert not session.verify_fails and not session.critic_fails
    assert not any(name == "loop.done_confirm" for name, _ in log.events)


def test_public_step_approval_cannot_cross_current_whole_task_rejection():
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True)
    definition = runtime.step_review.definition
    seen = []
    def execute(source):
        seen.append(source)
        return sp.StepResult(sp.StepStatus.APPROVED, 'this step only',
            effect=sp.StepEffect(sp.StepAction.ADVANCE), readable=True, review_done=True)
    replacement = replace(definition, execute=execute)
    runtime = replace(runtime, ordered_stages=tuple(
        replacement if actual is definition else actual for actual in runtime.ordered_stages))
    driver, session, body, log, frames, questions = fixture(runtime)
    completionreview.record_satisfaction(session, False, 'the whole task still lacks tests')
    result, returned, call = claim_then_return_required_probe(driver, session, body, log)
    assert len(seen) == 1 and not session.plan.items[0].done
    assert session.latest_satisfaction is False and session.pending_done_parts == ()
    assert driver._store.get(KEY) is session and result['choices'][0]['message'].get('tool_calls')
    assert not questions and 'whole task still lacks tests' in json.dumps(frames[-1]['messages'])


@pytest.mark.parametrize('bad', [None, {'done': True}, sp.StepResult('approved')])
def test_public_invalid_step_result_cannot_advance_or_release(bad):
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True)
    definition = runtime.step_review.definition
    seen = []
    def execute(source):
        seen.append(source)
        return bad
    replacement = replace(definition, execute=execute)
    runtime = replace(runtime, ordered_stages=tuple(
        replacement if actual is definition else actual for actual in runtime.ordered_stages))
    driver, session, body, log, frames, questions = fixture(runtime)
    with pytest.raises(TypeError):
        claim_then_return_required_probe(driver, session, body, log)
    assert len(seen) == 1 and seen[0].step == STEP
    assert not session.plan.items[0].done and session.latest_satisfaction is None
    assert driver._store.get(KEY) is session and not questions


@pytest.mark.parametrize("action", [sp.StepAction.KEEP_WORKING, sp.StepAction.NONE])
@pytest.mark.parametrize("observed", [False, True])
def test_public_scheduled_selected_action_vetoes_advance_and_observation(action, observed):
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True)
    definition = runtime.step_review.definition
    seen = []

    def execute(source):
        seen.append(source)
        return sp.StepResult(sp.StepStatus.APPROVED, "review is not an action grant",
            completionconfirmation.Result(completionconfirmation.Status.CONFIRMED,
                confirmed=True, observed=observed, authority=completionconfirmation.Authority.STEP),
            sp.StepEffect(action), readable=True, review_done=True)

    replacement = replace(definition, execute=execute)
    runtime = replace(runtime, ordered_stages=tuple(
        replacement if actual is definition else actual for actual in runtime.ordered_stages))
    driver, session, body, log, frames, questions = fixture(runtime, acting_only=True,
        workspace_root="/workspace/step-action-veto")
    for _ in range(sp.STEP_CHECK_EVERY):
        result = driver.drive(body, KEY, None, log)
    assert len(seen) == 1 and seen[0].trigger is sp.StepTrigger.SCHEDULED
    assert not questions and driver._ctx.pilot_runtime.step_review.definition is replacement
    assert not session.plan.items[0].done, "scheduled consumer ignored the selected action veto"
    assert not session.periodic_observation, "scheduled consumer invented an observation effect"
    assert not session.awaiting_probe and session.gate_plan is None
    assert len(frames) == sp.STEP_CHECK_EVERY and result["choices"][0]["message"].get("tool_calls")
    assert session.latest_satisfaction is None and driver._store.get(KEY) is session


def page(plan, raw, offset=0, size=None):
    data = raw.encode()
    chunk = data[offset:] if size is None else data[offset:offset + size]
    path = f"/tmp/.cria-gate-{plan.transport_id}.spool"
    return "\n".join([probegate._transport_marker(plan.transport_id),
        "path\t" + base64.b64encode(path.encode()).decode(), f"offset\t{offset}",
        f"total\t{len(data)}", "sha256\t" + hashlib.sha256(data).hexdigest(),
        "enc\traw", "data\t" + base64.b64encode(chunk).decode(),
        probegate._transport_marker(plan.transport_id, end=True)])


def returned_body(body, issued, text, *, cid=None):
    call = issued["choices"][0]["message"]["tool_calls"][0]
    return {**body, "messages": body["messages"] + [issued["choices"][0]["message"],
        {"role": "tool", "tool_call_id": cid or call["id"], "content": text}]}


@pytest.mark.parametrize("foreign_result", [False, True])
def test_public_scheduled_observation_requires_own_complete_raw_reading_and_fresh_rejudge(foreign_result):
    root = "/workspace/step-observation"
    view = wsview.View(root, KEY)
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True)
    definition = runtime.step_review.definition
    seen, measured = [], []

    def execute(source):
        seen.append(source)
        measured.append(view.read("report.md"))
        assert source.trigger is sp.StepTrigger.SCHEDULED
        if len(seen) == 1:
            return sp.StepResult(sp.StepStatus.UNOBSERVED, "discard this old positive",
                completionconfirmation.Result(completionconfirmation.Status.CONFIRMED,
                    confirmed=True, observed=False, authority=completionconfirmation.Authority.STEP),
                sp.StepEffect(sp.StepAction.OBSERVE_WORKSPACE), readable=True, review_done=True)
        return sp.StepResult(sp.StepStatus.REJECTED, "fresh reading still needs work",
            effect=sp.StepEffect(sp.StepAction.KEEP_WORKING), readable=True)

    replacement = replace(definition, execute=execute)
    runtime = replace(runtime, ordered_stages=tuple(
        replacement if actual is definition else actual for actual in runtime.ordered_stages))
    driver, session, body, log, frames, questions = fixture(runtime,
        acting_only=True, workspace_root=root)
    token = wsview.bind(view)
    try:
        for _ in range(sp.STEP_CHECK_EVERY):
            issued = driver.drive(body, KEY, None, log)
        assert len(seen) == 1, "scheduled review ignored the selected executor"
        assert session.periodic_observation and session.awaiting_probe, [
            (name, fields) for name, fields in log.events
            if name in ("loop.gate_error", "loop.periodic_step_check", "loop.periodic_step_satisfied",
                        "loop.periodic_step_observation_scheduled")]
        assert not session.plan.items[0].done and not view.surveyed
        assert len(frames) == sp.STEP_CHECK_EVERY - 1 and not questions
        content = "RAW OBSERVATION: report is still incomplete.\n"
        survey = "\n".join([wsview.SURVEY_OPEN, "___CRIA_SV_meta___", "root\t" + root,
            "___CRIA_SV_tree___", f"F\t1\t{len(content.encode())}\treport.md",
            "___CRIA_SV_blob___", "@" + base64.b64encode(b"report.md").decode(),
            base64.b64encode(content.encode()).decode(), "___CRIA_SV_done___",
            "entries\t1", "complete\t1", wsview.SURVEY_CLOSE, ""])
        plan = session.gate_plan
        if foreign_result:
            wrong = returned_body(body, issued, page(plan, survey), cid="unrelated-observation")
            issued = driver.drive(wrong, KEY, None, log)
            assert len(seen) == 1 and not view.surveyed and session.periodic_observation
            assert session.gate_plan is plan and session.awaiting_probe
        cut = len(survey.encode()) // 2
        issued = driver.drive(returned_body(body, issued, page(plan, survey, size=cut)), KEY, None, log)
        assert len(seen) == 1 and not view.surveyed and session.periodic_observation
        assert not plan.transport_complete and bytes(plan.transport_data) == survey.encode()[:cut]
        issued = driver.drive(returned_body(body, issued, page(plan, survey, offset=cut)), KEY, None, log)
        assert view.surveyed and view.read("report.md") == content
        assert len(seen) == 1 and session.periodic_observation  # required post-survey check remains
        assert session.gate_plan is not plan and session.gate_plan.surveyed_before
        final_plan = session.gate_plan
        final_raw = f"{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}\nabc\n"
        result = driver.drive(returned_body(body, issued, page(final_plan, final_raw)), KEY, None, log)
        assert len(seen) == 2 and measured == [None, content]
        assert seen[1] is not seen[0] and seen[1].original_task == TASK
        assert not seen[1].probe.pending and not seen[1].probe.transport_unknown
        assert not session.periodic_observation and not session.plan.items[0].done
        assert session.latest_satisfaction is None and not session.verify_fails and not session.critic_fails
        assert result["choices"][0]["message"].get("tool_calls") and not questions
        assert driver._ctx.pilot_runtime.step_review.definition is replacement
    finally:
        wsview.unbind(token)
