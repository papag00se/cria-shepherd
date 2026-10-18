"""Source orchestration above pure readers, exercised through actual root bindings."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from cria import (argumentconversion, assistbinding, assistruntime, callsyntax,
                  filecommands, massage, outboundpolicies, outputpolicies,
                  returnedpolicies, toolcontracts, toolstages, writeproxy)


class Log:
    def __init__(self):
        self.events = []
    def emit(self, kind, **fields):
        self.events.append((kind, fields))


MENU = [{'type': 'function', 'function': {'name': 'sample', 'parameters': {
    'type': 'object', 'properties': {'value': {'type': 'integer'}}, 'required': ['value']}}}]
XML = '<function=sample><parameter=value>7</parameter></function>'


def completion(text=XML, reasoning=False):
    message = {'content': None, 'reasoning_content': text} if reasoning else {'content': text}
    return {'choices': [{'finish_reason': 'stop', 'message': message}]}


def arguments(comp):
    return json.loads(comp['choices'][0]['message']['tool_calls'][0]['function']['arguments'])


def runtime(converter=None, disabled=(), *, level=5):
    registrations = tuple(replace(d, execute=converter) if converter is not None and
                          d.policy.id == argumentconversion.DEFINITION.policy.id else d
                          for d in assistruntime.DEFINITIONS)
    return assistruntime.AssistRuntime.select(registrations=registrations, disabled=disabled, level=level)


@pytest.mark.parametrize('reasoning', [False, True])
def test_root_replacement_conversion_and_its_own_event_attribution(reasoning, monkeypatch):
    calls = []
    def convert(name, args, schemas):
        calls.append((name, copy.deepcopy(args), schemas))
        return {**args, 'value': 19}
    selected = runtime(convert)
    monkeypatch.setattr(massage, '_extract_leaked', Mock(side_effect=AssertionError('old XML adapter')), raising=False)
    monkeypatch.setattr(assistruntime.AssistRuntime, 'arguments', Mock(side_effect=AssertionError('upper conversion dispatcher')))
    log = Log()
    with assistruntime.bound(selected):
        result = massage.apply(completion(reasoning=reasoning), MENU, log)
    assert arguments(result) == {'value': 19}
    assert len(calls) == 1 and calls[0][:2] == ('sample', {'value': '7'})
    assert calls[0][2] == {'sample': MENU[0]['function']['parameters']}
    converted = [fields for kind, fields in log.events if kind == 'massage.arguments_converted']
    assert converted == [{'assist_id': argumentconversion.DEFINITION.policy.id,
                          'family_id': argumentconversion.DEFINITION.policy.family_id, 'tool': 'sample'}]


@pytest.mark.parametrize('reasoning', [False, True])
def test_conversion_disabled_does_not_disable_selected_recovery(reasoning):
    log = Log()
    with assistruntime.bound(runtime(disabled=(argumentconversion.DEFINITION.policy.id,))):
        result = massage.apply(completion(reasoning=reasoning), MENU, log)
    assert arguments(result) == {'value': '7'}
    assert not [event for event in log.events if event[0] == 'massage.arguments_converted']


@pytest.mark.parametrize('text', [
    '<|tool_call_start|>[sample(value="7")]<|tool_call_end|>',
    '<tool_call>{"name":"sample","arguments":{"value":"7"}}</tool_call>',
    XML,
])
def test_every_reasoning_dialect_uses_exact_converter(text):
    convert = Mock(side_effect=lambda name, args, schemas: {**args, 'value': 23})
    with assistruntime.bound(runtime(convert)):
        result = massage.apply(completion(text, reasoning=True), MENU)
    assert arguments(result) == {'value': 23}
    convert.assert_called_once_with('sample', {'value': '7'}, {'sample': MENU[0]['function']['parameters']})


def test_unchanged_conversion_executes_without_inventing_an_event():
    convert = Mock(side_effect=lambda name, args, schemas: args)
    log = Log()
    with assistruntime.bound(runtime(convert)):
        result = massage.apply(completion(), MENU, log)
    assert arguments(result) == {'value': '7'}
    assert convert.call_count == 1
    assert not [event for event in log.events if event[0] == 'massage.arguments_converted']


@pytest.mark.parametrize('mode', ['length', 'non-action', 'protocol-error', 'recovery-disabled', 'empty'])
def test_converter_selection_never_grants_transport_eligibility(mode):
    convert = Mock(side_effect=AssertionError('ineligible conversion'))
    comp = completion()
    disabled = ()
    if mode == 'length':
        comp['choices'][0]['finish_reason'] = 'length'
    elif mode == 'non-action':
        comp['generation_evidence'] = {'content_is_non_action': True}
    elif mode == 'protocol-error':
        comp['error'] = {'type': 'invalid_model_output_error'}
    elif mode == 'recovery-disabled':
        disabled = tuple(d.policy.id for d in outputpolicies.RECOVERY)
    elif mode == 'empty':
        disabled = tuple(d.policy.id for d in assistruntime.DEFINITIONS)
    with assistruntime.bound(runtime(convert, disabled, level=0 if mode == 'empty' else 5)):
        result = massage.apply(comp, MENU)
    assert not result['choices'][0]['message'].get('tool_calls')
    convert.assert_not_called()


def test_standalone_xml_bound_empty_alias_resolution_and_nested_restoration():
    schemas = {'shell': {'properties': {'yield_time_ms': {'type': 'integer'}}}}
    xml = '<function=ls><parameter=yield_time_ms>7</parameter></function>'
    assert assistbinding.current() is assistbinding.UNBOUND
    calls, _ = outputpolicies._extract_leaked(xml, schemas)
    assert calls[0]['function']['name'] == 'shell'
    assert json.loads(calls[0]['function']['arguments']) == {'yield_time_ms': 7}
    with assistruntime.bound(runtime(disabled=(argumentconversion.DEFINITION.policy.id,))):
        calls, _ = outputpolicies._extract_leaked(xml, schemas)
        assert json.loads(calls[0]['function']['arguments']) == {'yield_time_ms': '7'}
        with assistruntime.bound(runtime()):
            calls, _ = outputpolicies._extract_leaked(xml, schemas)
            assert json.loads(calls[0]['function']['arguments']) == {'yield_time_ms': 7}
        calls, _ = outputpolicies._extract_leaked(xml, schemas)
        assert json.loads(calls[0]['function']['arguments']) == {'yield_time_ms': '7'}
    assert assistbinding.current() is assistbinding.UNBOUND


def test_fused_recovery_uses_per_parse_character_measurement_not_shared_state(monkeypatch):
    monkeypatch.setattr(massage, '_LAST_FUSED_TAIL', [99999], raising=False)
    monkeypatch.setattr(massage, '_recover_fused_call', Mock(side_effect=AssertionError('old parser')), raising=False)
    raws = ['{"value":1}<tool_call|>é', 'broken<tool_call|>longer', '{"value":2}<|channel>ββ']
    comp = {'choices': [{'message': {'tool_calls': [
        {'function': {'name': 'sample', 'arguments': raw}} for raw in raws]}}]}
    log = Log()
    outputpolicies.repair_tool_args(comp, log)
    calls = comp['choices'][0]['message']['tool_calls']
    assert [call['function']['arguments'] for call in calls] == ['{"value": 1}', raws[1], '{"value": 2}']
    assert [fields['discarded_chars'] for kind, fields in log.events if kind == 'massage.fused_call_recovered'] == [len('<tool_call|>é'), len('<|channel>ββ')]


def test_source_fenced_admission_preserves_draft_and_refusal_rules(monkeypatch):
    monkeypatch.setattr(massage, '_fenced_envelope_call', Mock(side_effect=AssertionError('old fenced admission')), raising=False)
    admitted = 'before\n```json\n{"name":"sample","arguments":{"value":7}}\n```\nafter'
    calls, keep, fields, why = outputpolicies._fenced_envelope_call(admitted, MENU)
    assert json.loads(calls[0]['function']['arguments']) == {'value': 7}
    assert keep == 'before' and why is None
    assert fields == {'later_envelopes': 0, 'dropped_chars': len(admitted) - len('before\n')}
    refused = '```python\ninvented result\n```\n' + admitted
    assert outputpolicies._fenced_envelope_call(refused, MENU)[3] == 'prefix_fence'
    assert outputpolicies._fenced_envelope_call(admitted, [])[0] == []
    content = 'x = "actual"\n' * 12
    tools = [{'function': {'name': 'write_file', 'parameters': {'properties': {
        'path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['path', 'content']}}}]
    draft = '```python\n' + content + '```\n```json\n' + json.dumps({'name': 'write_file', 'arguments': {'path': 'a.py', 'content': content}}) + '\n```'
    assert outputpolicies._fenced_envelope_call(draft, tools)[0]


def test_source_shell_orchestration_keeps_extra_arguments_and_event(monkeypatch):
    monkeypatch.setattr(massage, '_reshape_shell', Mock(side_effect=AssertionError('old shell adapter')), raising=False)
    shell = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
    fn = {'name': 'exec_command', 'arguments': json.dumps({'command': [['bash', '-lc', 'printf ok']], 'yield_time_ms': 50})}
    log = Log()
    outputpolicies._reshape_shell(fn, shell, log)
    assert json.loads(fn['arguments']) == {'cmd': 'printf ok', 'yield_time_ms': 50}
    assert log.events == [('massage.shell_reshaped', {})]


@pytest.mark.parametrize('disabled', [False, True])
def test_promotion_explicitly_runs_actual_selected_upper_repair(disabled):
    calls = []
    original = outputpolicies.REPAIR[0]
    def repair_stage(comp, log=None):
        calls.append(comp['choices'][0]['message']['tool_calls'][0]['id'])
        return comp
    replacement = replace(original, execute=repair_stage)
    registry = tuple(replacement if d.policy.id == original.policy.id else d for d in assistruntime.DEFINITIONS)
    selected = assistruntime.AssistRuntime.select(registrations=registry,
        disabled=(original.policy.id,) if disabled else ())
    def selected_repair(comp, tools, log):
        return toolstages.current().completions('repair', comp, tools, log)
    comp = completion('file prose')
    call = callsyntax._toolcall('sample', {'value': 7})
    with assistruntime.bound(selected):
        result = outputpolicies.promote_call(comp, call, 'keep', MENU, repair=selected_repair)
    assert result['choices'][0]['message']['content'] == 'keep'
    assert calls == ([] if disabled else [call['id']])
    comp = completion()
    comp['choices'][0]['finish_reason'] = 'length'
    assert outputpolicies.promote_call(comp, call, '', MENU,
        repair=Mock(side_effect=AssertionError('ineligible repair'))) is comp


def test_spill_source_renders_cached_facts_and_does_not_call_old_facade(monkeypatch):
    monkeypatch.setattr(writeproxy, '_spill_read_command', Mock(side_effect=AssertionError('old spill adapter')), raising=False)
    monkeypatch.setattr(outboundpolicies.webfetch, 'format_for_spill_path', lambda p: 'OpenAPI')
    monkeypatch.setattr(outboundpolicies.webfetch, 'spill_reading_hint', lambda p, n: 'extent')
    monkeypatch.setattr(outboundpolicies.webfetch, 'page_not_file_for_spill_path', lambda p: True)
    monkeypatch.setattr(outboundpolicies.webfetch, 'outline_for_spill_path', lambda p: 'real outline')
    # Capture the boundary, then use the real immutable pure builder.
    build = Mock(wraps=filecommands._spill_read_command)
    monkeypatch.setattr(outboundpolicies, '_format_spill_read', build)
    command = outboundpolicies._spill_read_command('a b')
    path, steer = build.call_args.args
    assert path == 'a b' and 'OpenAPI' in steer and 'extent' in steer and 'real outline' in steer
    assert command == filecommands._spill_read_command(path, steer)


@pytest.mark.parametrize('first', ['webfetch', 'apidiscovery', 'planner_tools'])
def test_research_library_entry_does_not_reenter_runtime_catalog(first):
    script = r'''
import importlib, importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'cria.assistruntime':
            raise AssertionError('research boundary reentered runtime catalog')
sys.meta_path.insert(0, Guard())
module = importlib.import_module('cria.' + sys.argv[1])
if sys.argv[1] == 'webfetch':
    text = module.render_page('https://fixture.invalid/doc', 200, 'text/plain', 'whole text', None, 0, 1000)
    assert 'whole text' in text
elif sys.argv[1] == 'apidiscovery':
    assert module.discover('https://fixture.invalid/readme', 200, 'ordinary text', 'text/plain') is None
else:
    assert module._no_structure_note(None) == ''
assert 'cria.assistruntime' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, first],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('first', ['outputpolicies', 'outboundpolicies', 'returnedpolicies', 'historyarguments', 'shrinkprotection'])
def test_source_imports_do_not_reenter_upper_catalog_or_facades(first):
    script = r'''
import importlib, importlib.abc, sys
blocked = {'cria.massage', 'cria.writeproxy', 'cria.toolstages', 'cria.assistruntime', 'cria.config', 'cria.loop', 'cria.server', 'cria.upstream', 'cria.assistfamilies'}
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            raise AssertionError('upper Source import: ' + fullname)
sys.meta_path.insert(0, Guard())
module = importlib.import_module('cria.' + sys.argv[1])
from cria import toolcontracts, argumentconversion, assistbinding
if sys.argv[1] == 'outputpolicies':
    assert module.CompletionDefinition is toolcontracts.CompletionDefinition
    assert module._extract_leaked('<function=x><parameter=v>7</parameter></function>')[0]
assert not (blocked & sys.modules.keys())
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, first],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
