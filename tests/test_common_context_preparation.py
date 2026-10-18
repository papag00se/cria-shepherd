"""Raw authority and outgoing presence are different horizons in both coder drivers."""
from types import SimpleNamespace
from unittest.mock import Mock
from dataclasses import replace
import io
import json
import copy

import pytest
from cria import assistruntime, bodykeys, config, contextfloor, focustrim, loop, selfcompact, wsview
from cria.memoryeffects import Effect
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


def test_raw_authority_survives_empty_outgoing_history_without_mutating_visibility(monkeypatch):
    raw = [{'role': 'tool', 'tool_call_id': 'f',
            'content': 'HTTP 200 · https://example.test/docs'}]
    sess = SimpleNamespace(read_files={'notes.txt': (7, '2 lines')}, read_ledger_seen=set(),
                           fetched_pages={}, workspace_root='', written_files={}, file_touch={})
    monkeypatch.setattr(loop, '_route_mismatch_fact', lambda fetches, messages, root: 'Observed HTTP mismatch')
    facts = loop._capture_context_facts(sess, raw)
    visible = {'https://example.test/docs'}
    anchor = loop._render_context_facts(facts, visible_messages=[], visible_fetch_urls=visible,
                                        restored_offered={}, workspace=None)
    assert 'notes.txt' in anchor['content']
    assert '2 lines' in anchor['content']
    assert 'https://example.test/docs' in anchor['content']
    assert 'Observed HTTP mismatch' in anchor['content']
    assert visible == {'https://example.test/docs'}
    assert sess.fetched_pages == {}
    # Capturing does not retain the mutable ledger as its authority.
    sess.read_files.clear()
    assert facts.ledger == (('notes.txt', (7, '2 lines')),)


def test_fact_renderer_uses_only_outgoing_read_presence_and_restoration(monkeypatch):
    raw = [{'role': 'tool', 'tool_call_id': 'f', 'content': 'real read'}]
    sess = SimpleNamespace(read_files={'notes.txt': (7, '2 lines')}, read_ledger_seen=set(),
                           fetched_pages={}, workspace_root='', written_files={}, file_touch={})
    monkeypatch.setattr(loop, '_file_events', lambda messages, key: [('call', 'read-id', 'read', 'notes.txt', 7, '2 lines')] if messages else [])
    monkeypatch.setattr(loop, '_apply_ledger_event', lambda *args: None)
    facts = loop._capture_context_facts(sess, raw)
    absent = loop._render_context_facts(facts, visible_messages=[], visible_fetch_urls=set(),
                                        restored_offered={}, workspace=None)['content']
    restored = loop._render_context_facts(facts, visible_messages=[], visible_fetch_urls=set(),
                                          restored_offered={'notes.txt': 'sha'}, workspace=None)['content']
    assert absent != restored
    assert 'notes.txt' in absent and 'notes.txt' in restored


