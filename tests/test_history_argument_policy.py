"""Historical recovery owns literals, not action admission or tool correlation."""
import ast
import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
from cria import callliterals, historyarguments as policy, jsontext, massage


class Log:
    phase = ''
    def __init__(self):
        self.events = []
    def emit(self, event, **fields):
        self.events.append((event, fields))


def call(raw, id='same-id', name='old_native_api'):
    return {'id': id, 'type': 'function', 'index': 7,
            'function': {'name': name, 'arguments': raw, 'historical_metadata': 'retain'}}


def arguments(messages):
    return [tc['function']['arguments'] for message in messages if isinstance(message, dict)
            for tc in message.get('tool_calls', []) if isinstance(tc, dict) and isinstance(tc.get('function'), dict)]


def prepare(messages, definition=policy.DEFINITION, recover=True, log=None):
    return policy.prepare_history(messages, log, definition=definition, recover=recover)


def test_full_history_keeps_names_ids_roles_outputs_and_literal_values():
    raw = 'wrapper ' + json.dumps({'cmd': "echo'literal"}) + ' trailing prose'
    messages = [
        {'role': 'system', 'content': 'old task and schema'},
        {'role': 'user', 'content': 'new schema does not include old_native_api'},
        {'role': 'assistant', 'tool_calls': [call(raw)], 'reasoning_content': 'old reasoning'},
        {'role': 'tool', 'tool_call_id': 'same-id', 'content': raw},
        {'role': 'assistant', 'tool_calls': [call(' { "kept" : false } ', name='renamed_now')]},
        {'role': 'tool', 'tool_call_id': 'same-id', 'content': 'second result: IDs may repeat across turns'},
        {'role': 'function', 'name': 'legacy', 'content': raw, 'function_call': {'arguments': raw}},
        {'role': 'user', 'content': 'continue'},
    ]
    original = copy.deepcopy(messages)
    result = prepare(messages)
    assert messages == original
    assert json.loads(result[2]['tool_calls'][0]['function']['arguments']) == {'cmd': "echo'literal"}
    expected = copy.deepcopy(original)
    expected[2]['tool_calls'][0]['function']['arguments'] = json.dumps({'cmd': "echo'literal"}, ensure_ascii=False)
    assert result == expected
    assert result[3] is messages[3] and result[6] is messages[6]


@pytest.mark.parametrize('raw', ['{}', '[]', 'null', 'false', '0', '""', '  {"x":0} \n',
    '{ "payload" : "\\u96ea \\\\n </think> <tool_call>" }', 'NaN', 'Infinity'])
def test_native_valid_json_is_byte_equivalent_and_never_enters_optional_readers(raw):
    execute = Mock(side_effect=AssertionError('valid history entered literal reconstruction'))
    definition = replace(policy.DEFINITION, execute=execute)
    messages = [{'role': 'assistant', 'tool_calls': [call(raw)]}]
    assert prepare(messages, definition) == messages
    execute.assert_not_called()


@pytest.mark.parametrize('raw', [None, {}, [], False, 0, '', '{"cmd":"unfinished',
    '{"path":"x","content":"partial', 'noise {}', 'unreadable \x00 λ secret',
    '{"cmd":"echo\\x"}'])
@pytest.mark.parametrize('recover', [True, False])
def test_unknown_empty_falsy_incomplete_values_are_not_fabricated(raw, recover):
    messages = [{'role': 'assistant', 'tool_calls': [call(raw)]}]
    result = prepare(messages, recover=recover)
    value = result[0]['tool_calls'][0]['function']['arguments']
    if isinstance(raw, str):
        assert json.loads(value) == {'_unparsed': raw}
    else:
        assert value == raw and type(value) is type(raw)
    assert result[0]['tool_calls'][0]['id'] == 'same-id'
    assert result[0]['tool_calls'][0]['function']['name'] == 'old_native_api'


