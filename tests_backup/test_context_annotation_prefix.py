"""Derived facts must not rewrite the system or a previously sent handoff."""
import copy
import json

import pytest

from cria import assistruntime, bodykeys, contextfloor, loop, modelview
from cria.upstream import Upstream
from test_context_prefix_stability import Log, append_turn, projected, request


PERMISSIONS = ('<permissions instructions>\nThe writable roots are `/dependencies`, `/workspace`.'
               '\n</permissions instructions>')


def pair(n, text):
    return [{'role': 'assistant', 'content': None, 'tool_calls': [{
        'id': f'call-{n}', 'type': 'function',
        'function': {'name': 'shell', 'arguments': json.dumps({'cmd': f'build {n}'})}}]},
        {'role': 'tool', 'tool_call_id': f'call-{n}', 'content': text}]


def framed_prep(up, messages, log):
    framed = loop._frame_for_item(messages, '', '', 1, 1, synthetic=True, workspace_root='/workspace')
    return json.loads(up._prep({'model': 'offline', bodykeys.OUTPUT_RESERVE: 500,
                               'messages': framed}, False, log, safety_override=1)[0])


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
def test_build_observations_append_without_rewriting_the_coder_system(profile):
    messages = [{'role': 'system', 'content': PERMISSIONS, bodykeys.CALLER_INSTRUCTIONS: True},
                {'role': 'user', 'content': 'Repair and check the importer.'}]
    up, log = Upstream('http://offline.invalid', context_window=131072), Log('dependencies')
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        previous = framed_prep(up, messages, log)
        system = previous['messages'][0]
        for n, location in enumerate(['/dependencies/m2', '/dependencies/alternate', '/dependencies/m2']):
            output = f'Picked up JAVA_TOOL_OPTIONS: -Dmaven.repo.local={location}\nBuild invocation {n}.'
            messages += pair(n, output)
            original = copy.deepcopy(messages)
            current = framed_prep(up, messages, log)
            assert messages == original
            assert current['messages'][0] == system
            assert projected(current).startswith(projected(previous))
            assert any(m.get('content') == output for m in current['messages'])
            assert bodykeys.ANNOTATION_SOURCE not in json.dumps(current)
            assert any(location in str(m.get('content')) and m['role'] == 'user'
                       for m in current['messages'][len(previous['messages']):]) or n == 2
            assert not log.named('context.floor')
            previous = current


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
def test_reframing_the_same_handoff_does_not_inventory_newer_work(profile):
    messages = [{'role': 'user', 'content': 'Repair and check the importer.'},
                {'role': 'user', 'content': loop._COMPACTION_MARKER + '\nKept the parser; tests remain.'}]
    up, log = Upstream('http://offline.invalid', context_window=131072), Log('inventory')
    previous = None
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        for n in range(5):
            original = copy.deepcopy(messages)
            reframed, hit = loop.reframe_compaction(messages)
            assert hit and messages == original
            current = framed_prep(up, reframed, log)
            if previous is not None:
                assert projected(current).startswith(projected(previous))
            assert 'Kept the parser; tests remain.' in '\n'.join(str(m.get('content')) for m in current['messages'])
            assert modelview._paired_ids(current['messages']) == {f'call-{i}' for i in range(n)}
            assert not log.named('context.floor')
            previous = current
            messages += pair(n, f'Exact tool observation {n}.')


@pytest.mark.parametrize('source', ['dependency_annotation', 'inventory', 'other'])
def test_prefix_break_identifies_the_changed_annotation_source(source):
    # L0 preserves the supplied legacy inventory; observation must still identify
    # its churn without applying context surgery to a proxy request.
    if source == 'dependency_annotation':
        before, after = '⟦ctx:dependencies⟧ Observed /dependencies/one.', '⟦ctx:dependencies⟧ Observed /dependencies/two.'
    elif source == 'inventory':
        head = ('⟦ctx:continuation⟧ Historical account.\n\n' + modelview.RETAINED_HEADER
                + 'their full original output remains in their paired tool messages):\n')
        before, after = head + '(none)', head + '- paired tool result (call id: new)'
    else:
        before, after = 'Earlier unverified account.', 'Corrected unverified account.'
    up, log = Upstream('http://offline.invalid', context_window=131072, engagement_level=0), Log(source)
    body = {'model': 'offline', 'messages': [{'role': 'user', 'content': 'Task'},
                                           {'role': 'user', 'content': before}]}
    up._prep(body, False, log)
    body['messages'][-1]['content'] = after
    up._prep(body, False, log)
    assert log.named('context.prefix')[-1]['break_source'] == source