@pytest.mark.parametrize('synthetic', [False, True])
def test_selected_focus_removes_whole_read_then_restoration_uses_raw_authority(tmp_path, monkeypatch, synthetic):
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    sess.workspace_root = str(tmp_path)
    monkeypatch.chdir(tmp_path)  # DirectView uses real process-relative paths.
    fresh = 'Exact current bytes after the read.\n'
    (tmp_path / 'notes.txt').write_text(fresh)
    body['messages'] += [
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'old-read', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"notes.txt"}'}}]},
        {'role': 'tool', 'tool_call_id': 'old-read', 'content': fresh}]
    view = wsview.DirectView(str(tmp_path))
    assert loop._extract_whole_reads(body['messages'], view) == {'notes.txt'}
    seen = []
    def focus(messages):
        seen.append(messages)
        return ([m for m in messages if m.get('tool_call_id') != 'old-read'
                 and not any(tc.get('id') == 'old-read' for tc in m.get('tool_calls') or [])],
                focustrim.TrimReport(dropped_calls=1, dropped_msgs=2))
    definition = replace(focustrim.DUPLICATES, execute=focus)
    runtime = assistruntime.AssistRuntime.select(level=5)
    driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(
        definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
    driver._ctx.focus_trim = True
    offered = []
    def coder(session, framed, raw, **kwargs):
        offered.append(framed)
        return loop._completion_toolcalls([{'id': 'next', 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])
    monkeypatch.setattr(driver, '_coder_turn', coder)
    token = wsview.bind(view)
    try:
        driver.drive(body, 'driver-fixture', None, _Rlog())
    finally:
        wsview.unbind(token)
    assert len(seen) == 1
    restored = [m for m in offered[0]['messages'] if m.get(bodykeys.RESTORED_FILES)]
    assert len(restored) == 1
    assert fresh in restored[0]['content']
    assert not any(m.get('tool_call_id') == 'old-read' for m in offered[0]['messages'])
    anchor = next(m for m in offered[0]['messages'] if str(m.get('content')).startswith('⟦ctx:facts⟧'))
    assert 'notes.txt' in anchor['content']
    assert offered[0]['messages'].index(restored[0]) < offered[0]['messages'].index(anchor)


def test_fact_renderer_retains_count_object_identity(monkeypatch):
    count = loop._Counted('2 lines')
    sess = SimpleNamespace(read_files={'notes.txt': [7, count]}, read_ledger_seen=set(),
                           fetched_pages={}, workspace_root='', written_files={}, file_touch={})
    facts = loop._capture_context_facts(sess, [])
    assert facts.ledger[0][1][1] is count
    sess.read_files['notes.txt'][0] = 999
    assert facts.ledger[0][1][0] == 7
    probe = Mock(return_value='measured count')
    monkeypatch.setattr(loop, '_dated_count', probe)
    loop._render_context_facts(facts, visible_messages=[], visible_fetch_urls=set(),
                               restored_offered={}, workspace=None)
    assert probe.call_args.args[3] is count


@pytest.mark.parametrize('synthetic', [False, True])
def test_raw_fetch_and_file_authority_survive_both_reducers_with_current_notes_outside(tmp_path, monkeypatch, synthetic):
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    sess.workspace_root = str(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'notes.txt').write_text('fresh exact bytes\n')
    sess.read_files = {'notes.txt': (17, '1 lines')}
    sess.nudge_reason = 'CURRENT NUDGE outside history'
    # The raw-task driver derives a guard steer through its own authority; the
    # shared entry receives the same live-note contract without inventing a cursor.
    events = []
    body['messages'] += [{'role': 'assistant', 'tool_calls': [{'id': 'fetch', 'type': 'function',
        'function': {'name': 'web_fetch', 'arguments': '{"url":"https://example.test/docs"}'}}]},
        {'role': 'tool', 'tool_call_id': 'fetch', 'content': 'HTTP 200 · https://example.test/docs'}]
    def rolling(source, state):
        events.append(('rolling', source.messages, source.force))
        return selfcompact.RollingResult([{'role': 'user', 'content': 'historical rollup'}],
                                        state, Effect.REDUCED)
    def focus(messages):
        events.append(('focus', messages, None))
        return [m for m in messages if m.get('content') != 'historical rollup'], focustrim.TrimReport(dropped_msgs=1)
    replacements = {selfcompact.DEFINITION.policy.id: replace(selfcompact.DEFINITION, execute=rolling),
                    focustrim.DUPLICATES.policy.id: replace(focustrim.DUPLICATES, execute=focus)}
    runtime = assistruntime.AssistRuntime.select(level=5)
    driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(replacements.get(d.policy.id, d)
                                                                  for d in runtime.ordered_stages))
    driver._ctx.self_compact = driver._ctx.focus_trim = True
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        with assistruntime.bound(driver._ctx.pilot_runtime):
            framed, _ = driver._prepare_coder_context(sess, body, _Rlog(), synthetic=synthetic,
                index=None if synthetic else 1, total=None if synthetic else 1,
                notes=[{'role': 'user', 'content': 'CURRENT NUDGE outside history'}])
    finally:
        wsview.unbind(token)
    assert [event[0] for event in events] == ['rolling', 'focus']
    assert all('CURRENT NUDGE' not in json.dumps(event[1]) for event in events)
    text = json.dumps(framed['messages'])
    assert 'https://example.test/docs' in text and 'notes.txt' in text
    assert 'fresh exact bytes' in text
    assert framed['messages'][-1]['content'] == 'CURRENT NUDGE outside history'
    assert framed['messages'][1]['content'] == body['messages'][0]['content']


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('removed', [False, True])
def test_actual_driver_floor_delivery_earns_only_surviving_restoration_credit(tmp_path, monkeypatch, synthetic, removed):
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    sess.workspace_root = str(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'notes.txt').write_text('fresh exact bytes\n')
    sess.read_files = {'notes.txt': (17, '1 lines')}
    up = driver._ctx.coder_chat.__self__
    posts = []
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])).encode())
    monkeypatch.setattr(up, '_receive_open', transport)
    original_fit = contextfloor.fit
    def fit(messages, tools, **budget):
        if removed:
            return [m for m in messages if not m.get(bodykeys.RESTORED_FILES)], tools, contextfloor.FloorReport(applied=True)
        return original_fit(messages, tools, **budget)
    monkeypatch.setattr(contextfloor, 'fit', fit)
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        driver.drive(body, 'driver-fixture', None, _Rlog())
    finally:
        wsview.unbind(token)
    assert len(posts) == 1
    assert ('fresh exact bytes' in json.dumps(posts[0])) is (not removed)
    assert set(sess.restored_current) == (set() if removed else {'notes.txt'})


