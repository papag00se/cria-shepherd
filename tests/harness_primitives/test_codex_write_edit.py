"""write_file / edit_file through the pinned Codex in its sandbox (docs/harness-programs.md, Phase 5): scripted model -> real CriaServer -> real
pinned Codex -> real `write`, `put`, `read`, `run` stubs, in a real workspace; and what a write costs the harness per round trip."""
import json
import os
import statistics
import threading

import pytest

from cria import harnessprims
from codex_rig import Sandbox, needs_codex
from ops_rig import TurnBackend, isolated_home  # noqa: F401
from prims_rig import GROUP, sha
from test_codex_primitives import Scripted

pytestmark = needs_codex

PRIVATE = ('CTX1', 'ctx_', 'python3', '-I -S', 'harness-call', 'CTX_EOF', 'env -i')
HEX = ''.join('%08x\n' % (i * 2654435761 % 2**32) for i in range(5000))            # 45,000 bytes
ROWS = ''.join(f'row {i} = {i}\n' for i in range(60))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    return Sandbox(tmp_path, monkeypatch)


def serve(sandbox, tmp_path, backend):
    from cria.config import Config, IndicatorsConfig, LoggingConfig, RoutingConfig, ServerConfig
    from cria.events import EventLog
    from cria.server import CriaServer
    cfg = Config(server=ServerConfig(host='127.0.0.1', port=0), logging=LoggingConfig(dir=str(tmp_path / 'logs'), console=False),
                 indicators=IndicatorsConfig(enabled=False), routing=RoutingConfig(engagement_level=2))
    log = EventLog(dir=cfg.logging.dir, console=False)
    server = CriaServer(cfg, log, backend)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        done = sandbox.run(f'http://127.0.0.1:{server.server_address[1]}/v1', timeout=600)
        assert done.returncode == 0, done.stderr[-2000:]
    finally:
        server.shutdown()
        server.server_close()
        log.close()


