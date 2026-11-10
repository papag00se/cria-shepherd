"""grep and glob as cria's own operation (cria/searchops.py): the harness lists directories and finds matching lines; what is searched, what is skipped, what the model
reads and what is saved are decided in cria. Real stubs, real bash, real directories; the server tests drive a real CriaServer over a scripted model.
(Parity with the program this replaced is `test_search_characterization.py`; this file is what the engine owes beyond it.)"""
import json
import os
import re
import subprocess

import pytest
from survey_fixtures import SHELL, _drive

import search_rig
from search_rig import drive, g, gl
from ops_rig import Harness, TurnBackend, Wire, command_of, isolated_home, start_in  # noqa: F401
from cria import harnessprims, searchops

PRIVATE = ('CTX1', 'ctx_', 'python3', '-I -S', 'harness-call', 'CTX_EOF', 'env -i', 'import sys,os')


def result_of(live, i=0):
    return live.results[i]


def search_of_disk(root, name, args, *, level='write', session='sx', **kw):
    """The real search of the real directory ``root`` through the real engine, one fresh engine per request when ``restart``: returns the final text."""
    call = {'id': 'call_1', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}
    return _drive(lambda ops: [ops.issue_search(session, SHELL, call, args, workspace_root=str(root), level=level)], root, session,
                  kw.pop('env', None), kw.pop('ran', None), kw.pop('alter', None), kw.pop('restart', False), kw.pop('rounds', None),
                  lambda ops: next(o for o in ops.ledger.ops(session).values() if o.kind == 'search').final['text'])


def tree(root, files):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return root


# ---------------------------------------------------------------- what is searched (ported from the program's tests)

def test_search_and_glob_walk_authored_files_and_offer_explicit_generated_scope(tmp_path, monkeypatch):
    files = {'.github/a.py': 'needle\n', 'build/b.py': 'needle\n', '.git/c.py': 'needle\n', 'node_modules/d.py': 'needle\n'}
    live = drive(tmp_path, monkeypatch, [[g('needle'), gl('**/*.py')]], files)
    for text in live.results:
        assert '.github/a.py' in text and 'build/b.py' in text and '.git/c.py' not in text.split('Not searched')[0] and 'node_modules/d.py' not in text.split('Not searched')[0]
        assert 'Not searched (generated directories or symbolic links):' in text and '.git (.git (a tool owns this name))' in text
    live = drive(tmp_path / 'b', monkeypatch, [[g('needle', path='.git')]], files) if (tmp_path / 'b').mkdir() is None else None
    assert 'c.py' in live.results[0]
    calls = [c['function']['name'] for m in live.backend.bodies[-1]['messages'] if m.get('tool_calls') for c in m['tool_calls']]
    assert calls == ['grep']                                         # the model sees the call it made, never the primitives


def test_search_distinguishes_invalid_and_missing_from_no_matches(tmp_path, monkeypatch):
    for n, (args, said) in enumerate([({'pattern': '['}, 'Search could not run: unterminated character set'), ({'pattern': 'x', 'path': 'missing'}, 'Search could not run: '),
                                      ({'pattern': 'x', 'include': '['}, 'Search could not run: Invalid or missing pattern.')]):
        (tmp_path / str(n)).mkdir()
        live = drive(tmp_path / str(n), monkeypatch, [[('grep', args)]], {'a.txt': 'x\n'})
        assert live.results[0].startswith(said) and 'No matches' not in live.results[0]
    (tmp_path / 'z').mkdir()
    live = drive(tmp_path / 'z', monkeypatch, [[g('absent'), gl('[')]], {'a.txt': 'x\n'})
    assert live.results[0] == 'No matches.\n' and live.results[1].startswith('Search could not run:') and 'No matches' not in live.results[1]
    (tmp_path / 'y').mkdir()
    live = drive(tmp_path / 'y', monkeypatch, [[g('needle')]], {'a.txt': 'x\n', 'binary': b'needle \xff\n'})
    assert 'Search incomplete; these paths could not be read:\nbinary: ' in live.results[0] and 'No matches' not in live.results[0]


