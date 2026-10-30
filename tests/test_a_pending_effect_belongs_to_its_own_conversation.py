"""An unreturned native effect withholds current bytes for the conversation that contains it, and for nothing else.

The unported r10 "lifecycle frontier" candidate was blocked by two boundary tests that assumed a store-owned
workspace authority. The current owners keep no effect ledger past a request (`wsview.View` is rebuilt from the
request's own history), so the properties hold structurally; these guard them against a future retained ledger.
"""
import json

from cria import loop, wsview, writeproxy
from cria.plan import Plan, PlanItem
from tests.test_a_result_is_ciras_refusal_only_when_ciras_own_lowering_proved_it import _lower, _run, _history


def _native(cid, name='delete_file'):
    return {'role': 'assistant', 'tool_calls': [{'id': cid, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps({'path': 'out.txt'})}}]}


def _represent(view, history):
    token = wsview.bind(view)
    try:
        return writeproxy.represent_inbound(history, workspace_root=view.root)
    finally:
        wsview.unbind(token)


def _read(root, cid, content):
    (root / 'out.txt').write_text(content)
    token = wsview.bind(wsview.View(str(root), cid))
    try:
        call = _lower('read_file', {'path': 'out.txt'}, cid=cid, root=str(root), session=cid)
    finally:
        wsview.unbind(token)
    return _history(call, _run(call, root))


def _plan_session(task):
    return loop.PlanSession(plan=Plan(id=task, task='task', created='offline', items=[PlanItem('work')]))


def test_pending_effect_withholds_only_its_own_conversation(tmp_path):
    _represent(wsview.View(str(tmp_path), 'sid:one'), [_native('mutation')])   # never returned
    other = tmp_path / 'other'
    other.mkdir()
    for root, key, text in ((other, 'sid:one', 'root two'), (tmp_path, 'sid:two', 'session two')):
        view = wsview.View(str(root), key)
        _represent(view, _read(root, 'read-' + text.replace(' ', ''), text))
        assert view.read('out.txt') == text
    own = _read(tmp_path, 'own', 'same conversation')
    view = wsview.View(str(tmp_path), 'sid:one')
    _represent(view, [_native('mutation')] + own)
    assert view.read('out.txt') is None


def test_a_finished_session_leaves_no_uncertainty_for_the_next_task(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, '_MAX_SESSIONS', 1)
    store = loop.LoopStore()
    finished = _plan_session('first')
    store.put('sid:one', finished)
    _represent(wsview.View(str(tmp_path), 'sid:one'), [_native('mutation')])
    finished.phase = loop.Phase.DONE
    store.put('sid:two', _plan_session('second'))
    assert store.get('sid:one') is None and store.get('sid:two') is not None
    view = wsview.View(str(tmp_path), 'sid:two')
    _represent(view, _read(tmp_path, 'fresh', 'current'))
    assert view.read('out.txt') == 'current'


def test_replaying_a_completed_effect_with_a_user_suffix_does_not_revoke_a_later_read(tmp_path):
    later = _read(tmp_path, 'later', 'after the effect')
    history = [_native('done'), {'role': 'tool', 'tool_call_id': 'done', 'content': 'ok'}] + later
    for suffix in ([], [{'role': 'user', 'content': 'continue'}]):
        view = wsview.View(str(tmp_path), 'sid:one')
        _represent(view, json.loads(json.dumps(history)) + suffix)
        assert view.read('out.txt') == 'after the effect'
