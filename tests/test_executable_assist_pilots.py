"""Executable pilots: real stages, opt-outs, replacement and task lifecycle.

All upstream responses and gate bytes here are synthetic; no executors/network.
"""
import copy
from dataclasses import replace
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from cria import assistruntime, completionapproval, completiondiagnosis, completionconfirmation, runnercontract, repositorychecks, evidencesummary, memoryhandoff, semanticquery, stalledwork, pastedfile, loop, massage, probegate
from tests.gatefixture import gate_page
from cria.argumentconversion import ArgumentInput, DEFINITION as ARGUMENTS
from cria.config import AssistConfig, Config, Role
from cria.modulestate import DEFINITION as MODULE, Judgment, ModuleInput, ModuleResult, ModuleState
from cria.plan import Plan, PlanItem
from cria.server import CriaHandler
from test_c10_module_state_reset import _outcome, _candidate
from cria import probediscovery, capacitypolicy, transientpolicy, discoverypolicy, documentguidance, externalization, completionredrive


class Log:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


TOOLS = [{"type": "function", "function": {"name": "exec_command", "parameters": {
    "type": "object", "properties": {"cmd": {"type": "string"}, "yield_time_ms": {"type": "integer"}},
    "required": ["cmd"]}}}]
XML = '<tool_call><function=exec_command><parameter=cmd>pwd</parameter><parameter=yield_time_ms>30000</parameter></function></tool_call>'


def completion(channel="content"):
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", channel: XML}}]}


