"""F71 production selection/consumption; synthetic histories and fake providers only.

These are Root binding tests, not summary-quality or final-wire delivery proofs.
No shell, network, native parser, model service or workspace command is executed.
"""
from dataclasses import replace
from types import SimpleNamespace
import json

import pytest

from cria import assistruntime, evidencesummary as policy, loop, prompts
from cria.config import Role
from cria.completionreview import ReviewTrigger, ReviewStatus
from cria.plan import Plan


class Log:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


def runtime(definition=policy.DEFINITION, *, disabled=False, level=5):
    # Include the actual candidate explicitly so a missing DEFAULT registration
    # cannot conceal the separate production-dispatch regression.
    registrations = tuple(d for d in assistruntime.DEFINITIONS
                          if d.policy.id != policy.DEFINITION.policy.id) + (definition,)
    return assistruntime.AssistRuntime.select(level=level, registrations=registrations,
        disabled=(policy.DEFINITION.policy.id,) if disabled else ())


def history(output="EXACT checker output: snow 雪\nsecond line\n"):
    return [{"role": "user", "content": "Implement the requested feature."},
            {"role": "assistant", "tool_calls": [{"id": "check", "type": "function",
             "function": {"name": "exec_command", "arguments": json.dumps({"cmd": "pytest -q"})}}]},
            {"role": "tool", "tool_call_id": "check", "content": output}]


def builder(kind, monkeypatch, messages, log, *, chat=None, role=None, fact_events=None):
    if kind == "task":
        return loop._satisfaction_evidence(messages, rlog=log, chat_fn=chat, role=role)
    driver = loop.Loop.__new__(loop.Loop)
    driver._ctx = SimpleNamespace(reasoner_chat=chat, reasoner_role=role, compactor_role=None)
    state = SimpleNamespace(workspace_root="", gate_plan=None)
    # Explicit independent factual services, not policy or old-owner oracles.
    def fetched(*args, **kwargs):
        if fact_events is not None:
            fact_events.append("fetch")
        return "DURABLE fetched-page fact"
    def inventory(*args, **kwargs):
        if fact_events is not None:
            fact_events.append("inventory")
        return "CURRENT workspace inventory"
    monkeypatch.setattr(loop, "_fetch_ground_truth", fetched)
    monkeypatch.setattr(loop, "workspace_inventory", inventory)
    return driver._grounded_evidence(state, {"messages": messages}, log)


@pytest.mark.parametrize("level", range(6))
def test_default_registration_and_immutable_exact_selected_projection(level):
    root = assistruntime.AssistRuntime.select(level=level)
    assert sum(d is policy.DEFINITION for d in assistruntime.DEFINITIONS) == 1
    assert root.evidence_summary is (policy.DEFINITION if level >= 2 else None)
    with pytest.raises(AttributeError):
        root.evidence_summary = None


@pytest.mark.parametrize("kind", ["step", "task"])
def test_real_evidence_builder_consumes_replacement_and_settles_its_exact_slot(kind, monkeypatch):
    executed, settlements = [], []
    selected_text = "EXACT selected evidence slot — not the raw log or the final joined packet"
    def execute(source):
        assert isinstance(source, policy.Input)
        assert "EXACT checker output: snow 雪\nsecond line" in source.raw
        result = policy.Result(source.raw, source.raw, selected_text,
                               policy.Selection.SUMMARY, summary=selected_text)
        executed.append((source, result))
        return result
    def settle(result, delivered):
        assert result is executed[-1][1]
        settlements.append((result, delivered))
        return policy.Settlement(result, delivered, delivered == result.selected)
    chosen = replace(policy.DEFINITION, execute=execute, settle=settle)
    with assistruntime.bound(runtime(chosen)):
        actual = builder(kind, monkeypatch, history(), Log())
    assert len(executed) == len(settlements) == 1
    assert selected_text in actual and "EXACT checker output" not in actual
    assert settlements[0][1] == selected_text
    assert settlements[0][0].raw == executed[0][0].raw
    if kind == "step":
        assert actual == selected_text + "\n\nDURABLE fetched-page fact\n\nCURRENT workspace inventory"
        assert settlements[0][1] != actual  # only the consumed slot, never unrelated facts


