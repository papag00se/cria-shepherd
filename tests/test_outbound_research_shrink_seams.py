"""Canonical research is an adapter; F15 uses typed factual services in production."""
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest

from cria import outboundpolicies, researchpolicies, shrinkprotection, toolstages, webfetch, writeproxy
from cria.assistcontract import Policy
from test_shrink_protection_policy import services, FRAGMENT

SHELL = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}


def completion(name='web_search', **arguments):
    return {'choices': [{'message': {'tool_calls': [{'id': 'c', 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}]}


@pytest.mark.parametrize('refused', [True, False])
def test_canonical_research_runs_last_with_rewritten_arguments_before_lowering(monkeypatch, refused):
    order = []
    def adapt(source, state):
        order.append(('research', source.query, source.session))
        return researchpolicies.Admission(researchpolicies.Effect.REFUSED, 'canonical refusal') if refused else researchpolicies.Admission()
    selection = replace(researchpolicies.ResearchSelection(), search=replace(researchpolicies.SEARCH, execute=adapt))
    definitions = []
    for i, definition in enumerate(outboundpolicies.DEFINITIONS):
        def execute(source, i=i, definition=definition):
            order.append(definition.policy.id)
            if i == 0:
                return toolstages.RewrittenCall(source.call, {'query': 'rewritten query'})
        definitions.append(replace(definition, execute=execute))
    stages = replace(toolstages.defaults(), outbound=tuple(definitions))
    def lower(source):
        order.append(('lower', source.arguments['query'], source.request.session))
        return toolstages.ShellCommand('printf permitted')
    monkeypatch.setattr(writeproxy, '_lower_synthetic', lower)
    with toolstages.bound(stages), researchpolicies.bound(selection):
        result = writeproxy.translate_outbound(completion(query='original query'), SHELL, session='real-session')
    expected = [d.policy.id for d in outboundpolicies.DEFINITIONS]
    assert expected[-1] == 'unread-file-protection'
    expected.append(('research', 'rewritten query', 'real-session'))
    if not refused:
        expected.append(('lower', 'rewritten query', 'real-session'))
    assert order == expected
    cmd = json.loads(result['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']
    assert ('canonical refusal' in cmd) == refused


def test_earlier_outbound_refusal_never_enters_research():
    execute = Mock(side_effect=AssertionError('research after prior refusal'))
    selection = replace(researchpolicies.ResearchSelection(), search=replace(researchpolicies.SEARCH, execute=execute))
    early = toolstages.OutboundDefinition(Policy('fixture-refusal', 'outbound-call', 2),
                                        lambda source: toolstages.ShellCommand('earlier refusal'))
    stages = replace(toolstages.defaults(), outbound=(early,))
    with toolstages.bound(stages), researchpolicies.bound(selection):
        source = toolstages.OutboundCall(completion(query='q')['choices'][0]['message']['tool_calls'][0],
                                        {'query': 'q'}, toolstages.LoweringRequest(frozenset(), session='s'))
        assert stages.outbound_call(source)[2].command == 'earlier refusal'
    execute.assert_not_called()


def test_empty_canonical_selection_prevents_namespace_defaults_and_detection(monkeypatch):
    forbidden = Mock(side_effect=AssertionError('disabled search detector'))
    monkeypatch.setattr(researchpolicies, 'searches_match', forbidden)
    selection = researchpolicies.ResearchSelection.from_definitions(())
    with toolstages.bound(toolstages.ToolStages.from_definitions(())), researchpolicies.bound(selection):
        out = writeproxy.translate_outbound(completion(query='q'), SHELL, native_search='local_web_search', session='s')
    assert out['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'local_web_search'
    forbidden.assert_not_called()


def test_library_tool_optout_does_not_leak_defaults_but_canonical_binding_wins(monkeypatch):
    execute = Mock(return_value=researchpolicies.Admission(researchpolicies.Effect.REFUSED, 'selected refusal'))
    selection = replace(researchpolicies.ResearchSelection(), search=replace(researchpolicies.SEARCH, execute=execute))
    gate = Mock(wraps=webfetch.gate_search)
    monkeypatch.setattr(webfetch, 'gate_search', gate)
    empty = toolstages.ToolStages.from_definitions(())
    with toolstages.bound(empty):
        source = toolstages.OutboundCall(completion(query='q')['choices'][0]['message']['tool_calls'][0],
                                        {'query': 'q'}, toolstages.LoweringRequest(frozenset(), session='s'))
        assert empty.outbound_call(source)[2] is None
        gate.assert_not_called()
        with researchpolicies.bound(selection):
            assert 'selected refusal' in empty.outbound_call(source)[2].command
    execute.assert_called_once()


def test_unbound_library_search_preserves_the_existing_guard_default():
    session = 'outbound-library-guard-default'
    webfetch.reset_session(session)
    try:
        webfetch.set_visible(session, (), ['the exact prior query'])
        out = writeproxy.translate_outbound(completion(query='the exact prior query'), SHELL,
                                           native_search='local_web_search', session=session)
        assert out['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'exec_command'
    finally:
        webfetch.reset_session(session)


def test_no_duplicate_search_or_shrink_record_remains():
    assert all(d.policy.id != 'search-repeat-admission' for d in toolstages.defaults().definitions)
    assert outboundpolicies.MUTATIONS[-1] is shrinkprotection.DEFINITION
    assert sum(d.policy.id == 'shrinking-file-protection' for d in toolstages.defaults().definitions) == 1


def test_production_factual_services_reach_real_shrink_definition_without_legacy_callback():
    source = services('OTHER')
    legacy = Mock(side_effect=AssertionError('bound request invoked whole legacy policy'))
    with toolstages.bound(toolstages.ToolStages.from_definitions((shrinkprotection.DEFINITION,))):
        result = writeproxy.translate_outbound(completion('write_file', path='file.txt', content=FRAGMENT),
            SHELL, injected={'write_file', 'edit_file'}, shrink_services=source, shrink_check=legacy)
    command = json.loads(result['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']
    assert 'ctx:denied' in command
    source.ask.assert_called_once()
    legacy.assert_not_called()


def test_disabled_shrink_does_not_gather_or_use_legacy_callback():
    source = services()
    source.session.side_effect = AssertionError('disabled session lookup')
    legacy = Mock(side_effect=AssertionError('bound request fell back to legacy callback'))
    with toolstages.bound(toolstages.ToolStages.from_definitions(())):
        writeproxy.translate_outbound(completion('write_file', path='file.txt', content=FRAGMENT), SHELL,
            injected={'write_file'}, shrink_services=source, shrink_check=legacy)
    source.session.assert_not_called()
    source.ask.assert_not_called()
    legacy.assert_not_called()


def test_unbound_explicit_shrink_callback_compatibility_has_no_policy_default():
    legacy = Mock(return_value={'text': 'legacy explicit hold', 'bytes': b'original'})
    result = writeproxy.translate_outbound(completion('write_file', path='file.txt', content=FRAGMENT),
        SHELL, injected={'write_file', 'edit_file'}, shrink_check=legacy)
    legacy.assert_called_once_with('file.txt', FRAGMENT, 'edit_file')
    command = json.loads(result['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']
    assert 'legacy explicit hold' in command and 'ctx:denied' in command
