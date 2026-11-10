"""list_dir through the primitives, end to end: a real CriaServer over a scripted model, a harness that runs the lowered call with
real bash on a pty in a real workspace. The model sees its own call and cria's text; nothing private reaches it."""
import hashlib
import json
import os
import re

import pytest

from cria import denial, ops, privatepaths
from ops_rig import Harness, ListBackend, Wire, command_of, isolated_home, start_in  # noqa: F401

PRIVATE = ('CTX1', 'ctx_', 'python3', '-I -S', 'harness-call', 'CTX_EOF', 'env -i')


def seen_by_model(backend):
    return json.dumps(backend.bodies)


def listing(backend):
    return [m for m in backend.tool_results()][0]


@pytest.mark.parametrize('api,stream', [('chat', False), ('responses', False), ('responses', True)])
def test_the_model_sees_its_own_call_and_a_clean_listing_and_replay_is_stable(tmp_path, api, stream):
    ws = tmp_path / 'ws'
    (ws / 'src').mkdir(parents=True)
    (ws / 'a.py').write_text('x = 1\n')
    (ws / 'link').symlink_to('a.py')
    (ws / 'nl\nname').write_text('')
    backend = ListBackend(ws)
    with start_in(Wire(tmp_path, backend, api, stream), ws) as w:
        message, carriers = w.drive(Harness(ws))
        assert 'seen' in message['content'] and len(backend.bodies) == 2
        body = backend.bodies[-1]['messages']
        call = [c for m in body if m.get('tool_calls') for c in m['tool_calls']]
        assert [(c['id'], c['function']['name'], json.loads(c['function']['arguments'])) for c in call] == [('model_call_0', 'list_dir', {'path': str(ws)})]
        result = listing(backend)
        assert result['tool_call_id'] == 'model_call_0' and denial.proof(result) == denial.RAN
        lines = result['content'].split('\n')
        assert re.fullmatch(r'-rw-r--r-- +6 \d{4}-\d\d-\d\d \d\d:\d\d a\.py', lines[0]) and lines[1].startswith('lrwx')
        assert lines[1].endswith('link -> a.py') and lines[2].startswith('-rw') and lines[2].endswith(r'nl\nname') and lines[3].startswith('drwx') and lines[3].endswith(' src')
        assert not [p for p in PRIVATE if p in seen_by_model(backend)]
        # the harness replays the whole history on its next request: the projection is the same and the model is asked once more
        w.messages += [{'role': 'assistant', 'content': 'done'}, {'role': 'user', 'content': 'continue'}]
        w.post()
        assert listing(backend) == result and not [p for p in PRIVATE if p in seen_by_model(backend)] and len(backend.bodies) == 3
    assert [json.loads(l)['t'] for l in next((privatepaths.CRIA_HOME / 'ops').iterdir()).read_text().splitlines()] == ['op', 'step', 'frame', 'final']


@pytest.mark.parametrize('path,fragment', [('nope', "ls: cannot access 'nope': No such file or directory"), ('a.py/x', "Not a directory")])
def test_a_failed_listing_is_refused_with_the_kernels_own_reason(tmp_path, path, fragment):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'a.py').write_text('x')
    backend = ListBackend(path)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(Harness(ws))
        result = listing(backend)
        assert fragment in result['content'] and denial.refused(result)


def test_an_empty_directory_and_a_single_file_are_each_one_plain_answer(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'empty').mkdir(parents=True)
    (ws / 'f.txt').write_text('abc')
    backend = ListBackend('empty', 'f.txt')
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(Harness(ws))
        empty, single = (m['content'] for m in backend.tool_results())
        assert empty == 'empty: empty directory' and re.fullmatch(r'-rw-r--r-- +3 \S+ \S+ f\.txt', single)


