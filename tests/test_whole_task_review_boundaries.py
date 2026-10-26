"""Synthetic offline regressions for whole-task release and raw-task redrive."""
import copy
import json

import pytest

from tests.gatefixture import gate_page
from cria import loop, probegate, probediscovery
from cria.config import Role
from cria.plan import Plan, PlanItem
from test_executable_assist_pilots import Log, TOOLS, completion
from test_c10_module_state_reset import _candidate


TASK = "Finish the requested artifact."


def driver_fixture(*, synthetic, coder=None, reasoner=None, scheduled=False, shell=True):
    plan = Plan(id="review", task=TASK, created="now", items=[PlanItem(TASK)])
    session = loop.PlanSession(plan=plan, synthetic=synthetic, plan_off=synthetic)
    store = loop.LoopStore()
    store.put("sid:review", session)
    frames = []
    def call(frame, log):
        frames.append(copy.deepcopy(frame))
        return (coder(frame, log) if coder else json.dumps(completion()).encode())
    context = loop.LoopContext(planner=None, coder_chat=call, reasoner_chat=reasoner,
        reasoner_role=Role(name="reasoner", backend="local") if reasoner else None,
        planner_enabled=not synthetic, runs_dir="", self_compact=False, focus_trim=False,
        satisfaction_check_start=1 if scheduled else 0, satisfaction_check_every=1)
    body = {"messages": [{"role": "user", "content": TASK}],
            "tools": copy.deepcopy(TOOLS) if shell else [{"type": "function", "function": {
                "name": "write_file", "parameters": {"type": "object", "properties": {
                    "path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"]}}}]}
    return loop.Loop(context, store), session, body, frames


def gate_reply(session, body, *, red=False):
    candidate = _candidate(probediscovery.ProbeKind.Test, ["go", "test", "./..."])
    session.gate_plan = probegate.GatePlan(workspace=".", candidates=[candidate], transport_id="0" * 24)   # a fixed id: the evidence must not vary by run
    raw = (f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
           + ("thing.go:8: broken\nEXIT:1\n" if red else "ok package\nEXIT:0\n")
           + f"{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}\nabc\n")
    return {**body, "messages": body["messages"] + [
        {"role": "tool", "tool_call_id": session.probe_call_id, "content": gate_page(session.gate_plan, raw)}]}


@pytest.mark.parametrize("red", [False, True])
def test_plan_on_scheduled_approval_has_a_real_gate_result_consumer(monkeypatch, red):
    driver, session, body, frames = driver_fixture(synthetic=False, scheduled=True,
        reasoner=lambda *_: b'{}')
    monkeypatch.setattr(loop, "judge_satisfaction", lambda *_a, **_k: (True, "reviewed", ""))
    log = Log()
    issued = driver.drive(body, "sid:review", None, log)
    assert issued["choices"][0]["message"].get("tool_calls") and not frames
    returned = gate_reply(session, body, red=red)
    result = driver.drive(returned, "sid:review", None, log)
    assert not session.done_probe, "scheduled whole-task probe remained ownerless on plan-on"
    assert session.pending_done_parts == ()
    if red:
        assert result["choices"][0]["message"].get("tool_calls")
        assert session.last_gate_red and driver._store.get("sid:review") is session
    else:
        assert not result["choices"][0]["message"].get("tool_calls")
        assert driver._store.get("sid:review") is None


def test_single_item_no_shell_rejection_redrives_the_raw_task_not_a_step(monkeypatch):
    replies = iter([{"choices": [{"finish_reason": "stop", "message": {"content": "done"}}]},
        {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{
            "id": "write", "type": "function", "function": {"name": "write_file",
            "arguments": '{"path":"artifact.txt","content":"work"}'}}]}}]}])
    driver, session, body, frames = driver_fixture(synthetic=True, shell=False,
        reasoner=lambda *_: b'{}', coder=lambda *_: json.dumps(next(replies)).encode())
    session.action_seq = 1  # no LEG0 retry: the session already acted
    monkeypatch.setattr(loop, "judge_satisfaction", lambda *_a, **_k: (False, "still needed", ""))
    log = Log()
    out = driver.drive(body, "sid:review", None, log)
    assert out["choices"][0]["message"].get("tool_calls") and len(frames) == 2
    observed = [fields["state"]["driver"] for event, fields in log.events if event == "loop.coder_preframe"]
    assert observed == ["plan_off", "plan_off"], "reactive rejection entered the step driver"
    assert session.drive_count == 2
    assert session.latest_satisfaction is False and not session.done_probe
