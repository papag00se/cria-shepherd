"""Production boundary checks with synthetic messages and fake evidence services."""
import asyncio
import copy
from dataclasses import replace
import json
from unittest.mock import Mock, patch

import pytest

from cria import massage, outboundpolicies, outputpolicies, returnedpolicies, toolstages, writeproxy


SHELL = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}


def completion(name='write_file', **arguments):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'content': None,
        'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps(arguments)}}]}}]}


def lower(comp, **kwargs):
    return writeproxy.translate_outbound(comp, SHELL, injected={'write_file', 'edit_file'}, **kwargs)


def command(comp):
    return json.loads(comp['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']


def without(*ids):
    bindings = toolstages.defaults()
    changes = {name: tuple(d for d in getattr(bindings, name) if d.policy.id not in ids)
               for name in ('recovery', 'repair', 'text_answer', 'outbound', 'returned', 'history', 'mutations')}
    if bindings.rejected_draft.policy.id in ids:
        changes['rejected_draft'] = None
    return replace(bindings, **changes)


def test_recovery_replacement_and_bypass_are_used_by_public_production_entry():
    comp = {'choices': [{'finish_reason': 'stop', 'message': {'content':
        '<tool_call>{"name":"write_file","arguments":{"path":"x","content":"hello"}}</tool_call>'}}]}
    original = copy.deepcopy(comp)
    with toolstages.bound(without('text-call-recovery')):
        assert massage.apply(comp, tool_call_fixes=True) == original
    seen = []
    def recover(comp, tools=None, rlog=None):
        seen.append(tools)
        comp['choices'][0]['message']['content'] = 'replacement ran'
        return comp
    definition = replace(outputpolicies.RECOVERY[0], execute=recover)
    with toolstages.bound(replace(toolstages.defaults(), recovery=(definition,))):
        assert massage.apply(copy.deepcopy(original), tool_call_fixes=True)['choices'][0]['message']['content'] == 'replacement ran'
    assert seen == [None]


def test_pure_proxy_still_skips_all_output_policy_detection():
    def forbidden(*args, **kwargs):
        raise AssertionError('output detector ran')
    definition = replace(outputpolicies.RECOVERY[0], execute=forbidden)
    comp = completion(path='x', content='x')
    with toolstages.bound(replace(toolstages.defaults(), recovery=(definition,))):
        assert massage.apply(comp, tool_call_fixes=False) is comp


def test_late_promotions_use_selected_repair_stage():
    seen = []
    def repair(comp, tools=None, rlog=None):
        seen.append(True)
        return comp
    definition = replace(outputpolicies.REPAIR[1], execute=repair)
    comp = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'draft'}}]}
    call = completion(path='x', content='body')['choices'][0]['message']['tool_calls'][0]
    with toolstages.bound(replace(toolstages.defaults(), repair=(definition,))):
        massage.promote_call(comp, call, '', None)
    assert seen == [True]


def test_disabled_unread_and_shrink_do_not_enter_callbacks_or_safety_service():
    forbidden = Mock(side_effect=AssertionError('disabled policy observed evidence'))
    with toolstages.bound(without('unread-file-protection', 'shrinking-file-protection', 'candidate-mutation-safety')):
        with patch('cria.cleanupsafety.review', forbidden):
            out = lower(completion(path='x', content='bytes'), unread_target=forbidden, shrink_check=forbidden)
    assert writeproxy._b64('bytes') in command(out)
    forbidden.assert_not_called()


def test_spill_correction_changes_execution_path_not_original_call_evidence():
    relative = writeproxy.webfetch.SPILL_DIR + '/reference.txt'
    absolute = '/' + relative.removeprefix('./')
    comp = completion('read_file', path=absolute)
    read = Mock(return_value='printf reference')
    with patch.object(outboundpolicies, '_spill_read_command', read), \
         patch.object(writeproxy, '_spill_read_command', side_effect=AssertionError('legacy helper reached')):
        writeproxy.translate_outbound(comp, SHELL, injected={'read_file'})
    read.assert_called_once_with(relative)
    original = writeproxy.original_call(command(comp))
    assert json.loads(original['arguments'])['path'] == absolute


def test_disabled_external_guard_does_not_queue_workspace_questions():
    forbidden = Mock(side_effect=AssertionError('disabled boundary detector ran'))
    with toolstages.bound(without('workspace-boundary')):
        with patch.object(writeproxy, '_external_refusal', forbidden):
            lower(completion(path='x', content='bytes'))
    forbidden.assert_not_called()