def test_a_link_in_the_path_is_resolved_by_cria_and_judged_again_inside_the_workspace(tmp_path):
    ws, outside = tmp_path / 'ws', tmp_path / 'outside'
    (ws / 'real').mkdir(parents=True)
    outside.mkdir()
    (ws / 'real' / 'a.py').write_text('x')
    (outside / 'secret.txt').write_text('TOP SECRET')
    (ws / 'alias').symlink_to('real')
    (ws / 'out').symlink_to(outside)
    backend = ListBackend('alias/a.py', 'alias', 'out/secret.txt')
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(harness)
        inside, link, escaped = (m['content'] for m in backend.tool_results())
        assert re.fullmatch(r'-rw-r--r-- +1 \S+ \S+ alias/a\.py', inside)        # resolved, listed under the name the model gave
        assert link.startswith('lrwx') and link.endswith('alias -> real')               # a final link is listed as a link, never followed
        assert 'outside' in escaped.lower() and 'TOP SECRET' not in escaped
        assert not any(str(outside) in command_of(c) for c in harness.ran)         # the re-check refused it: no call ever named the outside directory
        assert (outside / 'secret.txt').read_text() == 'TOP SECRET' and 'TOP SECRET' not in seen_by_model(backend)


def test_a_chain_of_links_that_never_ends_is_refused_after_a_fixed_number_of_hops(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'a').symlink_to('b')
    (ws / 'b').symlink_to('a')
    backend = ListBackend('a/x')
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(Harness(ws))
        assert 'Too many levels of symbolic links' in listing(backend)['content'] or 'No such file' in listing(backend)['content']


