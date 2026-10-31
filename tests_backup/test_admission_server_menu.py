"""Actual handler menu admission, after real advertisement and before instructions."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import copy

import pytest

from cria import assistruntime, server, toolmenu
from cria.loop import LoopStore


SHELL = {'type': 'function', 'function': {'name': 'bash', 'parameters': {
    'type': 'object', 'properties': {'command': {'type': 'string'}}}}}


@pytest.mark.parametrize('focus,instruction', [(True, True), (False, True), (True, False), (False, False)])
@pytest.mark.parametrize('disabled', [False, True])
def test_real_advertisement_then_selected_menu_stages(monkeypatch, focus, instruction, disabled):
    calls = []
    sentinel = {'type': 'function', 'function': {'name': 'replacement-visible', 'parameters': {}}}
    def execute_focus(source, log=None):
        calls.append(('focus', copy.deepcopy(source.tools)))
        assert any(t['function']['name'] == 'write_file' for t in source.tools)
        return toolmenu.FocusResult([sentinel], applied=True)
    def execute_instructions(source, log=None):
        calls.append(('instruction', copy.deepcopy(source.tools)))
        return toolmenu.InstructionResult('selected instruction',
            [{'role': 'system', 'content': 'selected instruction'}] + source.messages, applied=True)
    replacements = {d.policy.id: d for d in (
        replace(toolmenu.FOCUS_DEFINITION, execute=execute_focus),
        replace(toolmenu.INSTRUCTION_DEFINITION, execute=execute_instructions))}
    runtime = assistruntime.AssistRuntime.select(level=5,
        disabled=tuple(replacements) if disabled else ())
    runtime = replace(runtime, ordered_stages=tuple(replacements.get(d.policy.id, d) for d in runtime.ordered_stages))
    handler = server.CriaHandler.__new__(server.CriaHandler)
    handler.server = SimpleNamespace(cfg=SimpleNamespace(
        routing=SimpleNamespace(simple_tools=True), tools=SimpleNamespace(focus=focus, cheatsheet=instruction)), loop=None,
        loop_store=LoopStore(), _endpoint_for=lambda role: None)
    handler._workspace_root = '/offline-workspace'
    handler._bind_workspace_view = Mock()
    monkeypatch.setattr(server.brave, 'api_key', lambda: None)
    body = {'tools': [copy.deepcopy(SHELL)], 'messages': [{'role': 'user', 'content': 'work'}]}
    with assistruntime.bound(runtime):
        handler._setup_translation(body, 'offline-menu', Mock())
    expected = ([] if disabled else ['focus'] * focus + ['instruction'] * instruction)
    assert [kind for kind, _ in calls] == expected
    assert any(t['function']['name'] == 'write_file' for t in body['tools']) if disabled or not focus else body['tools'] == [sentinel]
    if instruction and not disabled:
        assert body['messages'][0]['content'] == 'selected instruction'
        assert calls[-1][1] == ([sentinel] if focus else body['tools'])
    else:
        assert body['messages'] == [{'role': 'user', 'content': 'work'}]
