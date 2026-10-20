"""Final-wire regressions for the run-1792385395 repeated-prefill incident."""
import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from cria import assistruntime, bodykeys, contextfloor, focustrim, modelview, tokenratio, upstream
from cria.upstream import Upstream


class Log:
    phase = 'coder-s1'

    def __init__(self, session='prefix-session'):
        self.session = session
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def named(self, kind):
        return [fields for name, fields in self.events if name == kind]


def request():
    persona = 'Standing caller instructions.\n' * 100
    return {'model': 'offline', bodykeys.OUTPUT_RESERVE: 500,
            'messages': [{'role': 'system', 'content': 'Coder rules.\n' + persona,
                          bodykeys.CALLER_SPAN: {'start': len('Coder rules.\n'), 'text': persona}},
                         {'role': 'user', 'content': 'Repair the importer and verify it.'}],
            'tools': [{'type': 'function', 'function': {'name': 'shell',
                'description': 'Execute a shell command.', 'parameters': {'type': 'object',
                'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}}]}


def append_turn(body, n):
    body['messages'] += [
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'call-{n}',
            'type': 'function', 'function': {'name': 'shell',
            'arguments': json.dumps({'cmd': f'check item {n}'})}}]},
        {'role': 'tool', 'tool_call_id': f'call-{n}',
         'content': (f'Observation {n} has distinct factual output for this invocation. ' * 18)}]


def projected(wire):
    # A deterministic append-friendly prompt renderer; excludes the generation suffix.
    return (json.dumps(wire.get('tools')) + '\n' + '\n'.join(
        json.dumps(m, sort_keys=True) for m in wire['messages'])).encode()


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
@pytest.mark.parametrize('live_notes', [False, True])
def test_long_session_keeps_exact_prefix_between_infrequent_reductions(profile, live_notes):
    runtime = assistruntime.AssistRuntime.select(level=5, profile=profile)
    up, body, log = Upstream('http://offline.invalid', context_window=6500), request(), Log()
    previous = None
    reductions = []
    previous_notes = None
    with assistruntime.bound(runtime):
        for n in range(90):
            append_turn(body, n)
            framed = copy.deepcopy(body)
            if live_notes:
                framed['messages'].append({'role': 'user', 'content': f'⟦ctx:facts⟧ Fresh observation {n}.'})
            original = copy.deepcopy(framed)
            log.events.clear()
            data, _, _ = up._prep(framed, False, log, safety_override=1)
            wire = json.loads(data)
            assert framed == original
            assert contextfloor.est_total(wire['messages'], wire['tools']) < 6500
            assert wire['messages'][-2 if live_notes else -1]['tool_call_id'] == f'call-{n}'
            assert any(m.get('content') == body['messages'][1]['content'] for m in wire['messages'])
            assert not any(k in data.decode() for k in bodykeys.ALL)
            reduced = any(e['msg_after'] < e['msg_before'] for e in log.named('context.floor'))
            if reduced:
                reductions.append(n)
            current = projected(wire)
            notes = [m['content'] for m in wire['messages']
                     if '⟦ctx:compacted⟧' in str(m.get('content'))]
            assert len(notes) <= 1  # new fits use original evidence, never stacked stand-ins
            if previous is not None and not reduced:
                assert current.startswith(previous), (n, len(os.path.commonprefix([previous, current])))
                assert notes == previous_notes
            # Fresh appended facts can change at the live tail. Everything before
            # newly appended history must keep the identical model-visible prefix.
            stable = projected({**wire, 'messages': wire['messages'][:-1]}) if live_notes else current
            previous, previous_notes = stable, notes
    assert 2 <= len(reductions) <= 22, reductions
    assert min(b - a for a, b in zip(reductions, reductions[1:])) >= 2, reductions


def test_reduced_caller_span_does_not_toggle_back_when_next_raw_request_fits():
    up, body, log = Upstream('http://offline.invalid', context_window=6500), request(), Log()
    for n in range(24):
        append_turn(body, n)
    first, _, _ = up._prep(body, False, log, safety_override=1)
    assert '⟦ctx:reduced⟧' in json.loads(first)['messages'][0]['content']
    # A refreshed tail (facts/restoration) can shrink while the same system span persists.
    body['messages'] = body['messages'][:2] + body['messages'][-10:]
    second, _, _ = up._prep(body, False, log, safety_override=1)
    assert json.loads(first)['messages'][0] == json.loads(second)['messages'][0]


def test_prefix_event_measures_utf8_and_identifies_changed_live_facts():
    up, body, log = Upstream('http://offline.invalid', context_window=6500), request(), Log()
    body['messages'] += [{'role': 'user', 'content': '⟦ctx:facts⟧ café: old'}]
    first, _, _ = up._prep(body, False, log, safety_override=1)
    body['messages'][-1]['content'] = '⟦ctx:facts⟧ café: new'
    second, _, _ = up._prep(body, False, log, safety_override=1)
    events = log.named('context.prefix')
    assert len(events) == 2
    before, after = projected(json.loads(first)), projected(json.loads(second))
    assert events[-1]['shared_bytes'] == len(os.path.commonprefix([before, after]))
    assert events[-1]['basis'] == 'messages-and-tools'
    assert events[-1]['reason'] == 'input_changed'
    assert events[-1]['changed_message'] == 2
    assert events[-1]['marker'] == '⟦ctx:facts⟧'
    assert events[-1]['reshape'] is None


def test_session_state_never_crosses_sessions_or_changed_system_input():
    up, body = Upstream('http://offline.invalid', context_window=6500), request()
    for n in range(24):
        append_turn(body, n)
    up._prep(body, False, Log('one'), safety_override=1)
    fresh = request()
    data, _, _ = up._prep(fresh, False, Log('two'), safety_override=1)
    assert json.loads(data)['messages'][0]['content'] == fresh['messages'][0]['content']
    fresh['messages'][0]['content'] = 'Changed system constraints; preserve them exactly.'
    data, _, _ = up._prep(fresh, False, Log('one'), safety_override=1)
    assert json.loads(data)['messages'][0]['content'] == fresh['messages'][0]['content']


def test_changed_history_invalidates_cached_removals_and_their_note():
    up, body, log = Upstream('http://offline.invalid', context_window=6500), request(), Log()
    for n in range(26):
        append_turn(body, n)
    data, _, _ = up._prep(body, False, log, safety_override=1)
    assert any('⟦ctx:compacted⟧' in str(m.get('content')) for m in json.loads(data)['messages'])
    # A fork corrects early evidence and removes most history. Its corrected source
    # fits and must be delivered, with no cached summary of the superseded source.
    body['messages'] = body['messages'][:4]
    body['messages'][3]['content'] = 'Corrected factual evidence: café.'
    data, _, _ = up._prep(body, False, log, safety_override=1)
    shown = json.loads(data)['messages']
    assert shown[-1]['content'] == 'Corrected factual evidence: café.'
    assert not any('⟦ctx:compacted⟧' in str(m.get('content')) for m in shown)
    assert log.named('context.prefix')[-1]['reason'] == 'reduction_source_changed'


def test_new_task_and_auxiliary_role_cannot_inherit_a_coder_reduction():
    up, body, log = Upstream('http://offline.invalid', context_window=6500), request(), Log()
    for n in range(26):
        append_turn(body, n)
    up._prep(body, False, log, safety_override=1)
    fresh = request()
    fresh['messages'][1]['content'] = 'An independent new task.'
    data, _, _ = up._prep(fresh, False, log, safety_override=1)
    assert json.loads(data)['messages'] == [
        {k: v for k, v in m.items() if k != bodykeys.CALLER_SPAN} for m in fresh['messages']]
    log.phase = 'satisfaction'
    fresh = request()
    data, _, _ = up._prep(fresh, False, log, safety_override=1)
    assert '⟦ctx:reduced⟧' not in json.loads(data)['messages'][0]['content']
    assert log.named('context.prefix')[-1]['previous_bytes'] is not None
    assert log.named('context.prefix')[-1]['previous_phase'] == 'coder-s1'
    assert log.named('context.prefix')[-1]['reason'] == 'phase_changed'


def test_rendered_metric_counts_utf8_and_only_the_successful_measured_refit(monkeypatch):
    up, body, log = Upstream('http://offline.invalid', context_window=6500), request(), Log()
    up._props = {'chat_template': 'fake template; no native execution'}
    for n in range(26):
        append_turn(body, n)
    rendered = []

    def render(out):
        text = 'café\n' + projected(out).decode()
        rendered.append(text)
        return text

    # The first measured candidate overflows. Exactly its successful tighter
    # replacement must become the previous request; the trial never does.
    counts = iter([7000, 5000, 5000])
    monkeypatch.setattr(up, '_render_prompt', render)
    monkeypatch.setattr(up, '_tokenize_prompt', lambda text, rlog: next(counts))
    up._prep(body, False, log, safety_override=1)
    assert len(rendered) == 2
    assert len(log.named('context.prefix')) == 1
    append_turn(body, 26)
    up._prep(body, False, log, safety_override=1)
    event = log.named('context.prefix')[-1]
    assert event['basis'] == 'rendered-prompt'
    assert event['shared_bytes'] == len(os.path.commonprefix([
        rendered[1].encode(), rendered[2].encode()]))
    assert event['previous_bytes'] == len(rendered[1].encode())


@pytest.mark.parametrize('level', [0, 1, 2])
def test_lower_levels_do_not_remember_or_apply_floor_edits(level):
    up, body, log = Upstream('http://offline.invalid', context_window=6500,
                            engagement_level=level), request(), Log()
    for n in range(26):
        append_turn(body, n)
    for _ in range(2):
        data, _, _ = up._prep(body, False, log)
        assert json.loads(data)['messages'][0]['content'] == body['messages'][0]['content']
        assert not log.named('context.floor')


def test_headroom_does_not_reduce_fitting_input_or_sacrifice_anchors_for_space():
    base = [{'role': 'system', 'content': 'Rules'}, {'role': 'user', 'content': 'Task'}]
    fitted, _, report = contextfloor.fit(base, None, window=3000, reserve=500,
                                         safety=1, headroom=True)
    assert fitted == base and not report.applied
    # Inside an active span, headroom must yield when the only remaining victim
    # is a protected fact. A hard-budget fit does not justify its removal.
    messages = base + [{'role': 'assistant', 'content': '⟦ctx:facts⟧ important fact ' * 30}]
    messages += [{'role': 'assistant', 'content': f'Live tail {n}'} for n in range(8)]
    kept, dropped = contextfloor._drop_protected_overflow(messages, 50, sacrifice_budget=1000)
    assert kept == messages and dropped == 0


def test_optional_wire_folds_are_not_remembered_as_floor_removals():
    up, log = Upstream('http://offline.invalid', context_window=6500), Log()
    body = {'model': 'offline', 'messages': [{'role': 'user', 'content': 'Root task'},
            {'role': 'user', 'content': 'Repeated ground truth. ' * 80},
            {'role': 'user', 'content': 'Repeated ground truth. ' * 80}]}
    runtime = assistruntime.AssistRuntime.select(level=5)
    with assistruntime.bound(runtime):
        first, _, _ = up._prep(body, False, log, safety_override=1)
    assert json.loads(first)['messages'] != body['messages']
    assert not log.named('context.floor')
    # The same selected binding can be replaced in an exact runtime scope. Its
    # no-op must see original evidence, never a retained optional pointer.
    identity = replace(modelview.REPEATED_PAYLOADS, execute=lambda messages: messages)
    scoped = replace(runtime, ordered_stages=tuple(
        identity if d.policy.id == identity.policy.id else d for d in runtime.ordered_stages))
    with assistruntime.bound(scoped):
        second, _, _ = up._prep(body, False, log, safety_override=1)
    assert json.loads(second)['messages'] == body['messages']
    assert all(e['reason'] != 'history_reduced' for e in log.named('context.prefix'))


def test_lost_typed_provenance_invalidates_reuse_even_when_json_is_identical():
    notice = focustrim.SupersededWriteNotice('Historical notice', 1, ('notes.txt',), ())
    source = [{'role': 'user', 'content': 'Historical notice', bodykeys.SUPERSEDED_WRITES: notice},
              {'role': 'user', 'content': 'Active request'}]
    fitted = [{'role': 'user', 'content': '⟦ctx:compacted⟧ Historical stand-in'}, source[1]]
    state = contextfloor.FitState()
    state.remember(source, None, fitted, None)
    untyped = json.loads(json.dumps(source))
    restored, _, invalidated = state.reuse(untyped, None)
    assert invalidated
    assert restored == untyped


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
@pytest.mark.parametrize('end', [46, 48])
def test_unchanged_prefix_rewind_preserves_current_request_and_live_tail(profile, end):
    body = {'model': 'offline', bodykeys.OUTPUT_RESERVE: 500, 'messages': [
        {'role': 'system', 'content': 'Rules'}, {'role': 'user', 'content': 'Root task'}]}
    for n in range(30):
        body['messages'] += [
            {'role': 'assistant', 'content': f'Working {n}. ' + 'Evidence detail. ' * 40},
            {'role': 'user', 'content': f'Request {n}: ' + 'Please check carefully. ' * 10}]
    log = Log('rewind')
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        up = Upstream('http://offline.invalid', context_window=4000)
        up._prep(body, False, log, safety_override=1)
        fork = {**body, 'messages': copy.deepcopy(body['messages'][:end])}
        original = copy.deepcopy(fork)
        fresh = json.loads(Upstream('http://offline.invalid', context_window=4000)
                           ._prep(fork, False, Log('fresh'), safety_override=1)[0])
        reused = json.loads(up._prep(fork, False, log, safety_override=1)[0])
    assert fork == original
    assert fork['messages'][-1] in fresh['messages']  # fresh fit is the passing control
    assert all(m in fresh['messages'] for m in fork['messages'][-8:])
    assert fork['messages'][-1] in reused['messages']
    assert all(m in reused['messages'] for m in fork['messages'][-8:])
    assert log.named('context.prefix')[-1]['reduction_source_changed']
    assert not log.named('context.floor')[-1]['over_budget']


def test_tail_source_becoming_current_request_also_invalidates_retained_deletion():
    messages = [{'role': 'system', 'content': 'Rules'}, {'role': 'user', 'content': 'Root task'}]
    messages += [{'role': 'assistant', 'content': f'⟦ctx:facts⟧ Recorded observation {n}.'}
                 for n in range(60)]
    messages[55] = {'role': 'user', 'content': 'Earlier request: ' + 'Please check carefully. ' * 70}
    messages[61] = {'role': 'user', 'content': 'Latest request'}
    # The rewind fits as-is; the original needs to reduce the one unprotected
    # historical request. That request was already in the old tail, so merely
    # tracking a single live/historical bit misses its new request protection.
    window = (contextfloor._msgs_tokens(messages) + contextfloor._msgs_tokens(messages[:56])) // 2 + 1
    body = {'model': 'offline', bodykeys.OUTPUT_RESERVE: 1, 'messages': messages}
    up, log = Upstream('http://offline.invalid', context_window=window), Log('tail-request')
    up._prep(body, False, log, safety_override=1)
    fork = {**body, 'messages': copy.deepcopy(messages[:56])}
    fresh = json.loads(Upstream('http://offline.invalid', context_window=window)
                       ._prep(fork, False, Log('control'), safety_override=1)[0])
    reused = json.loads(up._prep(fork, False, log, safety_override=1)[0])
    assert fork['messages'][-1] in fresh['messages']
    assert fork['messages'][-1] in reused['messages']
    assert log.named('context.prefix')[-1]['reduction_source_changed']


def test_late_result_restores_its_previously_unpaired_live_tail_call():
    body, log = request(), Log('late-result')
    for n in range(26):
        append_turn(body, n)
    body['messages'].append({'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'pending', 'type': 'function', 'function': {'name': 'shell', 'arguments': '{"cmd":"check"}'}}]})
    up = Upstream('http://offline.invalid', context_window=6500)
    first = json.loads(up._prep(body, False, log, safety_override=1)[0])
    assert not any(tc['id'] == 'pending' for m in first['messages'] for tc in m.get('tool_calls', []))
    body['messages'].append({'role': 'tool', 'tool_call_id': 'pending', 'content': 'The late result.'})
    fresh = json.loads(Upstream('http://offline.invalid', context_window=6500)
                       ._prep(body, False, Log('fresh'), safety_override=1)[0])
    reused = json.loads(up._prep(body, False, log, safety_override=1)[0])
    for shown in [fresh, reused]:
        assert any(tc['id'] == 'pending' for m in shown['messages'] for tc in m.get('tool_calls', []))
        assert any(m.get('role') == 'tool' and m.get('tool_call_id') == 'pending' for m in shown['messages'])
    assert log.named('context.prefix')[-1]['reduction_source_changed']


def hard_fit_body():
    # Review's minimized case: only sacrificing a marked historical anchor can
    # reach the hard window, but even sacrificing all candidates cannot buy headroom.
    spec = [
        ('assistant', 'facts', 0, 9), ('assistant', 'facts', 2, 17),
        ('user', 'facts', 3, 8), ('user', '', 4, 18),
        ('assistant', '', 5, 20), ('user', 'facts', 6, 16),
        ('assistant', 'rollup', 7, 18), ('assistant', 'facts', 9, 18),
        ('assistant', 'facts', 10, 7), ('assistant', '', 11, 21),
        ('assistant', '', 12, 17), ('assistant', 'facts', 14, 17),
        ('assistant', 'facts', 15, 1), ('assistant', '', 16, 12),
        ('assistant', 'rollup', 17, 1), ('assistant', '', 18, 2),
        ('assistant', 'rollup', 19, 8), ('assistant', '', 20, 11),
        ('assistant', 'rollup', 21, 21)]
    messages = [{'role': 'system', 'content': 'Rules'}, {'role': 'user', 'content': 'Task'}]
    for role, marker, n, count in spec:
        messages.append({'role': role, 'content': (f'⟦ctx:{marker}⟧ ' if marker else '')
                         + f'Turn {n}: ' + 'Observation of this invocation. ' * count})
    return {'model': 'offline', bodykeys.OUTPUT_RESERVE: 1, 'messages': messages}


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
def test_unattainable_headroom_does_not_defeat_a_feasible_final_wire_fit(profile):
    body, log = hard_fit_body(), Log('headroom')
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        control = json.loads(Upstream('http://offline.invalid', context_window=1926)
                             ._prep(body, False, Log(None), safety_override=1)[0])
        wire = json.loads(Upstream('http://offline.invalid', context_window=1926)
                          ._prep(body, False, log, safety_override=1)[0])
    assert contextfloor.est_total(control['messages'], None) <= 1925
    assert contextfloor.est_total(wire['messages'], None) <= 1925
    assert not log.named('context.floor')[-1]['over_budget']
    assert body['messages'][-1]['content'] in wire['messages'][-1]['content']
    assert any('⟦ctx:compacted⟧' in str(m.get('content')) for m in wire['messages'])


def test_unattainable_headroom_still_fits_at_the_floor_boundary():
    body = hard_fit_body()
    control, _, control_report = contextfloor.fit(body['messages'], None,
        window=1926, reserve=1, safety=1, headroom=False)
    fitted, _, report = contextfloor.fit(body['messages'], None,
        window=1926, reserve=1, safety=1, headroom=True)
    assert not control_report.over_budget
    assert contextfloor.est_total(control, None) <= 1925
    assert not report.over_budget
    assert contextfloor.est_total(fitted, None) <= 1925


def test_concurrent_sessions_keep_separate_reductions_and_prefix_observations():
    up = Upstream('http://offline.invalid', context_window=6500)
    barrier = Barrier(24)

    def worker(index):
        body, log = request(), Log(f'concurrent-{index}')
        body['messages'][1]['content'] = f'Repair independent workspace {index}.'
        for n in range(26):
            append_turn(body, n)
        with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
            first = json.loads(up._prep(body, False, log, safety_override=1)[0])
            assert log.named('context.prefix')[-1]['previous_bytes'] is None
            assert '⟦ctx:reduced⟧' in first['messages'][0]['content']
            barrier.wait(timeout=15)
            append_turn(body, 26)
            second = json.loads(up._prep(body, False, log, safety_override=1)[0])
        assert body['messages'][1] in second['messages']
        assert second['messages'][0] == first['messages'][0]
        event = log.named('context.prefix')[-1]
        assert event['previous_bytes'] == len(projected(first))
        assert event['shared_bytes'] == len(os.path.commonprefix([projected(first), projected(second)]))
        return index

    with ThreadPoolExecutor(max_workers=24) as pool:
        assert list(pool.map(worker, range(24))) == list(range(24))


def test_evicted_session_reentry_has_no_old_reduction_or_prefix_observation(monkeypatch):
    monkeypatch.setattr(upstream, '_MAX_PREFIX_SESSIONS', 2)
    up, body = Upstream('http://offline.invalid', context_window=6500), request()
    for n in range(26):
        append_turn(body, n)
    first = json.loads(up._prep(body, False, Log('evicted'), safety_override=1)[0])
    assert '⟦ctx:reduced⟧' in first['messages'][0]['content']
    for session in ['second', 'third']:
        up._prep(request(), False, Log(session), safety_override=1)
    fresh, log = request(), Log('evicted')
    shown = json.loads(up._prep(fresh, False, log, safety_override=1)[0])
    assert shown['messages'][0]['content'] == fresh['messages'][0]['content']
    assert log.named('context.prefix')[-1]['previous_bytes'] is None
    assert not log.named('context.floor')


@pytest.mark.parametrize('case', ['repeat-pointer', 'captured-pointer', 'evidence-pointer'])
def test_fixed_window_pointer_oracles_hold_after_another_request_teaches_high_density(case, monkeypatch):
    # Full-suite order: the no-change refit tests teach model "m" a density near
    # four. Small-window pointer oracles specify their own cost model; they must
    # neither inherit that assumption nor reset legitimate model observations.
    # Keep any ambient value; undo only this test's own observations at teardown,
    # after both producer and consumer have used the same live learned entry.
    monkeypatch.setitem(tokenratio._ratios, 'm', tokenratio.observed('m'))
    observer = Upstream('http://offline.invalid', context_window=49152)
    for _ in range(4):
        observer._calibrate('m', {'prompt_tokens': 4000, 'completion_tokens': 1}, 1000, Log('density-source'))
    learned = tokenratio.observed('m')
    assert learned > 3.9
    if case == 'repeat-pointer':
        from test_a_repeat_pointer_never_outlives_its_target import (
            test_the_old_order_dangles_somewhere_and_the_wire_never_does as check)
    elif case == 'captured-pointer':
        from test_c13b_the_wire_claims_are_true import (
            test_every_line_a_pointer_replaced_is_shown_in_the_body_sent as check)
    else:
        from test_a_pointer_never_outlives_its_target import (
            test_the_window_of_the_reproduction_carries_the_diagnostic_in_full as check)
    check()
    assert tokenratio.observed('m') == learned


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
def test_same_session_id_on_another_upstream_has_no_retained_edits_or_previous_prefix(profile):
    first = Upstream('http://offline.invalid', context_window=6500)
    second = Upstream('http://offline.invalid', context_window=131072)
    body = request()
    for n in range(26):
        append_turn(body, n)
    log = Log('reused-id')
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        reduced = json.loads(first._prep(body, False, log, safety_override=1)[0])
        assert any('⟦ctx:compacted⟧' in str(m.get('content')) for m in reduced['messages'])
        fresh_log = Log('reused-id')
        fresh = json.loads(second._prep(body, False, fresh_log, safety_override=1)[0])
        assert fresh['messages'][0]['content'] == body['messages'][0]['content']
        assert [m['content'] for m in fresh['messages'] if m['role'] == 'tool'] == [
            m['content'] for m in body['messages'] if m['role'] == 'tool']
        assert not any('⟦ctx:compacted⟧' in str(m.get('content')) for m in fresh['messages'])
        assert fresh_log.named('context.prefix')[-1]['previous_bytes'] is None
        assert not fresh_log.named('context.floor')
        again = json.loads(first._prep(body, False, log, safety_override=1)[0])
        assert again == reduced
        assert log.named('context.prefix')[-1]['previous_bytes'] == len(projected(reduced))
        assert log.named('context.prefix')[-1]['reason'] == 'identical'


@pytest.mark.parametrize('profile', ['default', 'rank4-ablation'])
def test_no_session_request_cannot_reuse_a_named_sessions_caller_replacement(profile):
    up, body, named = Upstream('http://offline.invalid', context_window=6500), request(), Log('named')
    for n in range(26):
        append_turn(body, n)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        reduced = json.loads(up._prep(body, False, named, safety_override=1)[0])
        assert '⟦ctx:reduced⟧' in reduced['messages'][0]['content']
        fresh, anonymous = request(), Log(None)
        shown = json.loads(up._prep(fresh, False, anonymous, safety_override=1)[0])
        assert shown['messages'][0]['content'] == fresh['messages'][0]['content']
        assert shown['messages'][-1] == fresh['messages'][-1]
        assert not anonymous.named('context.floor')
        assert not anonymous.named('context.prefix')
        assert tuple(up._prefix_sessions) == ('named',)