def args(result):
    return json.loads(result["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])


@pytest.mark.parametrize("channel", ["content", "reasoning_content"])
@pytest.mark.parametrize("mode", ["enabled", "disabled", "replacement"])
def test_recovery_stage_uses_selection_and_actual_replacement(channel, mode):
    calls = []

    def replacement(name, values, schemas):
        calls.append((name, values.copy(), schemas))
        return {**values, "yield_time_ms": 17}

    runtime = assistruntime.AssistRuntime()
    if mode == "disabled":
        runtime = replace(runtime, argument_conversion=None)
    elif mode == "replacement":
        runtime = replace(runtime, argument_conversion=replace(ARGUMENTS, execute=replacement))
    log = Log()
    with assistruntime.bound(runtime):
        result = massage.apply(completion(channel), TOOLS, log, tool_call_fixes=True)
    assert args(result)["yield_time_ms"] == {"enabled": 30000, "disabled": "30000", "replacement": 17}[mode]
    assert len(calls) == (1 if mode == "replacement" else 0)
    applied = [fields for event, fields in log.events if event == "massage.arguments_converted"]
    assert len(applied) == (0 if mode == "disabled" else 1)
    if applied:
        assert applied[0]["assist_id"] == ARGUMENTS.policy.id
        assert applied[0]["family_id"] == "F03"


def test_disabled_conversion_does_not_even_read_schema_or_execute():
    class Poison(dict):
        def get(self, *_):
            raise AssertionError("disabled detector read schema")
    values = {"n": "3"}
    runtime = replace(assistruntime.DEFAULT, argument_conversion=None)
    result = runtime.arguments(ArgumentInput("x", values, Poison()), Log())
    assert result.arguments is values and not result.changed


def test_disabled_module_does_not_detect_gather_ask_log_or_change_state():
    def forbidden(*_):
        raise AssertionError("disabled policy executed")
    class Poison:
        @property
        def report(self):
            forbidden()
    log = Log()
    state = ModuleState("keep")
    runtime = replace(assistruntime.DEFAULT, periodic_judgments=())
    result = runtime.module_judgment(ModuleInput(Poison(), forbidden, forbidden, forbidden, log), state)
    assert result.judgment is Judgment.NOT_APPLICABLE
    assert state.signature == "keep" and log.events == []


@pytest.mark.parametrize("answer,judgment", [("ON_TRACK", Judgment.ON_TRACK), ("REANCHOR", Judgment.STEER),
                                             ("unknown", Judgment.WITHHELD), ("", Judgment.WITHHELD)])
def test_judgment_outcomes_and_repeat_settlement(answer, judgment):
    calls = []
    source = ModuleInput(_outcome(), lambda: "exact checker bytes", lambda: ("task", "session"),
                         lambda q: calls.append(q) or answer, Log())
    state = ModuleState()
    first = assistruntime.DEFAULT.module_judgment(source, state)
    second = assistruntime.DEFAULT.module_judgment(source, state)
    assert first.judgment is judgment
    if judgment is Judgment.WITHHELD:
        assert state.signature == "" and len(calls) == 2 and second.judgment is judgment
    else:
        assert state.signature and len(calls) == 1 and second.judgment is Judgment.REPEATED
    assert (first.steer is not None) == (judgment is Judgment.STEER)


def test_withheld_and_steering_effects_cannot_be_confused():
    with pytest.raises(ValueError, match="cannot carry"):
        ModuleResult(Judgment.WITHHELD, "incorrectly deliver this")
    with pytest.raises(ValueError, match="concrete effect"):
        ModuleResult(Judgment.STEER)
    with pytest.raises(ValueError, match="Unknown"):
        ModuleResult("done")


def test_unobserved_test_exit_and_missing_judge_are_silent():
    def forbidden(*_):
        raise AssertionError("unobserved evidence was judged")
    outcome = _outcome()
    outcome.report.results.clear()
    source = ModuleInput(outcome, forbidden, forbidden, forbidden, Log())
    state = ModuleState()
    assert assistruntime.DEFAULT.module_judgment(source, state).judgment is Judgment.NOT_APPLICABLE
    source = replace(source, outcome=_outcome(), ask=None)
    assert assistruntime.DEFAULT.module_judgment(source, state).judgment is Judgment.NOT_APPLICABLE
    assert not state.signature and source.log.events == []


def test_changed_gate_is_rejudged_and_state_does_not_cross_sessions():
    calls = []
    source = ModuleInput(_outcome(), lambda: "first", lambda: ("task", "session"),
                         lambda q: calls.append(q) or "ON_TRACK", Log())
    a, b = ModuleState(), ModuleState()
    assistruntime.DEFAULT.module_judgment(source, a)
    assistruntime.DEFAULT.module_judgment(replace(source, checks=lambda: "changed"), a)
    assistruntime.DEFAULT.module_judgment(source, b)
    assert len(calls) == 3 and a.signature != b.signature


def rig(synthetic, runtime, *, periodic=False):
    seen = []
    plan = Plan(id="pilot", task="Implement the cart billing endpoint.", created="now",
                items=[PlanItem("Implement the cart billing endpoint.")])
    session = loop.PlanSession(plan=plan, synthetic=synthetic, plan_off=synthetic)
    body = {"messages": [{"role": "user", "content": plan.task}], "tools": copy.deepcopy(TOOLS)}
    if periodic:
        test = _candidate(probediscovery.ProbeKind.Test,
                          ["go", "test", "-mod=readonly", "-count=1", "-v", "./..."])
        session.gate_plan = probegate.GatePlan(workspace=".", candidates=[test])
        session.periodic_probe = session.awaiting_probe = True
        session.probe_call_id = "gate"
        raw = (f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
               "billing/money.go:8: missing go.sum entry\nEXIT:1\n"
               f"{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}\nabc\n")
        body["messages"] += [{"role": "assistant", "tool_calls": [{"id": "gate", "type": "function",
                              "function": {"name": "exec_command", "arguments": '{"cmd":"checks"}'}}]},
                             {"role": "tool", "tool_call_id": "gate", "content": gate_page(session.gate_plan, raw)}]

    def coder(frame, log):
        seen.append(copy.deepcopy(frame))
        return json.dumps(completion()).encode()

    store = loop.LoopStore()
    store.put("sid:pilot", session)
    context = loop.LoopContext(planner=None, coder_chat=coder, reasoner_chat=None,
                               reasoner_role=Role(name="reasoner", backend="local"),
                               planner_enabled=not synthetic, runs_dir="", focus_trim=False,
                               self_compact=False, satisfaction_check_start=0, pilot_runtime=runtime)
    return loop.Loop(context, store), session, body, seen


@pytest.mark.parametrize("synthetic", [True, False])
@pytest.mark.parametrize("disabled", [True, False])
def test_both_real_driver_paths_deliver_replaced_policy_and_converted_arguments(synthetic, disabled):
    received = []

    def replacement(source, state):
        received.append(source)
        assert source.outcome.report.results[0].exit_code == 1
        assert "missing go.sum entry" in source.checks()
        state.signature = "replacement-owned"
        return ModuleResult(Judgment.STEER, "A replacement judgment reached the coder.")

    runtime = assistruntime.AssistRuntime(
        argument_conversion=replace(ARGUMENTS, execute=lambda n, a, s: {**a, "yield_time_ms": 19}),
        periodic_judgments=() if disabled else (replace(MODULE, execute=replacement),))
    driver, session, body, frames = rig(synthetic, runtime, periodic=True)
    log = Log()
    result = driver.drive(body, "sid:pilot", None, log)
    assert args(result)["yield_time_ms"] == 19
    assert len(received) == (0 if disabled else 1)
    text = "\n".join(str(m.get("content", "")) for m in frames[0]["messages"])
    assert ("A replacement judgment reached the coder." in text) is not disabled
    if disabled:
        assert "missing go.sum entry" in text
    assert session.module_state.signature == ("" if disabled else "replacement-owned")
    assert not session.periodic_probe and not session.awaiting_probe
    assert session.pilot_selection == runtime.selected
    assert log.coder_preframe["pilot_assists"] == list(runtime.selected)
    # Selection belongs to capture metadata, never the model-facing frame.
    for identity in runtime.selected:
        assert identity not in json.dumps(frames[0])


@pytest.mark.parametrize("synthetic", [True, False])
def test_default_go_judgment_runs_through_both_drivers(synthetic):
    driver, session, body, frames = rig(synthetic, assistruntime.DEFAULT, periodic=True)
    questions = []
    def reasoner(question, log):
        questions.append(copy.deepcopy(question))
        return json.dumps({"choices": [{"message": {"content": "REANCHOR"}}]}).encode()
    driver._ctx.reasoner_chat = reasoner
    log = Log()
    assert args(driver.drive(body, "sid:pilot", None, log))["yield_time_ms"] == 30000
    assert len(questions) == 1 and session.module_state.signature
    assert questions[0]["max_tokens"] == loop.JUDGE_MAX_TOKENS
    text = "\n".join(str(m.get("content", "")) for m in frames[0]["messages"])
    assert "Do not guess a package, version" in text
    events = [fields for name, fields in log.events if name == "loop.module_state"]
    assert len(events) == 1 and events[0]["applied"]
    assert events[0]["assist_id"] == MODULE.policy.id and events[0]["family_id"] == "F47"
    assert not session.gate_fresh  # a periodic judgment cannot release completion


@pytest.mark.parametrize("enabled", [True, False])
def test_stream_recovery_uses_the_same_argument_registration(enabled):
    from test_massage import _sse, StreamMassageTests
    runtime = assistruntime.DEFAULT if enabled else replace(assistruntime.DEFAULT, argument_conversion=None)
    stream = [_sse({"role": "assistant"}), _sse({"content": XML[:37]}),
              _sse({"content": XML[37:]}), _sse({}, "stop"), b"data: [DONE]\n\n"]
    with assistruntime.bound(runtime):
        _, calls = StreamMassageTests()._assemble(massage.massage_stream(iter(stream), "fixture", TOOLS, Log()))
    assert len(calls) == 1
    assert json.loads(calls[0]["function"]["arguments"])["yield_time_ms"] == (30000 if enabled else "30000")


def test_selection_is_task_stable_and_durable_but_signatures_are_transient():
    driver, state, body, _ = rig(True, assistruntime.DEFAULT)
    driver.drive(body, "sid:pilot", None, Log())
    state.module_state.signature = "transient"
    restored = loop._session_from_dict(json.loads(json.dumps(loop._session_to_dict(state))))
    assert restored.pilot_selection == state.pilot_selection
    assert restored.module_state.signature == "" and restored.pilot_binding is None
    driver._ctx.pilot_runtime = replace(assistruntime.DEFAULT, argument_conversion=replace(
        ARGUMENTS, execute=lambda n, a, s: a))
    with pytest.raises(ValueError, match="active task"):
        driver.drive(body, "sid:pilot", None, Log())
    driver._ctx.pilot_runtime = replace(assistruntime.DEFAULT, periodic_judgments=())
    with pytest.raises(ValueError, match="active task"):
        driver.drive(body, "sid:pilot", None, Log())
    assert state.module_state.signature == "transient"
    driver._store.drop("sid:pilot")
    fresh = loop.PlanSession(plan=state.plan, synthetic=True)
    assert fresh.pilot_selection is None and fresh.module_state.signature == ""


def test_registration_dependency_combinations_and_scope_errors(monkeypatch):
    dependency = replace(MODULE, policy=replace(MODULE.policy, dependencies=(ARGUMENTS.policy.id,)))
    monkeypatch.setattr(assistruntime, "DEFINITIONS", (ARGUMENTS, dependency))
    with pytest.raises(ValueError, match="Disabled dependency"):
        assistruntime.AssistRuntime.select(disabled=(ARGUMENTS.policy.id,))
    with pytest.raises(ValueError, match="dependency order"):
        assistruntime.validate((dependency, ARGUMENTS))
    with pytest.raises(ValueError, match="unsupported"):
        assistruntime.validate((replace(ARGUMENTS, policy=replace(ARGUMENTS.policy, scope="native")),))
    for level in (-1, 6, True, 2.5):
        with pytest.raises(ValueError, match="integer"):
            assistruntime.AssistRuntime.select(level=level)


def test_config_selection_unknowns_levels_dependencies_and_planner_consent(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[engagement]\nlevel = 5\n[assists]\ndisabled = ["go-module-state-judgment"]\n')
    cfg = Config.load(path)
    assert not cfg.planner.enabled
    assert assistruntime.AssistRuntime.select(level=cfg.routing.engagement_level,
                                             disabled=cfg.assists.disabled).selected == (
        ARGUMENTS.policy.id, "whole-task-review") + tuple(
            d.policy.id for d in assistruntime.TOOL_DEFINITIONS + assistruntime.RESEARCH_DEFINITIONS
            + assistruntime.HISTORY_DEFINITIONS + assistruntime.ADMISSION_DEFINITIONS + assistruntime.GENERATION_DEFINITIONS + assistruntime.CONTEXT_DEFINITIONS + completionapproval.PRE_RELEASE + completiondiagnosis.DEFINITIONS + completionconfirmation.DEFINITIONS + (runnercontract.DEFINITION,) + repositorychecks.DEFINITIONS + (evidencesummary.DEFINITION, memoryhandoff.DEFINITION) + semanticquery.DEFINITIONS + (stalledwork.DEFINITION, pastedfile.DEFINITION, capacitypolicy.DEFINITION, transientpolicy.TRANSIENT_RECOVERY, discoverypolicy.DEFINITION, documentguidance.DEFINITION, externalization.DEFINITION, completionredrive.DEFINITION))
    for bad in ('disabled = ["unknown"]', 'disabled = "schema-argument-conversion"', 'enabled = true',
                'disabled = ["go-module-state-judgment", "go-module-state-judgment"]'):
        path.write_text('[assists]\n' + bad)
        with pytest.raises(ValueError):
            Config.load(path)
    assert assistruntime.AssistRuntime.select(level=0).selected == tuple(
        d.policy.id for d in assistruntime.TOOL_DEFINITIONS + assistruntime.RESEARCH_DEFINITIONS
        + assistruntime.HISTORY_DEFINITIONS + assistruntime.ADMISSION_DEFINITIONS
        + assistruntime.GENERATION_DEFINITIONS + assistruntime.CONTEXT_DEFINITIONS + completionapproval.PRE_RELEASE + completiondiagnosis.DEFINITIONS + completionconfirmation.DEFINITIONS + (runnercontract.DEFINITION,) + repositorychecks.DEFINITIONS + (evidencesummary.DEFINITION, memoryhandoff.DEFINITION) + semanticquery.DEFINITIONS + (stalledwork.DEFINITION, pastedfile.DEFINITION, capacitypolicy.DEFINITION, transientpolicy.TRANSIENT_RECOVERY, discoverypolicy.DEFINITION, documentguidance.DEFINITION, externalization.DEFINITION, completionredrive.DEFINITION) if d.policy.default_level == 0)
    assert assistruntime.AssistRuntime.select(level=4).selected == (
        ARGUMENTS.policy.id, "whole-task-review") + tuple(
            d.policy.id for d in assistruntime.TOOL_DEFINITIONS + assistruntime.RESEARCH_DEFINITIONS
            + assistruntime.HISTORY_DEFINITIONS + assistruntime.ADMISSION_DEFINITIONS
            + assistruntime.GENERATION_DEFINITIONS + assistruntime.CONTEXT_DEFINITIONS + completionapproval.PRE_RELEASE + completiondiagnosis.DEFINITIONS + completionconfirmation.DEFINITIONS + (runnercontract.DEFINITION,) + repositorychecks.DEFINITIONS + (evidencesummary.DEFINITION, memoryhandoff.DEFINITION) + semanticquery.DEFINITIONS + (stalledwork.DEFINITION, pastedfile.DEFINITION, capacitypolicy.DEFINITION, transientpolicy.TRANSIENT_RECOVERY, discoverypolicy.DEFINITION, documentguidance.DEFINITION, externalization.DEFINITION, completionredrive.DEFINITION) if d.policy.default_level <= 4)
    assert not Config(assists=AssistConfig()).planner.enabled
    dependency = replace(MODULE, policy=replace(MODULE.policy, dependencies=("missing",)))
    with pytest.raises(ValueError, match="dependency"):
        assistruntime.validate((ARGUMENTS, dependency))
    with pytest.raises(ValueError, match="Duplicate"):
        assistruntime.validate((ARGUMENTS, ARGUMENTS))
    wrong = replace(ARGUMENTS, policy=replace(ARGUMENTS.policy, stage="periodic-check-result"))
    with pytest.raises(ValueError, match="wrong stage"):
        assistruntime.AssistRuntime(argument_conversion=wrong)


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses"])
def test_handler_binds_configured_selection_without_network(path):
    disabled = replace(assistruntime.DEFAULT, argument_conversion=None)
    seen = []
    handler = SimpleNamespace(path=path, server=SimpleNamespace(pilot_runtime=disabled),
                              _handle_chat=lambda: seen.append(assistruntime.current()),
                              _handle_responses=lambda: seen.append(assistruntime.current()))
    CriaHandler.do_POST(handler)
    assert seen == [disabled] and assistruntime.current() is assistruntime.DEFAULT


def test_concurrent_bindings_and_exception_reset():
    disabled = replace(assistruntime.DEFAULT, argument_conversion=None)
    def run(runtime):
        with assistruntime.bound(runtime):
            return args(massage.apply(completion(), TOOLS, Log(), tool_call_fixes=True))["yield_time_ms"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, [assistruntime.DEFAULT, disabled] * 4)) == [30000, "30000"] * 4
    with pytest.raises(RuntimeError):
        with assistruntime.bound(disabled):
            raise RuntimeError("interruption")
    assert assistruntime.current() is assistruntime.DEFAULT
