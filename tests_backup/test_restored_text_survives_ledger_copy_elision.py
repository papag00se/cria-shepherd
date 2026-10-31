"""Whole-read credit follows exact delivered text, not a surviving stale hint."""
from cria.fetchfacts import Shape
import hashlib
import io
import json

import pytest
from cria import assistruntime, bodykeys, contextrestoration, ledgercopies, loop, modelview, prompts, wsview
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


UNIT = '  GET /report → ' + 'field_' * 45
TEXT = 'first\n' + UNIT + '\nmiddle\n' + UNIT + '\nlast\n'


def test_the_real_rank4_driver_keeps_repeated_restored_lines_and_credits_only_that_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'a.txt').write_text(TEXT)
    driver, session, body = setup_driver()
    session.workspace_root = str(tmp_path)
    session.read_files = {'a.txt': (1, '5 lines')}
    session.fetched_pages = {'https://example.test/spec': ('HTTP 200', ('/report',), (Shape(UNIT.strip()),), (), '')}
    driver._ctx.pilot_runtime = assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')
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
    restored = next(m['content'] for m in messages if modelview.RESTORED_MARKER in str(m.get('content')))
    assert TEXT in restored
    assert restored.count(UNIT) == 2
    assert session.restored_current == {'a.txt': hashlib.sha1(TEXT.encode()).hexdigest()}


def test_each_ordinary_copy_retains_its_position_and_resolves_to_exact_authoritative_lines():
    facts = {'https://example.test/spec': ('HTTP 200', ('/report',), (Shape(UNIT.strip()),), (), '')}
    ledger = loop._format_fetches(facts, location=False)
    original = TEXT + '\n\n\nfooter'
    messages = [{'role': 'tool', 'content': original},
                {'role': 'user', 'content': '⟦ctx:facts⟧\n' + ledger}]
    result = ledgercopies.elide(ledgercopies.LedgerCopyInput(messages, lambda: ledger))
    note = prompts.load('ledger_dedup_note')
    reduced = result.messages[0]['content']
    assert reduced.count(note) == 2
    reference = prompts.render('ledger_dedup_reference', NOTE=note,
                               ENTRY='- https://example.test/spec', FIRST=3, LAST=3, SPAN='')
    assert reduced.replace(reference, UNIT) == original
    assert result.messages[1] is messages[1]


@pytest.mark.parametrize('change', ['remove_repeat', 'replace', 'drop', 'unsigned'])
def test_wire_credit_rejects_modified_or_missing_authenticated_body(tmp_path, monkeypatch, change):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'a.txt').write_text(TEXT)
    view = wsview.DirectView(str(tmp_path))
    source = contextrestoration.RestoreInput(lambda: view,
        lambda: contextrestoration.FileHistory(('a.txt',), (), (), (), str, {}))
    result = contextrestoration.restore(source)
    assert result.offered
    assert modelview.settle_restored_text([result.message])[1] == result.offered
    message = dict(result.message)
    if change == 'remove_repeat':
        message['content'] = message['content'].replace(UNIT + '\n', '', 1)
    elif change == 'replace':
        message['content'] = 'different text'
    elif change == 'drop':
        message.pop('content')
    else:
        message[bodykeys.RESTORED_FILES] = {key: value for key, value in
            message[bodykeys.RESTORED_FILES].items() if key != 'content_sha256'}
    assert message[bodykeys.RESTORED_FILES]['offered'] == result.offered
    assert modelview.settle_restored_text([message])[1] == {}
