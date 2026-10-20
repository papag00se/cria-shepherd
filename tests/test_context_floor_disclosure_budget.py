"""Complete labelled replacements must fit, not just their digest allowance."""
import copy
import json

import pytest

from cria import assistruntime, bodykeys, contextfloor as cf, prompts
from cria.upstream import Upstream, UpstreamError
from test_context_prefix_stability import Log


def disclosure_body():
    spec = [
        (1, 21, 'rollup'), (2, 5, ''), (3, 12, ''), (4, 9, ''),
        (6, 2, 'facts'), (7, 11, ''), (11, 14, ''), (12, 4, 'rollup'),
        (13, 2, ''), (14, 6, ''), (15, 2, ''), (16, 6, 'facts'),
        (17, 21, ''), (19, 8, ''), (20, 22, ''), (21, 11, 'facts'),
        (22, 6, ''), (23, 18, ''), (24, 20, ''), (25, 6, 'rollup'),
        (26, 14, '')]
    messages = [{'role': 'system', 'content': 'Rules'}, {'role': 'user', 'content': 'Task'}]
    for n, count, marker in spec:
        messages.append({'role': 'assistant', 'content': (f'⟦ctx:{marker}⟧ ' if marker else '')
                         + f'Turn {n}: ' + 'Observation of this invocation. ' * count})
    return {'model': 'offline', bodykeys.OUTPUT_RESERVE: 1, 'messages': messages}


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
@pytest.mark.parametrize('session', [None, 'headroom'])
def test_complete_compaction_disclosure_fits_the_final_wire(profile, session):
    body, log = disclosure_body(), Log(session)
    original = copy.deepcopy(body)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        packed = Upstream('http://offline.invalid', context_window=1521)._prep(
            body, False, log, safety_override=1)[0]
    wire = json.loads(packed)
    assert body == original
    assert cf.est_total(wire['messages'], None) <= 1520
    assert not log.named('context.floor')[-1]['over_budget']
    text = '\n'.join(cf._msg_text(m) for m in wire['messages'])
    assert prompts.load('compacted_turn_stub').strip() in text
    assert prompts.load('compacted_history_provenance').strip() in text
    assert body['messages'][-1]['content'] in text


@pytest.mark.parametrize('headroom', [False, True])
def test_complete_compaction_disclosure_fits_at_the_floor(headroom):
    body = disclosure_body()
    fitted, _, report = cf.fit(body['messages'], None, window=1521, reserve=1,
                               safety=1, headroom=headroom)
    assert not report.over_budget
    assert cf.est_total(fitted, None) <= 1520
    assert report.msg_tokens_after == cf.est_total(fitted, None)


def test_actual_complete_fit_does_not_sacrifice_a_historical_anchor_for_headroom():
    messages, preferred = disclosure_body()['messages'], 1148
    candidates = [i for i, m in enumerate(messages)
                  if 1 < i < len(messages) - cf.OVERFLOW_KEEP_TAIL and not cf._has_protect_marker(m)]
    removed = [messages[i] for i in candidates]
    survivors = [m for i, m in enumerate(messages) if i not in candidates]
    complete_note = cf._compacted_note(removed, len(removed), preferred)
    hard = cf.est_total(survivors + [complete_note], None)
    assert hard > preferred
    fitted, dropped = cf._drop_protected_overflow(messages, preferred, sacrifice_budget=hard)
    assert dropped == len(removed)
    assert cf.est_total(fitted, None) <= hard
    assert all(m in fitted for m in messages if cf._has_protect_marker(m))


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
def test_retained_and_new_notes_both_count_before_accepting_a_fit(profile):
    body = disclosure_body()
    retained = {'role': 'user', 'content': '⟦ctx:compacted⟧ Earlier labelled history.\n' + 'Recorded fact. ' * 30}
    body['messages'].insert(1, retained)
    body[bodykeys.PINNED_TASK] = 'Task'
    log = Log('retained-notes')
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        up = Upstream('http://offline.invalid', context_window=1650)
        for _ in range(2):
            packed = up._prep(body, False, log, safety_override=1)[0]
            shown = json.loads(packed)['messages']
            assert retained in shown
            assert sum(cf._COMPACTED_MARK in str(m.get('content')) for m in shown) >= 2
            assert cf.est_total(shown, None) <= 1649
            assert all(not e['over_budget'] for e in log.named('context.floor'))


def test_unfittable_input_is_refused_without_capture_or_prefix_commit(monkeypatch, tmp_path):
    up, log = Upstream('http://offline.invalid', context_window=1000, capture_dir=tmp_path), Log()
    capture = []
    monkeypatch.setattr('cria.upstream.callcapture.capture', lambda *a, **kw: capture.append(a))
    body = {'model': 'offline', bodykeys.OUTPUT_RESERVE: 1,
            'messages': [{'role': 'user', 'content': 'Required input. ' * 400}]}
    with pytest.raises(UpstreamError, match='context'):
        up._prep(body, False, log, safety_override=1)
    assert capture == []
    assert not log.named('context.prefix')


