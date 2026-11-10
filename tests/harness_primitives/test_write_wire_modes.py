"""write_file / edit_file in every wire mode the harness may speak (Chat Completions, Responses buffered and streamed): the same model-visible results,
the model's own calls restored in the replayed history, and nothing private in any body it receives."""
import json

import pytest

import ops_rig
from ops_rig import Harness, TurnBackend, isolated_home, start_in  # noqa: F401

PRIVATE = ('CTX1', 'ctx_', 'python3', '-I -S', 'harness-call', 'CTX_EOF', 'env -i')


@pytest.mark.parametrize('api,stream', [('chat', False), ('responses', False), ('responses', True)])
def test_a_turn_of_writes_and_edits_reads_the_same_in_every_wire_mode(tmp_path, api, stream):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 't.txt').write_text(''.join(f'row {i} = {i}\n' for i in range(20)))
    backend = TurnBackend(
        [('write_file', {'path': 'new/a.txt', 'content': 'hello\n'}),
         ('edit_file', {'path': 't.txt', 'old_string': 'row 3 = 3', 'new_string': 'row 3 = THREE'}),
         ('edit_file', {'path': 't.txt', 'old_string': 'row 99 = 99', 'new_string': 'x'}),
         ('edit_file', {'path': 't.txt', 'old_string': 'row 5 = 5', 'new_string': 'row 5 = FIVE'}),
         ('write_file', {'path': 'broken.json'})],            # a call cut off before its content: refused in cria's words, never run
        [('edit_file', {'path': 't.txt', 'old_string': 'row 3 = THREE', 'new_string': 'row 3 = 3'})])
    wire = ops_rig._BaseWire(tmp_path, backend, api, stream)
    with start_in(wire, ws) as live:
        message, _ = live.drive(Harness(ws))
    assert 'seen' in message['content']
    assert (ws / 'new' / 'a.txt').read_text() == 'hello\n'
    assert (ws / 't.txt').read_text().splitlines()[3:6] == ['row 3 = 3', 'row 4 = 4', 'row 5 = FIVE']
    shown = {m['tool_call_id']: m['content'] for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool'}
    first = [shown[f'model_call_0_{i}'] for i in range(5)]
    assert first[0] == 'Wrote new/a.txt' and first[1] == 'Wrote t.txt' and first[3] == 'Wrote t.txt'
    assert 'not in the file' in first[2] and first[4].startswith('⟦ctx:denied⟧ Your write_file call has no `content` value')
    assert shown['model_call_1_0'] == 'Wrote t.txt'
    calls = [(c['id'], c['function']['name']) for m in backend.bodies[-1]['messages'] if m.get('tool_calls') for c in m['tool_calls']]
    assert calls == [(f'model_call_0_{i}', n) for i, n in enumerate(['write_file', 'edit_file', 'edit_file', 'edit_file', 'write_file'])] + [('model_call_1_0', 'edit_file')]
    assert not [p for p in PRIVATE if p in json.dumps(backend.bodies, default=str)]