def test_write_and_edit_through_the_pinned_codex_and_a_real_cria_server(sandbox, tmp_path):
    """Nothing imitated. A new file, an overwrite, a cold edit, a batch of 30 edits to one file, a unique-miss, an edit that would break a
    parsing file, a 45,000-byte write (one command), a 150 KB and a 300 KB write (past the argument limit: staged by `put` and committed
    by one `write`), a write through a link inside the workspace and one through a link out of it. The files are what was sent, the model
    reads cria's own words, nothing private reaches it, and the file outside the workspace is untouched."""
    ws = sandbox.workspace
    outside = tmp_path / 'outside.txt'
    outside.write_text('OUTSIDE ORIGINAL\n')
    (ws / 'a.txt').write_text('before\n')
    (ws / 'a.py').write_text('def f():\n    return 1\n')
    (ws / 't.txt').write_text(ROWS)
    (ws / 'real.txt').write_text('real\n')
    (ws / 'inside').symlink_to('real.txt')
    (ws / 'out').symlink_to(outside)
    big150, big300 = ''.join(f'line {i} of a big file, with some words in it\n' for i in range(3300)), ''.join(f'line {i} of the big file, with some words\n' for i in range(7000))
    assert 140_000 < len(big150.encode()) < 160_000 and len(big300.encode()) > 280_000
    backend = TurnBackend(
        [('write_file', {'path': 'src/new.py', 'content': 'x = 1\n'}), ('write_file', {'path': 'a.txt', 'content': 'after\n'}),
         ('edit_file', {'path': 'a.py', 'old_string': 'return 1', 'new_string': 'return 2'}),
         ('edit_file', {'path': 'a.py', 'old_string': 'return 2', 'new_string': 'return (2'}),
         ('edit_file', {'path': 'a.py', 'old_string': 'not in the file at all', 'new_string': 'x'})],
        [('edit_file', {'path': 't.txt', 'old_string': f'row {i} = {i}\n', 'new_string': f'row {i} = {i + 1000}\n'}) for i in range(30)],
        [('write_file', {'path': 'big45.txt', 'content': HEX}), ('write_file', {'path': 'big150.txt', 'content': big150}),
         ('write_file', {'path': 'big300.txt', 'content': big300})],
        [('write_file', {'path': 'inside', 'content': 'through the link\n'}), ('write_file', {'path': 'out', 'content': 'ESCAPED\n'})],
        [('write_file', {'path': 'r.rb', 'content': 'def a\n  1\nend\n'})],
        [('write_file', {'path': 'r.rb', 'content': 'def a(\n  1\nend\n'})])
    serve(sandbox, tmp_path, backend)
    assert (ws / 'src' / 'new.py').read_text() == 'x = 1\n' and (ws / 'a.txt').read_text() == 'after\n'
    assert (ws / 'a.py').read_text() == 'def f():\n    return 2\n'
    assert (ws / 't.txt').read_text() == ''.join(f'row {i} = {i + (1000 if i < 30 else 0)}\n' for i in range(60))
    assert (ws / 'big45.txt').read_text() == HEX and (ws / 'big150.txt').read_text() == big150 and (ws / 'big300.txt').read_text() == big300
    assert (ws / 'inside').is_symlink() and (ws / 'real.txt').read_text() == 'through the link\n'
    assert outside.read_text() == 'OUTSIDE ORIGINAL\n'                                              # the link out of the workspace was refused
    assert not [p for p in os.listdir(ws) if p.startswith('.ctx')] and not [p for p in os.listdir(ws / 'src') if p.startswith('.ctx')]
    first = {m['tool_call_id']: m['content'] for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool'}
    results = [first[f'model_call_{t}_{i}'] for t, n in enumerate((5, 30, 3, 2)) for i in range(n)]
    assert results[:2] == ['Wrote src/new.py', 'Wrote a.txt'] and results[2] == 'Wrote a.py'
    assert 'would break a.py' in results[3] and 'your old_string is not in the file' in results[4]
    assert results[5:35] == ['Wrote t.txt'] * 30 and results[35:38] == ['Wrote big45.txt', 'Wrote big150.txt', 'Wrote big300.txt']
    assert results[38] == 'Wrote inside' and results[39].startswith('⟦ctx:denied⟧') and 'outside the project directory' in results[39]
    ruby = [first['model_call_4_0'], first['model_call_5_0']]                                   # the harness's own `ruby -c`, through `run`, in the sandbox
    shutil_ruby = __import__('shutil').which('ruby')
    if shutil_ruby:
        assert ruby[0] == 'Wrote r.rb' and ruby[1].startswith('⟦ctx:denied⟧ write_file REFUSED') and 'r.rb:' in ruby[1] and 'cand.rb' not in ruby[1]
        assert (ws / 'r.rb').read_text() == 'def a\n  1\nend\n'
        assert not [n for n in os.listdir(sandbox.scratch) if n.startswith('.ctx-run-')]
    seen = json.dumps(backend.bodies, default=str)
    assert not [p for p in PRIVATE if p in seen], [p for p in PRIVATE if p in seen]


def test_write_round_trip_latency_through_the_sandboxed_harness(sandbox):
    """What a `write` costs the real pinned Codex: a 1.4 KB whole write, a 45,000-byte one (a 62.9 KB command) and a splice edit of a
    larger file (a ~3 KB command), 20 sequential calls each."""
    ws = str(sandbox.workspace)
    body = ''.join(f'line {i} of a file that is edited by a splice\n' for i in range(5000)).encode()
    for i in range(20):
        (sandbox.workspace / f'edit{i}.txt').write_bytes(body)
    small, big = b'x' * 1400, HEX.encode()
    commands = [harnessprims.compose('write', '%032x' % (400 + i), [ws, f's{i}.txt', '*', '-', sha(small), 0, 1, GROUP], small, comment='write_file') for i in range(20)]
    commands += [harnessprims.compose('write', '%032x' % (500 + i), [ws, f'b{i}.txt', '*', '-', sha(big), 0, 1, GROUP], big, comment='write_file') for i in range(20)]
    start, end, new = body.index(b'line 2500'), body.index(b'line 2500') + 9, b'LINE 2500'
    spliced = body[:start] + new + body[end:]
    for i in range(20):
        commands.append(harnessprims.compose('write', '%032x' % (600 + i), [ws, f'edit{i}.txt', sha(body), json.dumps([[start, end, len(new)]]), sha(spliced), 0, 0, GROUP], new, comment='edit_file'))
    with Scripted(commands) as server:
        done = sandbox.run(server.url)
        assert done.returncode == 0, done.stderr[-2000:]
        seconds = server.timeline.seconds
    assert len(seconds) >= 59
    small_t, big_t, edit_t = sorted(seconds[:20]), sorted(seconds[20:40]), sorted(seconds[40:60])
    print('LATENCY write 1.4 KB: median=%.3f p90=%.3f max=%.3f | write 45,000 B: median=%.3f p90=%.3f max=%.3f | splice edit: median=%.3f p90=%.3f max=%.3f' % (
        statistics.median(small_t), small_t[17], small_t[-1], statistics.median(big_t), big_t[17], big_t[-1], statistics.median(edit_t), edit_t[17], edit_t[-1]))
    assert max(statistics.median(small_t), statistics.median(big_t), statistics.median(edit_t)) < 5