@pytest.mark.parametrize('synthetic', [False, True])
def test_canonical_focus_precedes_native_role_collapse_at_real_post(monkeypatch, synthetic):
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    driver._ctx.focus_trim = True
    calls, posts, order = [], [], []
    class ObservedRole(config.Role):
        def apply(self, frame, **kwargs):
            order.append('role')
            return super().apply(frame, **kwargs)
    driver._ctx.coder_role = ObservedRole(name='coder', backend='local', collapse_system_prompt=True,
                                        merge_consecutive_turns=True)
    def focus(messages):
        calls.append(messages)
        order.append('focus')
        # The protected header/root partition is not historical reduction input.
        assert not any(m.get('role') == 'system' for m in messages)
        return messages, focustrim.TrimReport()
    replacement = replace(focustrim.DUPLICATES, execute=focus)
    runtime = assistruntime.AssistRuntime.select(level=5)
    driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(
        replacement if d.policy.id == replacement.policy.id else d for d in runtime.ordered_stages))
    up = driver._ctx.coder_chat.__self__
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])).encode())
    monkeypatch.setattr(up, '_receive_open', transport)
    driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(calls) == len(posts) == 1
    assert order == ['focus', 'role']
    assert posts[0]['messages'][0]['role'] == 'user'
    assert body['messages'][0]['content'] in posts[0]['messages'][0]['content']


