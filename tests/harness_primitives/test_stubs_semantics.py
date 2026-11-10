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
    assert done.header['landed'] == 1 and (root / 'f').read_bytes() == b'x = 3\n' and len(done.command) < 3800
    bad = run('write', [root, 'f', sha(b'x = 3\n'), splice, sha(b'nope'), 0, 1, GROUP, root], b'9', cwd=root)
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
        assert run('put', [root, GROUP, off], chunk, cwd=root).header['ok'] == 1
    assert run('put', [root, GROUP, parts[0][0]], parts[0][1], cwd=root).header['staged'] == len(big)    # a re-sent chunk
    assert write(root, 'big.bin', big, '-', staged=True).header['landed'] == 1
    assert (root / 'big.bin').read_bytes() == big and sorted(p.name for p in root.iterdir()) == ['big.bin', 'tmp']
    assert os.listdir(root / 'tmp/reference') == []                                        # the staging file was renamed onto the target: none is left, and none was ever beside it
    replay = write(root, 'big.bin', big, '-', staged=True).header                          # the reply was lost: the same call again
    assert replay['err'] == 'FileNotFoundError'                                            # the landed write consumed its staging file ...
    assert run('read', [root, 'big.bin', 0, 0, 0], cwd=root).header['fsha'] == sha(big)       # ... so cria reads the target's hash: landed


def test_a_stale_stage_never_lands_wrong_bytes(root):
    run('put', [root, GROUP, 0], b'half', cwd=root)
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
    names, after = [], ''                                                                   # AFTER is the resume cursor of a depth-1 listing
    while True:
        page = ls(root, 'many', 1, 7, after=after)
        names += [r[1].rsplit('/', 1)[-1] for r in page.records]
        if page.header['done']:
            break
        after = names[-1]
    assert names == [f'f{i:02}' for i in range(30)] and ls(root, 'many', 1, 7, after='f29').records == []   # each entry once; past the last name: nothing


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
    paged = run('read', [scratch / '.ctx-run-tokb', 'out', 0, 100, 0], cwd=root)
    assert paged.header['fsha'] == big.header['osha']


def gone(pattern, seconds=6):
    import subprocess
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if subprocess.run(['pgrep', '-f', pattern], capture_output=True).returncode != 0:
            return True
        time.sleep(0.1)
    return False


def test_run_in_the_foreground_answers_in_its_own_call_and_a_deadline_kills_the_group(root, tmp_path):
    """`fg` is `start` without the detach: the harness's own call is the supervisor, so a harness that keeps a yielded call alive keeps the run alive."""
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    began = time.monotonic()
    done = run('run', ['fg', scratch, 'tokf', 10, 1, root, 1], cwd=root, text='echo hello; echo err >&2; sleep 1.5; exit 3')
    assert (done.header['exit'], done.header['state'], done.data) == (3, 'done', b'hello\nerr\n') and time.monotonic() - began >= 1.5      # it waited for the end
    assert run('run', ['wait', scratch, 'tokf', 10, 1, root, 1], cwd=root).header['exit'] == 3                   # the run's own directory answers the same afterwards
    killed = run('run', ['fg', scratch, 'tokg', 1, 1, root, 1], cwd=root, text='sleep 27.1')
    assert killed.header['timeout'] == 1 and time.monotonic() - began < 8 and gone('[s]leep 27.1')
    assert run('run', ['fg', scratch, 'tokf', 5, 1, root, 1], cwd=root, text='echo x').header['err'] == 'FileExistsError'


@pytest.mark.parametrize('mode', ['start', 'fg'])
def test_removing_the_run_s_directory_stops_the_run(root, tmp_path, mode):
    """Abandoning a run is removing its directory (cria's `rm t`, which it issues on every path out of a gate): the supervisor sees it go and kills the group."""
    import shutil
    import threading
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    threading.Timer(1.2, lambda: shutil.rmtree(scratch / '.ctx-run-toka')).start()
    began = time.monotonic()
    run('run', ['start' if mode == 'start' else 'fg', scratch, 'toka', 60, 2, root, 1], cwd=root, text='sleep 27.7; echo never')
    assert gone('[s]leep 27.7') and time.monotonic() - began < 10


# ---- phase 3 review, low items -------------------------------------------------------------------------------------

