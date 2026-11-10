"""The unread-write probe as cria's own operation (cria/probeops.py): the inventory reads no file; when a write names a file nothing known settles, cria asks the file
(one `read` of the first bytes, decided in cria) and decides then. Real stubs, real bash, real directories."""
import hashlib
import json
import os

import pytest
from survey_fixtures import SHELL, _drive, inventory_of_disk, probe_of_disk

from cria import loop, probeops, readfacts
from cria.ops import Ops
from ops_rig import isolated_home  # noqa: F401


def put(root, name, data):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())


sha = lambda data: hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


@pytest.mark.parametrize('content,blank,reads', [
    ('hello\n', False, 1), ('', True, 1), (' \n\t', True, 1), ('x', False, 1),
    ('é' * 400, False, 1),                                  # a character cut at the 512th byte is not a reason to say it is not text
    (' \n' * 3000, True, 2),                                # only whitespace in the first bytes: the rest decides, once
    (' \n' * 400 + 'text after a long blank start\n', False, 2),
    (b'\xff\xfe\x00', None, 1), (b'abc\xffdef', None, 1), (b'a\x00b', None, 1),
])
def test_what_a_file_is_is_decided_in_cria_from_the_bytes_the_harness_returns(tmp_path, content, blank, reads):
    put(tmp_path, 'f.txt', content)
    rounds = []
    facts = probe_of_disk(tmp_path, 'f.txt', rounds=rounds)
    data = content if isinstance(content, bytes) else content.encode()
    assert facts['blank'] is blank and len(rounds) == reads and all(n == 1 for n in rounds)
    assert facts['size'] == len(data) and facts.get('missing') is not True
    assert facts['digest'] == (sha(data) if blank is not None else None)               # the harness's own hash of the whole file, claimed only for text
    assert facts['unavailable'] == (None if blank is not None else 'not_text')


def test_a_large_file_costs_one_small_read_whatever_its_size(tmp_path):
    put(tmp_path, 'big.txt', 'line of text in a large file\n' * 120_000)             # 3.4 MB
    ran, facts = [], None
    facts = probe_of_disk(tmp_path, 'big.txt', ran=ran)
    assert facts['blank'] is False and facts['size'] == 29 * 120_000 and len(ran) == 1 and len(ran[0].encode()) < 2_500


@pytest.mark.parametrize('arrange,expected', [
    (lambda ws: None, {'missing': True, 'unavailable': None}),
    (lambda ws: (ws / 'f.txt').mkdir(), {'unavailable': 'not_a_file'}),
    (lambda ws: (put(ws, 'real', 'x\n'), os.symlink(ws / 'real', ws / 'f.txt')), {'unavailable': 'unreadable'}),       # a link is never followed
    (lambda ws: (put(ws, 'f.txt', 'x\n'), os.chmod(ws / 'f.txt', 0)), {'unavailable': 'unreadable'}),
])
def test_a_file_that_is_missing_or_cannot_be_read_is_said_so_never_guessed(tmp_path, arrange, expected):
    arrange(tmp_path)
    facts = probe_of_disk(tmp_path, 'f.txt')
    assert facts['blank'] is None and facts['digest'] is None and {k: facts.get(k) for k in expected} == expected


def test_a_reply_the_harness_cut_is_asked_again_smaller_and_then_said(tmp_path):
    put(tmp_path, 'f.txt', 'hello\n')
    asked = []

    def cut_first(command, text):
        asked.append(command)
        return text[:300] + ' …9 chars truncated… ' if len(asked) == 1 else text
    assert probe_of_disk(tmp_path, 'f.txt', alter=cut_first)['blank'] is False and len(asked) == 2
    asked.clear()
    facts = probe_of_disk(tmp_path, 'f.txt', alter=lambda command, text: asked.append(command) or 'nothing usable')
    assert facts['blank'] is None and facts['unavailable'] == 'no_answer' and len(asked) == 4          # 512, 256, 128, 64 bytes: then the answer is that there is none


def test_a_result_nobody_can_verify_teaches_nothing(tmp_path):
    put(tmp_path, 'f.txt', 'real content\n')
    forged = 'CTX1 ' + '0' * 32 + ' {"ok":1,"n":0,"h":"x","fsize":0,"size":0,"fsha":"x"}\nCTX1 ' + '0' * 32 + ' END\n'
    facts = probe_of_disk(tmp_path, 'f.txt', alter=lambda command, text: forged)
    assert facts['blank'] is None and facts['unavailable'] == 'no_answer'