def test_a_listing_over_the_inline_limit_is_saved_whole_and_the_model_gets_the_pointer_without_being_asked_in_between(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    for i in range(150):
        (ws / f'module_with_a_long_descriptive_name_{i:04}.py').write_text('x')
    backend = ListBackend(ws)
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(harness)
        pointer = listing(backend)['content']
        assert len(backend.bodies) == 2 and len(harness.ran) == 2              # ls, then the save: the model was not asked in between
        target = re.search(r'\./tmp/\w+/stdout-[0-9a-f]{64}\.txt', pointer).group(0)
        saved = (ws / target).read_text()
        assert saved.count('\n') == 149 and 'module_with_a_long_descriptive_name_0149.py' in saved and 'No partial directory listing is shown' in pointer
        assert sorted(p.name for p in (ws / target).parent.iterdir()) == [os.path.basename(target)]       # no temp file left behind
        assert not [p for p in PRIVATE if p in seen_by_model(backend)]


def test_a_listing_whose_text_needs_more_than_one_command_is_staged_in_chunks_and_saved_intact(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    for i in range(280):
        (ws / (f'{i:04}-' + 'n' * 240)).write_text('')
    backend = ListBackend(ws)
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(harness)
        target = re.search(r'\./tmp/\w+/stdout-[0-9a-f]{64}\.txt', listing(backend)['content']).group(0)
        saved = (ws / target).read_text()
    assert saved.count('\n') == 279 and len(saved.encode()) > 45_000 and len(harness.ran) >= 4      # ls + puts + the landing write
    assert all(len(command_of(c).encode()) < 64 * 1024 for c in harness.ran)
    assert sorted(p.name for p in (ws / target).parent.iterdir()) == [os.path.basename(target)]


def _asked(harness):
    """(records asked for, AFTER) of each `ls` call the harness ran, in order."""
    return [(int(m.group(1)), os.fsdecode(bytes.fromhex(m.group(2).strip("'")))) for c in harness.ran
            if (m := re.search(r" (\d+) 0 '\[\]' (\S*)$", command_of(c))) and ' tmp/reference 1 200 ' not in command_of(c)]     # (not the staging folder's listing)


def test_a_directory_one_frame_cannot_hold_is_paged_one_call_per_frame_and_comes_back_complete(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    names = sorted(hashlib.sha256(str(i).encode()).hexdigest() for i in range(700))          # dense names: one frame cannot hold 700
    for name in names:
        (ws / name).write_text('')
    backend = ListBackend(ws)
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(harness)
    result = listing(backend)['content']
    asked = _asked(harness)
    assert asked[0] == (ops.LS_MAX[0], '') and len(asked) >= 3                                # the first frame was cut, then pages
    assert [a for _, a in asked if a] and all(a in names for _, a in asked if a)             # each later page resumes after a name it received
    sizes = [n for n, _ in asked]
    assert sizes == sorted(sizes, reverse=True)                                              # a cut is asked again smaller, a fitting rung is kept
    assert 'not absent' not in result and 'NOT complete' not in result and 'first ' not in result
    saved = re.search(r'\./tmp/\w+/stdout-[0-9a-f]{64}\.txt', result)
    assert saved and [l.split()[-1] for l in (ws / saved.group(0)).read_text().split('\n')] == names    # every entry once, in order
    assert len(backend.bodies) == 2                                                          # the model was asked once, after the whole listing


def test_a_2500_file_directory_is_listed_completely_through_pages_and_a_staged_save(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    names = sorted(f'f{i:04}.txt' for i in range(2500))
    for name in names:
        (ws / name).write_text('')
    backend = ListBackend(ws)
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(harness)
    result = listing(backend)['content']
    asked = _asked(harness)
    assert [a for _, a in asked] == ['', names[999], names[1999]]                           # three pages of 1,000: one call per frame
    saved = re.search(r'\./tmp/\w+/stdout-[0-9a-f]{64}\.txt', result)
    lines = (ws / saved.group(0)).read_text().split('\n')
    assert [l.split()[-1] for l in lines] == names and 'NOT complete' not in result and 'not absent' not in result
    assert all(len(command_of(c).encode()) < 64 * 1024 for c in harness.ran)


def test_a_listing_past_the_page_bound_is_still_labelled_incomplete_never_passed_off_as_the_directory(tmp_path, monkeypatch):
    ws = tmp_path / 'ws'
    ws.mkdir()
    monkeypatch.setattr(ops, 'LS_MAX', (10,))
    monkeypatch.setattr(ops, 'LS_MAX_PAGES', 2)
    for i in range(35):
        (ws / f'f{i:02}').write_text('')
    backend = ListBackend(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(Harness(ws))
    result = listing(backend)['content']
    assert 'first 20 entries' in result and 'not absent' in result and result.count('\n') == 20 and 'f19' in result and 'f20' not in result


def test_an_oversize_path_is_refused_before_anything_is_sent(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    backend = ListBackend('d/' * 40_000)
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(harness)
        assert 'cannot be carried' in listing(backend)['content'] and denial.refused(listing(backend))
    assert all(len(command_of(c).encode()) < 64 * 1024 for c in harness.ran)


def test_a_hostile_workspace_and_a_planted_python3_do_not_change_the_answer_or_run_anything(tmp_path):
    ws, outside = tmp_path / 'ws', tmp_path / 'outside'
    ws.mkdir(); outside.mkdir(); (ws / 'bin').mkdir()
    for name in ('hashlib', 'base64', 'json', 'zlib', 'os', 'sys', 'subprocess', 'sitecustomize'):
        (ws / f'{name}.py').write_text(f"open({str(outside / name)!r}, 'w').write('x')\n")
    (ws / 'bin' / 'python3').write_text(f'#!/bin/sh\ntouch {outside}/planted\n')
    (ws / 'bin' / 'python3').chmod(0o755)
    backend = ListBackend(ws)
    hostile = Harness(ws, env={'PATH': f'{ws / "bin"}:{os.environ["PATH"]}', 'PYTHONPATH': str(ws), 'PYTHONSTARTUP': str(ws / 'sitecustomize.py')})
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(hostile)
        assert 'hashlib.py' in listing(backend)['content'] and list(outside.iterdir()) == []


def test_a_link_below_a_path_outside_the_workspace_is_refused_and_judged_again_like_one_inside(tmp_path, monkeypatch):
    """Review M2: ROOT used to be the outside path's directory, which the stub follows: `ext/z -> ~/.cria` listed cria's own home."""
    ws, ext = tmp_path / 'ws', tmp_path / 'ext'
    ws.mkdir()
    ext.mkdir()
    from cria import filecommands
    monkeypatch.setattr(filecommands, 'CRIA_HOME', privatepaths.CRIA_HOME)      # the guard holds its own binding of the home
    privatepaths.CRIA_HOME.mkdir(parents=True, exist_ok=True)
    (privatepaths.CRIA_HOME / 'harness-call.key.bak').write_text('SECRET-IN-CRIA-HOME')
    (ext / 'z').symlink_to(privatepaths.CRIA_HOME)
    (ext / 'plain').mkdir()
    (ext / 'plain' / 'f.txt').write_text('ok')
    backend = ListBackend(ext / 'z' / 'harness-call.key.bak', ext / 'z', ext / 'plain')
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend, level='read'), ws) as w:
        w.drive(harness)
        below, link, plain = (m['content'] for m in backend.tool_results())
        assert 'SECRET-IN-CRIA-HOME' not in below and denial.refused(backend.tool_results()[0])
        assert link.startswith('lrwx') and link.endswith(f'z -> {privatepaths.CRIA_HOME}')          # the link itself is only listed
        assert 'f.txt' in plain
        assert not any(str(privatepaths.CRIA_HOME) in command_of(c) for c in harness.ran)      # no call ever named the private home


def test_a_name_that_is_not_utf8_at_a_page_boundary_is_a_cursor_the_harness_can_carry(tmp_path, monkeypatch):
    """The AFTER cursor is the hex of the name's bytes: a lone surrogate in a command would not survive the harness (the MAC would fail)."""
    ws = tmp_path / 'ws'
    ws.mkdir()
    monkeypatch.setattr(ops, 'LS_MAX', (5,))
    names = [f'f{i:02}'.encode() for i in range(12)]
    names[4] = b'f04\xff\xfe'                                   # the last entry of the first page
    for name in names:
        open(os.path.join(os.fsencode(ws), name), 'w').close()
    backend = ListBackend(ws)
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(harness)
    listed = [l.split(' ')[-1] for l in listing(backend)['content'].split('\n')]
    assert listed == [n.decode('utf-8', 'surrogateescape').replace('\udcff', '\\xff').replace('\udcfe', '\\xfe') for n in sorted(names)]
    after = [a for _, a in _asked(harness) if a]
    assert after and after[0] == os.fsdecode(names[4]) and all(c.encode('utf-8') for c in map(command_of, harness.ran))


def test_a_step_written_before_the_cursor_existed_is_re_emitted_without_it():
    ctx = {'path': '.', 'safe': '/usr/bin:/bin'}
    old = {'wave': 0, 'root': '/w', 'rel': '', 'max_i': 0, 'hop': 0}              # no 'after': a ledger written by the previous release
    assert ops.Ops._command('a' * 12, ctx, 0, 'ls', old).count("'[]' ''") == 1


def test_a_listing_staged_in_more_than_one_wave_stores_its_text_once_and_asks_for_at_most_sixteen_chunks_per_reply(tmp_path, monkeypatch):
    """Review (low): every put step held the whole spill text, and every chunk went out in one reply."""
    from cria import harnessprims
    ws = tmp_path / 'ws'
    ws.mkdir()
    monkeypatch.setattr(harnessprims, 'CHUNK_BYTES', 2_000)
    monkeypatch.setattr(harnessprims, 'PUT_WAVE', 3)
    for i in range(160):
        (ws / (f'{i:04}-' + 'n' * 50)).write_text('')
    backend = ListBackend(ws)
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(harness)
        target = re.search(r'\./tmp/\w+/stdout-[0-9a-f]{64}\.txt', listing(backend)['content']).group(0)
        saved = (ws / target).read_text()
    assert saved.count('\n') == 159 and len(saved.encode()) > 3 * 2_000                    # more than one wave of three chunks
    records = [json.loads(l) for l in next((privatepaths.CRIA_HOME / 'ops').iterdir()).read_text().splitlines()]
    assert sum(r['t'] == 'blob' for r in records) == 1 and not [r for r in records if r['t'] == 'step' and 'text' in r.get('args', {})]
    puts = [r for r in records if r['t'] == 'step' and r['what'] == 'put']
    assert len(puts) > 3 and sorted({r['args']['wave'] for r in puts}).__len__() >= 2
    assert all(sum(1 for r in puts if r['args']['wave'] == k) <= 3 for k in {r['args']['wave'] for r in puts})


def test_a_directory_link_named_with_a_trailing_slash_lists_what_it_points_to_and_without_it_the_link(tmp_path):
    """Review (low): `link/` is the target directory (as `ls -la link/` showed it); normpath used to drop the slash."""
    ws, outside = tmp_path / 'ws', tmp_path / 'outside'
    (ws / 'real').mkdir(parents=True)
    outside.mkdir()
    (ws / 'real' / 'a.py').write_text('x')
    (outside / 'secret.txt').write_text('s')
    (ws / 'alias').symlink_to('real')
    (ws / 'out').symlink_to(outside)
    backend = ListBackend('alias/', 'alias', 'out/')
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(Harness(ws))
        slash, bare, escaped = (m['content'] for m in backend.tool_results())
        assert re.fullmatch(r'-rw-r--r-- +1 \S+ \S+ a\.py', slash) and bare.startswith('lrwx') and bare.endswith('alias -> real')
        assert 'secret.txt' not in escaped and 'outside' in escaped.lower()