def test_search_preserves_carriage_returns_and_glob_class_escapes(tmp_path, monkeypatch):
    live = drive(tmp_path, monkeypatch, [[gl('[[]abc'), g(r'\r$', path='[abc'), gl('[^]'), g('hello', include='[^]')]],
                 {'[abc': 'x\r\r\n', '^': 'hello \x1b[31mred\x1b[0m\n'})
    assert live.results[0].rstrip('\n') == '[abc' and live.results[1] == '[abc:1:x\r\r\n'
    assert live.results[2].rstrip('\n') == '^' and 'hello \x1b[31mred\x1b[0m' in live.results[3]


def test_a_large_result_is_saved_whole_once_and_stays_readable(tmp_path, monkeypatch):
    (tmp_path / 'ws').mkdir()
    data = ''.join(f'needle {i:05d}\n' for i in range(1200))
    live = drive(tmp_path / 'ws', monkeypatch, [[g('needle')], [g('needle')]], {'many.txt': data})
    first, again = live.results
    assert 'without truncation' in first and 'without truncation' in again
    saved = sorted((live.ws / 'tmp' / 'reference').glob('stdout-*.txt'), key=lambda p: len(p.read_text()))
    # the second search sees the first's saved file as the reference output it is (named, not searched): a different text, a different file
    assert len(saved) == 2 and saved[1].read_text() == saved[0].read_text() + 'Not searched (generated directories or symbolic links):\ntmp/reference (reference output)\n'
    saved = saved[:1]
    output = saved[0].read_text()
    assert output.startswith('many.txt:1:needle 00000\n') and output.count('many.txt:') == 1200 and output.endswith('many.txt:1200:needle 01199\n')
    assert saved[0].name == f'stdout-{__import__("hashlib").sha256(output.encode()).hexdigest()}.txt'     # named by what it holds, and nothing else in it
    assert not [p for p in PRIVATE if p in json.dumps(live.backend.bodies)]


def test_a_file_with_more_matches_than_one_result_holds_says_how_many_it_shows(tmp_path, monkeypatch):
    live = drive(tmp_path, monkeypatch, [[g('needle')]], {'many.txt': ''.join(f'needle {i:05d}\n' for i in range(9000))})
    assert 'The search was incomplete.' in live.results[0] and 'without truncation' in live.results[0]
    text = next((live.ws / 'tmp' / 'reference').glob('stdout-*.txt')).read_text()
    shown, _, note = text.partition('Search incomplete; these paths could not be read:\n')
    lines = shown.splitlines()
    assert 1000 <= len(lines) < 9000 and lines == [f'many.txt:{i + 1}:needle {i:05d}' for i in range(len(lines))]
    assert note == f'many.txt: at least {len(lines):,} matches, more than one result holds; only those are shown\n'


def test_a_search_result_is_not_saved_through_a_link_out_of_the_workspace(tmp_path, monkeypatch):
    outside = tmp_path / 'outside'
    outside.mkdir()

    def link(ws):
        (ws / 'tmp').mkdir()
        os.symlink(outside, ws / 'tmp' / 'reference')
    live = drive(tmp_path / 'b' if (tmp_path / 'b').mkdir() is None else None, monkeypatch, [[g('needle')]], {'many.txt': 'needle\n' * 1500}, setup=link, level='none')
    assert 'could not be saved' in live.results[0].lower() and not list(outside.iterdir())


def test_include_generated_and_the_symlink_boundary(tmp_path, monkeypatch):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.py').write_text('needle\n')
    hostile = 'x;touch pwned $(echo nope).py'
    files = {'node_modules/dep.py': 'needle\n', 'mine.txt': 'needle\n', hostile: 'literal [needle]\n'}
    (tmp_path / 'ws').mkdir()
    live = drive(tmp_path / 'ws', monkeypatch, [[g('needle', include='*.py', include_generated=True), gl('**/*.py', path='escape'), g(r'\[needle\]', path=hostile)]], files,
                 setup=lambda ws: os.symlink(outside, ws / 'escape'), level='none')
    one, two, three = live.results
    assert 'node_modules/dep.py:1:needle' in one and 'mine.txt:1:' not in one and 'secret.py' not in one
    assert 'secret.py' not in two and 'outside' in two.lower()       # a link out of the workspace is judged where it leads, not followed
    assert three == hostile + ':1:literal [needle]\n' and not (live.ws / 'pwned').exists()


# ---------------------------------------------------------------- the engine