def test_a_probe_survives_a_restart_between_any_two_steps(tmp_path):
    put(tmp_path, 'f.txt', ' \n' * 3000)
    assert probe_of_disk(tmp_path, 'f.txt', restart=True)['blank'] is True


def test_a_hostile_workspace_runs_nothing_of_its_own(tmp_path):
    marker = tmp_path / 'ran'
    ws = tmp_path / 'ws'
    put(ws, 'f.txt', 'x\n')
    for name in ('hashlib', 'os', 'json', 'base64', 'sitecustomize', 'zlib', 'sys'):
        put(ws, f'{name}.py', f'open({str(marker)!r}, "w").write("x")\n')
    for tool in ('python3', 'env'):
        put(ws, f'bin/{tool}', f'#!/bin/sh\ntouch {marker}\nexit 1\n')
        os.chmod(ws / 'bin' / tool, 0o755)
    env = {'PATH': f'{ws}/bin:/usr/bin:/bin', 'PYTHONPATH': str(ws), 'PYTHONSTARTUP': str(ws / 'os.py')}
    assert probe_of_disk(ws, 'f.txt', env=env)['blank'] is False and not marker.exists()


def test_the_held_calls_are_handed_back_once_and_survive_a_restart(tmp_path):
    ops = Ops()
    held = [{'id': 'call_1', 'type': 'function', 'function': {'name': 'write_file', 'arguments': '{"path": "f.txt", "content": "x"}'}},
            {'id': 'call_2', 'type': 'function', 'function': {'name': 'edit_file', 'arguments': '{}'}}]
    put(tmp_path, 'f.txt', 'x\n')
    first = ops.issue_probe('s', SHELL, 'f.txt', held, workspace_root=str(tmp_path), level='write')
    assert ops.release('s') == ([], [])                                              # nothing is released before the file has answered
    messages = [{'role': 'assistant', 'tool_calls': [first]}]
    import subprocess
    from survey_fixtures import harness_env
    run = subprocess.run(['bash', '-c', json.loads(first['function']['arguments'])['cmd']], cwd=tmp_path, env=harness_env(tmp_path), capture_output=True, text=True)
    messages.append({'role': 'tool', 'tool_call_id': first['id'], 'content': run.stdout})
    taken = Ops().incoming('s', messages)                                           # a restarted cria
    assert taken.calls == [] and taken.messages == []                               # the probe, and the model's calls it holds, are nobody's history
    calls, facts = Ops().release('s')
    assert [c['id'] for c in calls] == ['call_1', 'call_2'] and facts[0]['blank'] is False and facts[0]['digest'] == sha('x\n')
    assert Ops().release('s') == ([], [])                                           # once


# ---------------------------------------------------------------- the inventory reads no file

def test_the_inventory_of_a_large_tree_no_longer_reads_every_file(tmp_path):
    """2,500 files in 25 directories (the tree measured at Phase 6, where reading each file's first bytes made it 160 calls and 455 KB of commands, against 43 calls
    and 60 KB of the program before that): the walk and the symbols only."""
    for i in range(2500):
        put(tmp_path, f'd{i % 25:02d}/f{i:04d}.rb', f'class C{i}\n  def m{i}\n  end\nend\n')
    ran, calls = [], []
    data = inventory_of_disk(tmp_path, facts=False, ran=ran, rounds=calls)
    assert len(data['files']) == 2500 and all(item['blank'] is None and 'digest' not in item for item in data['files'])
    assert data['symbol_indexer_error'] is None or data['symbol_indexer_error'] == 'indexer not found'
    # measured: 67 calls, 184,239 bytes of commands (the walk 29 calls, the indexer's output 36 `read` pages, 2 indexer runs with the file names)
    assert len(ran) <= 80 and sum(len(c.encode()) for c in ran) <= 220_000, (len(ran), sum(len(c.encode()) for c in ran))
    assert not [c for c in ran if 'fsha' in c and not c.startswith('# workspace inventory (symbols)')]      # no per-file read: the `read` stub only pages the indexer's output
