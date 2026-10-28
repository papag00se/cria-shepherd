"""A carried guidance note says how old it is, in the coder's own calls.

Run04 (ornith1.5_9b / Java, session 20261027T032006): the guidance history carried the periodic
gate's exact note — "I am giving you the CURRENT state of the repo" over a red `mvn -q compile`
block — in all 38 coder requests from 0067 to 0106, after the coder's own build returned exit 0. The block header said these
were not current findings, but each note stood undated: at 0065 the coder read the older
getHeader() block as "the LATEST check" and re-ran the build; at 0097 it re-read the whole file
because "the steer says the current Importer.java has a compile error". The note's words stay
exact; its age, measured by the forwarded-call counter that dates a handoff's check block, is
what lets the coder place it against its own newer results. See docs/guidance-continuity.md.
"""
import copy
import io
import json
from unittest.mock import patch

import pytest
from cria import loop, prompts
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog

RED = ("[GROUND TRUTH — the repo's own checks fail] The failures:\n"
       "$ mvn -q compile — src/main/java/pipeline/Importer.java:66: cannot find symbol\n"
       "symbol:   method setSkipLines(int)")
REASON = prompts.render('periodic_gate', truth=RED)
NOTE = prompts.render('nudge', reason=REASON)
SEEDED = '⟦ctx:steer⟧ an earlier observation whose delivery this session never recorded'


def _age(calls):
    return prompts.fill(prompts.load_map('guidance_history_age')['aged'], calls=calls)


def _history(post):
    found = [m['content'] for m in post['messages']
             if str(m.get('content')).startswith('⟦ctx:guidance-history⟧')]
    assert len(found) == 1
    return found[0]


def _drive(synthetic, calls_per_reply, redeliver_at=None):
    driver, session, body = setup_driver()
    session.synthetic = session.plan_off = synthetic
    session.guidance_history = [SEEDED]
    session.nudge_reason = REASON
    posts = []

    def transport(request, **kw):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        n = len(posts)
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{
            'id': f'read-{n}-{i}', 'type': 'function', 'function': {
                'name': 'read_file', 'arguments': json.dumps({'path': f'f{i}.txt'})}}
            for i in range(calls_per_reply[n - 1])])).encode())

    up = driver._ctx.coder_chat.__self__
    with patch.object(up, '_receive_open', transport):
        for turn in range(len(calls_per_reply)):
            if turn == redeliver_at:
                session.nudge_reason = REASON
            reply = driver.drive(body, 'driver-fixture', None, _Rlog())
            body = copy.deepcopy(body)
            message = reply['choices'][0]['message']
            body['messages'].append(message)
            body['messages'] += [{'role': 'tool', 'tool_call_id': tc['id'], 'content': 'current text'}
                                 for tc in message['tool_calls']]
    return posts


@pytest.mark.parametrize('synthetic', [False, True])
def test_a_carried_red_check_note_is_dated_by_the_coders_calls_since_delivery(synthetic):
    posts = _drive(synthetic, [2, 1, 1])
    assert sum(m.get('content') == NOTE for m in posts[0]['messages']) == 1   # delivered live once
    # Next request: the reply that answered it made 2 calls; one later reply made 1 more.
    assert _age(2) + '\n' + NOTE in _history(posts[1])
    assert _age(3) + '\n' + NOTE in _history(posts[2])
    # The note's own words are carried exactly — the age is beside it, never a rewrite of it.
    assert all(NOTE in _history(p) for p in posts[1:])


@pytest.mark.parametrize('synthetic', [False, True])
def test_an_undelivered_entry_gets_no_invented_age(synthetic):
    """Control: an entry with no recorded delivery is carried as before, with no number."""
    posts = _drive(synthetic, [2, 1])
    history = _history(posts[1])
    assert SEEDED in history and NOTE in history
    assert not any(_age(n) + '\n' + SEEDED in history for n in range(0, 10))


@pytest.mark.parametrize('synthetic', [False, True])
def test_redelivery_keeps_one_copy_dated_by_the_latest_delivery(synthetic):
    """Control: identical text stays one entry (first-delivery order); its age restarts."""
    posts = _drive(synthetic, [2, 3, 1, 1], redeliver_at=2)
    assert _age(5) + '\n' + NOTE in _history(posts[2])
    assert sum(m.get('content') == NOTE for m in posts[2]['messages']) == 1   # live again
    assert _history(posts[3]).count(NOTE) == 1
    assert _age(1) + '\n' + NOTE in _history(posts[3])


def test_zero_age_states_nothing():
    """Control: delivered but no call of the coder's since — no '0 of your calls' sentence."""
    session = loop.PlanSession(plan=loop.Plan(id='p', task='t', created='now', items=[]))
    session.guidance_delivered_seq = {NOTE: 4}
    session.action_seq = 4
    assert loop._dated_guidance(session, [NOTE]) == [NOTE]