def test_disabled_advice_cannot_disable_write_evidence_or_eof_read_credit():
    stages = replace(toolstages.defaults(), returned=(), history=(), rejected_draft=None)
    view = Mock()
    lowered = lower(completion(path='x', content='bytes without newline'))
    history = [{'role': 'assistant', 'tool_calls': lowered['choices'][0]['message']['tool_calls']},
               {'role': 'tool', 'tool_call_id': 'c1', 'content': writeproxy._WROTE}]
    with toolstages.bound(stages), patch.object(writeproxy.wsview, 'current', return_value=view):
        result = writeproxy.represent_inbound(history)
    view.note_written.assert_called_once_with('x', 'bytes without newline')
    assert result[0]['tool_calls'][0]['function']['name'] == 'write_file'
    # A successful whole read remains evidence even when every annotation is disabled.
    read = writeproxy.translate_outbound(completion('read_file', path='x'), SHELL, injected={'read_file'})
    history = [{'role': 'assistant', 'tool_calls': read['choices'][0]['message']['tool_calls']},
               {'role': 'tool', 'tool_call_id': 'c1', 'content': 'Process exited with code 0\nOutput:\nbytes without newline'}]
    view.reset_mock()
    with toolstages.bound(stages), patch.object(writeproxy.wsview, 'current', return_value=view):
        writeproxy.represent_inbound(history)
    view.note_read.assert_called_once_with('x', 'bytes without newline')


def test_disabled_history_never_scans_dependency_failures_or_changes_anchor_state():
    forbidden = Mock(side_effect=AssertionError('disabled advice detector ran'))
    with toolstages.bound(replace(toolstages.defaults(), history=())):
        with patch.object(writeproxy.probeparse, 'dependency_missing', forbidden), \
             patch.object(writeproxy.depsurface, 'declared_coordinates', forbidden):
            assert writeproxy.represent_inbound([{'role': 'tool', 'content': 'No module named fake'}],
                workspace_root='/fake', sess_key='fake') == [{'role': 'tool', 'content': 'No module named fake'}]
    forbidden.assert_not_called()


def test_dependency_anchor_settlement_and_abstention_counters_stop_when_deselected():
    coordinate = ('go', 'example.invalid/pkg', 'v1')
    session = 'stage-lifecycle'
    deps = writeproxy.depsurface
    declared = Mock(return_value=[coordinate])
    gather = Mock(side_effect=AssertionError('anchored text must not be gathered again'))
    anchors = {session: {coordinate: ('old', 'cached exact evidence')}}
    counters = {session: {coordinate: 7}}
    selected = toolstages.ToolStages.from_definitions((returnedpolicies.HISTORY[2],))
    with patch.object(deps, '_ANCHOR', anchors), patch.object(deps, '_ABSTAINED', counters), \
         patch.object(deps, 'declared_coordinates', declared), patch.object(deps, 'gather', gather), \
         patch.object(writeproxy.dirguard, 'dependency_roots', return_value={}):
        with toolstages.bound(toolstages.ToolStages.from_definitions(())):
            writeproxy.represent_inbound([{'role': 'tool', 'tool_call_id': 'new', 'content': 'payload'}],
                workspace_root='/fake', sess_key=session)
        assert anchors[session][coordinate] == ('old', 'cached exact evidence')
        assert counters[session][coordinate] == 7
        declared.assert_not_called()
        with toolstages.bound(selected):
            out = writeproxy.represent_inbound([{'role': 'tool', 'tool_call_id': 'new', 'content': 'payload'}],
                workspace_root='/fake', sess_key=session)
        assert anchors[session][coordinate] == ('new', 'cached exact evidence')
        assert out[0]['content'].endswith('cached exact evidence')
        assert writeproxy.payload_of(out[0], out[0]['content']) == 'payload'
        with toolstages.bound(selected):
            writeproxy.represent_inbound([{'role': 'tool', 'tool_call_id': 'compaction', 'content': 'summary'}],
                workspace_root='/fake', sess_key=session, tools_present=False)
        assert anchors[session][coordinate][0] == 'new'
        gather.assert_not_called()


def test_disabled_stream_recovery_does_not_run_its_capture_detector():
    detector = Mock(return_value=-1)
    definition = replace(outputpolicies.RECOVERY[0], stream_start=detector)
    chunks = [massage._sse({'content': 'plain prose'}, 'fake'),
              massage._sse({}, 'fake', finish='stop'), b'data: [DONE]\\n\\n']
    with toolstages.bound(toolstages.ToolStages.from_definitions((definition,))):
        list(massage.massage_stream(iter(chunks), 'fake'))
    detector.assert_called_once_with('plain prose')
    detector.reset_mock()
    with toolstages.bound(toolstages.ToolStages.from_definitions(())):
        list(massage.massage_stream(iter(chunks), 'fake'))
    detector.assert_not_called()


