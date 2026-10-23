"""Delivered notes survive prerequisite inspection as reducible history, not orders.

Both real drivers and their serialized HTTP bodies exercise the custody boundary.
See docs/guidance-continuity.md.
"""
import copy
import io
import json
from unittest.mock import patch

import pytest
from cria import loop, prompts
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('retain_history', [False, True])
def test_real_driver_distinguishes_transient_note_from_historical_transcript(retain_history, synthetic):
    driver, session, body = setup_driver()
    session.synthetic = session.plan_off = synthetic
    directive = 'Inspect the current source before repairing the reported discrepancy.'
    session.nudge_reason = directive
    posts = []
    historical = 'Historical guidance previously delivered; not a current finding or renewed order:\n' + directive

    def transport(request, **kwargs):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]} ')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{
            'id': 'inspect-' + str(len(posts)), 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"notes.txt"}'}}])).encode())

    up = driver._ctx.coder_chat.__self__
    with patch.object(up, '_receive_open', transport):
        reply = driver.drive(body, 'driver-fixture', None, _Rlog())
        body = copy.deepcopy(body)
        if retain_history:
            # An explicit harness-retained historical record, not a session-level
            # claim that a proposed note reached the final transport.
            body['messages'].append({'role': 'user', 'content': historical})
        body['messages'] += [reply['choices'][0]['message'], {
            'role': 'tool', 'tool_call_id': 'inspect-1',
            'content': 'Read-only inspection returned current text.'}]
        driver.drive(body, 'driver-fixture', None, _Rlog())

    note = prompts.render('nudge', reason=directive)
    assert len(posts) == 2
    assert sum(m.get('content') == note for m in posts[0]['messages']) == 1
    assert not any('Previously requested:' in str(m.get('content')) for m in posts[0]['messages'])
    assert not any(m.get('content') == note for m in posts[1]['messages'])
    assert any(m.get('content') == historical for m in posts[1]['messages']) is retain_history
    assert any('⟦ctx:guidance-history⟧' in str(m.get('content')) and directive in str(m.get('content'))
               for m in posts[1]['messages'])
    assert session.guidance_history == [note]
    assert session.nudge_reason == ''
    assert not session.plan.items[0].done
    assert all(any(m.get('content') == session.plan.task for m in p['messages']) for p in posts)
