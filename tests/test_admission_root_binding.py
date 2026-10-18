"""Admission choices execute through the real root and production consumers."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess
import sys

import pytest

from cria import assistruntime, classify, loop, server, toolmenu


TOOLS = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object'}}}]
MESSAGES = [{'role': 'user', 'content': 'Implement the requested change'}]


def runtime_for(definition=None, disabled=()):
    runtime = assistruntime.AssistRuntime.select(level=5, disabled=disabled)
    if definition is not None:
        runtime = replace(runtime, ordered_stages=tuple(
            definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
    return runtime


@pytest.mark.parametrize('first', ['classify', 'toolmenu', 'server', 'loop', 'assistruntime'])
def test_admission_fresh_import_orders(first):
    script = f'''import importlib
importlib.import_module("cria.{first}")
from cria import assistruntime, classify, completionapproval, completiondiagnosis, completionconfirmation, runnercontract, repositorychecks, evidencesummary, memoryhandoff, semanticquery, stalledwork, pastedfile, toolmenu
r = assistruntime.AssistRuntime.select(level=5)
expected = ((assistruntime.ARGUMENTS, assistruntime.MODULE, assistruntime.TASK_REVIEW)
            + assistruntime.TOOL_DEFINITIONS + assistruntime.RESEARCH_DEFINITIONS
            + assistruntime.HISTORY_DEFINITIONS + assistruntime.ADMISSION_DEFINITIONS
            + assistruntime.GENERATION_DEFINITIONS + assistruntime.CONTEXT_DEFINITIONS
            + completionapproval.PRE_RELEASE + completiondiagnosis.DEFINITIONS + completionconfirmation.DEFINITIONS + (runnercontract.DEFINITION,) + repositorychecks.DEFINITIONS + (evidencesummary.DEFINITION, memoryhandoff.DEFINITION) + semanticquery.DEFINITIONS + (stalledwork.DEFINITION, pastedfile.DEFINITION))
assert r.definitions == expected
assert tuple(d.policy.id for d in r.definitions) == tuple(d.policy.id for d in expected)
assert all(actual is canonical for actual, canonical in zip(r.definitions, expected, strict=True))
assert all(actual is canonical for actual, canonical in
           zip(r.pre_release, completionapproval.PRE_RELEASE, strict=True))
assert toolmenu.selected_policies(r.definitions).focus(toolmenu.FocusInput(None)).tools is None
with assistruntime.bound(r):
    assert classify.selected_definition() is classify.DEFINITION
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_admission_definitions_are_canonical():
    assert all(d in assistruntime.DEFINITIONS for d in (classify.DEFINITION,) + toolmenu.DEFINITIONS)


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('disabled', [False, True])
def test_actual_coder_frame_selected_note(synthetic, disabled):
    calls = []
    def instructions(request, log=None):
        calls.append(request)
        return toolmenu.InstructionResult('unique selected note', None, applied=True)
    definition = replace(toolmenu.INSTRUCTION_DEFINITION, execute=instructions)
    runtime = runtime_for(definition, (definition.policy.id,) if disabled else ())
    with assistruntime.bound(runtime):
        framed = loop._frame_for_item(MESSAGES, 'task', '', 0, 1, tools=TOOLS, synthetic=synthetic)
    assert ('unique selected note' in framed[0]['content']) is not disabled
    assert len(calls) == (0 if disabled else 1)
    if calls:
        assert calls[0].messages is None and calls[0].configured


@pytest.mark.parametrize('disabled', [False, True])
def test_actual_handler_classification_selection_before_lifecycle(disabled):
    service = classify.Classifier(Mock())
    service._cache['sentinel'] = 'unchanged'
    calls = []
    verdict = classify.Classification('task', 'coding', 'selected replacement')
    def execute(instance, messages, log, *, enabled=True):
        calls.append((instance, messages))
        return verdict
    definition = replace(classify.DEFINITION, execute=execute)
    runtime = runtime_for(definition, (definition.policy.id,) if disabled else ())
    handler = server.CriaHandler.__new__(server.CriaHandler)
    handler.server = SimpleNamespace(classifier=service)
    with assistruntime.bound(runtime):
        result = handler._classify({'messages': MESSAGES}, Mock())
    assert result == (None if disabled else verdict)
    assert calls == ([] if disabled else [(service, MESSAGES)])
    assert service._cache == {'sentinel': 'unchanged'}
    service._provider.chat.assert_not_called()
