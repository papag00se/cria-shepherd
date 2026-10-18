"""Usage sizing executes the same explicit wire selection, without fitting or delivery."""
from dataclasses import replace

import pytest

from cria import contextfloor, modelview


def history():
    return [{"role": "user", "content": "authoritative evidence " * 40}]


def forbidden(*args, **kwargs):
    raise AssertionError("unselected fold executed")


def test_explicit_empty_tuple_never_resurrects_default_folding(monkeypatch):
    messages = history()
    monkeypatch.setattr(modelview, "WIRE_FOLD_STAGE", tuple(
        replace(d, execute=forbidden) for d in modelview.WIRE_FOLD_STAGE))
    assert modelview.visible_tokens(messages, None, fold=True, definitions=()) == contextfloor.est_total(messages, None)


@pytest.mark.parametrize("counted", [False, True])
def test_exact_selected_replacement_output_determines_estimate(monkeypatch, counted):
    messages, calls = history(), []
    tools = [{"type": "function", "function": {"name": "inspect", "parameters": {"type": "object"}}}]
    chosen = messages + [{"role": "user", "content": "selected replacement fact " * 150}]
    def execute(supplied):
        calls.append(supplied)
        return (chosen, 7) if counted else chosen
    selected = (replace(modelview.REPEATED_PAYLOADS, execute=execute),)
    monkeypatch.setattr(modelview, "WIRE_FOLD_STAGE", (replace(modelview.REPEATED_CHECKS, execute=forbidden),))
    actual = modelview.visible_tokens(messages, tools, fold=True, definitions=selected)
    assert actual == contextfloor.est_total(chosen, tools)
    assert actual != contextfloor.est_total(messages, tools)
    assert calls == [messages] and len(messages) == 1


def test_false_boolean_gate_executes_no_supplied_or_default_folding(monkeypatch):
    messages = history()
    selected = (replace(modelview.REPEATED_PAYLOADS, execute=forbidden),)
    monkeypatch.setattr(modelview, "WIRE_FOLD_STAGE", selected)
    assert modelview.visible_tokens(messages, None, definitions=selected) == contextfloor.est_total(messages, None)
    assert modelview.visible_tokens(messages, None, fold=False) == contextfloor.est_total(messages, None)


def test_omitted_tuple_preserves_library_default_stage_order(monkeypatch):
    messages, calls = history(), []
    first = messages + [{"role": "user", "content": "first fact"}]
    second = first + [{"role": "user", "content": "second fact"}]
    def one(supplied):
        assert supplied == messages
        calls.append("one")
        return first, 1
    def two(supplied):
        assert supplied == first
        calls.append("two")
        return second
    selected = (replace(modelview.REPEATED_PAYLOADS, execute=one),
                replace(modelview.REPEATED_CHECKS, execute=two))
    monkeypatch.setattr(modelview, "WIRE_FOLD_STAGE", selected)
    assert modelview.visible_tokens(messages, None, fold=True) == contextfloor.est_total(second, None)
    assert calls == ["one", "two"]


def test_actual_library_defaults_and_explicit_tuple_match_existing_fold_evidence():
    messages = history() * 3
    # A literal surviving wire body is independent of every folding entry point.
    pointer = {"role": "user", "content":
               "(duplicate of content shown IN FULL further down this conversation — nothing was "
               "shortened, cut, or lost; read the full copy below)"}
    expected_body = [pointer, pointer, history()[0]]
    expected = contextfloor.est_total(expected_body, None)
    assert modelview.fold_evidence(messages) == expected_body  # adapter wiring only
    assert modelview.visible_tokens(messages, None, fold=True) == expected
    assert modelview.visible_tokens(messages, None, fold=True, definitions=modelview.WIRE_FOLD_STAGE) == expected