@pytest.mark.parametrize('recover,selected', [(False, True), (True, False), (False, False)])
def test_disabled_or_library_optout_only_runs_lossless_foundation(monkeypatch, recover, selected):
    forbidden = Mock(side_effect=AssertionError('optional recovery ran'))
    definition = replace(policy.DEFINITION, execute=forbidden) if selected else None
    monkeypatch.setattr(jsontext, 'extract_json_object', forbidden)
    monkeypatch.setattr(massage, '_recover_write_args', forbidden)
    raw = 'wrapper {"cmd":"recoverable"}'
    log = Log()
    result = prepare([{'role': 'assistant', 'tool_calls': [call(raw)]}], definition, recover, log)
    assert json.loads(arguments(result)[0]) == {'_unparsed': raw}
    assert log.events == [('upstream.history_args_enveloped', {'count': 1})]
    forbidden.assert_not_called()


def test_replacement_controls_only_aligned_literals_and_cannot_skip_foundation():
    execute = Mock(return_value=policy.RecoveredArguments(({'chosen': False}, None, {})))
    definition = replace(policy.DEFINITION, execute=execute)
    raw = ['invalid one', 'invalid two', 'invalid three']
    messages = [{'role': 'assistant', 'tool_calls': [call(value, id=str(i)) for i, value in enumerate(raw)]}]
    result = prepare(messages, definition)
    execute.assert_called_once_with(policy.HistoricalArguments(tuple(raw)))
    assert [json.loads(value) for value in arguments(result)] == [
        {'chosen': False}, {'_unparsed': raw[1]}, {'_unparsed': raw[2]}]
    assert [tc['id'] for tc in result[0]['tool_calls']] == ['0', '1', '2']


@pytest.mark.parametrize('replacement', [None, policy.RecoveredArguments(()),
                                         policy.RecoveredArguments((None, None))])
def test_untyped_or_misaligned_replacement_fails_without_leaking_payload(replacement):
    raw = 'private-secret'
    definition = replace(policy.DEFINITION, execute=lambda source: replacement)
    with pytest.raises(ValueError) as error:
        prepare([{'role': 'assistant', 'tool_calls': [call(raw)]}], definition)
    assert raw not in str(error.value)


def test_imported_literal_readers_keep_order_and_counts_without_fresh_policy(monkeypatch):
    literal = Mock(wraps=jsontext.extract_json_object)
    write = Mock(wraps=callliterals._recover_write_args)
    monkeypatch.setattr(jsontext, 'extract_json_object', literal)
    monkeypatch.setattr(callliterals, '_recover_write_args', write)
    monkeypatch.setattr(massage, '_recover_write_args',
                        Mock(side_effect=AssertionError('legacy helper reached')), raising=False)
    # Install poison seats even after the obsolete entry point is removed; a
    # regression to either whole callback must still fail rather than disappear.
    monkeypatch.setattr(massage, 'repair_history_tool_args', Mock(side_effect=AssertionError('old whole policy')), raising=False)
    monkeypatch.setattr(massage, 'repair_tool_args', Mock(side_effect=AssertionError('fresh whole policy')), raising=False)
    result = prepare([{'role': 'assistant', 'tool_calls': [
        call('{"valid":true}'), call('wrapper {"x":false}'), call('unrecoverable')]}])
    assert literal.call_count == 2 and write.call_count == 1
    assert [json.loads(value) for value in arguments(result)] == [
        {'valid': True}, {'x': False}, {'_unparsed': 'unrecoverable'}]


def test_reader_failure_does_not_mutate_history_log_or_invent_an_execution(monkeypatch):
    original = [{'role': 'assistant', 'tool_calls': [call('unreadable secret')]}]
    snapshot, log = copy.deepcopy(original), Log()
    monkeypatch.setattr(jsontext, 'extract_json_object', Mock(side_effect=RuntimeError('reader unavailable')))
    with pytest.raises(RuntimeError, match='reader unavailable'):
        prepare(original, log=log)
    assert original == snapshot and log.events == []


