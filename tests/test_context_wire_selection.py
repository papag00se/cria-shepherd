"""Selected wire folds are shared by estimates, floor trials and actual survivors."""
from dataclasses import replace
import json
import copy
import subprocess
import sys
from unittest.mock import Mock

import pytest
from cria import assistruntime, bodykeys, contextfloor, focustrim, loop, modelview, upstream
from test_upstream import _Rlog


@pytest.mark.parametrize('first', ['massage', 'assistruntime', 'modelview', 'loop', 'groundedaction', 'reorientation', 'memoryhandoff'])
def test_fresh_process_dependency_directions(first):
    result = subprocess.run([sys.executable, '-c', f'import cria.{first}; import cria.assistruntime; import cria.loop'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('disabled', [False, True])
def test_wire_uses_exact_selected_fold_without_default_fallback(monkeypatch, disabled):
    calls = []
    def fold(messages):
        calls.append(messages)
        if any(m.get('content') == 'chosen folded view' for m in messages):
            return messages
        return messages + [{'role': 'user', 'content': 'chosen folded view'}]
    definition = replace(modelview.REPEATED_PAYLOADS, execute=fold)
    runtime = assistruntime.AssistRuntime.select(level=5,
        disabled=tuple(d.policy.id for d in modelview.WIRE_FOLD_STAGE) if disabled else ())
    runtime = replace(runtime, ordered_stages=tuple(definition if d.policy.id == definition.policy.id else d
                                                  for d in runtime.ordered_stages))
    monkeypatch.setattr(modelview, 'fold_evidence', Mock(side_effect=AssertionError('legacy fold')))
    up = upstream.Upstream('http://offline.invalid', context_window=8192, engagement_level=5)
    with assistruntime.bound(runtime):
        packed, _size, _model = up._prep({'model': 'offline', 'messages': [
            {'role': 'user', 'content': 'real task'}]}, False, _Rlog())
    shown = json.loads(packed)['messages']
    assert bool(calls) is (not disabled)
    assert any(m.get('content') == 'chosen folded view' for m in shown) is (not disabled)


def test_changed_trial_refits_original_unfolded_history_with_identical_budgets(monkeypatch):
    runtime = assistruntime.AssistRuntime.select(level=5)
    raw = [{'role': 'user', 'content': 'root task'},
           {'role': 'user', 'content': 'long evidence ' * 80},
           {'role': 'user', 'content': 'long evidence ' * 80}]
    fits, folds = [], []
    original_fold = modelview.fold_selected
    def fold(source, definitions=None):
        folds.append(definitions)
        return original_fold(source, definitions)
    def fit(messages, tools, **budget):
        fits.append((messages, tools, budget))
        if len(fits) == 1:
            assert messages != raw
            return messages[:1], tools, contextfloor.FloorReport(applied=True)
        assert messages == raw
        return messages[:2], tools, contextfloor.FloorReport(applied=True)
    monkeypatch.setattr(modelview, 'fold_selected', fold)
    monkeypatch.setattr(contextfloor, 'fit', fit)
    up = upstream.Upstream('http://offline.invalid', context_window=8192, engagement_level=5)
    with assistruntime.bound(runtime):
        packed, _size, _model = up._prep({'model': 'offline', 'messages': raw}, False, _Rlog())
    assert len(fits) == 2 and fits[0][2] == fits[1][2]
    assert all(definitions is runtime.wire_folds for definitions in folds)
    shown = json.loads(packed)['messages']
    assert not any('full copy below' in str(m.get('content')) for m in shown)
    assert shown == raw[:2]


def test_wire_bindings_remain_exact_in_nested_and_concurrent_scopes():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    boundary = Barrier(2)
    up = upstream.Upstream('http://offline.invalid', context_window=8192, engagement_level=5)
    original = assistruntime.current()
    def worker(tag):
        empty = assistruntime.AssistRuntime.select(level=0)
        def fold(messages):
            assert assistruntime.current() is runtime
            with assistruntime.bound(empty):
                assert assistruntime.current().wire_folds == ()
            assert assistruntime.current() is runtime
            boundary.wait(timeout=5)
            return (messages if any(m.get('content') == tag for m in messages)
                    else messages + [{'role': 'user', 'content': tag}])
        definition = replace(modelview.REPEATED_PAYLOADS, execute=fold)
        base = assistruntime.AssistRuntime.select(level=5)
        runtime = replace(base, ordered_stages=tuple(
            definition if d.policy.id == definition.policy.id else d for d in base.ordered_stages))
        assert runtime.wire_folds[0] is definition
        with assistruntime.bound(runtime):
            packed, _size, _model = up._prep({'model': 'offline', 'messages': [
                {'role': 'user', 'content': 'Original task.'}]}, False, _Rlog())
        return [m['content'] for m in json.loads(packed)['messages']]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ('first exact scope', 'second exact scope')))
    assert results == [['Original task.', 'first exact scope'], ['Original task.', 'second exact scope']]
    assert assistruntime.current() is original