def test_real_step_boundary_compaction_keeps_fresh_restoration_verbatim(tmp_path, monkeypatch):
    from test_loop import _SHELL
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = False
    sess.compact_pending = True
    sess.workspace_root = str(tmp_path)
    driver._ctx.planner_enabled = driver._ctx.self_compact = True
    body['tools'].append(_SHELL)
    monkeypatch.chdir(tmp_path)
    fresh = 'Fresh exact bytes: alpha / beta\nsecond line, not a rollup\n'
    (tmp_path / 'notes.txt').write_text(fresh)
    sess.read_files = {'notes.txt': (len(fresh.encode()), '2 lines')}
    body['messages'] += [{'role': 'assistant', 'content': 'old work evidence\n' * 2000},
                         {'role': 'user', 'content': 'Continue with the current working files.'}]
    calls, offered = [], []
    def rolling(source, state):
        calls.append(source)
        assert source.force is True
        assert source.pinned_task == ''  # required authority remains outside historical reduction
        assert fresh not in json.dumps(source.messages)
        result = selfcompact.DEFINITION.execute(source, state)
        assert result.applied
        return result
    monkeypatch.setattr(loop, 'summarize', lambda *args, **kwargs: 'Old work was summarized.')
    monkeypatch.setattr(loop, 'validate_compaction_briefing', lambda *args, **kwargs: True)
    definition = replace(selfcompact.DEFINITION, execute=rolling)
    runtime = assistruntime.AssistRuntime.select(level=5)
    driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(
        definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
    def coder(session, framed, raw, **kwargs):
        offered.append(framed)
        return loop._completion_toolcalls([{'id': 'next', 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])
    monkeypatch.setattr(driver, '_coder_turn', coder)
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        driver.drive(body, 'driver-fixture', None, _Rlog())
    finally:
        wsview.unbind(token)
    assert len(calls) == len(offered) == 1
    restored = next(m for m in offered[0]['messages'] if m.get(bodykeys.RESTORED_FILES))
    assert fresh in restored['content']
    assert not sess.compact_pending


@pytest.mark.parametrize('synthetic', [False, True])
def test_absent_context_selection_never_runs_optional_leaf_detection(monkeypatch, synthetic):
    from cria import contextrestoration, ledgercopies, preamblepolicy, reorientation, steppreparation
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    driver._ctx.self_compact = driver._ctx.focus_trim = True
    driver._ctx.pilot_runtime = assistruntime.AssistRuntime.select(level=0,
        disabled=(preamblepolicy.DEFINITION.policy.id,))
    poison = Mock(side_effect=AssertionError('unselected detector'))
    monkeypatch.setattr(loop, 'workspace_inventory', poison)
    monkeypatch.setattr(loop, 'step_artifacts_on_disk', poison)
    # Root projection must not leak the library's None/defaults contract.
    for module, name in [(focustrim, '_collapse_duplicates'), (focustrim, '_squash_failures'),
                         (contextrestoration, 'restore'), (ledgercopies, 'elide'),
                         (preamblepolicy, 'workspace_instructions'), (reorientation, '_reason')]:
        monkeypatch.setattr(module, name, poison)
    offered = []
    def coder(session, framed, raw, **kwargs):
        offered.append(framed)
        return loop._completion_toolcalls([{'id': 'next', 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])
    monkeypatch.setattr(driver, '_coder_turn', coder)
    driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(offered) == 1
    poison.assert_not_called()
    assert offered[0]['messages'][1]['content'] == body['messages'][0]['content']
    assert not any(m.get(bodykeys.RESTORED_FILES) for m in offered[0]['messages'])


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('mode', ['empty', 'disabled'])
def test_required_root_protection_does_not_deduplicate_later_equal_user_turn(monkeypatch, synthetic, mode):
    from cria import preamblepolicy
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    body['messages'] += [{'role': 'assistant', 'content': 'earlier response'}, dict(body['messages'][0])]
    assert body['messages'][0] == body['messages'][2]
    assert body['messages'][0] is not body['messages'][2]
    driver._ctx.self_compact = driver._ctx.focus_trim = True
    driver._ctx.pilot_runtime = (assistruntime.AssistRuntime.select(level=0,
        disabled=(preamblepolicy.DEFINITION.policy.id,)) if mode == 'empty' else
        assistruntime.AssistRuntime.select(level=5, disabled=tuple(d.policy.id for d in assistruntime.CONTEXT_DEFINITIONS)))
    up = driver._ctx.coder_chat.__self__
    posts = []
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])).encode())
    monkeypatch.setattr(up, '_receive_open', transport)
    driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(posts) == 1
    assert posts[0]['messages'][1:] == body['messages']


