"""1792370046/0033: a read-only history acquired an unconditional change claim.

The coder repeated the footer's premise and reread unchanged files. Past tool
observations still need dated provenance, but compaction is not a filesystem event.
"""
import io
import json

import pytest

from cria import assistruntime, contextfloor, loop, prompts, wsview
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


@pytest.mark.parametrize('changed', [False, True])
def test_dated_read_provenance_does_not_assert_a_workspace_mutation(tmp_path, changed):
    source = tmp_path / 'source.txt'
    source.write_text('original observed source\n')
    observed = source.read_text()
    dropped = [{'role': 'assistant', 'content': 'historical read-only discussion\n' * 100},
               {'role': 'assistant', 'tool_calls': [{'id': 'read', 'type': 'function',
                'function': {'name': 'read_file', 'arguments': '{"path":"source.txt"}'}}]},
               {'role': 'tool', 'tool_call_id': 'read', 'content': observed}]
    if changed:
        source.write_text('later independently changed source\n')
    note = contextfloor._compacted_note(dropped, len(dropped), 8000)['content']
    assert observed.strip() in note
    assert 'workspace has moved on since' not in note
    assert prompts.load('compacted_history_provenance').strip() in note
    # Neither an unchanged file nor a genuinely later mutation is read or undone
    # by the history writer. Both require the same dated, not current, authority.
    assert source.read_text() == ('later independently changed source\n' if changed else observed)


@pytest.mark.parametrize('changed', [False, True])
def test_exact48_real_driver_final_post_keeps_history_dated_without_a_change_claim(tmp_path, monkeypatch, changed):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source.txt'
    source.write_text('previous source observation\n')
    observed = source.read_text()
    driver, session, body = setup_driver()
    runtime = assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')
    driver._ctx.pilot_runtime = runtime
    session.workspace_root = str(tmp_path)
    body['messages'] += [
        {'role': 'assistant', 'tool_calls': [{'id': 'historical-read', 'type': 'function',
         'function': {'name': 'read_file', 'arguments': '{"path":"source.txt"}'}}]},
        {'role': 'tool', 'tool_call_id': 'historical-read', 'content': observed},
        {'role': 'assistant', 'content': 'historical read-only discussion\n' * 1800},
        {'role': 'user', 'content': 'Continue the original task.'}]
    if changed:
        source.write_text('later independently changed source\n')
    posts = []
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        reply = loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"source.txt"}'}}])
        return io.BytesIO(json.dumps(reply).encode())
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        driver.drive(body, 'driver-fixture', None, _Rlog())
    finally:
        wsview.unbind(token)
    assert len(posts) == 1
    notes = [m['content'] for m in posts[0]['messages']
             if str(m.get('content') or '').startswith('⟦ctx:compacted⟧')]
    assert notes, 'the actual final wire must exercise the pressure-driven history writer'
    assert all('workspace has moved on since' not in note for note in notes)
    assert all(prompts.load('compacted_history_provenance').strip() in note for note in notes)
    assert source.read_text() == ('later independently changed source\n' if changed else observed)
    assert not session.plan.items[0].done


@pytest.mark.parametrize('state', ['unchanged', 'changed', 'deleted'])
@pytest.mark.parametrize('wire', [False, True])
def test_historical_modified_paths_do_not_certify_current_existence(tmp_path, monkeypatch, state, wire):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'historical.txt'
    source.write_text('recorded write\n')
    history = [
        {'role': 'assistant', 'tool_calls': [{'id': 'historical-write', 'type': 'function',
         'function': {'name': 'write_file', 'arguments': json.dumps(
             {'path': 'historical.txt', 'content': 'recorded write\n'})}}]},
        {'role': 'tool', 'tool_call_id': 'historical-write', 'content': 'Wrote historical.txt'},
        {'role': 'assistant', 'content': 'historical discussion\n' * 1800}]
    if state == 'changed':
        source.write_text('independent replacement\n')
    elif state == 'deleted':
        source.unlink()
    before = source.read_bytes() if source.exists() else None
    if wire:
        driver, session, body = setup_driver()
        driver._ctx.pilot_runtime = assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')
        session.workspace_root = str(tmp_path)
        body['messages'] += history + [{'role': 'user', 'content': 'Continue the original task.'}]
        posts = []
        def transport(request, **options):
            if not request.full_url.endswith('/v1/chat/completions'):
                return io.BytesIO(b'{"tokens":[1],"data":[]}')
            posts.append(json.loads(request.data))
            reply = loop._completion_toolcalls([{'id': 'next', 'type': 'function',
                'function': {'name': 'read_file', 'arguments': '{"path":"historical.txt"}'}}])
            return io.BytesIO(json.dumps(reply).encode())
        monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
        token = wsview.bind(wsview.DirectView(str(tmp_path)))
        try:
            driver.drive(body, 'driver-fixture', None, _Rlog())
        finally:
            wsview.unbind(token)
        assert len(posts) == 1
        notes = [m['content'] for m in posts[0]['messages']
                 if str(m.get('content') or '').startswith('⟦ctx:compacted⟧')]
        assert not session.plan.items[0].done
    else:
        notes = [contextfloor._compacted_note(history, len(history), 8000)['content']]
    assert notes and any('Files modified in them' in note and 'historical.txt' in note for note in notes)
    assert all('still on disk' not in note for note in notes)
    assert (source.read_bytes() if source.exists() else None) == before
