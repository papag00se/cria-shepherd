"""Offline verdicts prove delivery policy, not the semantic accuracy of a judge."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from cria import assistruntime, loop, prompts, reorientation, selfcompact
from cria.config import Role
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


SAVED = json.loads((Path(__file__).parent / 'fixtures/reorientation_required_target_0057.json').read_text())


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('verdict,accepted', [('{"grounded": true}', True),
    ('{"grounded": false}', False), ('UNDECIDABLE', False),
    ('{"grounded":', False), (RuntimeError('provider error'), False)])
def test_saved_required_target_reaches_prepared_coder(synthetic, verdict, accepted, monkeypatch):
    driver, sess, body = setup_driver()
    driver._ctx.reasoner_role = Role(name='reasoner', backend='local')
    sess.synthetic = sess.plan_off = synthetic
    # This scenario is historical continuation AFTER actual assistant work, not
    # an initial USER packet whose marker could be mistaken for origin proof.
    # Keep the saved task/history verbatim; an ordinary paired directory lookup
    # establishes the work-role boundary without an annotation or synthetic ack.
    body['messages'] = [{'role': 'user', 'content': SAVED['task']},
                        {'role': 'assistant', 'tool_calls': [{
                            'id': 'prior-listing', 'type': 'function', 'function': {
                                'name': 'list_dir', 'arguments': '{"path":"."}'}}]},
                        {'role': 'tool', 'tool_call_id': 'prior-listing',
                         'content': 'README.md\npom.xml\nsrc/main\n'},
                        {'role': 'user', 'content': SAVED['summary']}]
    assert selfcompact.root_user_indices(body['messages']) == (0,)
    assert loop._history_root(body['messages'])[0] == SAVED['task']
    monkeypatch.setattr('urllib.request.urlopen', Mock(side_effect=AssertionError('offline fixture')))
    author = Mock(return_value=SAVED['directive'])
    judge = Mock(side_effect=verdict) if isinstance(verdict, Exception) else Mock(return_value=verdict)
    monkeypatch.setattr(loop, 'summarize', author)
    monkeypatch.setattr(loop, 'ask_closed', judge)
    monkeypatch.setattr(loop, 'workspace_inventory', lambda *a, **k: SAVED['inventory'])
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        framed, oriented = driver._prepare_coder_context(
            sess, body, _Rlog(), synthetic=synthetic, rewritten=True)
    assert oriented
    expected = prompts.render('nudge', reason=SAVED['directive'] if accepted else prompts.load('reanchor'))
    assert framed['messages'][-1]['content'] == expected
    assert any(m.get('content') == SAVED['task'] for m in framed['messages'])
    author.assert_called_once()
    assert author.call_args.args[3] == prompts.render('reanchor_context',
        task=SAVED['task'], summary=SAVED['summary'], inventory=SAVED['inventory'])
    judge.assert_called_once()
    blocks = judge.call_args.kwargs['evidence_blocks']
    assert any(SAVED['task'] in b for b in blocks)
    assert any(SAVED['summary'] in b for b in blocks)
    assert any(SAVED['directive'] in b for b in blocks)
    assert judge.call_args.kwargs['retry_off'] is False
    packed, _, _ = driver._ctx.coder_chat.__self__._prep(
        {**framed, 'model': 'offline'}, False, _Rlog())
    wire = json.loads(packed)
    assert any(m.get('content') == SAVED['task'] for m in wire['messages'])
    assert loop._history_root(wire['messages'])[0] == SAVED['task']
    assert wire['messages'][-1]['content'] == expected


@pytest.mark.parametrize('synthetic', [False, True])
def test_unproven_initial_continuation_packet_remains_in_the_complete_root(synthetic, monkeypatch):
    """Without prior work, marker-shaped USER text cannot exclude itself from root.

    The historical scenario above must not license dropping indistinguishable
    initial context. Check exact root selection and provider input, not merely
    whether the final body happens to contain both strings somewhere.
    """
    driver, sess, body = setup_driver()
    driver._ctx.reasoner_role = Role(name='reasoner', backend='local')
    sess.synthetic = sess.plan_off = synthetic
    initial = [{'role': 'user', 'content': SAVED['task']},
               {'role': 'user', 'content': SAVED['summary']}]
    body['messages'] = initial
    joined_root = SAVED['task'] + '\n\n' + SAVED['summary']
    assert selfcompact.root_user_indices(initial) == (0, 1)
    assert loop._history_root(initial)[0] == joined_root
    author = Mock(return_value=SAVED['directive'])
    judge = Mock(return_value='{"grounded": true}')
    monkeypatch.setattr(loop, 'summarize', author)
    monkeypatch.setattr(loop, 'ask_closed', judge)
    monkeypatch.setattr(loop, 'workspace_inventory', lambda *a, **k: SAVED['inventory'])
    monkeypatch.setattr('urllib.request.urlopen', Mock(side_effect=AssertionError('offline fixture')))
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        framed, oriented = driver._prepare_coder_context(
            sess, body, _Rlog(), synthetic=synthetic, rewritten=True)
    assert oriented
    author.assert_called_once()
    context = prompts.render('reanchor_context', task=joined_root,
                             summary=SAVED['summary'], inventory=SAVED['inventory'])
    assert author.call_args.args[3] == context
    judge.assert_called_once()
    assert context in judge.call_args.kwargs['evidence_blocks']
    assert judge.call_args.kwargs['retry_off'] is False
    packed, _, _ = driver._ctx.coder_chat.__self__._prep(
        {**framed, 'model': 'offline'}, False, _Rlog())
    wire = json.loads(packed)
    # The entire initial bundle survives unchanged in its original order; no
    # whole-root reconstruction may silently discard the marker-bearing packet.
    assert [m for m in wire['messages'] if m.get('role') == 'user'][:2] == initial
    assert wire['messages'][-1]['content'] == prompts.render('nudge', reason=SAVED['directive'])
    assert loop._history_root(body['messages'])[0] == joined_root


def request(directive='Verify that audit.txt satisfies the required report.', *, task='Produce audit.txt.', judge=None):
    return reorientation.ReorientationInput(True,
        lambda: reorientation.ReorientationFacts(('⟦ctx:continuation⟧ Existing main.py was edited.',), True, task),
        lambda: 'main.py', lambda _: directive, None, _Rlog(), judge=judge)


@pytest.mark.parametrize('directive,verdict,accepted', [
    ('Verify that audit.txt satisfies the required report.', '{"grounded": true}', True),
    ('audit.txt already exists; inspect it.', '{"grounded": false}', False),
    ('Verify audit.txt; it already exists.', '{"grounded": false}', False),
    ('Verify that unknown.txt satisfies the task.', '{"grounded": false}', False),
    ('Verify audit.txt.', '{"grounded": "true"}', False),
    ('Verify audit.txt.', '{"grounded": 1}', False),
    ('Verify audit.txt.', '{"grounded": null}', False),
    ('Verify audit.txt.', '{"grounded": true, "extra": true}', False),
    ('Verify audit.txt.', 'UNDECIDABLE', False),
    ('Verify audit.txt.', '{"grounded":', False),
    ('Verify audit.txt.', '', False),
])
def test_judgment_routes_whole_directive_without_task_name_permission(directive, verdict, accepted):
    judge = Mock(return_value=verdict)
    result = reorientation.reorient(request(directive, judge=judge))
    assert (result.reason == 'authored') is accepted
    assert result.message['content'] == prompts.render('nudge',
        reason=directive if accepted else prompts.load('reanchor'))
    question, blocks = judge.call_args.args
    expected_name = 'unknown.txt' if 'unknown.txt' in directive else 'audit.txt'
    assert expected_name in question
    assert 'Produce audit.txt.' in blocks[0]
    assert 'Existing main.py was edited.' in blocks[0]
    assert directive in blocks[1]
    judge.assert_called_once()


@pytest.mark.parametrize('task', ['', '⟦ctx:continuation⟧ Produce audit.txt.'])
def test_no_independent_task_cannot_release_unobserved_target(task):
    judge = Mock(side_effect=AssertionError('must not judge without task'))
    assert reorientation.reorient(request(task=task, judge=judge)).reason == 'ungrounded'
    judge.assert_not_called()


def test_judge_error_withholds_authored_guidance():
    judge = Mock(side_effect=RuntimeError('provider error'))
    assert reorientation.reorient(request(judge=judge)).reason == 'ungrounded'
    judge.assert_called_once()


def test_observed_names_do_not_add_a_question():
    judge = Mock(side_effect=AssertionError)
    assert reorientation.reorient(request('Inspect main.py.', judge=judge)).reason == 'authored'
    judge.assert_not_called()


def test_disabled_control_has_no_owned_effects():
    bomb = Mock(side_effect=AssertionError)
    source = reorientation.ReorientationInput(True, bomb, bomb, bomb, bomb, _Rlog(), judge=bomb)
    assert reorientation.reorient(source, enabled=False).message is None
    bomb.assert_not_called()
