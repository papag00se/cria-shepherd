"""The config syntax floor and the survey's probe text through the pinned Codex in its sandbox (docs/harness-programs.md, Phase 9b): scripted model -> real
CriaServer -> real pinned Codex -> real `read`, `run`, `ls`, `rm` stubs in a real workspace. The floor is parsed in cria from files Codex's sandbox hands back
(nothing of it runs there); the survey's one straight-line shell text runs under Codex's own `bash -lc` and answers about its `PATH` and its paths."""
import json
import os

import pytest

from cria import privatepaths, surveyops, wsview
from codex_rig import Sandbox, needs_codex
from ops_rig import TurnBackend, isolated_home  # noqa: F401
from test_codex_gate import assert_nothing_left, run_gate
from test_codex_survey_inventory import PRIVATE, seed_workspace
from test_codex_write_edit import serve

pytestmark = needs_codex


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    return Sandbox(tmp_path, monkeypatch)


def ledger():
    return [json.loads(line) for f in (privatepaths.CRIA_HOME / 'ops').iterdir() for line in f.read_text().splitlines()]


def test_the_config_floor_is_read_through_the_sandbox_and_parsed_in_cria(sandbox, tmp_path):
    files = {'pyproject.toml': '[project\nname = "x"\n', 'package.json': '{"name": "x",}\n', 'app.py': 'x = 1\n'}
    events, seen, records = run_gate(sandbox, tmp_path, files)
    assert 'ctx:checks' in seen and 'pyproject.toml: Expected' in seen and 'package.json: Illegal trailing comma' in seen       # the model read the parsers' own words
    assert not [p for p in PRIVATE if p in seen] and 'tomllib' not in seen
    gate = next(r for r in records if r['t'] == 'op' and r['kind'] == 'gate' and any(f['cmd'][0] == 'toml-syntax' for f in r['ctx']['facts']))
    script = next(r['text'] for r in records if r['t'] == 'blob' and r['op'] == gate['op'])
    assert 'tomllib' not in script and 'toml-syntax' not in script and 'json-syntax' not in script and 'package.json' not in script      # the harness is told nothing of it
    reads = [r for r in records if r['t'] == 'step' and r['op'] == gate['op'] and r['what'] == 'fread']
    assert {r['args']['rel'] for r in reads} == {'pyproject.toml', 'package.json'}
    frames = {r['s']: r for r in records if r['t'] == 'frame' and r['op'] == gate['op']}
    assert all(frames[r['s']]['hdr'].get('ok') == 1 for r in reads)
    assert_nothing_left(sandbox, records)
    print('CONFIG FLOOR through the pinned Codex: %d read calls for 2 config files, %d steps in the whole gate' % (
        len(reads), len([r for r in records if r['t'] == 'step' and r['op'] == gate['op']])))


class Once(dict):
    """A table of questions every session has asked: they stand until the survey that is composed for them clears them (`wsview.clear_pending` stores the rest)."""
    def __init__(self, items):
        super().__init__()
        self.items = items

    def get(self, key, default=None):
        return super().get(key, default) if key in self else list(self.items)


def test_the_survey_asks_the_coders_shell_about_programs_and_paths_through_the_sandbox(sandbox, tmp_path, monkeypatch):
    ws = sandbox.workspace
    seed_workspace(ws)
    monkeypatch.setattr(wsview, '_PROG_MISSES', Once(['sh', 'no-such-program-zz', 'zruby']))
    monkeypatch.setattr(wsview, '_OUTSIDE_MISSES', Once(['/', '/nonexistent-zz', '~']))
    for name in ('zruby3.2', 'zruby3.10'):                                   # a versioned program on the coder's PATH, which the old script and the new text both find
        (sandbox.scratch / name).write_text('#!/bin/sh\n')
        (sandbox.scratch / name).chmod(0o755)
    monkeypatch.setenv('PATH', f'{sandbox.scratch}:{os.environ["PATH"]}')
    backend = TurnBackend([('write_file', {'path': 'new.rb', 'content': 'x = 1\n'})], [('list_dir', {'path': '.'})])
    serve(sandbox, tmp_path, backend)
    seen = json.dumps(backend.bodies, default=str)
    assert not [p for p in PRIVATE if p in seen] and 'compgen' not in seen and 'BASH_VERSION' not in seen
    records = ledger()
    survey = next(r['op'] for r in records if r['t'] == 'op' and r['kind'] == 'survey' and r['ctx']['progs'])
    run = next(r for r in records if r['t'] == 'step' and r['op'] == survey and r['what'] == 'vrun')
    frame = next(r for r in records if r['t'] == 'frame' and r['op'] == survey and r['s'] == run['s'])
    assert frame['hdr'].get('exit') == 0 and frame['hdr'].get('removed') == 1            # the text ran under Codex's bash and its run directory is gone
    ctx = next(r['ctx'] for r in records if r['t'] == 'op' and r['op'] == survey)
    answers = surveyops._resolved(frame['text'], ctx['progs'])
    assert answers['sh'] == 'sh' and answers['no-such-program-zz'] == '' and answers['zruby'] == 'zruby3.10', (answers, frame['text'])
    lines = {line.split('\t')[1]: line.split('\t')[2] for line in frame['text'].split('\n') if line.startswith('O\t')}
    assert lines[str(ctx['outside'].index('/'))] == 'd' and lines[str(ctx['outside'].index('/nonexistent-zz'))] == '-'
    assert not [n for n in os.listdir(ws) if n.startswith('.ctx')] and not [n for n in os.listdir(sandbox.scratch) if n.startswith('.ctx-run-')]
