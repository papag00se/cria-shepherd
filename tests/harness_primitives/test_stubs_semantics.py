"""What each stub does to a real filesystem: write is a compare-and-swap that cannot land the wrong bytes, put stages chunks, ls walks
without following links, run outlives its caller and kills at its deadline. Lifted from the phase-1 prototype."""
import concurrent.futures
import json
import os
import time

import pytest

from prims_rig import GROUP, ls, run, sha, write


@pytest.fixture
def root(tmp_path):
    (tmp_path / 'root').mkdir()
    return tmp_path / 'root'


def test_write_creates_replaces_and_refuses_by_compare_and_swap(root):
    new = b'x = 1\n'
    assert write(root, 'src/a.py', new, '-').header['landed'] == 1 and (root / 'src/a.py').read_bytes() == new
    again = write(root, 'src/a.py', b'y\n', '-').header                                   # create over an existing file
    assert again['err'] == 'stale' and again['sha'] == sha(new) and (root / 'src/a.py').read_bytes() == new
    v2 = b'x = 2\n'
    assert write(root, 'src/a.py', v2, sha(new)).header['landed'] == 1 and (root / 'src/a.py').read_bytes() == v2
    assert write(root, 'src/a.py', b'z\n', sha(new)).header['err'] == 'stale' and (root / 'src/a.py').read_bytes() == v2


def test_write_splices_only_the_changed_bytes_and_refuses_a_result_that_does_not_hash_to_new(root):
    (root / 'f').write_bytes(b'x = 2\n')
    splice = json.dumps([[4, 5, 1]])
    done = write(root, 'f', b'x = 3\n', sha(b'x = 2\n'), sp=splice, payload=b'3')
    assert done.header['landed'] == 1 and (root / 'f').read_bytes() == b'x = 3\n' and len(done.command) < 3200
    bad = run('write', [root, 'f', sha(b'x = 3\n'), splice, sha(b'nope'), 0, 1, GROUP], b'9', cwd=root)
    assert bad.header['err'] == 'newsha' and (root / 'f').read_bytes() == b'x = 3\n'
    assert [p.name for p in root.iterdir()] == ['f']                                       # no temp file left behind


def test_write_keeps_mode_and_every_byte_and_makes_parents_only_when_asked(root):
    (root / 'f').write_bytes(b'x = 3\n')
    os.chmod(root / 'f', 0o750)
    write(root, 'f', b'x = 4\n', sha(b'x = 3\n'), sp=json.dumps([[4, 5, 1]]), payload=b'4')
    assert oct((root / 'f').stat().st_mode & 0o7777) == '0o750'
    raw = b'a\r\nb\xff\xfe\r\n'
    write(root, 'crlf.txt', raw, '-')
    assert (root / 'crlf.txt').read_bytes() == raw
    assert write(root, 'a/b/c/d.txt', b'deep\n', '-').header['landed'] == 1 and (root / 'a/b/c/d.txt').read_bytes() == b'deep\n'
    assert write(root, 'q/r/s.txt', b'deep\n', '-', mk=0).header['errno'] == 2 and not (root / 'q').exists()


def test_a_payload_over_one_command_is_staged_out_of_order_and_lands_with_its_hash_and_a_replay_is_harmless(root):
    big = os.urandom(300_000)
    parts = [(i, big[i:i + 45_000]) for i in range(0, len(big), 45_000)]
    for off, chunk in reversed(parts):
        assert run('put', [root, 'big.bin', GROUP, off, 1], chunk, cwd=root).header['ok'] == 1
    assert run('put', [root, 'big.bin', GROUP, parts[0][0], 1], parts[0][1], cwd=root).header['staged'] == len(big)    # a re-sent chunk
    assert write(root, 'big.bin', big, '-', staged=True).header['landed'] == 1
    assert (root / 'big.bin').read_bytes() == big and [p.name for p in root.iterdir()] == ['big.bin']
    replay = write(root, 'big.bin', big, '-', staged=True).header                          # the reply was lost: the same call again
    assert replay['err'] == 'FileNotFoundError'                                            # the landed write consumed its staging file ...
    assert run('read', [root, 'big.bin', 0, 0], cwd=root).header['fsha'] == sha(big)       # ... so cria reads the target's hash: landed


def test_a_stale_stage_never_lands_wrong_bytes(root):
    run('put', [root, 'big.bin', GROUP, 0, 1], b'half', cwd=root)
    assert write(root, 'big.bin', b'the whole thing', '-', staged=True).header['err'] == 'newsha'
    assert not (root / 'big.bin').exists()


