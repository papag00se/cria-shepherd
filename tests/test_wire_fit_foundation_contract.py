"""The required floor strategy is not a collection of removable steering policies."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import bodykeys, contextfloor
from cria.assistfamilies import BY_ID, SourceOwner


def test_the_floor_has_one_explicit_required_source_contract():
    family = BY_ID["F68"]
    assert family.kind == "foundation"
    assert family.coverage == "required_wire_contract"
    assert SourceOwner("cria/contextfloor.py", "fit") in family.owners


def test_fitting_offers_no_partial_or_disabled_foundation_mode():
    # Unsupported combinations must fail, not return an unprocessed oversized body.
    messages = [{"role": "user", "content": "irreducible " * 4000}]
    for option in ("enabled", "compress_tools", "reduce_outputs", "drop_history"):
        with pytest.raises(TypeError, match=option):
            contextfloor.fit(messages, None, window=2000, reserve=200, **{option: False})


def test_a_fitting_body_is_unchanged_and_owned_inputs_are_never_mutated():
    messages = [{"role": "system", "content": "permissions remain authoritative"},
                {"role": "user", "content": "the complete task"}]
    tools = [{"type": "function", "function": {
        "name": "read_file", "description": "Read the whole file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}}]
    original = deepcopy((messages, tools))
    output, menu, report = contextfloor.fit(messages, tools, window=16000, reserve=2000)
    assert (output, menu) == original
    assert (messages, tools) == original
    assert not report.applied and not report.over_budget


def test_oversized_irreducible_input_is_not_reported_as_acceptable():
    messages = [{"role": "system", "content": "constraint " * 4000},
                {"role": "user", "content": "the exact active request"}]
    output, _, report = contextfloor.fit(messages, None, window=2000, reserve=200)
    assert output == messages
    assert report.over_budget
    assert report.as_event()["over_budget"] is True


def test_schema_pressure_preserves_capabilities_and_discloses_shortening():
    tools = [{"type": "function", "function": {
        "name": f"operation_{i}", "description": "Complete sentence. " * 300,
        "parameters": {"type": "object", "properties": {
            "choice": {"type": "string", "enum": ["a", "b"],
                       "description": "Choose one option. " * 300}}, "required": ["choice"]}}}
        for i in range(3)]
    original = deepcopy(tools)
    _, menu, report = contextfloor.fit(
        [{"role": "user", "content": "task"}], tools, window=4000, reserve=400)
    assert tools == original
    assert report.tools_compressed == 3 and report.tools_dropped == 0
    for before, after in zip(tools, menu):
        assert after["function"]["description"].endswith(" […more]")
        assert after["function"]["parameters"]["properties"]["choice"]["description"].endswith(" […more]")
        expected = deepcopy(before)
        expected["function"]["description"] = after["function"]["description"]
        expected["function"]["parameters"]["properties"]["choice"]["description"] = after["function"]["parameters"]["properties"]["choice"]["description"]
        assert after == expected


@pytest.mark.parametrize("level", [0, 1, 2])
def test_existing_lower_levels_do_not_activate_fitting(level):
    from cria.upstream import Upstream
    messages = [{"role": "user", "content": "oversized task " * 4000}]
    with patch.object(contextfloor, "fit", side_effect=AssertionError("floor activated below its existing rung")):
        wire, _, _ = Upstream("http://synthetic.invalid", api_key="synthetic-test-key",
                              context_window=2000, engagement_level=level)._prep(
            {"model": "synthetic", "messages": messages}, False,
            SimpleNamespace(emit=lambda *args, **kwargs: None))
    assert json.loads(wire)["messages"] == messages


def test_an_unknown_window_still_does_not_authorize_reduction():
    from cria.upstream import Upstream
    messages = [{"role": "user", "content": "oversized task " * 4000}]
    with patch.object(contextfloor, "fit", side_effect=AssertionError("floor guessed a window")):
        wire, _, _ = Upstream("http://synthetic.invalid", api_key="synthetic-test-key",
                              engagement_level=3)._prep(
            {"model": "synthetic", "messages": messages}, False,
            SimpleNamespace(emit=lambda *args, **kwargs: None))
    assert json.loads(wire)["messages"] == messages


def test_caller_and_restored_blocks_are_shed_before_tool_evidence():
    persona = "Harness standing persona. " * 1500
    system = {"role": "system", "content": "constraints\n" + persona + "\nprotected suffix",
              bodykeys.CALLER_SPAN: {"start": len("constraints\n"), "text": persona}}
    restored = {"role": "user", "content": "restored workspace text\n" * 600,
                bodykeys.RESTORED_FILES: {"offered": {"a.txt": 1}, "named": ["a.txt"]}}
    evidence = {"role": "tool", "tool_call_id": "read", "content": "exact result\n" * 100}
    messages = [system, {"role": "user", "content": "root task"}, restored,
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "read", "function": {"name": "read_file", "arguments": "{}"}}]},
                evidence, {"role": "user", "content": "current question"}]
    original = deepcopy(messages)
    output, _, report = contextfloor.fit(
        messages, None, window=3000, reserve=300, safety=1.0, pinned_task="root task")
    assert messages == original
    assert report.caller_reduced == report.restored_reduced == 1
    assert report.outputs_reduced == report.turns_dropped == report.protected_dropped == 0
    assert not report.over_budget
    assert evidence in output
    assert output[0]["content"].startswith("constraints\n")
    assert output[0]["content"].endswith("\nprotected suffix")
    assert "⟦ctx:reduced⟧" in output[0]["content"]
    replacement = next(message for message in output if "⟦ctx:current⟧" in message.get("content", ""))
    assert "a.txt" in replacement["content"] and bodykeys.RESTORED_FILES not in replacement


def test_history_loss_is_labelled_and_protected_task_and_gate_pair_survive():
    task = "Keep every deliverable in the original task."
    pair = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "gate", "function": {"name": "shell", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "gate", "content": "___CRIA_GATE_ exact checker result"}]
    messages = [{"role": "system", "content": "permissions"},
                {"role": "user", "content": task}, *pair,
                {"role": "assistant", "content": "old history " * 4000},
                {"role": "user", "content": "current question"}]
    original = deepcopy(messages)
    output, _, report = contextfloor.fit(
        messages, None, window=3000, reserve=300, pinned_task=task)
    assert messages == original
    assert report.turns_dropped > 0 and not report.over_budget
    assert messages[0] in output and messages[1] in output and messages[-1] in output
    assert all(message in output for message in pair)
    assert any("⟦ctx:compacted⟧" in message.get("content", "") for message in output)