def test_a_fifo_is_refused_without_hanging_and_without_holding_the_directory_lock(root):
    os.mkfifo(root / 'pipe')
    started = time.monotonic()
    assert write(root, 'pipe', b'x', '*').header['err'] == 'notfile'
    assert write(root, 'pipe', b'x', sha(b'x'), sp=json.dumps([[0, 0, 1]]), payload=b'x').header['ok'] == 0
    (root / 'tmp/reference').mkdir(parents=True)
    os.mkfifo(root / 'tmp/reference' / ('.ctx' + GROUP[:16] + '.part'))
    assert write(root, 'g.txt', b'x', '-', staged=True).header['ok'] == 0              # an empty (non-regular) staging file never lands anything
    assert run('put', [root, GROUP, 0], b'x', cwd=root).header['ok'] == 0   # put onto a FIFO staging name: refused, not blocked
    os.mkfifo(root / 'p2')
    assert run('rm', [root, 'p2', 'f', sha(b'x')], cwd=root).header['ok'] == 0
    assert write(root, 'after.txt', b'ok', '-').header['landed'] == 1                    # no flock was left held by the stuck calls
    assert time.monotonic() - started < 30


def test_put_never_writes_through_a_hard_link_to_a_file_outside(root, tmp_path):
    victim = tmp_path / 'victim.txt'
    victim.write_text('PRECIOUS')
    (root / 'tmp/reference').mkdir(parents=True)
    os.link(victim, root / 'tmp/reference' / ('.ctx' + GROUP[:16] + '.part'))
    done = run('put', [root, GROUP, 0], b'OVERWRITTEN', cwd=root)
    assert done.header['ok'] == 0 and victim.read_text() == 'PRECIOUS'


@pytest.mark.parametrize('existing', [True, False])
def test_a_write_that_the_disk_takes_only_part_of_fails_and_leaves_the_target_and_the_directory_as_they_were(root, existing):
    """A full disk, a quota or a file-size limit makes write(2) take fewer bytes than asked. The stub used to fsync and rename the cut file in
    place of the user's and answer `landed` with the hash of bytes that were never all written; now every byte is written or the call fails."""
    if existing:
        (root / 'f.txt').write_bytes(b'ORIGINAL\n')
    data = b'x' * 20_000 + b'\n'
    ex = sha(b'ORIGINAL\n') if existing else '-'
    done = write(root, 'f.txt', data, ex, fsize=10_000)
    assert done.header['ok'] == 0 and 'landed' not in done.header and done.header['err'] == 'OSError' and done.header['errno']
    assert sorted(p.name for p in root.iterdir()) == (['f.txt'] if existing else [])
    assert not existing or (root / 'f.txt').read_bytes() == b'ORIGINAL\n'
    assert write(root, 'f.txt', data, ex).header['landed'] == 1 and (root / 'f.txt').read_bytes() == data    # with room, the same call lands


def test_a_chunk_the_disk_takes_only_part_of_is_never_answered_as_staged(root):
    done = run('put', [root, GROUP, 0], b'y' * 20_000, cwd=root, fsize=10_000)
    assert done.header['ok'] == 0 and 'staged' not in done.header
    assert run('put', [root, GROUP, 0], b'y' * 20_000, cwd=root).header['staged'] == 20_000


def test_write_keeps_setuid_and_setgid_bits_not_only_the_permission_bits(root):
    (root / 'f').write_bytes(b'a')
    os.chmod(root / 'f', 0o4755)
    assert write(root, 'f', b'b', sha(b'a')).header['landed'] == 1
    assert (root / 'f').stat().st_mode & 0o7777 == 0o4755


def test_run_starts_the_supervisor_with_a_clean_environment_and_hands_the_command_the_users_own(root, tmp_path):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    env = {**os.environ, 'MYVAR': 'kept', 'LD_PRELOAD': ''}
    done = run('run', ['start', scratch, 'tokE', 10, 5, root, 0], cwd=root, env=env,
               text='echo "child=$MYVAR"; echo "supervisor=$(tr "\\0" "\\n" < /proc/$PPID/environ | grep -c "^MYVAR=")"')
    assert done.data.decode().split() == ['child=kept', 'supervisor=0']


def test_run_wait_refuses_a_directory_it_did_not_make(root, tmp_path):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    planted = scratch / '.ctx-run-tokP'
    planted.mkdir(mode=0o777)
    os.chmod(planted, 0o777)
    (planted / 'done').write_text(json.dumps(dict(exit=0, timeout=0, size=6)))
    (planted / 'out').write_text('forged')
    (planted / 's.sh').write_text('')
    assert run('run', ['wait', scratch, 'tokP', 5, 1, root, 0], cwd=root).header['ok'] == 0