@pytest.mark.parametrize('location', ['request', 'message'])
def test_focus_private_packet_never_leaks_or_executes_without_surviving_obligations(location):
    settle = Mock(side_effect=AssertionError('no pending obligation'))
    packet = assistruntime.FocusWireBindings((replace(focustrim.SUPERSESSION, settle=settle),))
    body = {'model': 'offline', 'messages': [{'role': 'user', 'content': 'Preserve this user packet.'}]}
    (body if location == 'request' else body['messages'][0])[bodykeys.FOCUS_PRODUCERS] = packet
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=0)):
        encoded, _estimate, _model = upstream.Upstream('http://offline.invalid', context_window=8192,
            engagement_level=0)._prep(body, False, _Rlog())
    assert bodykeys.FOCUS_PRODUCERS.encode() not in encoded
    assert focustrim.SUPERSESSION.policy.id.encode() not in encoded
    settle.assert_not_called()


def test_focus_wire_packet_is_nonempty_immutable_and_copy_stable():
    packet = assistruntime.FocusWireBindings((focustrim.SUPERSESSION,))
    assert copy.copy(packet) is packet and copy.deepcopy(packet) is packet
    assert packet.definitions[0] is focustrim.SUPERSESSION
    assert json.loads(json.dumps(packet)) == [focustrim.SUPERSESSION.policy.id]
    with pytest.raises(AttributeError):
        packet.definitions = ()
    for invalid in ((), [], (focustrim.DUPLICATES,)):
        with pytest.raises(ValueError):
            assistruntime.FocusWireBindings(invalid)


@pytest.mark.parametrize('synthetic', [False, True])
def test_actual_focus_producer_binding_survives_disabled_production_and_refit(monkeypatch, synthetic):
    from test_generation_driver_policy import setup_driver
    driver, sess, body = setup_driver()
    sess.synthetic = sess.plan_off = synthetic
    driver._ctx.focus_trim = True
    for call_id, text in [('old-write', 'old body\n' * 200), ('new-write', 'new body\n' * 200)]:
        body['messages'] += [{'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': call_id, 'type': 'function', 'function': {'name': 'write_file',
                'arguments': json.dumps({'path': 'notes.txt', 'content': text})}}]},
            {'role': 'tool', 'tool_call_id': call_id, 'content': 'Wrote notes.txt',
             'cria_result_outcome': 'landed'}]
    settlements, frames = [], []
    def settle(messages):
        settlements.append(messages)
        return focustrim.SUPERSESSION.settle(messages) + [{'role': 'user', 'content': 'exact original settlement replacement'}]
    definition = replace(focustrim.SUPERSESSION, settle=settle)
    runtime = assistruntime.AssistRuntime.select(level=5)
    driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(
        definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
    def coder(session, framed, raw, **kwargs):
        frames.append(framed)
        return loop._completion_toolcalls([{'id': 'next', 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])
    monkeypatch.setattr(driver, '_coder_turn', coder)
    driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(frames) == 1
    assert any(isinstance(m.get(bodykeys.SUPERSEDED_WRITES), focustrim.SupersededWriteNotice)
               for m in frames[0]['messages'])
    # A retry/refit owns this same body even if the next scope no longer produces focus.
    copied = copy.deepcopy(frames[0])
    assert copied[bodykeys.FOCUS_PRODUCERS].definitions == (definition,)
    assert copied[bodykeys.FOCUS_PRODUCERS].definitions[0] is definition
    copied['model'] = 'offline'
    def fit(messages, tools, **budget):
        kept = [m for m in messages if m.get('tool_call_id') != 'new-write' and
                not any(tc.get('id') == 'new-write' for tc in m.get('tool_calls') or [])]
        return kept, tools, contextfloor.FloorReport(applied=True)
    monkeypatch.setattr(contextfloor, 'fit', fit)
    disabled = assistruntime.AssistRuntime.select(level=5,
        disabled=tuple(d.policy.id for d in assistruntime.CONTEXT_DEFINITIONS))
    up = driver._ctx.coder_chat.__self__
    with assistruntime.bound(disabled):
        first, _size, _model = up._prep(copied, False, _Rlog())
        refit, _size, _model = up._prep(copied, False, _Rlog(), safety_override=2.0)
    assert len(settlements) == 2
    for packed in (first, refit):
        post = json.loads(packed)
        assert 'exact original settlement replacement' in json.dumps(post)
        assert not any(k in post for k in bodykeys.ALL)
        assert not any(bodykeys.SUPERSEDED_WRITES in m for m in post['messages'])
        assert 'not both carried above in full' in json.dumps(post)
