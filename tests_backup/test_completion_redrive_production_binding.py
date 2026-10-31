"""Real completion drivers, fake coder only; no external execution.

Run only after the actual runtime selection projection exists. The same tests
must witness ignored selection before binding and retained behavior afterward.
"""
import copy
import json
from dataclasses import replace

import pytest

from cria import assistruntime, completionredrive as policy, loop
from cria.config import Role
from cria.plan import Plan, PlanItem


TASK = "Write the report."
KEY = "sid:completion-act-first"
STEP_TEXT = "you used no tools and changed nothing this step — do the step's work with tool calls first, then report"
TASK_TEXT = "you used no tools and changed nothing — do the actual work with tool calls first, then report when it is genuinely done"
TOOLS = [{"type": "function", "function": {"name": "exec_command", "parameters": {
    "type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}}]


class Log:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


def action():
    return {"choices": [{"message": {"role": "assistant", "content": "retained exact action", "tool_calls": [
        {"id": "actual-followup", "type": "function", "function": {
            "name": "exec_command", "arguments": '{"cmd":"printf work"}'}}]}}]}


def selected(*, synthetic, definition=policy.DEFINITION, disabled=False, level=5):
    # Isolate this optional reask, not the required completion fact/check path.
    disabled_ids = tuple(d.policy.id for d in assistruntime.DEFINITIONS
        if d.policy.id not in (policy.DEFINITION.policy.id, "whole-task-review", "repository-check-lifecycle"))
    if disabled:
        disabled_ids += (policy.DEFINITION.policy.id,)
    registrations = tuple(definition if d.policy.id == policy.DEFINITION.policy.id else d
                          for d in assistruntime.DEFINITIONS)
    return assistruntime.AssistRuntime.select(level=level, registrations=registrations,
        disabled=disabled_ids, experimental_planning=not synthetic)


def fixture(runtime, *, synthetic, on_coder=None, first=None, second=None, consent=None):
    frames = []
    replies = [({"choices": [{"message": {"role": "assistant", "content": "Done."}}]} if first is None else first),
               action() if second is None else second]

    def coder(body, log):
        frames.append(copy.deepcopy(body))
        if on_coder is not None:
            on_coder(len(frames))
        value = replies.pop(0)
        if isinstance(value, BaseException):
            raise value
        return json.dumps(value).encode()

    session = loop.PlanSession(plan=Plan(id="act-first", task=TASK, created="now", items=[PlanItem(TASK)]))
    session.synthetic = session.plan_off = synthetic
    store = loop.LoopStore()
    store.put(KEY, session)
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=coder, reasoner_chat=None,
        reasoner_role=None, planner_enabled=(not synthetic if consent is None else consent), pilot_runtime=runtime,
        runs_dir="", self_compact=False, focus_trim=False, satisfaction_check_start=0,
        assists=runtime.engagement_level >= 5), store)
    body = {"messages": [{"role": "user", "content": TASK}], "tools": copy.deepcopy(TOOLS)}
    return driver, session, body, Log(), frames


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_disabled_skips_only_optional_reask_and_still_requests_gate(synthetic):
    driver, state, body, log, frames = fixture(selected(synthetic=synthetic, disabled=True), synthetic=synthetic)
    result = driver.drive(body, KEY, None, log)
    assert len(frames) == 1
    assert state.leg0_nudged is False and state.verify_fails == 0
    assert not [fields for event, fields in log.events
                if event == "loop.step_incomplete" and fields.get("reason") == "no tools used"]
    call = result["choices"][0]["message"]["tool_calls"][0]
    assert call["id"] == state.probe_call_id
    assert (state.done_probe if synthetic else state.awaiting_probe)
    assert state.action_seq == 0 and state.step_tool_calls == 0


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_default_exact_prompt_and_real_one_shot_effect(synthetic):
    driver, state, body, log, frames = fixture(selected(synthetic=synthetic), synthetic=synthetic)
    result = driver.drive(body, KEY, None, log)
    assert len(frames) == 2
    expected = "⟦ctx:steer⟧ " + (TASK_TEXT if synthetic else STEP_TEXT)
    assert frames[-1]["messages"][-1] == {"role": "user", "content": expected}
    assert state.leg0_nudged is True
    assert state.verify_fails == (0 if synthetic else 1)
    assert result["choices"][0]["message"]["tool_calls"] == action()["choices"][0]["message"]["tool_calls"]
    events = [fields for event, fields in log.events
              if event == "loop.step_incomplete" and fields.get("reason") == "no tools used"]
    assert events == ([dict(plan_off=True, reason="no tools used")] if synthetic else
                      [dict(step=1, reason="no tools used", attempt=1)])


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_exact_replacement_receives_authoritative_state(synthetic):
    seen = []
    replacement_text = "selected exact act-first bytes\nΩ\n"

    def execute(request):
        seen.append(request)
        return policy.Result(replacement_text, {"role": "user", "content": replacement_text})

    definition = replace(policy.DEFINITION, execute=execute)
    runtime = selected(synthetic=synthetic, definition=definition)
    driver, state, body, log, frames = fixture(runtime, synthetic=synthetic)
    result = driver.drive(body, KEY, None, log)
    assert len(seen) == 1
    assert seen[0].state is state and seen[0].log is log
    assert seen[0].activity == 0
    assert seen[0].authority is (policy.Authority.TASK if synthetic else policy.Authority.STEP)
    expected = replacement_text if synthetic else "⟦ctx:steer⟧ " + replacement_text
    assert frames[-1]["messages"][-1] == {"role": "user", "content": expected}
    assert state.leg0_nudged is False and state.verify_fails == 0
    assert result["choices"][0]["message"]["tool_calls"] == action()["choices"][0]["message"]["tool_calls"]


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_selected_silence_preserves_required_gate(synthetic):
    seen = []

    def execute(request):
        seen.append(request)
        return None

    definition = replace(policy.DEFINITION, execute=execute)
    driver, state, body, log, frames = fixture(
        selected(synthetic=synthetic, definition=definition), synthetic=synthetic)
    result = driver.drive(body, KEY, None, log)
    assert len(seen) == 1 and seen[0].state is state
    assert len(frames) == 1
    assert state.leg0_nudged is False and state.verify_fails == 0
    assert state.action_seq == 0 and state.step_tool_calls == 0
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == state.probe_call_id
    assert state.done_probe if synthetic else state.awaiting_probe
    assert not [fields for event, fields in log.events
                if event == "loop.step_incomplete" and fields.get("reason") == "no tools used"]


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_f44_absent_retained_action_dates_required_clock(synthetic):
    runtime = selected(synthetic=synthetic)
    assert runtime.stalled_work is None
    driver, state, body, log, frames = fixture(runtime, synthetic=synthetic)
    result = driver.drive(body, KEY, None, log)
    assert len(frames) == 2
    assert result["choices"][0]["message"]["tool_calls"] == action()["choices"][0]["message"]["tool_calls"]
    assert state.action_seq == 1
    assert state.step_tool_calls == (0 if synthetic else 1)
    assert state.gate_fresh is False


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_second_prose_reaches_gate_without_repeating_nudge(synthetic):
    second = {"choices": [{"message": {"role": "assistant", "content": "Still done."}}]}
    driver, state, body, log, frames = fixture(selected(synthetic=synthetic),
        synthetic=synthetic, second=second)
    result = driver.drive(body, KEY, None, log)
    assert len(frames) == 2
    assert state.leg0_nudged is True
    assert state.verify_fails == (0 if synthetic else 1)
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == state.probe_call_id
    assert state.done_probe if synthetic else state.awaiting_probe
    assert state.action_seq == 0 and state.step_tool_calls == 0
    assert len([fields for event, fields in log.events
                if event == "loop.step_incomplete" and fields.get("reason") == "no tools used"]) == 1


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_failed_reask_spends_actual_session_once(synthetic):
    failure = RuntimeError("actual coder reinvocation failed")
    driver, state, body, log, frames = fixture(selected(synthetic=synthetic),
        synthetic=synthetic, second=failure)
    with pytest.raises(RuntimeError) as caught:
        driver.drive(body, KEY, None, log)
    assert caught.value is failure
    assert len(frames) == 2
    assert state.leg0_nudged is True
    assert state.verify_fails == (0 if synthetic else 1)
    assert state.action_seq == 0 and state.step_tool_calls == 0
    events = [fields for event, fields in log.events
              if event == "loop.step_incomplete" and fields.get("reason") == "no tools used"]
    assert events == ([dict(plan_off=True, reason="no tools used")] if synthetic else
                      [dict(step=1, reason="no tools used", attempt=1)])


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_captures_selected_definition_before_coder_callback(synthetic):
    seen = []
    exact = "captured A bytes\nΩ\n"

    def execute_a(request):
        seen.append(("A", request))
        return policy.Result(exact, {"role": "user", "content": exact})

    def execute_b(request):
        seen.append(("B", request))
        raise AssertionError("ambient replacement B must not own the in-flight decision")

    runtime_a = selected(synthetic=synthetic, definition=replace(policy.DEFINITION, execute=execute_a))
    runtime_b = selected(synthetic=synthetic, definition=replace(policy.DEFINITION, execute=execute_b))

    captured = runtime_a.completion_act_first

    def swap(call):
        if call == 1:
            # Deliberate process-local projection fault, not an illegal task-runtime swap.
            object.__setattr__(runtime_a, "completion_act_first", runtime_b.completion_act_first)

    driver, state, body, log, frames = fixture(runtime_a, synthetic=synthetic, on_coder=swap)
    try:
        result = driver.drive(body, KEY, None, log)
    finally:
        object.__setattr__(runtime_a, "completion_act_first", captured)
    assert [name for name, request in seen] == ["A"]
    assert seen[0][1].state is state and seen[0][1].log is log
    expected = exact if synthetic else "⟦ctx:steer⟧ " + exact
    assert frames[-1]["messages"][-1] == {"role": "user", "content": expected}
    assert result["choices"][0]["message"]["tool_calls"] == action()["choices"][0]["message"]["tool_calls"]
    assert state.action_seq == 1
    assert state.leg0_nudged is False and state.verify_fails == 0


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_prior_flag_suppresses_reask_not_real_gate(synthetic):
    driver, state, body, log, frames = fixture(selected(synthetic=synthetic), synthetic=synthetic)
    state.leg0_nudged = True
    result = driver.drive(body, KEY, None, log)
    assert len(frames) == 1
    assert state.leg0_nudged is True and state.verify_fails == 0
    assert state.action_seq == 0 and state.step_tool_calls == 0
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == state.probe_call_id
    assert (state.done_probe if synthetic else state.awaiting_probe)
    assert not [fields for event, fields in log.events
                if event == "loop.step_incomplete" and fields.get("reason") == "no tools used"]


@pytest.mark.parametrize("synthetic", [False, True])
@pytest.mark.parametrize("disabled", [False, True])
def test_public_acting_reply_dates_required_clocks_without_optional_redrive(synthetic, disabled):
    seen = []

    def execute(request):
        seen.append(request)
        raise AssertionError("an acting reply must not request act-first steering")

    runtime = selected(synthetic=synthetic,
        definition=replace(policy.DEFINITION, execute=execute), disabled=disabled)
    driver, state, body, log, frames = fixture(runtime, synthetic=synthetic, first=action())
    result = driver.drive(body, KEY, None, log)
    assert seen == [] and len(frames) == 1
    assert result["choices"][0]["message"]["tool_calls"] == action()["choices"][0]["message"]["tool_calls"]
    assert state.action_seq == 1
    assert state.step_tool_calls == (0 if synthetic else 1)
    assert state.leg0_nudged is False and state.verify_fails == 0


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_captures_absence_before_enabled_callback(synthetic):
    seen = []

    def execute_b(request):
        seen.append(request)
        raise AssertionError("callback cannot enable an absent in-flight policy")

    runtime_a = selected(synthetic=synthetic, disabled=True)
    runtime_b = selected(synthetic=synthetic, definition=replace(policy.DEFINITION, execute=execute_b))

    captured = runtime_a.completion_act_first

    def swap(call):
        if call == 1:
            # Keep the selected task runtime intact while faulting only late projection reads.
            object.__setattr__(runtime_a, "completion_act_first", runtime_b.completion_act_first)

    driver, state, body, log, frames = fixture(runtime_a, synthetic=synthetic, on_coder=swap)
    try:
        result = driver.drive(body, KEY, None, log)
    finally:
        object.__setattr__(runtime_a, "completion_act_first", captured)
    assert seen == [] and len(frames) == 1
    assert state.leg0_nudged is False and state.verify_fails == 0
    assert state.action_seq == 0 and state.step_tool_calls == 0
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == state.probe_call_id
    assert (state.done_probe if synthetic else state.awaiting_probe)
    assert not [fields for event, fields in log.events
                if event == "loop.step_incomplete" and fields.get("reason") == "no tools used"]


@pytest.mark.parametrize("synthetic", [False, True])
def test_public_existing_activity_uses_the_correct_authoritative_clock(synthetic):
    driver, state, body, log, frames = fixture(selected(synthetic=synthetic), synthetic=synthetic)
    # Deliberately disagree: the STEP cadence is step-local, TASK is lifetime.
    state.action_seq = 1 if synthetic else 0
    state.step_tool_calls = 0 if synthetic else 1
    result = driver.drive(body, KEY, None, log)
    assert len(frames) == 1
    assert state.action_seq == (1 if synthetic else 0)
    assert state.step_tool_calls == (0 if synthetic else 1)
    assert state.leg0_nudged is False and state.verify_fails == 0
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == state.probe_call_id
    assert (state.done_probe if synthetic else state.awaiting_probe)


@pytest.mark.parametrize("synthetic,level,consent,redrive", [
    (True, 4, False, True),
    (True, 5, False, True),
    (False, 4, True, False),
    (False, 5, False, False),
    (False, 5, True, True),
])
def test_public_caller_rung_and_consent_do_not_reclassify_runtime_policy(synthetic, level, consent, redrive):
    runtime = selected(synthetic=synthetic, level=level)
    assert runtime.completion_act_first is policy.DEFINITION
    assert runtime.stalled_work is None
    driver, state, body, log, frames = fixture(runtime, synthetic=synthetic, consent=consent)
    result = driver.drive(body, KEY, None, log)
    assert len(frames) == (2 if redrive else 1)
    assert state.leg0_nudged is redrive
    assert state.verify_fails == (1 if redrive and not synthetic else 0)
    if redrive:
        assert result["choices"][0]["message"]["tool_calls"] == action()["choices"][0]["message"]["tool_calls"]
        assert state.action_seq == 1
    else:
        assert result["choices"][0]["message"]["tool_calls"][0]["id"] == state.probe_call_id
        assert state.awaiting_probe and state.action_seq == 0


def test_public_real_step_advance_resets_one_shot_before_next_step():
    allowed = {policy.DEFINITION.policy.id, "whole-task-review", "repository-check-lifecycle", "experimental-step-review"}
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True,
        disabled=tuple(d.policy.id for d in assistruntime.DEFINITIONS if d.policy.id not in allowed))
    frames, questions = [], []
    done = {"choices": [{"message": {"role": "assistant", "content": "Done."}}]}
    replies = [done, action(), done, done, action()]

    def coder(body, log):
        frames.append(copy.deepcopy(body))
        return json.dumps(replies.pop(0)).encode()

    def reasoner(body, log):
        questions.append(copy.deepcopy(body))
        content = "NO" if getattr(log, "phase", "") == "confirm-applies" else json.dumps(
            {"done": True, "reason": "", "proposed_fix": ""})
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    state = loop.PlanSession(plan=Plan(id="act-first-reset", task=TASK, created="now",
        items=[PlanItem("Write the report."), PlanItem("Check the report.")]))
    store = loop.LoopStore()
    store.put(KEY, state)
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=coder, reasoner_chat=reasoner,
        reasoner_role=Role(name="reasoner", backend="local"), planner_enabled=True,
        pilot_runtime=runtime, runs_dir="", self_compact=False, focus_trim=False,
        satisfaction_check_start=0), store)
    body = {"messages": [{"role": "user", "content": TASK}], "tools": copy.deepcopy(TOOLS)}
    log = Log()
    first = driver.drive(body, KEY, None, log)
    assert state.leg0_nudged is True and state.verify_fails == 1
    assert state.action_seq == 1 and state.step_tool_calls == 1
    history = body["messages"] + [first["choices"][0]["message"],
        {"role": "tool", "tool_call_id": "actual-followup", "content": "work"}]
    issued = driver.drive({**body, "messages": history}, KEY, None, log)
    call = issued["choices"][0]["message"]["tool_calls"][0]
    assert call["id"] == state.probe_call_id and state.awaiting_probe
    returned = {**body, "messages": history + [issued["choices"][0]["message"],
        {"role": "tool", "tool_call_id": call["id"], "content": "sandbox refused command"}]}
    result = driver.drive(returned, KEY, None, log)
    assert state.plan.items[0].done and not state.plan.items[1].done
    assert state.plan.status != "done" and state.latest_satisfaction is None
    assert state.leg0_nudged is True and state.verify_fails == 1
    assert state.step_tool_calls == 1 and state.action_seq == 2
    assert len(frames) == 5 and questions
    assert result["choices"][0]["message"]["tool_calls"] == action()["choices"][0]["message"]["tool_calls"]
    events = [fields for event, fields in log.events
              if event == "loop.step_incomplete" and fields.get("reason") == "no tools used"]
    assert events == [dict(step=1, reason="no tools used", attempt=1),
                      dict(step=2, reason="no tools used", attempt=1)]