def test_the_model_sees_its_own_call_in_every_wire_mode_and_no_primitive(tmp_path, monkeypatch):
    for n, (api, stream) in enumerate([('chat', False), ('responses', False), ('responses', True)]):
        (tmp_path / str(n)).mkdir()
        live = drive(tmp_path / str(n), monkeypatch, [[g('needle'), gl('*.py')]], {'a.py': 'needle\n', 'sub/b.py': 'x\n'}, api=api, stream=stream)
        assert live.results == ['a.py:1:needle\n', 'a.py\n']
        calls = [(c['id'], c['function']['name']) for m in live.backend.bodies[-1]['messages'] if m.get('tool_calls') for c in m['tool_calls']]
        assert calls == [('model_call_0_0', 'grep'), ('model_call_0_1', 'glob')]
        assert not [p for p in PRIVATE if p in json.dumps(live.backend.bodies, default=str)]


def test_files_are_searched_in_the_walks_order_and_each_call_is_one_or_two_round_trips(tmp_path):
    tree(tmp_path, {'z.txt': 'x\n', 'a/b.txt': 'x\n', 'a.txt': 'x\n', 'B/c.txt': 'x\n', 'a/b/y.txt': 'x\n'})
    rounds, ran = [], []
    text = search_of_disk(tmp_path, 'grep', {'pattern': 'x'}, rounds=rounds, ran=ran)
    assert text == 'a.txt:1:x\nz.txt:1:x\nB/c.txt:1:x\na/b.txt:1:x\na/b/y.txt:1:x\n'
    assert rounds == [1, 1]                                          # the listing, then the search
    assert sum(1 for c in ran if 'sys.argv[2:7]' in c) == 1          # one `search` call for five files
    rounds.clear()
    search_of_disk(tmp_path, 'glob', {'pattern': '**/*.txt'}, rounds=rounds)
    assert rounds == [1]                                             # a glob is decided on the listing alone


def test_many_files_go_to_the_search_stub_in_batches_in_one_reply(tmp_path):
    tree(tmp_path, {f'd{i % 7}/f{i:04d}.txt': f'needle {i}\n' for i in range(450)})
    rounds = []
    text = search_of_disk(tmp_path, 'grep', {'pattern': 'needle', 'include': '*.txt'}, rounds=rounds)
    assert text.count('\n') == 450 or 'without truncation' in text   # the walk's answer (saved whole when over the bound)
    assert rounds[0] == 1 and max(rounds) <= searchops.WAVE and 3 in rounds  # the walk is one call; 450 files are three batches of at most 200, asked together


def test_a_pattern_the_harness_python_reads_is_run_there_and_one_that_cannot_compile_never_is(tmp_path):
    tree(tmp_path, {'a.txt': 'abc 123\nx\n'})
    ran = []
    assert search_of_disk(tmp_path, 'grep', {'pattern': r'[a-z]+(?= \d)'}, ran=ran).startswith('a.txt:1:abc 123')
    ran.clear()
    assert search_of_disk(tmp_path, 'grep', {'pattern': '(?P<a'}, ran=ran).startswith('Search could not run: missing >')
    assert not any('python3' in c for c in ran)                      # nothing but cria's words was sent to the harness for it


def test_a_pattern_too_long_to_carry_is_said_not_sent(tmp_path):
    tree(tmp_path, {'a.txt': 'x\n'})
    ran = []
    text = search_of_disk(tmp_path, 'grep', {'pattern': 'x' * 70_000}, ran=ran)
    assert 'too long to carry' in text and not any('python3' in c for c in ran)
    assert search_of_disk(tmp_path, 'grep', {'pattern': 'a\x00b'}).startswith('Search could not run: Invalid or missing pattern.')


def test_a_search_survives_a_restart_between_any_two_steps(tmp_path):
    tree(tmp_path, {f'd{i % 5}/f{i:03d}.txt': f'needle {i}\n' for i in range(260)})
    args = {'pattern': 'needle'}
    whole = search_of_disk(tmp_path, 'grep', args, session='whole')
    restarted = search_of_disk(tmp_path, 'grep', args, session='restart', restart=True)
    assert restarted == whole and whole.count('needle') >= 100