def test_reduced_protected_input_wins_over_a_stale_output_reservation():
    persona = 'Standing caller instructions.\n' * 400
    body = {'model': 'offline', bodykeys.OUTPUT_RESERVE: 1000, 'messages': [
        {'role': 'system', 'content': 'Rules.\n' + persona + 'Configured constraints.',
         bodykeys.CALLER_SPAN: {'start': len('Rules.\n'), 'text': persona}},
        {'role': 'user', 'content': 'Current request.\n' * 200}]}
    fitted, _, report = cf.fit(body['messages'], None, window=1300, reserve=1000, safety=1)
    assert fitted[-1] == body['messages'][-1]
    assert report.caller_reduced == 1
    assert report.reserve_requested == 1000
    assert 0 < report.reserve < report.reserve_requested
    assert cf.est_total(fitted, None) + report.reserve <= 1300
    assert not report.over_budget
    log = Log('reduced-reservation')
    wire = json.loads(Upstream('http://offline.invalid', context_window=1300)._prep(
        body, False, log, safety_override=1)[0])
    assert wire['messages'][-1] == body['messages'][-1]
    assert bodykeys.OUTPUT_RESERVE not in wire and 'max_tokens' not in wire


def test_message_rounding_and_final_assistant_separators_are_budgeted():
    body = {'model': 'offline', bodykeys.OUTPUT_RESERVE: 1, 'messages': [
        {'role': 'system', 'content': 'r' * 2400}, {'role': 'user', 'content': 'Task'},
        *[{'role': 'assistant', 'content': 'abc'} for _ in range(500)],
        {'role': 'user', 'content': 'Current request'}]}
    log = Log('rounding')
    packed = Upstream('http://offline.invalid', context_window=1000)._prep(
        body, False, log, safety_override=1)[0]
    shown = json.loads(packed)['messages']
    assert cf.est_total(shown, None) <= 999
    assert shown[-1] == body['messages'][-1]
    assert log.named('context.wire_refit')  # separators grew an initially fitting request
    assert log.named('context.wire_refit')[0]['reshape'] is None


def test_tool_result_label_counts_before_stopping_output_reduction():
    result = '{"key":' + ' ' * 2000 + '"value"}'
    messages = [{'role': 'tool', 'tool_call_id': str(i), 'content': result} for i in range(2)]
    fitted, reduced = cf._reduce_tool_outputs(messages, 540)
    assert reduced == 2  # one labelled reduction still leaves 572 estimated tokens
    assert cf.est_total(fitted, None) <= 540
    assert all(m['content'].startswith(cf._REDUCED_MARK) and '"value"' in m['content'] for m in fitted)


@pytest.mark.parametrize('kind', ['caller', 'restored'])
def test_other_complete_replacement_labels_are_in_the_reported_budget(kind):
    body = {'model': 'offline', bodykeys.OUTPUT_RESERVE: 1, 'messages': [
        {'role': 'system', 'content': 'Coder rules.'}, {'role': 'user', 'content': 'Task'}]}
    if kind == 'caller':
        persona = 'Standing caller instructions.\n' * 300
        body['messages'][0].update(content='Coder rules.\n' + persona + 'Configured constraints.',
            **{bodykeys.CALLER_SPAN: {'start': len('Coder rules.\n'), 'text': persona}})
        expected = prompts.render('caller_instructions_reduced', chars=f'{len(persona):,}').strip()
        field = 'caller_reduced'
    else:
        body['messages'].append({'role': 'user', 'content': '⟦ctx:current⟧\nfile.txt\n' + 'Exact file bytes.\n' * 700,
            bodykeys.RESTORED_FILES: {'offered': {'file.txt': 'source-hash'}, 'named': ['file.txt', 'absent.txt']}})
        body['messages'].append({'role': 'user', 'content': 'Current request'})
        expected = prompts.render('restore_reduced', paths='file.txt').strip()
        field = 'restored_reduced'
    log = Log('other-labels')
    packed = Upstream('http://offline.invalid', context_window=1500)._prep(
        body, False, log, safety_override=1)[0]
    shown = json.loads(packed)['messages']
    assert expected in '\n'.join(cf._msg_text(m) for m in shown)
    if kind == 'restored':
        uncarried = prompts.render('restore_reduced_uncarried', paths='absent.txt').strip()
        assert uncarried.removeprefix(cf._RESTORED_MARK).strip() in '\n'.join(cf._msg_text(m) for m in shown)
    assert log.named('context.floor')[-1][field] == 1
    assert log.named('context.floor')[-1]['msg_after'] == cf.est_total(shown, None)
    assert cf.est_total(shown, None) <= 1499


@pytest.mark.parametrize('padding', range(4))
def test_schema_fraction_and_complete_notes_share_one_request_budget(padding):
    body = disclosure_body()
    body['tools'] = [{'type': 'function', 'function': {'name': 'shell', 'description': 'Execute safely.' + ' ' * padding,
        'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}]
    log = Log('schema-fraction')
    packed = Upstream('http://offline.invalid', context_window=1600)._prep(
        body, False, log, safety_override=1)[0]
    wire = json.loads(packed)
    assert wire['tools'] == body['tools']
    assert cf.est_total(wire['messages'], wire['tools']) <= 1599
    assert not log.named('context.floor')[-1]['over_budget']