def test_returned_replacement_runs_before_later_notes_and_keeps_payload_boundary():
    seen = []
    def first(source):
        seen.append(source.own_command)
        return writeproxy._noted(source.message, source.content, 'replacement note')
    def forbidden(source):
        raise AssertionError('later returned stage must short circuit')
    definitions = (replace(returnedpolicies.RESULTS[1], execute=first),
                   replace(returnedpolicies.RESULTS[2], execute=forbidden))
    with toolstages.bound(replace(toolstages.defaults(), returned=definitions, history=())):
        out = writeproxy.represent_inbound([{'role': 'tool', 'content': 'original bytes'}])
    assert seen == ['']
    assert writeproxy.payload_of(out[0], out[0]['content']) == 'original bytes'
    assert out[0]['content'].endswith('replacement note')


def test_rejected_draft_switch_controls_both_payload_movement_and_note():
    body = 'a' * 500
    lowered = lower(completion(path='x', content=body))
    history = [{'role': 'assistant', 'tool_calls': lowered['choices'][0]['message']['tool_calls']},
               {'role': 'tool', 'tool_call_id': 'c1', 'content': '⟦ctx:denied⟧ did not run'}]
    with toolstages.bound(replace(toolstages.defaults(), history=())):
        active = writeproxy.represent_inbound(copy.deepcopy(history))
    assert body not in active[0]['tool_calls'][0]['function']['arguments']
    assert body in active[1]['content']
    with toolstages.bound(replace(toolstages.defaults(), history=(), rejected_draft=None)):
        inactive = writeproxy.represent_inbound(copy.deepcopy(history))
    assert body in inactive[0]['tool_calls'][0]['function']['arguments']
    assert body not in inactive[1]['content']


def test_missing_and_null_mutations_still_refused_without_optional_mutation_policies():
    with toolstages.bound(replace(toolstages.defaults(), outbound=(), mutations=())):
        missing = lower(completion(path='x'))
        empty = lower(completion(path='x', content=''))
        deleting = lower(completion('edit_file', path='x', old_string='old', new_string=''))
    assert '⟦ctx:denied⟧' in command(missing)
    assert 'exit 1' in command(missing)
    assert 'base64.b64decode' in command(empty)
    assert 'base64.b64decode' in command(deleting)


def test_authoritative_projection_keeps_empty_selection_empty_and_replacements_real():
    empty = toolstages.ToolStages.from_definitions(())
    assert empty.definitions == ()
    seen = []
    def recover(comp, tools=None, rlog=None):
        seen.append(True)
        return comp
    definition = replace(outputpolicies.RECOVERY[0], execute=recover)
    selected = toolstages.ToolStages.from_definitions((definition,))
    assert selected.recovery == (definition,)
    assert selected.repair == ()
    assert selected.history == ()
    comp = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'plain'}}]}
    with toolstages.bound(selected):
        massage.apply(comp, tool_call_fixes=True)
    assert seen == [True]
    with toolstages.bound(empty):
        massage.apply(comp, tool_call_fixes=True)
    assert seen == [True]


def test_existing_intervention_events_have_source_identity_without_noop_events():
    log = Mock()
    definition = next(d for d in outboundpolicies.DEFINITIONS if d.policy.id == 'unread-file-protection')
    stages = toolstages.ToolStages.from_definitions((definition,))
    with toolstages.bound(stages):
        writeproxy.translate_outbound(completion(path='x', content='body'), SHELL,
            log, injected={'write_file'}, unread_target=lambda path: 'not yet read')
    event = next(c for c in log.emit.call_args_list if c.args[0] == 'writeproxy.write_unread_target')
    assert event.kwargs['assist_id'] == definition.policy.id
    assert event.kwargs['family_id'] == definition.policy.family_id
    log.reset_mock()
    with toolstages.bound(stages):
        writeproxy.translate_outbound(completion('native', key='value'), SHELL,
            log, injected={'write_file'}, unread_target=lambda path: 'not yet read')
    log.emit.assert_not_called()


def test_stage_registration_rejects_wrong_stage_or_duplicate_ids():
    with pytest.raises(ValueError):
        replace(toolstages.defaults(), recovery=(outputpolicies.REPAIR[0],))
    with pytest.raises(ValueError):
        replace(toolstages.defaults(), repair=outputpolicies.REPAIR * 2)


def test_context_local_bindings_do_not_bleed_between_concurrent_consumers():
    default = toolstages.current()
    async def worker(selected):
        with toolstages.bound(selected):
            await asyncio.sleep(0)
            assert toolstages.current() is selected
        assert toolstages.current() == default
    async def both():
        await asyncio.gather(worker(without('text-call-recovery')), worker(without('reasoning-call-recovery')))
    asyncio.run(both())