def test_sixteen_writers_editing_one_base_land_exactly_one_and_the_rest_see_stale(root):
    base = b'line0\nline1\nline2\n'
    (root / 'f.txt').write_bytes(base)

    def attempt(i):
        old = b'line%d' % (i % 3)
        at = base.index(old)
        edit = b'EDIT%02d' % i
        return write(root, 'f.txt', base.replace(old, edit), sha(base), sp=json.dumps([[at, at + 5, 6]]), payload=edit).header
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        headers = list(pool.map(attempt, range(16)))
    assert sum(h.get('landed', 0) for h in headers) == 1 and sum(h.get('err') == 'stale' for h in headers) == 15
    assert [h for h in headers if not h.get('landed') and h.get('err') != 'stale'] == []
    assert (root / 'f.txt').read_bytes().count(b'EDIT') == 1 and [p.name for p in root.iterdir()] == ['f.txt']


def test_one_command_carries_45000_raw_bytes_and_the_kernel_refuses_far_more(root):
    done = write(root, 'ok.bin', os.urandom(45_000), '-')
    assert done.header['landed'] == 1 and len(done.command.encode()) < 64 * 1024
    with pytest.raises(OSError):                                    # E2BIG: the harness never gets to run it, so cria never sends it
        write(root, 'huge.bin', os.urandom(110_000), '-')


def test_ls_walks_sorted_without_following_links_and_marks_what_it_did_not_enter(tmp_path):
    root, outside = tmp_path / 'root', tmp_path / 'outside'
    for d in ('src/pkg', 'node_modules/x', 'many'):
        (root / d).mkdir(parents=True)
    outside.mkdir()
    for f in ('src/a.py', 'src/pkg/b.py', 'node_modules/x/i.js', 'top.txt', 'nl\nname.txt'):
        (root / f).write_text('x')
    for i in range(30):
        (root / 'many' / f'f{i:02}').write_text('')
    (root / 'lnk').symlink_to(outside)
    walk = ls(root, skip=['node_modules'])
    paths = [r[1] for r in walk.records]
    top = [p for p in paths if '/' not in p]
    assert walk.header['done'] == 1 and paths[:len(top)] == top == sorted(top)             # breadth first, sorted by name
    assert 'node_modules' in paths and 'node_modules/x' not in paths and 'src/pkg/b.py' in paths and 'nl\nname.txt' in paths
    assert [r for r in walk.records if r[1] == 'node_modules'][0][-1] == 1 and [r for r in walk.records if r[1] == 'lnk'][0][0] == 'l'
    assert [r[1] for r in ls(root, 'src', 1).records] == ['src/a.py', 'src/pkg']
    assert [r for r in ls(root, fold=10).records if r[0] == 'x'] == [['x', 'many', 30, 0, 0]]
    capped = ls(root, mx=5)
    assert capped.header['done'] == 0 and len(capped.records) == 5                           # done:0 is "unknown beyond", never "absent"


def test_run_returns_exit_and_output_detached_runs_outlive_the_caller_and_a_deadline_kills_the_group(root, tmp_path):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    quick = run('run', ['start', scratch, 'tokq', 10, 5, root, 0], cwd=root, text='echo hello; echo err >&2; exit 3')
    assert (quick.header['exit'], quick.header['state'], quick.data) == (3, 'done', b'hello\nerr\n') and quick.header['removed'] == 1
    assert not list(scratch.iterdir())                                                    # a fully inline result leaves nothing behind
    began = time.monotonic()
    slow = run('run', ['start', scratch, 'toks', 20, 1, root, 0], cwd=root, text='sleep 3; echo late')
    assert slow.header['state'] == 'running' and time.monotonic() - began < 2.5
    later = run('run', ['wait', scratch, 'toks', 20, 8, root, 0], cwd=root)
    assert later.header['state'] == 'done' and later.data == b'late\n'
    began = time.monotonic()
    killed = run('run', ['start', scratch, 'tokk', 1, 6, root, 0], cwd=root, text='sleep 30')
    assert killed.header['timeout'] == 1 and time.monotonic() - began < 5
    big = run('run', ['start', scratch, 'tokb', 10, 5, root, 0], cwd=root, text='head -c 20000 /dev/zero | tr "\\0" "a"')
    assert big.header['size'] == 20000 and big.header['head'] == 6000 and len(big.data) == 6000 and 'removed' not in big.header
    assert run('run', ['start', scratch, 'tokb', 5, 1, root, 0], cwd=root, text='echo x').header['err'] == 'FileExistsError'   # a retried start never adopts a directory
    paged = run('read', [scratch / '.ctx-run-tokb', 'out', 0, 100], cwd=root)
    assert paged.header['fsha'] == big.header['osha']
