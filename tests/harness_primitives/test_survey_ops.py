"""The workspace survey as cria's own operation (cria/surveyops.py): it is asked on cria's cadence, run through the primitives, decided in cria, and the model never
sees it. Real stubs, real bash, real directories; the server tests drive a real CriaServer over a scripted model."""
import json
import os
import stat

import pytest
from survey_fixtures import survey_of_disk

from cria import privatepaths, surveyops, wsview
from ops_rig import Harness, TurnBackend, Wire, command_of, isolated_home, start_in  # noqa: F401

SID = 'sid:sid'
PRIVATE = ('CTX1', 'ctx_', 'python3', '-I -S', 'harness-call', 'CTX_EOF', 'env -i', 'workspace survey')


@pytest.fixture(autouse=True)
def clean_questions():
    yield
    for table in (wsview._BODY_MISSES, wsview._PROG_MISSES, wsview._OUTSIDE_MISSES, wsview._BODY_CACHE, wsview._PROG_CACHE, wsview._BODY_ABSENT):
        table.clear()
    wsview._REFRESH.clear()


def ledger_kinds(home=None):
    f = next((privatepaths.CRIA_HOME / 'ops').iterdir())
    ops = {}
    for line in f.read_text().splitlines():
        r = json.loads(line)
        if r['t'] == 'op':
            ops[r['op']] = r['kind']
    return list(ops.values())


# ---------------------------------------------------------------- the cadence, through a real server

@pytest.mark.parametrize('api,stream', [('chat', False), ('responses', True)])
def test_a_survey_follows_the_write_that_lands_and_the_model_never_sees_it(tmp_path, api, stream):
    ws = tmp_path / 'ws'
    (ws / 'src').mkdir(parents=True)
    (ws / 'src' / 'a.py').write_text('x = 1\n')
    backend = TurnBackend([('write_file', {'path': 'new.py', 'content': 'y = 2\n'})])
    h = Harness(ws)
    with start_in(Wire(tmp_path, backend, api, stream), ws) as w:
        message, _ = w.drive(h)
        assert 'seen' in message['content'] and len(backend.bodies) == 2          # the model was asked twice: the survey is no model turn
        assert ledger_kinds() == ['mutate', 'survey']
        seen = json.dumps(backend.bodies)
        assert not [p for p in PRIVATE if p in seen]
        last = backend.bodies[-1]['messages']
        assert [m['role'] for m in last] == ['user', 'assistant', 'tool'] and last[2]['content'] == 'Wrote new.py'
        ran = [command_of(c).split('\n')[0] for c in h.ran]
        assert ran[0] == '# write_file new.py' and ran[1:] == ['# workspace survey .'] and (ws / 'new.py').read_text() == 'y = 2\n'
        # the harness replays the whole history on its next request: nothing is asked twice
        w.messages += [{'role': 'assistant', 'content': 'done'}, {'role': 'user', 'content': 'continue'}]
        w.post()
        assert ledger_kinds() == ['mutate', 'survey'] and len(h.ran) == 2


def test_questions_the_view_could_not_answer_are_asked_at_the_next_request_and_never_twice_on_nothing(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'Cargo.toml').write_text('[package]\n')

    class Asking(TurnBackend):
        """The model lists the directory five times; a new question appears after its second call, an absence to re-check after its fourth."""
        def chat(self, body, rlog=None):
            if len(self.bodies) == 2:
                wsview.want_program(SID, 'no-such-program-here')
            if len(self.bodies) == 4:
                wsview._PROG_CACHE.setdefault(SID, {})['another-absent'] = ''
                wsview.want_program(SID, 'another-absent')
            return super().chat(body, rlog)
    backend = Asking(*[[('list_dir', {'path': '.'})] for _ in range(5)])
    wsview.want_body(SID, 'Cargo.toml')
    wsview.want_program(SID, 'cargo')
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(Harness(ws))
        kinds = ledger_kinds()
        assert kinds[:2] == ['survey', 'list_dir']                                  # asked before the model's first call
        # a new question after the model's second call: one more survey, but not at the very next request (two turns apart); the absence adds none
        assert kinds.count('survey') == 2 and wsview.pending(SID)[1] == ['another-absent']
        assert kinds.index('survey', 1) > kinds.index('list_dir', 1)


