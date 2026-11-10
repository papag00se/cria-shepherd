"""A harness that sends no session header: every request of a conversation reaches the SAME ledger, so a listing issued after an
earlier operation is still projected away (phase 3 review B2: the read bridge's anonymous-session resolution split the two)."""
import json

import pytest

from ops_rig import Harness, TurnBackend, Wire, isolated_home, start_in  # noqa: F401

PRIVATE = ('CTX1', 'ctx_', 'python3', '-I -S', 'harness-call', 'CTX_EOF', 'env -i')


@pytest.mark.parametrize('api,stream', [('chat', False), ('responses', False), ('responses', True)])
def test_a_headerless_conversation_never_shows_the_model_a_primitive_call_or_frame(tmp_path, api, stream):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'a.txt').write_text('hello\n')
    backend = TurnBackend([('read_file', {'path': str(ws / 'a.txt')})], [('list_dir', {'path': str(ws)})])
    with start_in(Wire(tmp_path, backend, api, stream, header=False), ws) as w:
        message, _ = w.drive(Harness(ws))
        assert 'seen' in message['content'] and len(backend.bodies) == 3
        sent = json.dumps(backend.bodies, default=str)
        assert not [p for p in PRIVATE if p in sent]
        results = [m['content'] for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool']
        assert results[0] == 'hello\n' and results[1].endswith('a.txt')