@pytest.mark.parametrize('synthetic', [False, True])
def test_required_prefix_uses_received_origin_not_planner_task_text(monkeypatch, synthetic):
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    original = 'Caller-owned current requirements, preserved verbatim.'
    assert original != sess.plan.task
    body['messages'] = [{'role': 'user', 'content': original}]
    frames = []
    def coder(session, framed, raw, **kwargs):
        frames.append(framed)
        return loop._completion_toolcalls([{'id': 'next', 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])
    monkeypatch.setattr(driver, '_coder_turn', coder)
    driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(frames) == 1
    assert frames[0]['messages'][1] == {'role': 'user', 'content': original}
    assert not any(m.get('content') == sess.plan.task for m in frames[0]['messages'])
    # The required packet is the source-indexed input, not an inferred replacement.
    # Wire budgeting measures exactly the outgoing body.
    wire_body = {**frames[0], 'model': 'offline'}
    packed, measured, _model = driver._ctx.coder_chat.__self__._prep(wire_body, False, _Rlog())
    post = json.loads(packed)
    assert post['messages'][1]['content'] == original
    assert measured == contextfloor.est_total(post['messages'], post.get('tools'))


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('producer', ['lossless-copy', 'real-rolling'])
def test_required_prefix_survives_copy_and_canonical_rolling_once(monkeypatch, synthetic, producer):
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    body['messages'] += [{'role': 'assistant', 'content': 'obsolete draft ' * (7000 if producer == 'real-rolling' else 1)},
                         {'role': 'user', 'content': 'current historical followup'}]
    driver._ctx.self_compact = producer == 'real-rolling'
    driver._ctx.focus_trim = producer == 'lossless-copy'
    driver._ctx.trigger_compaction = 100
    called = []
    def focus(messages):
        called.append('focus')
        return copy.deepcopy([m for m in messages if not str(m.get('content')).startswith('obsolete draft ')]), focustrim.TrimReport(dropped_msgs=1)
    def rolling(source, state):
        called.append('rolling')
        return selfcompact.DEFINITION.execute(source, state)
    definition = (replace(focustrim.DUPLICATES, execute=focus) if producer == 'lossless-copy' else
                  replace(selfcompact.DEFINITION, execute=rolling))
    runtime = assistruntime.AssistRuntime.select(level=5)
    driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(
        definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
    monkeypatch.setattr(loop, 'summarize', lambda *args, **kwargs: 'Observed work was summarized.')
    monkeypatch.setattr(loop, 'validate_compaction_briefing', lambda *args, **kwargs: True)
    up = driver._ctx.coder_chat.__self__
    posts = []
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])).encode())
    monkeypatch.setattr(up, '_receive_open', transport)
    driver.drive(body, 'driver-fixture', None, _Rlog())
    assert called == ['focus' if producer == 'lossless-copy' else 'rolling']
    assert len(posts) == 1
    messages = posts[0]['messages']
    assert len([m for m in messages if m['role'] == 'system']) == 1
    task = body['messages'][0]['content']
    assert sum(task in str(m.get('content') or '') for m in messages) == 1
    assert messages[1]['content'] == task
    if producer == 'real-rolling':
        assert 'Observed work was summarized.' in json.dumps(messages)