def test_private_wrappers_are_not_promoted_and_valid_literal_tags_are_opaque():
    private = '<think>{"secret":"PRIVATE"}</think> wrapper {"public":"literal </think> 雪"}'
    valid = json.dumps({'literal': '<think>PRIVATE</think> ```json </tool_call> \\n'}, ensure_ascii=False)
    log = Log()
    result = prepare([{'role': 'assistant', 'tool_calls': [call(private), call(valid)]}], log=log)
    assert json.loads(arguments(result)[0]) == {'public': 'literal </think> 雪'}
    assert arguments(result)[1] == valid
    assert 'PRIVATE' not in repr(log.events)
    assert log.events == [('massage.history_args_repaired', {'count': 1,
        'assist_id': 'historical-argument-recovery', 'family_id': 'F06'})]


def test_multiple_choices_and_unknown_shapes_are_not_conflated_or_recursively_repaired():
    raw1, raw2 = 'wrapper {"one":1}', 'wrapper {"two":2}'
    messages = [
        {'role': 'assistant', 'choice_index': 3, 'tool_calls': [call(raw1, id='shared')]},
        {'role': 'assistant', 'choice_index': 8, 'tool_calls': [call(raw2, id='shared')]},
        {'role': 'tool', 'tool_call_id': 'unknown-result', 'content': raw1},
        {'role': 'function', 'function_call': {'arguments': raw2}},
        {'choices': [{'message': {'tool_calls': [call(raw1)]}}]},
        {'role': 'assistant', 'tool_calls': [None, 'unknown', {'function': None}, {'function': {}}]},
        {'role': 'assistant', 'tool_calls': {'unknown-shape': raw1}}, None,
    ]
    original = copy.deepcopy(messages)
    result = prepare(messages)
    assert [json.loads(value) for value in arguments(result[:2])] == [{'one': 1}, {'two': 2}]
    assert result[2:] == original[2:]
    assert messages == original


@pytest.mark.parametrize('role', ['assistant', 'user', 'system', 'tool', 'function', 'developer'])
def test_historical_role_is_not_used_to_guess_a_new_call_or_correlation(role):
    message = {'role': role, 'content': 'leave role and output alone',
               'tool_call_id': 'unknown', 'tool_calls': [call('wrapper {"old":0}')]}
    result = prepare([message])[0]
    assert result['role'] == role and result['content'] == message['content']
    assert result['tool_call_id'] == 'unknown'
    assert json.loads(result['tool_calls'][0]['function']['arguments']) == {'old': 0}
    assert result['tool_calls'][0]['id'] == 'same-id'


def test_replay_is_idempotent_and_has_no_task_or_delivery_state():
    log = Log()
    first = prepare([{'role': 'assistant', 'tool_calls': [call('bad')]}], log=log)
    before = copy.deepcopy(log.events)
    execute = Mock(side_effect=AssertionError('enveloped history is already valid JSON'))
    assert prepare(first, replace(policy.DEFINITION, execute=execute), log=log) == first
    execute.assert_not_called()
    assert log.events == before


def test_final_prep_repairs_a_downstream_append_with_optional_recovery_disabled(monkeypatch):
    # Production integration gate: deliberately no stub of the recovery hook.
    # The current early hook cannot settle this later shared transform's output.
    from cria import config, upstream
    late_raw = '{"cmd":"late unfinished'
    appended = [
        {'role': 'assistant', 'tool_calls': [call(late_raw, id='late')]},
        {'role': 'tool', 'tool_call_id': 'late', 'content': 'already happened; not a new execution'},
    ]
    original_merge = upstream._merge_consecutive_assistant
    monkeypatch.setattr(upstream, '_merge_consecutive_assistant', lambda messages: original_merge(messages) + appended)
    up = upstream.Upstream('http://unused', context_window=8192, engagement_level=config.PURE_PROXY)
    raw, _, _ = up._prep({'model': 'offline', 'messages': [{'role': 'user', 'content': 'continue'}]}, False, Log())
    wire = json.loads(raw)['messages']
    assert json.loads(wire[-2]['tool_calls'][0]['function']['arguments']) == {'_unparsed': late_raw}
    assert wire[-1] == appended[-1]
    assert wire[-2]['tool_calls'][0]['id'] == 'late'