def test_search_gives_up_on_a_pathological_pattern(root):
    (root / 'f.txt').write_text('a' * 40 + 'b\n')
    started = time.monotonic()
    done = run('search', [root, '(a+)+$', 0, 10, 1 << 20, 0], text='["f.txt"]', cwd=root)
    assert done.header['ok'] == 0 and done.header['err'] == 'TimeoutError' and time.monotonic() - started < 30


def pages_of(root, names, pattern, size, total_pages=None):
    """The matching lines of ``names`` read as consecutive pages of ``size`` matches (the stub's SKIP and MAX), as cria reads a heavy batch: returns (records, pages asked)."""
    got, skip, asked = [], 0, 0
    while True:
        done = run('search', [root, pattern, 0, size, 1 << 20, skip], text=json.dumps(names), cwd=root)
        assert done.header['ok'] == 1
        records = [r for r in done.records if r[0] == 'm']
        asked += 1
        got += records
        if done.records[-1:] != [['#']]:
            return got, asked
        assert len(records) == size                       # a page that says it is full holds exactly its size
        skip += size


def test_search_skip_reads_any_number_of_matches_as_consecutive_pages_across_files_with_crlf_and_notes(root):
    (root / 'a.txt').write_bytes(b'x1\r\nno\r\nx2\r\nx3\r\n')
    (root / 'b.txt').write_bytes(''.join(f'x{i}\n' for i in range(10)).encode())
    (root / 'c.txt').write_bytes(b'x end')
    (root / 'big.txt').write_bytes(b'x' * 3000)             # one long matching line
    names = ['a.txt', 'big.txt', 'b.txt', 'missing.txt', 'c.txt']
    whole = run('search', [root, 'x', 0, 1000, 1 << 20, 0], text=json.dumps(names), cwd=root)
    everything = [r for r in whole.records if r[0] == 'm']
    assert len(everything) == 3 + 1 + 10 + 1
    for size in (1, 2, 3, 4, 7, 100):
        got, asked = pages_of(root, names, 'x', size)
        assert got == everything and asked == len(everything) // size + 1       # the first page that is not full is the last
    page = run('search', [root, 'x', 0, 2, 1 << 20, 3], text=json.dumps(names), cwd=root)          # a page across the boundary between files
    assert [r[:3] for r in page.records if r[0] == 'm'] == [list(r[:3]) for r in everything[3:5]]
    tail = run('search', [root, 'x', 0, 9, 1 << 20, 10], text=json.dumps(names), cwd=root)         # the last page: it reaches the missing file
    assert [r[:3] for r in tail.records if r[0] == 'm'] == [list(r[:3]) for r in everything[10:]]
    assert any(r[0] == '!' and r[1] == 'missing.txt' for r in tail.records)                          # a note is not a match: it is not counted, and repeats on every page that reaches it
    assert run('search', [root, 'x', 0, 2, 1 << 20, 10_000], text=json.dumps(names), cwd=root).records[:1] != [['#']]   # past the end: an empty last page


def test_search_skip_of_twenty_thousand_matches_in_one_file(root):
    (root / 'f.txt').write_text(''.join(f'needle {i}\n' for i in range(20_000)))
    got, asked = pages_of(root, ['f.txt'], 'needle', 4096)
    assert [r[2] for r in got] == list(range(1, 20_001)) and got[-1][3] == 'needle 19999' and asked == 5