@pytest.mark.parametrize('synthetic', [False, True])
def test_selected_replacement_system_context_survives_exactly_at_final_wire(monkeypatch, synthetic):
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    driver._ctx.focus_trim = True
    extra = 'Replacement-owned system context: exact bytes \\n [alpha] <beta>.'
    amendment = '\nReplacement amended the original header without deleting its authority.'
    body['messages'].append({'role': 'assistant', 'content': 'obsolete disposable draft'})
    def focus(messages):
        kept = [m for m in messages if m.get('content') != 'obsolete disposable draft']
        return [{'role': 'system', 'content': 'Replacement-owned supplemental header' + amendment}, *kept,
                {'role': 'system', 'content': extra}], focustrim.TrimReport(dropped_msgs=1)
    definition = replace(focustrim.DUPLICATES, execute=focus)
    runtime = assistruntime.AssistRuntime.select(level=5)
    driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(
        definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
    up = driver._ctx.coder_chat.__self__
    posts = []
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])).encode())
    monkeypatch.setattr(up, '_receive_open', transport)
    driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(posts) == 1
    messages = posts[0]['messages']
    assert any(m.get('content') == extra for m in messages)
    assert any(str(m.get('content')).endswith(amendment) for m in messages)
    assert messages[1]['content'] == body['messages'][0]['content']


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('kind', ['read', 'write'])
def test_surviving_whole_copy_prevents_duplicate_restoration(tmp_path, monkeypatch, synthetic, kind):
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    sess.workspace_root = str(tmp_path)
    monkeypatch.chdir(tmp_path)
    fresh = 'Whole current file bytes\n'
    (tmp_path / 'notes.txt').write_text(fresh)
    sess.read_files = {'notes.txt': (len(fresh.encode()), '1 lines')}
    args = {'path': 'notes.txt'}
    if kind == 'write':
        args['content'] = fresh
    body['messages'] += [{'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'whole', 'type': 'function', 'function': {'name': kind + '_file',
                                                       'arguments': json.dumps(args)}}]},
        {'role': 'tool', 'tool_call_id': 'whole',
         'content': fresh if kind == 'read' else 'Wrote notes.txt'}]
    if kind == 'write':
        assert list(loop._write_events_paths(body['messages'])) == [(2, 'whole', 'notes.txt')]
    offered = []
    def coder(session, framed, raw, **kwargs):
        offered.append(framed)
        return loop._completion_toolcalls([{'id': 'next', 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])
    monkeypatch.setattr(driver, '_coder_turn', coder)
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        driver.drive(body, 'driver-fixture', None, _Rlog())
    finally:
        wsview.unbind(token)
    assert len(offered) == 1
    assert not any(m.get(bodykeys.RESTORED_FILES) for m in offered[0]['messages'])
    assert any(m.get('tool_call_id') == 'whole' for m in offered[0]['messages'])


@pytest.mark.parametrize('synthetic', [False, True])
def test_disabled_step_framing_keeps_required_remediation_and_raw_task_nudge(monkeypatch, synthetic):
    from cria import prompts, steppreparation
    from test_loop import _SHELL
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    driver._ctx.planner_enabled = not synthetic
    body['tools'].append(_SHELL)
    sess.completion_remediation_subject = 'missing.txt'
    sess.completion_remediation_reason = sess.nudge_reason = 'Original measured missing-file evidence.'
    runtime = assistruntime.AssistRuntime.select(level=5, disabled=(steppreparation.DEFINITION.policy.id,))
    driver._ctx.pilot_runtime = runtime
    offered = []
    monkeypatch.setattr(loop, '_item_prompt', Mock(side_effect=AssertionError('legacy step fallback')))
    def coder(session, framed, raw, **kwargs):
        offered.append(framed)
        return loop._completion_toolcalls([{'id': 'next', 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])
    monkeypatch.setattr(driver, '_coder_turn', coder)
    driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(offered) == 1
    messages = offered[0]['messages']
    assert offered[0][bodykeys.COMPLETION_REMEDIATION] == 'missing.txt'
    assert messages[1]['content'] == body['messages'][0]['content']
    assert messages[-1]['content'] == prompts.render('nudge', reason='Original measured missing-file evidence.')
    assert (prompts.load('completion_remediation') in messages[0]['content']) is (not synthetic)
    assert not any('Prioritize this step (' in str(m.get('content')) for m in messages)


@pytest.mark.parametrize('consent', [False, True])
def test_production_step_framing_requires_explicit_consent_and_exact_selected_definition(monkeypatch, consent):
    from cria import steppreparation
    from test_loop import _SHELL
    driver, sess, body = setup_driver()
    settings = config.Config(planner=config.PlannerConfig(enabled=consent))
    driver._ctx.planner_enabled = settings.planner.enabled
    sess.synthetic = sess.plan_off = not consent
    body['tools'].append(_SHELL)
    executed, posts = [], []
    directive = 'Exact selected experimental framing.'
    def execute(source):
        executed.append(source)
        return steppreparation.StepResult(steppreparation.StepStatus.PREPARED,
            steppreparation.with_directive(source.base, directive), prompt=directive)
    definition = replace(steppreparation.DEFINITION, execute=execute)
    runtime = assistruntime.AssistRuntime.select(level=5)
    driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(
        definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
    assert driver._ctx.pilot_runtime.bindings(definition.policy.stage) == (definition,)
    poison = Mock(side_effect=AssertionError('default step detector or legacy fallback'))
    monkeypatch.setattr(loop, 'step_artifacts_on_disk', poison)
    monkeypatch.setattr(loop, '_item_prompt', poison)
    up = driver._ctx.coder_chat.__self__
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])).encode())
    monkeypatch.setattr(up, '_receive_open', transport)
    driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(posts) == 1
    assert len(executed) == int(consent)
    assert (directive in json.dumps(posts[0])) is consent
    if consent:
        assert executed[0].planner_enabled is True and executed[0].synthetic is False
        assert (executed[0].index, executed[0].total) == (1, 1)
    poison.assert_not_called()