@pytest.mark.parametrize('mode', ['empty', 'disabled', 'fresh-only'])
def test_public_compat_uses_bound_root_absence_not_library_default(monkeypatch, mode):
    from cria import assistruntime, outputpolicies
    forbidden = Mock(side_effect=AssertionError('bound absence inherited library recovery'))
    monkeypatch.setattr(jsontext, 'extract_json_object', forbidden)
    monkeypatch.setattr(massage, '_recover_write_args', forbidden)
    definitions = (policy.DEFINITION,)
    disabled = ()
    if mode == 'empty':
        level = 0
    else:
        level = 1
        disabled = (policy.DEFINITION.policy.id,)
    if mode == 'fresh-only':
        fresh = next(d for d in outputpolicies.REPAIR if d.policy.id == 'malformed-argument-repair')
        definitions += (fresh,)
    runtime = assistruntime.AssistRuntime.select(level=level, registrations=definitions, disabled=disabled)
    raw = 'wrapper {"recoverable":false}'
    log = Log()
    with assistruntime.bound(runtime):
        assert assistruntime.is_bound()
        result = massage.repair_history_tool_args([{'role': 'assistant', 'tool_calls': [call(raw)]}], log)
    assert json.loads(arguments(result)[0]) == {'_unparsed': raw}
    forbidden.assert_not_called()
    assert log.events == [('upstream.history_args_enveloped', {'count': 1})]


def test_public_compat_uses_exact_root_replacement_and_restores_nested_binding():
    from cria import assistruntime
    execute = Mock(return_value=policy.RecoveredArguments(({'selected': 0},)))
    replacement = replace(policy.DEFINITION, execute=execute)
    high = assistruntime.AssistRuntime.select(level=1, registrations=(replacement,))
    empty = assistruntime.AssistRuntime.select(level=0, registrations=(replacement,))
    raw = 'unrecoverable original bytes'
    messages = [{'role': 'assistant', 'tool_calls': [call(raw)]}]
    from cria.massage import repair_history_tool_args as public_alias
    assert public_alias is massage.repair_history_tool_args
    with assistruntime.bound(high):
        assert policy.selected_definition(assistruntime.current().definitions) is replacement
        assert json.loads(arguments(public_alias(messages))[0]) == {'selected': 0}
        with assistruntime.bound(empty):
            assert json.loads(arguments(public_alias(messages))[0]) == {'_unparsed': raw}
        assert json.loads(arguments(public_alias(messages))[0]) == {'selected': 0}
    assert execute.call_count == 2
    assert messages[0]['tool_calls'][0]['function']['arguments'] == raw


def test_public_compat_explicit_optout_overrides_selected_replacement_but_envelopes():
    from cria import assistruntime
    execute = Mock(side_effect=AssertionError('explicit recover=False reconstructed history'))
    replacement = replace(policy.DEFINITION, execute=execute)
    root = assistruntime.AssistRuntime.select(level=1, registrations=(replacement,))
    raw = 'wrapper {"would":"recover"}'
    with assistruntime.bound(root):
        result = massage.repair_history_tool_args([{'role': 'assistant', 'tool_calls': [call(raw)]}], recover=False)
    assert json.loads(arguments(result)[0]) == {'_unparsed': raw}
    execute.assert_not_called()


def test_unbound_public_compat_retains_default_and_lossless_library_optout():
    from cria import assistruntime
    assert not assistruntime.is_bound()
    raw = 'wrapper {"literal":"λ\\\\n"}'
    original = [{'role': 'assistant', 'tool_calls': [call(raw)]}]
    log = Log()
    result = massage.repair_history_tool_args(original, log)
    assert json.loads(arguments(result)[0]) == {'literal': 'λ\\n'}
    envelope = massage.repair_history_tool_args(original, recover=False)
    assert json.loads(arguments(envelope)[0]) == {'_unparsed': raw}
    assert 'λ' not in repr(log.events)
    assert original[0]['tool_calls'][0]['function']['arguments'] == raw


