"""grep, glob, web_fetch, web_search and the file they save, through the pinned Codex in its sandbox (docs/harness-programs.md, Phase 6b): scripted model -> real
CriaServer -> real pinned Codex -> real `ls`, `search`, `write`, `put` stubs, in a real workspace; and what the new calls cost the harness per round trip."""
import json
import os
import statistics
import threading

import pytest

import search_rig
from cria import brave, harnessprims, webfetch
from codex_rig import Sandbox, needs_codex
from ops_rig import TurnBackend, isolated_home  # noqa: F401
from prims_rig import GROUP, sha
from search_rig import BIGURL, URL, doc, f, g, gl, s, spec, web
from test_codex_primitives import Scripted
from test_codex_write_edit import serve

pytestmark = needs_codex

PRIVATE = ('CTX1', 'ctx_', 'python3', '-I -S', 'harness-call', 'CTX_EOF', 'env -i', 'base64 -d', '__CTX_SPILL__')


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    return Sandbox(tmp_path, monkeypatch)


def test_search_fetch_and_the_files_they_save_through_the_pinned_codex_and_a_real_cria_server(sandbox, tmp_path, monkeypatch):
    """Nothing imitated but the network. A grep and a glob over a tree (generated directories named and not searched), a grep whose answer is saved whole and
    pointed to, a link out of the workspace refused, a small page, a 250 KB page saved through `put` waves and one `write`, a search answered inline and one
    saved: the files are what cria held byte for byte, the model reads cria's words and nothing private reaches it, nothing is left beside the files."""
    ws = sandbox.workspace
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.py').write_text('needle\n')
    files = {'a.py': 'needle 1\nother\nneedle 2\n', 'sub/b.py': 'x\nneedle in sub\n', 'node_modules/d.py': 'needle\n', 'many.txt': ''.join(f'needle {i:05d}\n' for i in range(1200)),
             'huge.txt': ''.join(f'needle {i:05d} in a file with a great many matches\n' for i in range(20_000))}
    for rel, text in files.items():
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text(text)
    (ws / 'out').symlink_to(outside)
    big = spec(1100)
    docs = {URL: doc(200, 'Hello, world.\n'), BIGURL: doc(200, big, 'application/json')}
    answers = {'go decimal': web(search_rig.R5), 'ruby eu': web(search_rig.R20)}
    net = search_rig._Net({'docs': docs, 'brave': answers})
    monkeypatch.setattr(webfetch, 'fetch', net.fetch)
    monkeypatch.setattr(brave, 'search', net.search)
    monkeypatch.setattr(brave, 'api_key', lambda: 'k')
    webfetch.clear_cache()
    backend = TurnBackend([g('needle', include='*.py'), gl('**/*.py'), g('needle', path='many.txt'), g('needle', path='out', include_generated=True), g('needle', path='huge.txt')],
                          [f(), f(BIGURL), s('go decimal'), s('ruby eu')])
    serve(sandbox, tmp_path, backend)
    shown = [m['content'] for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool']
    assert shown[0].startswith('a.py:1:needle 1\na.py:3:needle 2\nsub/b.py:2:needle in sub\n') and 'node_modules (node_modules (a tool owns this name))' in shown[0]
    assert shown[1].startswith('a.py\nsub/b.py\n') and 'node_modules' in shown[1].split('Not searched')[1]
    assert 'complete result was saved without truncation to ./tmp/reference/stdout-' in shown[2]
    saved = next(p for p in (ws / 'tmp/reference').glob('stdout-*.txt') if p.read_text().startswith('many.txt:1:'))
    assert saved.read_text() == ''.join(f'many.txt:{i + 1}:needle {i:05d}\n' for i in range(1200))
    assert shown[3] == 'The search root resolves outside the permitted workspace; the search did not run.\n'      # a link is judged where it leads, not followed
    assert (outside / 'secret.py').read_text() == 'needle\n'
    assert 'complete result was saved without truncation to ./tmp/reference/stdout-' in shown[4] and 'incomplete' not in shown[4]
    huge = [p for p in (ws / 'tmp/reference').glob('stdout-*.txt') if p.read_text().startswith('huge.txt:1:')]
    assert len(huge) == 1 and huge[0].read_text() == ''.join(f'huge.txt:{i + 1}:needle {i:05d} in a file with a great many matches\n' for i in range(20_000))
    assert shown[5].startswith('HTTP 200 OK') and 'saved IN FULL to ./tmp/reference/docs.example.com_big.txt' in shown[6]
    whole = webfetch.spill_content(*webfetch.reduce_for_cache(big, 'application/json', BIGURL), 'application/json')
    assert (ws / 'tmp/reference/docs.example.com_big.txt').read_text() == whole and len(whole.encode()) > 250_000
    assert shown[7].startswith('5 results:\nResult 0\n') and shown[8].startswith('20 results:\n')
    assert (ws / webfetch.search_spill_name('ruby eu').removeprefix('./')).read_text().startswith('20 results:\n')
    assert not [p for p in os.listdir(ws / 'tmp/reference') if p.startswith('.ctx')]
    assert not [p for p in PRIVATE if p in json.dumps(backend.bodies, default=str)]


def test_ls_search_and_probe_round_trip_latency_through_the_sandboxed_harness(sandbox):
    """What the new calls cost the real pinned Codex: a 100-file `ls`, a `search` of 20 files, the 512-byte `read` that asks a file what it is, and a 45,000-byte
    `put` (one chunk of a saved page), 20 sequential calls each."""
    ws, scratch = str(sandbox.workspace), str(sandbox.scratch)
    for i in range(100):
        (sandbox.workspace / f'f{i:03d}.txt').write_text(f'needle {i}\nother line\n' * 40)
    names = [f'f{i:03d}.txt' for i in range(20)]
    commands = [harnessprims.compose('ls', '%032x' % (100 + i), [ws, '', 0, 1000, 0, '[]', ''], comment='list_dir .') for i in range(20)]
    commands += [harnessprims.compose('search', '%032x' % (200 + i), [ws, 'needle', 0, 4096, 1 << 25, 0], text=json.dumps(names), comment='grep needle') for i in range(20)]
    commands += [harnessprims.compose('read', '%032x' % (300 + i), [ws, 'f050.txt', 0, 512, 0], comment='unread-write check f050.txt') for i in range(20)]
    page = b'x' * harnessprims.CHUNK_BYTES                                              # one chunk of a saved page: the largest payload one command carries
    commands += [harnessprims.compose('put', '%032x' % (400 + i), [ws, '%032x' % (500 + i), 0], page, comment='web_fetch') for i in range(20)]
    with Scripted(commands) as server:
        done = sandbox.run(server.url)
        assert done.returncode == 0, done.stderr[-2000:]
        seconds = server.timeline.seconds
    assert len(seconds) >= 79
    groups = [sorted(seconds[i * 20:(i + 1) * 20]) for i in range(4)]
    print('LATENCY ls 100 files: median=%.3f p90=%.3f max=%.3f | search 20 files: median=%.3f p90=%.3f max=%.3f | read 512 B: median=%.3f p90=%.3f max=%.3f | '
          'put 45,000 B: median=%.3f p90=%.3f max=%.3f' % tuple(x for g_ in groups for x in (statistics.median(g_), g_[17], g_[-1])))
    assert max(statistics.median(g_) for g_ in groups) < 5