def test_a_non_cooperating_writer_that_replaces_the_target_inside_the_window_is_detected_by_the_post_write_restat(root):
    """The compare-and-swap's last line (review: removing the re-stat was not caught, flock hid it): an interloper takes no lock, replaces
    the file while the stub is flushing its temp file, and must not be overwritten."""
    import subprocess
    from cria import harnessprims
    (root / 'f').write_bytes(b'base')
    interloper = b'WRITTEN BY SOMEONE WHO TOOK NO LOCK'
    program = '\n'.join([
        'import os,sys',
        'real=os.fsync',
        'done=[]',
        'def fs(fd):',
        '    if not done:',
        '        done.append(1)',
        f'        open({str(root / "other")!r},"wb").write({interloper!r})',
        f'        os.rename({str(root / "other")!r},{str(root / "f")!r})',
        '    real(fd)',
        'os.fsync=fs',
        f'sys.argv=["stub",{"%032x" % 5!r},{str(root)!r},"f",{sha(b"base")!r},"-",{sha(b"new")!r},"0","1",{GROUP!r},{str(root)!r}]',
        f'exec(compile({harnessprims.STUBS["write"]!r},"stub","exec"))'])
    done = subprocess.run(['python3', '-I', '-S', '-c', program], input=__import__('base64').b64encode(b'new'), capture_output=True, timeout=30)
    frame = harnessprims.read_frame(done.stdout.decode(), '%032x' % 5)
    assert frame.header['err'] == 'stale' and (root / 'f').read_bytes() == interloper
    assert sorted(p.name for p in root.iterdir()) == ['f']                                    # and no temp file left behind


# ---- read SK: start a range at the byte after the SK-th newline --------------------------------------------------------

@pytest.mark.parametrize('raw,sk,off,ln,expected_off,expected_ln', [
    (b'a\nbb\nccc\n', 0, 0, 100, 0, 3), (b'a\nbb\nccc\n', 1, 0, 100, 2, 3), (b'a\nbb\nccc\n', 2, 0, 100, 5, 3),
    (b'a\nbb\nccc\n', 3, 0, 100, 9, 3),                              # SK = number of lines: starts at EOF, empty
    (b'a\nbb\nccc\n', 4, 0, 100, None, 3),                           # beyond EOF: no start, nothing returned
    (b'a\r\nbb\r\nccc', 1, 0, 100, 3, 3), (b'a\r\nbb\r\nccc', 2, 0, 100, 7, 3),   # CRLF, and a final line without a newline
    (b'a\nbb\nccc', 3, 0, 100, None, 3), (b'', 1, 0, 10, None, 0), (b'x', 0, 0, 10, 0, 1),
    (b'a\nbb\nccc\n', 1, 1, 100, 3, 3)])                             # OFF pages within the window
def test_read_sk_starts_at_the_byte_after_the_sk_th_newline_and_counts_the_lines_in_the_same_pass(root, raw, sk, off, ln, expected_off, expected_ln):
    (root / 'f').write_bytes(raw)
    done = run('read', [root, 'f', off, ln, sk], cwd=root)
    assert done.header['off'] == expected_off and done.header['ln'] == expected_ln and done.header['fsha'] == sha(raw)
    assert done.data == (raw[expected_off:expected_off + ln] if expected_off is not None else b'')


def test_read_sk_crosses_chunk_boundaries_and_keeps_the_whole_file_hash_size_and_a_bounded_window(root):
    raw = b''.join(b'line %d\n' % i for i in range(400_000))              # ~3.4 MB: several 1 MiB chunks
    (root / 'f').write_bytes(raw)
    done = run('read', [root, 'f', 0, 40, 399_990], cwd=root)
    assert done.data == raw[raw.index(b'line 399990\n'):][:40] and done.header['ln'] == 400_000
    assert done.header['size'] == done.header['fsize'] == len(raw) and done.header['fsha'] == sha(raw)


def test_a_staged_write_renames_the_staged_file_and_onto_another_filesystem_fails_with_exdev_writing_nothing(root, tmp_path):
    """The landing of a staged payload is a rename of the staged file out of WS/tmp/reference (no copy): onto a filesystem it cannot rename
    onto it fails with EXDEV, the destination is not touched, and no temporary file is made there."""
    shm = '/dev/shm'
    if not os.path.isdir(shm) or os.stat(shm).st_dev == os.stat(root).st_dev:
        pytest.skip('no second filesystem')
    big = os.urandom(60_000)
    assert run('put', [root, GROUP, 0], big, cwd=root).header['ok'] == 1
    away = __import__('pathlib').Path(shm) / ('cria-exdev-' + tmp_path.name)
    away.mkdir()
    try:
        done = write(away, 'big.bin', big, '-', staged=True, ws=root, cwd=root).header
        assert done['ok'] == 0 and done['errno'] == 18 and 'landed' not in done
        assert os.listdir(away) == [] and os.listdir(root / 'tmp/reference') == ['.ctx' + GROUP[:16] + '.part']   # nothing written; the staged file is still there (cria removes it)
    finally:
        __import__('shutil').rmtree(away, ignore_errors=True)