def test_public_compat_and_final_prep_use_the_same_replacement_raw_bytes_and_logs():
    from cria import assistruntime, upstream
    execute = Mock(return_value=policy.RecoveredArguments(({'literal': 'λ\\n', 'false': False},)))
    replacement = replace(policy.DEFINITION, execute=execute)
    runtime = assistruntime.AssistRuntime.select(level=1, registrations=(replacement,))
    raw = 'malformed λ original'
    messages = [{'role': 'user', 'content': 'task'},
                {'role': 'assistant', 'tool_calls': [call(raw)]},
                {'role': 'tool', 'tool_call_id': 'same-id', 'content': 'actual result'},
                {'role': 'user', 'content': 'continue'}]
    first_log, wire_log = Log(), Log()
    with assistruntime.bound(runtime):
        expected = massage.repair_history_tool_args(messages, first_log)
        up = upstream.Upstream('http://unused', context_window=8192, engagement_level=1)
        data, _, _ = up._prep({'model': 'offline', 'messages': messages,
            'tools': [{'type': 'function', 'function': {'name': 'new_api', 'parameters': {'type': 'object'}}}]}, False, wire_log)
    actual = json.loads(data)['messages']
    assert actual == expected
    assert arguments(actual)[0].encode('utf-8') == arguments(expected)[0].encode('utf-8')
    assert actual[1]['tool_calls'][0]['function']['name'] == 'old_native_api'
    assert actual[2] == messages[2]
    assert execute.call_count == 2  # one compatibility call, one actual wire call
    expected_events = [(kind, fields) for kind, fields in wire_log.events if kind == 'massage.history_args_repaired']
    assert expected_events == first_log.events


def test_public_alias_is_context_local_for_overlapping_selected_and_empty_roots():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from cria import assistruntime
    from cria.massage import repair_history_tool_args as alias
    definition = replace(policy.DEFINITION, execute=lambda source: policy.RecoveredArguments(({'root': 'selected'},)))
    roots = [assistruntime.AssistRuntime.select(level=level, registrations=(definition,)) for level in (1, 0)]
    barrier = Barrier(2)
    def invoke(root):
        with assistruntime.bound(root):
            barrier.wait(timeout=5)
            return json.loads(arguments(alias([{'role': 'assistant', 'tool_calls': [call('original malformed')]}]))[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(invoke, roots)) == [{'root': 'selected'}, {'_unparsed': 'original malformed'}]


def test_source_projection_is_empty_exact_and_rejects_duplicate_or_wrong_contract():
    assert policy.selected_definition(()) is None
    execute = Mock(return_value=policy.RecoveredArguments(()))
    selected = replace(policy.DEFINITION, execute=execute)
    assert policy.selected_definition((selected,)) is selected
    with pytest.raises(ValueError, match='Duplicate'):
        policy.selected_definition((selected, selected))
    with pytest.raises(ValueError, match='typed policy contract'):
        policy.selected_definition((replace(selected, policy=replace(selected.policy, default_level=0)),))


def test_source_imports_independently_without_the_entry_module_or_runtime():
    script = ('import sys; from cria import historyarguments; '
              "assert 'cria.massage' not in sys.modules; assert 'cria.assistruntime' not in sys.modules; "
              "assert 'cria.loop' not in sys.modules")
    result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_metadata_names_real_wire_hook_readers_and_behavioral_regressions():
    assert policy.DEFINITION.execute is policy.recover_arguments
    assert policy.DEFINITION.policy.default_level == 1
    assert policy.DEFINITION.policy.scope == 'runtime'
    assert policy.DEFINITION.policy.state == 'none'
    assert not policy.DEFINITION.policy.prompts and not policy.DEFINITION.policy.migrated
    root = Path(__file__).resolve().parents[1]
    for ref in policy.DEFINITION.policy.hooks + policy.DEFINITION.policy.regressions:
        body = ast.parse((root / ref.path).read_text()).body
        for name in ref.symbol.split('.'):
            node = next(n for n in body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name == name)
            body = node.body