def test_prepared_role_is_not_reapplied_on_required_coder_renudge(monkeypatch):
    driver, sess, body = setup_driver()
    applications = []
    class CountingRole(config.Role):
        def apply(self, frame, **kwargs):
            applications.append(frame)
            return super().apply(frame, **kwargs)
    role = CountingRole(name='coder', backend='local', think_protocol='system_directive',
                        reasoning='off', collapse_system_prompt=True)
    driver._ctx.coder_role = role
    up = driver._ctx.coder_chat.__self__
    posts = []
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        if len(posts) == 1:
            return io.BytesIO(b'{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"I will act now."}}]}')
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])).encode())
    monkeypatch.setattr(up, '_receive_open', transport)
    result = driver.drive(body, 'driver-fixture', None, _Rlog())
    assert result['choices'][0]['message']['tool_calls']
    assert len(posts) == 2
    assert len(applications) == 1


def test_disabled_handoff_hardener_is_never_used_for_required_evidence(monkeypatch):
    from cria import memoryhandoff, preamblepolicy, server
    poison = Mock(side_effect=AssertionError('optional handoff lifecycle'))
    monkeypatch.setattr(memoryhandoff, 'harden', poison)
    monkeypatch.setattr(memoryhandoff, 'frame', poison)
    raw = [{'role': 'system', 'content': 'harness persona'},
           {'role': 'user', 'content': 'original user request'},
           {'role': 'assistant', 'content': 'native bytes \x00 unchanged'},
           {'role': 'user', 'content': 'please summarize'}]
    runtime = assistruntime.AssistRuntime.select(level=0, disabled=(preamblepolicy.DEFINITION.policy.id,))
    with assistruntime.bound(runtime):
        evidence = server._compaction_messages(raw)
    assert evidence == raw[1:3]
    poison.assert_not_called()


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('literal_role', ['tool', 'assistant'])
@pytest.mark.parametrize('tag', ['user_instructions', 'environment_context'])
def test_literal_markup_keeps_history_role_read_visibility_and_pairing_at_final_post(
        tmp_path, monkeypatch, synthetic, literal_role, tag):
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    sess.workspace_root = str(tmp_path)
    monkeypatch.chdir(tmp_path)
    literal = f'Source literal follows:\n<{tag}>Preserve this literal.</{tag}>\n'
    read_text = literal if literal_role == 'tool' else 'Exact whole-file bytes from disk.\n'
    (tmp_path / 'notes.txt').write_text(read_text)
    sess.read_files = {'notes.txt': (len(read_text.encode()), '2 lines')}
    pair = [
        {'role': 'assistant', 'tool_calls': [{'id': 'read-source', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"notes.txt"}'}}]},
        {'role': 'tool', 'tool_call_id': 'read-source', 'content': read_text}]
    body['messages'] += pair
    if literal_role == 'assistant':
        body['messages'] += [{'role': 'assistant', 'content': literal},
                             {'role': 'user', 'content': 'Continue from the actual history.'}]
    raw = copy.deepcopy(body)
    assert selfcompact.is_env_context({'role': literal_role, 'content': literal})
    assert loop._extract_whole_reads(body['messages'], wsview.DirectView(str(tmp_path))) == {'notes.txt'}
    posts = []
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])).encode())
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        driver.drive(body, 'driver-fixture', None, _Rlog())
    finally:
        wsview.unbind(token)
    assert len(posts) == 1
    messages = posts[0]['messages']
    assert sum(str(m.get('content') or '').count('Source literal follows:') for m in messages) == 1
    assert not any(str(m.get('content') or '').startswith('⟦ctx:current⟧') for m in messages)
    assert sess.restored_current == {}
    call_at = next(i for i, m in enumerate(messages) if any(
        tc.get('id') == 'read-source' for tc in m.get('tool_calls') or []))
    assert messages[call_at:call_at + 2] == raw['messages'][1:3]
    anchor_at = next(i for i, m in enumerate(messages)
                     if str(m.get('content') or '').startswith('⟦ctx:facts⟧'))
    assert call_at + 1 < anchor_at
    if literal_role == 'assistant':
        literal_at = next(i for i, m in enumerate(messages) if m.get('content') == literal)
        followup_at = next(i for i, m in enumerate(messages)
                           if m.get('content') == 'Continue from the actual history.')
        assert messages[literal_at]['role'] == 'assistant'
        assert call_at + 1 < literal_at < followup_at < anchor_at
    assert body == raw


