"""Where a payload past one command is staged (operator, 2026-11-10): in the workspace's guarded ./tmp/reference/, never next to the destination.
The landing write renames the verified staged file onto the destination; a destination on another filesystem cannot be reached by a rename, so the
write fails in plain words and nothing is written (no copy fallback); and the next staging sweeps the staging files cria's own earlier operations
left behind (cria/stagesweep.py)."""
import os
import shutil
import time

import pytest

from cria import callauth, denial, stagesweep
from write_edit_helpers import _ENGINE, call, command_of, do, lower, run, settle, write_edit_workspace_view  # noqa: F401
from test_write_edit_primitives import body

SHM = '/dev/shm'


def _staged_write(ws, path, content, cid='w', ran=None, fault=None, **kw):
    tc = lower([call('write_file', {'path': path, 'content': content}, cid)], root=str(ws), **kw)[0]
    first = run(tc, ws)
    return settle([{'role': 'assistant', 'tool_calls': [tc]}, {'role': 'tool', 'tool_call_id': tc['id'], 'content': first.stdout}], ws, ran=ran, fault=fault)


def _parts(ws):
    folder = ws / stagesweep.DIR
    return sorted(p.name for p in folder.iterdir() if p.name.endswith('.part')) if folder.is_dir() else []


def test_a_staged_payload_is_staged_in_the_reference_folder_never_beside_the_destination_and_is_renamed_onto_it(tmp_path):
    (tmp_path / 'src').mkdir()
    content = body(100_000).decode()
    seen = []

    def watch(tc):
        """Before each call the harness runs: where the staging file is."""
        seen.append((_parts(tmp_path), sorted(p.name for p in (tmp_path / 'src').iterdir())))

    shown = _staged_write(tmp_path, 'src/big.txt', content, fault=watch)
    assert denial.landed(shown[1]) and (tmp_path / 'src/big.txt').read_text() == content
    assert all(beside == [] or beside == ['big.txt'] for _, beside in seen)         # never a staging file (or any other) beside the destination
    assert any(parts for parts, _ in seen)                                          # it was in ./tmp/reference while the chunks were arriving ...
    assert _parts(tmp_path) == [] and sorted(os.listdir(tmp_path / 'src')) == ['big.txt']   # ... and the landing consumed it (renamed, not copied)
    assert (tmp_path / 'src/big.txt').stat().st_mode & 0o777 == 0o666 & ~_umask()        # a new file has the mode a written file has


def _umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask


def test_a_staged_overwrite_keeps_the_mode_of_the_file_it_replaces(tmp_path):
    (tmp_path / 'big.txt').write_text('old\n')
    os.chmod(tmp_path / 'big.txt', 0o750)
    content = body(100_000).decode()
    shown = _staged_write(tmp_path, 'big.txt', content)
    assert denial.landed(shown[1]) and (tmp_path / 'big.txt').read_text() == content
    assert (tmp_path / 'big.txt').stat().st_mode & 0o7777 == 0o750 and _parts(tmp_path) == []


@pytest.mark.skipif(not os.path.isdir(SHM) or os.stat(SHM).st_dev == os.stat('/var/tmp').st_dev, reason='no second filesystem')
def test_a_destination_on_another_filesystem_fails_in_plain_words_and_nothing_is_written(tmp_path):
    """EXDEV: ./tmp/reference is on the project's filesystem and the destination is not, so the rename cannot happen. No copy is made instead."""
    ws, away = tmp_path / 'ws', pathlib_dir(SHM, tmp_path)
    ws.mkdir()
    try:
        assert os.stat(ws).st_dev != os.stat(away).st_dev
        content = body(100_000).decode()
        shown = _staged_write(ws, str(away / 'big.txt'), content, external_dir_permission='write')
        text = shown[1]['content']
        assert denial.unlanded(shown[1]) and 'different filesystem' in text and 'Nothing was changed' in text and 'big.txt' in text
        assert 'tmp/reference' in text and 'Invalid cross-device link' not in text
        assert os.listdir(away) == []                                               # nothing was written there: no file, no temp file
        assert _parts(ws) == [] and not (ws / 'big.txt').exists()                  # and the staged file was removed, not left to be found
    finally:
        shutil.rmtree(away, ignore_errors=True)


def pathlib_dir(base, tmp_path):
    import pathlib
    away = pathlib.Path(base) / ('cria-staging-' + tmp_path.name)
    away.mkdir()
    return away


def _closed_staging_name(session='s'):
    """The staging name of an operation of this session's ledger that staged a payload and has ended."""
    names = stagesweep.closed_names(_ENGINE['ops'].ledger.ops(session))
    assert names
    return names[0]


def test_the_next_staging_removes_what_cria_s_own_earlier_operations_left_and_nothing_else(tmp_path):
    first = body(100_000).decode()
    assert denial.landed(_staged_write(tmp_path, 'one.txt', first, cid='w1')[1])          # an operation that staged, and ended
    ended = _closed_staging_name()
    folder = tmp_path / stagesweep.DIR
    old, young, other, notes = '.ctx' + 'a' * 16 + '.part', '.ctx' + 'b' * 16 + '.part', '.ctx' + 'c' * 15 + '.part', 'notes.txt'
    for name in (ended, old, young, other, notes):
        (folder / name).write_text('left\n')
    long_ago = time.time() - stagesweep.MAX_AGE_S - 60
    os.utime(folder / old, (long_ago, long_ago))
    (folder / 'sub').mkdir()
    (folder / 'sub' / old).write_text('inside a folder: not the staging folder itself\n')
    ran = []
    shown = _staged_write(tmp_path, 'two.txt', body(100_000).decode(), cid='w2', ran=ran)
    assert denial.landed(shown[1]) and (tmp_path / 'two.txt').read_text() == body(100_000).decode()
    left = sorted(p.name for p in folder.iterdir())
    assert ended not in left and old not in left                                         # an ended operation's name, and a name past its age: removed
    assert {young, other, notes, 'sub'} <= set(left) and (folder / 'sub' / old).exists()   # a young name nobody owns, a different shape, any other file: untouched
    assert callauth and not [n for n in left if n == stagesweep.name_of(_last_op())]      # and its own staging file went with its landing


def _last_op():
    ops = _ENGINE['ops'].ledger.ops('s')
    return [op for op in ops.values() if any(st.what == 'mput' for st in op.steps.values())][-1].op


def test_an_open_operations_staging_file_is_never_swept(tmp_path):
    """The name of the operation doing the staging is its own: a sweep that listed it before its landing must leave it."""
    content = body(100_000).decode()
    seen = []

    def watch(tc):
        seen.append(_parts(tmp_path))

    shown = _staged_write(tmp_path, 'one.txt', content, fault=watch)
    assert denial.landed(shown[1]) and (tmp_path / 'one.txt').read_text() == content
    assert any(len(parts) == 1 for parts in seen)
