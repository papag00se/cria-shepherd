"""Unusable optional guidance must not override a producer-owned handoff's task."""
import copy
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest
from cria import assistruntime, loop, prompts, reorientation as policy, tokenratio, upstream, wsview
from cria.config import Role
from cria.plan import Plan, PlanItem

WRITE = {'type': 'function', 'function': {'name': 'write_file', 'parameters': {
    'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}},
    'required': ['path', 'content']}}}

class _Rlog:
    def __init__(self): self.events = []
    def emit(self, kind, **fields): self.events.append((kind, fields))


def setup_driver():
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, planner_enabled=False,
        reasoner_chat=None, runs_dir='', workspace_root='', self_compact=False,
        focus_trim=False, assists=False, satisfaction_check_start=0))
    task = 'Perform the requested action.'
    session = loop.PlanSession(plan=Plan(id='fallback', task=task, created='now', items=[PlanItem(task)]),
        synthetic=True, plan_off=True)
    return driver, session, {'messages': [{'role': 'user', 'content': task}], 'tools': [copy.deepcopy(WRITE)]}

SUMMARY = '⟦ctx:continuation⟧ Earlier work in existing.py; historical command: INSPECT first.'
NEGATIVE = 'Do not inspect any files. Make the first requested edit immediately.'
POSITIVE = 'Inspect the relevant files before making changes, then finish the edit.'
MODES = ('no-reasoner', 'no-prose', 'fenced-script', 'command-script', 'ungrounded',
         'judge-denied', 'judge-malformed', 'judge-error', 'empty', 'keep-task')


def make_source(mode, task=NEGATIVE, ownership='matched'):
    summary = SUMMARY + (' ' + policy.DROPPED_PROSE_LEAD if mode == 'no-prose' else '')
    owned = summary if ownership == 'matched' else ('not a packet' if ownership == 'mismatch' else '')
    text = {'fenced-script': '```sh\ncat existing.py\n```',
            'command-script': 'cat existing.py\ncat existing.py\ncat existing.py',
            'empty': '', 'keep-task': 'KEEP_TASK'}.get(mode, 'Inspect phantom.py before proceeding.')
    judge = None
    if mode.startswith('judge-'):
        judge = Mock(return_value='{"grounded":false}' if mode == 'judge-denied' else 'undecidable')
        if mode == 'judge-error': judge.side_effect = RuntimeError('unavailable')
    source = policy.ReorientationInput(True,
        lambda: policy.ReorientationFacts((task, summary), mode != 'no-reasoner', task, owned),
        Mock(return_value='existing.py (13 B)'), Mock(return_value=text), Mock(), _Rlog(), judge)
    return source


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('task', [NEGATIVE, POSITIVE])
def test_owned_unusable_guidance_never_becomes_canned_inspection(mode, task):
    source = make_source(mode, task)
    result = policy.DEFINITION.execute(source)
    assert result.message is None
    assert not result.consumed
    source.consume_rewrite.assert_not_called()
    if mode in ('no-reasoner', 'no-prose'):
        source.inventory.assert_not_called()
        source.author.assert_not_called()
    else:
        source.inventory.assert_called_once_with()
        source.author.assert_called_once()
    if source.judge is not None: source.judge.assert_called_once()


@pytest.mark.parametrize('mode', MODES[:-2])
@pytest.mark.parametrize('ownership', ['absent', 'mismatch'])
def test_unowned_compatibility_notice_and_acknowledgement_remain(mode, ownership):
    source = make_source(mode, ownership=ownership)
    result = policy.reorient(source)
    assert result.message == {'role': 'user', 'content': prompts.render('nudge', reason=prompts.load('reanchor'))}
    assert result.consumed
    source.consume_rewrite.assert_called_once_with()


@pytest.mark.parametrize('text', [
    'Inspect existing.py before editing.',
    'Inspect relevant files; the phrase KEEP_TASK quoted here is not an abstention.',
])
def test_compatible_authored_inspection_is_delivered_and_acknowledged(text):
    source = replace(make_source('ungrounded', POSITIVE), author=Mock(return_value=text))
    result = policy.reorient(source)
    assert result.message == {'role': 'user', 'content': prompts.render('nudge', reason=text)}
    assert result.reason == 'authored' and result.consumed
    source.consume_rewrite.assert_called_once_with()