def test_one_survey_every_fourth_landed_write_and_the_first_one(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    turns = [[('write_file', {'path': f'f{i}.txt', 'content': f'{i}\n'})] for i in range(6)]
    backend = TurnBackend(*turns)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(Harness(ws))
        assert ledger_kinds() == ['mutate', 'survey', 'mutate', 'mutate', 'mutate', 'mutate', 'survey', 'mutate']


def test_a_survey_answered_by_a_restarted_cria_is_the_same_survey(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'pkg').mkdir(parents=True)
    (ws / 'pkg' / 'a.py').write_text('1')
    (ws / 'Cargo.toml').write_text('x')
    (ws / 'target').mkdir()
    steady = survey_of_disk(ws, bodies=['Cargo.toml'], progs=['sh'], outside=['/'])
    restarted = survey_of_disk(ws, bodies=['Cargo.toml'], progs=['sh'], outside=['/'], restart=True)
    assert steady == restarted and steady.outputs == {'target': 'Cargo.toml'} and steady.bodies == {'Cargo.toml': b'x'}


# ---------------------------------------------------------------- what the tree says

def test_the_tree_is_one_call_when_it_fits_and_walked_by_wave_when_it_does_not(tmp_path):
    small = tmp_path / 'small'
    (small / 'a/b').mkdir(parents=True)
    (small / 'a/b/f.py').write_text('1')
    rounds = []
    found = survey_of_disk(small, rounds=rounds)
    assert rounds == [1] and set(found.files) == {'a/b/f.py'} and set(found.dirs) == {'a', 'a/b'} and found.complete and found.listed
    big = tmp_path / 'big'
    for d in range(30):
        for f in range(15):
            (big / f'd{d:02}/s{f % 3}').mkdir(parents=True, exist_ok=True)
            (big / f'd{d:02}/s{f % 3}/f{f}.txt').write_text('x')
    rounds = []
    found = survey_of_disk(big, rounds=rounds)
    assert len(found.files) == 450 and len(found.dirs) == 30 + 90 and found.complete and rounds[0] == 1 and max(rounds) <= surveyops.WAVE
    assert len(rounds) <= 1 + 1 + 2 + 3 + 3      # whole-tree call that did not fit, root, 30 dirs (two waves), their 90 subdirectories (six waves at most)


def test_a_directory_with_more_than_fold_at_files_is_named_and_unknown_inside_and_the_bound_names_what_it_left(tmp_path, monkeypatch):
    for i in range(wsview.FOLD_AT + 3):
        (tmp_path / 'crowd').mkdir(exist_ok=True)
        (tmp_path / 'crowd' / f'f{i}').write_text('x')
    (tmp_path / 'ok').mkdir()
    (tmp_path / 'ok' / 'a').write_text('x')
    found = survey_of_disk(tmp_path)
    assert found.folded == ('crowd',) and 'crowd' in found.dirs and not any(p.startswith('crowd/') for p in found.files) and found.complete
    assert 'ok/a' in found.files
    monkeypatch.setattr(wsview, 'TREE_MAX_ENTRIES', 8)
    for i in range(3):
        (tmp_path / 'deep' / f'n{i}' / 'm').mkdir(parents=True)
    found = survey_of_disk(tmp_path)
    assert not found.complete and {'deep/n0', 'deep/n1', 'deep/n2'} <= set(found.folded) and 'deep/n0' in found.dirs and 'deep/n0/m' not in found.dirs


def test_a_build_output_is_named_on_its_manifests_proof_and_walked_without_it_and_git_is_never_entered(tmp_path):
    for d in ('rs/target/debug', 'plain/build/out', 'jvm/target/classes', 'jvm2/build/x', '.git/objects'):
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / 'file').write_text('x')
    (tmp_path / 'rs/Cargo.toml').write_text('x')
    (tmp_path / 'jvm/pom.xml').write_text('x')
    (tmp_path / 'jvm2/build.gradle').write_text('x')
    found = survey_of_disk(tmp_path)
    assert found.outputs == {'rs/target': 'Cargo.toml', 'jvm/target': 'pom.xml', 'jvm2/build': 'build.gradle'}
    assert 'plain/build/out/file' in found.files and not any(p.startswith(('rs/target/', 'jvm/target/', 'jvm2/build/')) for p in found.files)
    assert not any('.git' in p.split('/') for p in set(found.files) | set(found.dirs)) and found.complete