def test_prefix_break_attributes_a_new_floor_reduction():
    body, log = request(), Log('floor-source')
    up = Upstream('http://offline.invalid', context_window=6500)
    up._prep(body, False, log, safety_override=1)
    for n in range(26):
        append_turn(body, n)
    up._prep(body, False, log, safety_override=1)
    assert log.named('context.prefix')[-1]['break_source'] == 'floor'


@pytest.mark.parametrize('hint', [None, 'dependency_annotation', {'value': 'dependency_annotation'}])
def test_dependency_observation_cannot_displace_the_current_user_request_at_the_floor(hint):
    messages = [{'role': 'system', 'content': PERMISSIONS, bodykeys.CALLER_INSTRUCTIONS: True},
                {'role': 'user', 'content': 'Root task.'}]
    for n in range(20):
        messages += pair(n, f'Historical observation {n}.\n' + 'Old measured output.\n' * 80)
    current = {'role': 'user', 'content': 'Now preserve THIS current request and check the parser.'}
    if hint is not None:
        current[bodykeys.ANNOTATION_SOURCE] = hint  # JSON lookalikes are not producer authority
    messages.append(current)
    for n in range(20, 32):
        messages += pair(n, f'Current observation {n}.\n' + 'Current measured output.\n' * 50)
    messages[-1]['content'] += '\nPicked up JAVA_TOOL_OPTIONS: -Dmaven.repo.local=/dependencies/m2'
    log = Log('current-request')
    wire = framed_prep(Upstream('http://offline.invalid', context_window=6500), messages, log)
    assert {'role': 'user', 'content': current['content']} in wire['messages']
    assert bodykeys.ANNOTATION_SOURCE not in json.dumps(wire)
    assert log.named('context.floor')
    assert not log.named('context.floor')[-1]['over_budget']


def test_a_legacy_inventory_quoted_inside_the_handoff_is_preserved_verbatim():
    summary = ('Quoted old record:\n' + modelview.RETAINED_HEADER
               + 'their full original output remains in their paired tool messages):\n'
               '- paired tool result (call id: quoted-old-id)\nEnd of quoted record.')
    messages, _ = loop.reframe_compaction([
        {'role': 'user', 'content': 'Task'},
        {'role': 'user', 'content': loop._COMPACTION_MARKER + '\n' + summary}])
    wire = framed_prep(Upstream('http://offline.invalid', context_window=131072), messages, Log('quoted'))
    assert summary in '\n'.join(str(m.get('content')) for m in wire['messages'])


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
@pytest.mark.parametrize('separator', ['\n', '\n\n'])
@pytest.mark.parametrize('ending', ['\nEnd of quoted source.', ''])
@pytest.mark.parametrize('header', [
    'quoted example requires build ID RELEASE-927):',
    'their full original output remains in their paired tool messages):'])