@pytest.mark.parametrize('synthetic', [False, True])
def test_genuine_user_environment_is_protected_from_both_reducers_and_reframed_once(
        tmp_path, monkeypatch, synthetic):
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    sess.workspace_root = str(tmp_path)
    monkeypatch.chdir(tmp_path)
    packet = {'role': 'user', 'content': f'<environment_context><cwd>{tmp_path}</cwd>'
              '<shell>fixture-shell</shell></environment_context>'}
    body['messages'].insert(0, packet)
    raw = copy.deepcopy(body)
    observed = []
    def rolling(source, state):
        observed.append(('rolling', copy.deepcopy(source.messages)))
        return selfcompact.RollingResult(source.messages, state, Effect.NO_OP)
    def focus(messages):
        observed.append(('focus', copy.deepcopy(messages)))
        return copy.deepcopy(messages), focustrim.TrimReport()
    replacements = {selfcompact.DEFINITION.policy.id: replace(selfcompact.DEFINITION, execute=rolling),
                    focustrim.DUPLICATES.policy.id: replace(focustrim.DUPLICATES, execute=focus)}
    runtime = assistruntime.AssistRuntime.select(level=5)
    driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(
        replacements.get(d.policy.id, d) for d in runtime.ordered_stages))
    driver._ctx.self_compact = driver._ctx.focus_trim = True
    posts = []
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])).encode())
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        driver.drive(body, 'driver-fixture', None, _Rlog())
    finally:
        wsview.unbind(token)
    assert [kind for kind, _messages in observed] == ['rolling', 'focus']
    assert all(packet not in messages for _kind, messages in observed)
    assert len(posts) == 1
    messages = posts[0]['messages']
    environment = [m for m in messages if str(m.get('content') or '').startswith('Working environment —')]
    assert environment == [{'role': 'user', 'content':
        f'Working environment — cwd: {tmp_path}, shell: fixture-shell.'}]
    assert packet not in messages
    assert messages[1] == raw['messages'][1]
    assert body == raw