def test_task_required_target_still_uses_existing_name_judgment():
    source = replace(make_source('judge-denied', 'Inspect required.py before editing.'),
        author=Mock(return_value='Inspect required.py before editing.'),
        judge=Mock(return_value='{"grounded":true}'))
    result = policy.reorient(source)
    assert result.reason == 'authored' and 'required.py' in result.message['content']
    source.judge.assert_called_once()


def test_provider_exception_still_propagates_without_acknowledgement():
    source = replace(make_source('ungrounded'), author=Mock(side_effect=RuntimeError('provider unavailable')))
    with pytest.raises(RuntimeError, match='provider unavailable'):
        policy.reorient(source)
    source.consume_rewrite.assert_not_called()


@pytest.mark.parametrize('mode,owned,task', [
    (mode, owned, task)
    for mode in ('no-reasoner', 'no-prose', 'fenced-script', 'ungrounded', 'positive')
    for owned in (True, False) for task in (NEGATIVE, POSITIVE)
    if mode != 'positive' or task == POSITIVE
])
def test_real_driver_keeps_task_and_next_call_without_fallback_override(tmp_path, monkeypatch, mode, owned, task):
    driver, session, body = setup_driver()
    summary = SUMMARY + (' ' + policy.DROPPED_PROSE_LEAD if mode == 'no-prose' else '')
    session.workspace_root = str(tmp_path)
    session.handoff_origin = loop._HandoffOrigin('Earlier work', '', False,
        continuation=summary if owned else '⟦ctx:continuation⟧ A different boundary')
    body['messages'] = [{'role': 'user', 'content': task}, {'role': 'user', 'content': summary}]
    body['tools'] = [copy.deepcopy(WRITE)]
    key = 'sid:owned-fallback'
    driver._store.put(key, session)
    driver._store.observe_shape_with_ticket(key, loop._history_root(body['messages'])[1], len(body['messages']) + 10)
    driver._ctx.reasoner_role = None if mode == 'no-reasoner' else Role(name='reasoner', backend='local')
    answer = {'positive': 'Inspect existing.py before editing.',
              'fenced-script': '```sh\ncat existing.py\n```'}.get(mode, 'Inspect phantom.py before editing.')
    author = Mock(side_effect=lambda *a, **k: '{"grounded":false}' if k.get('phase') == 'reanchor-name-grounding' else answer)
    monkeypatch.setattr(loop, 'summarize', author)
    monkeypatch.setattr(tokenratio, 'record', lambda *a, **k: None)
    wires = []
    def coder(frame, rlog):
        frame['model'] = 'fixture'
        up = upstream.Upstream('http://unused.invalid', context_window=16000, capture_rendered=False)
        up._props = {'chat_template': 'fixture'}
        monkeypatch.setattr(up, '_render_prompt', lambda out: json.dumps(out))
        monkeypatch.setattr(up, '_tokenize_prompt', lambda rendered, log: 300)
        wires.append(json.loads(up._prep(frame, False, rlog, safety_override=1)[0]))
        return json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function', 'function': {
            'name': 'write_file', 'arguments': '{"path":"existing.py","content":"work"}'}}])).encode()
    driver._ctx.coder_chat = coder
    token = wsview.bind(wsview.View(str(tmp_path)))
    try:
        with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
            result = driver._drive_locked(body, key, None, _Rlog())
    finally:
        wsview.unbind(token)
    assert len(wires) == 1
    assert task in str(wires[0]['messages'])
    steers = [m['content'] for m in wires[0]['messages'] if isinstance(m.get('content'), str)
              and m['content'].startswith('⟦ctx:steer⟧')]
    if mode == 'positive':
        assert steers == [prompts.render('nudge', reason=answer)]
    elif owned:
        assert not steers
    else:
        assert steers == [prompts.render('nudge', reason=prompts.load('reanchor'))]
    assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'next'
    if mode in ('no-reasoner', 'no-prose'): author.assert_not_called()
    else:
        assert [call.kwargs.get('phase') for call in author.call_args_list] == (
            ['reasoner', 'reanchor-name-grounding'] if mode == 'ungrounded' else ['reasoner'])