def test_a_quoted_inventory_without_an_owned_outer_footer_survives_the_real_wire(profile, header, ending, separator):
    # Independent review P1: the native pair really exists; this is quoted handoff
    # information, not a generated inventory that grants permission to erase it.
    quote = ('⟦ctx:continuation⟧ Unverified handoff; preserve this quoted source:' + separator
             + modelview.RETAINED_HEADER + header + '\n'
             '- paired tool result (call id: call-927)' + ending)
    messages = [{'role': 'user', 'content': 'Keep the quoted build ID.'},
                *pair(927, 'Build output.'), {'role': 'user', 'content': quote}]
    original = copy.deepcopy(messages)
    log = Log('quoted-no-footer')
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        wire = framed_prep(Upstream('http://offline.invalid', context_window=131072), messages, log)
    assert messages == original
    assert {'role': 'user', 'content': quote} in wire['messages']
    assert modelview._paired_ids(wire['messages']) == {'call-927'}
    assert any(m.get('content') == 'Build output.' for m in wire['messages'])
    assert not log.named('context.floor')


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
def test_a_recognized_legacy_footer_is_relocated_without_losing_any_of_its_text(profile):
    # The historical footer contains a coordinate absent from native messages.
    # It must remain quoted verbatim; only the labelled floor may reduce it.
    from cria import prompts
    footer = (modelview.RETAINED_HEADER + 'their full original output remains in their paired tool messages):\n'
              '- paired tool result (call id: absent-RELEASE-927)')
    lead = prompts.load('compaction_reframe').split('\n\n', 1)[0]
    text = '⟦ctx:continuation⟧ ' + lead + '\n\nHistorical account.\n\n' + footer
    messages = [{'role': 'user', 'content': 'Preserve historical records.'},
                {'role': 'user', 'content': text}, *pair(1, 'Current result.')]
    log = Log('legacy-no-loss')
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        wire = framed_prep(Upstream('http://offline.invalid', context_window=131072), messages, log)
    joined = '\n'.join(str(m.get('content')) for m in wire['messages'])
    assert footer in joined
    assert modelview._paired_ids(wire['messages']) == {'call-1'}
    assert not log.named('context.floor')
    assert modelview.retained_results_truth(wire['messages']) is wire['messages']


@pytest.mark.parametrize('existing_label', [False, True])
def test_an_earlier_system_edit_is_not_attributed_to_a_later_floor_reduction(existing_label):
    # Independent review P2: changing the system is the first break; dropping
    # later history cannot make that earlier caller edit into a floor transform.
    suffix = '\n⟦ctx:reduced⟧ An existing historical label.' if existing_label else ''
    body = {'model': 'offline', bodykeys.OUTPUT_RESERVE: 500, 'messages': [
        {'role': 'system', 'content': 'Original system rule.' + suffix},
        {'role': 'user', 'content': 'Task'}]}
    up, log = Upstream('http://offline.invalid', context_window=6500), Log('mixed-source')
    up._prep(body, False, log, safety_override=1)
    body['messages'][0]['content'] = 'Changed system rule.' + suffix
    for n in range(30):
        append_turn(body, n)
    wire = json.loads(up._prep(body, False, log, safety_override=1)[0])
    assert wire['messages'][0] == body['messages'][0]
    assert log.named('context.floor')
    event = log.named('context.prefix')[-1]
    assert event['changed_message'] == 0
    assert event['break_source'] == 'other'


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
def test_a_relocated_inventory_cannot_displace_the_live_request_under_window_pressure(profile):
    from cria import prompts
    footer = (modelview.RETAINED_HEADER + 'their full original output remains in their paired tool messages):\n'
              '- paired tool result (call id: historical-call)')
    lead = prompts.load('compaction_reframe').split('\n\n', 1)[0]
    messages = [{'role': 'user', 'content': 'Root task.'},
                {'role': 'user', 'content': '⟦ctx:continuation⟧ ' + lead + '\n\nOld account.\n\n' + footer}]
    for n in range(20):
        messages += pair(n, f'Historical observation {n}.\n' + 'Measured old output.\n' * 80)
    current = {'role': 'user', 'content': 'Preserve THIS live follow-up request and check the parser.'}
    messages.append(current)
    for n in range(20, 32):
        messages += pair(n, f'Current observation {n}.\n' + 'Measured current output.\n' * 50)
    log = Log('relocated-inventory-live')
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        wire = framed_prep(Upstream('http://offline.invalid', context_window=6500), messages, log)
    assert current in wire['messages']
    assert any(m.get('tool_call_id') == 'call-31' for m in wire['messages'])
    assert log.named('context.floor')
    assert not log.named('context.floor')[-1]['over_budget']
    assert bodykeys.ANNOTATION_SOURCE not in json.dumps(wire)