@pytest.mark.parametrize("kind", ["step", "task"])
@pytest.mark.parametrize("selection", ["disabled", "empty", "below-level"])
def test_absent_policy_never_folds_summarizes_settles_or_loses_raw_facts(kind, selection, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("absent evidence policy executed optional work")
    chosen = replace(policy.DEFINITION, execute=forbidden, settle=forbidden)
    if selection == "empty":
        root = assistruntime.AssistRuntime(None, (), None, 0, (), ())
    else:
        root = runtime(chosen, disabled=selection == "disabled", level=1 if selection == "below-level" else 5)
    monkeypatch.setattr(loop.dedup, "fold_repeated_actions", forbidden)
    monkeypatch.setattr(loop, "summarize", forbidden)
    output = "first authoritative byte\n" + "x" * 48001 + "\nlast authoritative byte"
    log = Log()
    with assistruntime.bound(root):
        actual = builder(kind, monkeypatch, history(output), log)
    assert output in actual
    assert not any(event.startswith("evidence.") for event, _ in log.events)
    if kind == "step":
        assert "DURABLE fetched-page fact" in actual and "CURRENT workspace inventory" in actual


@pytest.mark.parametrize("kind", ["step", "task"])
def test_actual_shared_provider_label_role_complete_input_and_no_cross_call_cache(kind, monkeypatch):
    bodies, settlements = [], []
    role = Role(name="compactor", backend="local", reasoning="off", temperature=0.0)
    def chat(body, log):
        bodies.append(body)
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": " provider-authored summary 雪 "}}]}).encode()
    def settle(result, delivered):
        settlements.append((result, delivered))
        return policy.settle(result, delivered)
    raw_output = "BEGIN authoritative result\n" + "z" * 48001 + "\nEND authoritative result"
    with assistruntime.bound(runtime(replace(policy.DEFINITION, settle=settle))):
        first = builder(kind, monkeypatch, history(raw_output), Log(), chat=chat, role=role)
        second = builder(kind, monkeypatch, history(raw_output), Log(), chat=chat, role=role)
    label = prompts.render("evidence_summary_note", summary="provider-authored summary 雪")
    assert label in first and label in second and len(bodies) == 2
    assert all(body["temperature"] == 0.0 for body in bodies)
    assert all(any(raw_output in m.get("content", "") for m in body["messages"]) for body in bodies)
    assert len(settlements) == 2 and settlements[0][0] is not settlements[1][0]
    assert all(result.raw.endswith("END authoritative result") and delivered == label
               for result, delivered in settlements)


@pytest.mark.parametrize("kind", ["step", "task"])
def test_selected_policy_survives_invocation_local_reentry_without_cross_settlement(kind, monkeypatch):
    executed, settled, nested = [], [], []
    def execute(source):
        ordinal = len(executed)
        result = policy.Result(source.raw, source.raw, f"selected invocation {ordinal}", policy.Selection.FOLDED)
        executed.append(result)
        if ordinal == 0:
            nested.append(builder(kind, monkeypatch, history("nested exact tool result"), Log()))
        return result
    def settle(result, delivered):
        settled.append((result, delivered))
        return policy.Settlement(result, delivered, delivered == result.selected)
    with assistruntime.bound(runtime(replace(policy.DEFINITION, execute=execute, settle=settle))):
        outer = builder(kind, monkeypatch, history(), Log())
    assert "selected invocation 0" in outer and "selected invocation 1" in nested[0]
    assert [result for result, _ in settled] == [executed[1], executed[0]]
    assert all(delivered == result.selected for result, delivered in settled)


@pytest.mark.parametrize("trigger", list(ReviewTrigger))
def test_whole_task_entry_consumes_selected_history_before_authoritative_judgment(trigger, monkeypatch):
    executions, settlements, judgments = [], [], []
    def execute(source):
        result = policy.Result(source.raw, source.raw, "SELECTED history for the actual task judge",
                               policy.Selection.FOLDED)
        executions.append(result)
        return result
    def settle(result, delivered):
        settlements.append((result, delivered))
        return policy.Settlement(result, delivered, delivered == result.selected)
    def judge(task, evidence, *args, **kwargs):
        judgments.append((task, evidence))
        return False, "The requested work is not complete.", ""
    monkeypatch.setattr(loop, "judge_satisfaction", judge)
    monkeypatch.setattr(loop, "_gate_notes", lambda state: "\nREQUIRED measured check facts")
    driver = loop.Loop.__new__(loop.Loop)
    driver._ctx = SimpleNamespace(reasoner_chat=None, reasoner_role=None, compactor_role=None)
    state = loop.PlanSession(plan=Plan(id="task", task="Original task scope", created="now", items=[]),
                             pending_done="must be cleared by the actual negative task judgment")
    with assistruntime.bound(runtime(replace(policy.DEFINITION, execute=execute, settle=settle))):
        result = driver._review_task(state, {"messages": history(), "tools": []}, Log(), trigger=trigger)
    assert judgments == [("Original task scope",
        "SELECTED history for the actual task judge\nREQUIRED measured check facts")]
    assert result.status is ReviewStatus.REJECTED and state.latest_satisfaction is False
    assert state.pending_done == "" and state.latest_satisfaction_evidence == "The requested work is not complete."
    assert len(executions) == len(settlements) == 1
    assert settlements[0][0] is executions[0]
    assert settlements[0][1] == "SELECTED history for the actual task judge"


@pytest.mark.parametrize("bad", ["foreign-class", "execute", "settle", "id", "stage", "id-and-stage"])
def test_incompatible_source_binding_is_rejected_at_runtime_construction(bad):
    chosen = policy.DEFINITION
    if bad == "foreign-class":
        chosen = SimpleNamespace(policy=chosen.policy, execute=chosen.execute, settle=chosen.settle)
    elif bad in ("execute", "settle"):
        chosen = replace(chosen, **{bad: None})
    else:
        metadata = {}
        if bad in ("id", "id-and-stage"):
            metadata["id"] = "forged-evidence-policy"
        if bad in ("stage", "id-and-stage"):
            metadata["stage"] = "forged-evidence-stage"
        chosen = replace(chosen, policy=replace(chosen.policy, **metadata))
    with pytest.raises(ValueError):
        runtime(chosen)


@pytest.mark.parametrize("kind", ["step", "task"])
@pytest.mark.parametrize("fault", ["execute-type", "raw-rewrite", "settle-type", "settle-result", "settle-slot"])
def test_malformed_selected_results_cannot_misstate_raw_or_consumed_evidence(kind, fault, monkeypatch):
    seen = []
    def execute(source):
        seen.append(source)
        if fault == "execute-type":
            return SimpleNamespace(raw=source.raw, selected="fake DTO")
        raw = "invented raw fact" if fault == "raw-rewrite" else source.raw
        return policy.Result(raw, source.raw, "selected evidence", policy.Selection.FOLDED)
    def settle(result, delivered):
        if fault == "settle-type":
            return SimpleNamespace(result=result, delivered=delivered, selected_delivered=True)
        if fault == "settle-result":
            result = replace(result)
        if fault == "settle-slot":
            delivered = "not the slot actually consumed"
        return policy.Settlement(result, delivered, delivered == result.selected)
    with assistruntime.bound(runtime(replace(policy.DEFINITION, execute=execute, settle=settle))):
        with pytest.raises(ValueError):
            builder(kind, monkeypatch, history(), Log())
    assert len(seen) == 1  # actual selected callback invoked before result validation


@pytest.mark.parametrize("kind", ["step", "task"])
def test_settlement_follows_actual_consumer_assembly_not_execute_self_confirmation(kind, monkeypatch):
    facts, settled = [], []
    def measured(value):
        facts.append("measured")
        return "EXACT measured file fact"
    monkeypatch.setattr(loop.filefacts, "render", measured)
    def execute(source):
        assert facts == []
        return policy.Result(source.raw, source.raw, "selected action slot", policy.Selection.FOLDED)
    def settle(result, delivered):
        assert facts == (["fetch", "inventory"] if kind == "step" else ["measured"])
        settled.append((result, delivered))
        return policy.Settlement(result, delivered, delivered == result.selected)
    with assistruntime.bound(runtime(replace(policy.DEFINITION, execute=execute, settle=settle))):
        actual = builder(kind, monkeypatch, history(), Log(), fact_events=facts)
    assert actual.startswith("selected action slot") and len(settled) == 1
    assert settled[0][1] == "selected action slot" and settled[0][1] != actual
    assert ("EXACT measured file fact" if kind == "task" else "CURRENT workspace inventory") in actual