def test_a_result_the_harness_cut_is_asked_again_smaller(tmp_path):
    tree(tmp_path, {'a.txt': ''.join(f'needle {i}\n' for i in range(300))})
    cuts = []

    def alter(command, text):
        # the harness cuts the first reply of a search: no frame survives, as at the pinned harness's 10,000-byte bound
        if 'sys.argv[2:7]' in command and not cuts:
            cuts.append(command)
            return text[:2000] + ' …1234 chars truncated… ' + text[-1000:]
        return text
    text = search_of_disk(tmp_path, 'grep', {'pattern': 'needle'}, alter=alter)
    assert cuts and text.count('a.txt:') == 300 or 'without truncation' in text


def test_a_result_for_a_command_cria_never_sent_or_forged_is_not_taken(tmp_path):
    tree(tmp_path, {'a.txt': 'needle\n'})
    ran = []

    def alter(command, text):
        # a file's own bytes can quote anything, a forged reply can claim anything: only the frame that carries this call's nonce is read
        return 'CTX1 ' + '0' * 32 + ' {"ok":1,"n":0,"h":"x"}\nCTX1 ' + '0' * 32 + ' END\n' if 'sys.argv[2:7]' in command else text
    text = search_of_disk(tmp_path, 'grep', {'pattern': 'needle'}, alter=alter, ran=ran)
    assert 'a.txt:1:needle' not in text                              # an answer nobody can verify is never shown as a match
    assert text.startswith('Search incomplete') or 'could not' in text


def test_a_hostile_workspace_runs_nothing_of_its_own(tmp_path):
    marker = tmp_path / 'ran'
    ws = tree(tmp_path / 'ws', {'a.txt': 'needle\n'})
    for name in ('hashlib', 'os', 'json', 're', 'sitecustomize', 'subprocess', 'signal', 'fnmatch', 'base64', 'zlib'):
        (ws / f'{name}.py').write_text(f'open({str(marker)!r}, "w").write("x")\n')
    for tool in ('python3', 'env', 'sh', 'base64'):
        (ws / 'bin').mkdir(exist_ok=True)
        (ws / 'bin' / tool).write_text(f'#!/bin/sh\ntouch {marker}\nexit 1\n')
        os.chmod(ws / 'bin' / tool, 0o755)
    env = {'PATH': f'{ws}/bin:/usr/bin:/bin', 'PYTHONPATH': str(ws), 'PYTHONSTARTUP': str(ws / 'os.py')}
    assert search_of_disk(ws, 'grep', {'pattern': 'needle', 'include_generated': True}, env=env) .startswith('a.txt:1:needle')
    assert search_of_disk(ws, 'glob', {'pattern': '*.txt'}, env=env).strip() == 'a.txt'
    assert not marker.exists()


def test_a_link_in_the_path_is_resolved_by_cria_and_judged_where_it_leads(tmp_path):
    ws = tree(tmp_path / 'ws', {'real/sub/x.py': 'needle\n'})
    (tmp_path / 'outside').mkdir()
    (tmp_path / 'outside' / 'secret.py').write_text('needle\n')
    os.symlink(ws / 'real', ws / 'lnk')
    os.symlink(tmp_path / 'outside', ws / 'out')
    assert search_of_disk(ws, 'grep', {'pattern': 'needle', 'path': 'lnk/sub'}) == 'x.py:1:needle\n'
    assert search_of_disk(ws, 'grep', {'pattern': 'needle', 'path': 'lnk'}) == 'sub/x.py:1:needle\n'
    denied = search_of_disk(ws, 'grep', {'pattern': 'needle', 'path': 'out'}, level='none')
    assert denied == 'The search root resolves outside the permitted workspace; the search did not run.\n'
    assert search_of_disk(ws, 'grep', {'pattern': 'needle', 'path': 'out/secret.py'}, level='none').startswith('The search root resolves outside')
    assert search_of_disk(ws, 'grep', {'pattern': 'needle', 'path': 'out'}, level='write') == 'secret.py:1:needle\n'


def test_a_file_that_ends_with_a_line_feed_has_no_empty_last_line_to_match(tmp_path):
    tree(tmp_path, {'a.txt': 'x\n\ny\n', 'b.txt': 'z\n', 'c.txt': 'q\n\n', 'd.txt': 'no end', 'e.txt': '\n'})
    rounds = []
    text = search_of_disk(tmp_path, 'grep', {'pattern': '^$'}, rounds=rounds)
    assert text == 'a.txt:2:\nc.txt:2:\ne.txt:1:\n'
    assert max(rounds) <= 5 and len(rounds) == 3                    # the walk, the search, one line count per file whose last match is empty