def test_names_that_cannot_be_one_line_of_utf8_are_not_listed_and_their_directory_is_not_whole(tmp_path):
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'fine.py').write_text('1')
    (tmp_path / 'sub' / 'two\nlines').write_text('1')
    os.close(os.open(os.fsencode(tmp_path) + b'/sub/bad\xffname', os.O_CREAT | os.O_WRONLY))
    (tmp_path / 'ok.txt').write_text('1')
    found = survey_of_disk(tmp_path)
    assert set(found.files) == {'ok.txt', 'sub/fine.py'} and 'sub' in found.folded and not found.complete


def test_links_are_listed_as_what_they_are_and_never_followed_and_an_unreadable_directory_is_unknown_not_empty(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.txt').write_text('s')
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'alias').symlink_to(outside)
    (ws / 'filelink').symlink_to(outside / 'secret.txt')
    (ws / 'locked').mkdir()
    (ws / 'locked' / 'x').write_text('x')
    os.chmod(ws / 'locked', 0)
    try:
        found = survey_of_disk(ws, bodies=['alias/secret.txt', 'filelink'])
    finally:
        os.chmod(ws / 'locked', stat.S_IRWXU)
    assert set(found.files) == {'alias', 'filelink'} and not any('secret' in p for p in found.files)       # a link is a file entry of its own size
    assert found.bodies == {} and set(found.refused) == {'alias/secret.txt', 'filelink'}                    # no link is followed to read
    if os.geteuid() != 0:
        assert 'locked' in found.folded and not found.complete and 'locked' in found.dirs


def test_a_frame_the_harness_cut_is_asked_again_smaller(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    for i in range(40):
        (ws / f'file_{i}.txt').write_text('x')
    cut = {'n': 0}

    def alter(command, text):
        if 'workspace survey .' in command and cut['n'] < 3:      # the walk's whole-tree call, then the first level call, are cut in transit
            cut['n'] += 1
            return text[:len(text) // 2]
        return text
    found = survey_of_disk(ws, alter=alter)
    assert cut['n'] == 3 and len(found.files) == 40 and found.complete


# ---------------------------------------------------------------- a hostile workspace

def test_nothing_in_the_workspace_runs_during_a_survey(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'bin').mkdir(parents=True)
    marker = tmp_path / 'ran-marker'
    for name in ('python3', 'env', 'ctags', 'bash', 'sh', 'base64'):
        (ws / 'bin' / name).write_text(f'#!/bin/sh\necho {name} >> {marker}\nexit 0\n')
        os.chmod(ws / 'bin' / name, 0o755)
    for mod in ('hashlib', 'base64', 'json', 'os', 'sys', 'zlib', 'sitecustomize', 'usercustomize', 'subprocess'):
        (ws / f'{mod}.py').write_text(f'open({str(marker)!r}, "w").write("x")\n')
    (ws / 'x.py').write_text('1')
    found = survey_of_disk(ws, bodies=['x.py'], progs=['python3', 'ctags'], env={'PATH': f'{ws / "bin"}:/usr/bin:/bin', 'PYTHONPATH': str(ws), 'PYTHONSTARTUP': str(ws / 'os.py')})
    assert not marker.exists(), marker.read_text()
    assert found.bodies == {'x.py': b'1'} and found.complete and 'x.py' in found.files and found.progs == {'python3': 'python3', 'ctags': 'ctags'}
