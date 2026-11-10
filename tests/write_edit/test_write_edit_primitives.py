"""The write route's engine against the real stubs on a real directory: payload size classes (one command, staged, waves), a path that cannot be
carried, a restart between steps, two writers of one file (compare-and-swap: no update lost), links in the path, and a harness checker."""
import os
import shutil
import subprocess

import pytest

from cria import denial, syntaxcheck
from cria.ops import Ops
from write_edit_helpers import _ENGINE, call, command_of, do, lower, run, settle, write_edit_workspace_view  # noqa: F401


def stubs(commands, verb):
    """Commands that ran the stub of ``verb`` (`write`, `put`, `read`, `ls`, `rm`, `run`): found by the stub's own first statements."""
    marks = {'write': 'import stat,fcntl', 'put': 'os.pwrite', 'read': 'fsha', 'ls': 'os.scandir', 'rm': 'def rt_', 'run': 'CTX_ENV'}
    return [c for c in commands if marks[verb] in c]


def body(n):
    out, i = bytearray(), 0
    while len(out) < n:
        out += b'%08x ' % (i * 2654435761 % 2**32) + b'abc def ghi jkl mno\n'
        i += 1
    return bytes(out[:n - 1]) + b'\n'


@pytest.mark.parametrize('size,puts', [(44_999, 0), (45_000, 0), (45_001, 2), (300_000, 7), (719_999, 16), (720_001, 17)])
def test_a_payload_is_one_command_up_to_45_000_bytes_then_staged_by_put_and_committed_by_one_write(tmp_path, size, puts):
    content = body(size).decode()
    tc = lower([call('write_file', {'path': 'big.txt', 'content': content}, 'w')], root=str(tmp_path))[0]
    ran = []
    first = run(tc, tmp_path)
    msgs = [{'role': 'assistant', 'tool_calls': [tc]}, {'role': 'tool', 'tool_call_id': tc['id'], 'content': first.stdout}]
    shown = settle(msgs, tmp_path, ran=ran)
    assert denial.landed_call_ids(shown) == {'w'} and (tmp_path / 'big.txt').read_bytes() == content.encode()
    sent = [command_of(tc)] + ran
    assert len(stubs(sent, 'put')) == puts and len(stubs(sent, 'write')) == 1             # ceil(size / 45,000) chunks in waves of at most 16, then ONE write that checks the hash
    assert all(len(c.encode()) < 64 * 1024 for c in sent)                                           # no command past the budget (the kernel refuses 128 KiB)
    assert not [n for n in os.listdir(tmp_path) if n.startswith('.ctx')]                           # the staging file went with the landing


@pytest.mark.parametrize('size,limit', [(20_000, 10_000), (100_000, 40_000)], ids=['one command', 'staged by put'])
def test_a_disk_that_takes_only_part_of_a_write_is_never_reported_as_a_landing_and_the_users_file_is_untouched(tmp_path, size, limit):
    """The harness's disk is full (a file-size limit stands in): the stub's write returned short, and the file it had cut was renamed over the
    user's and answered `landed`. The model is now told the truth (not written, and why), the file is what the user had, nothing is left
    beside it (the temp file, and for a staged payload the staging file) and cria does not remember bytes that never landed."""
    (tmp_path / 'f.txt').write_text('ORIGINAL\n')
    content = body(size).decode()
    tc = lower([call('write_file', {'path': 'f.txt', 'content': content}, 'w')], root=str(tmp_path))[0]
    first = run(tc, tmp_path, fsize=limit)
    msgs = [{'role': 'assistant', 'tool_calls': [tc]}, {'role': 'tool', 'tool_call_id': tc['id'], 'content': first.stdout}]
    shown = settle(msgs, tmp_path, fsize=limit)
    assert denial.unlanded(shown[1]) and 'f.txt' in shown[1]['content'] and 'File too large' in shown[1]['content']
    assert (tmp_path / 'f.txt').read_text() == 'ORIGINAL\n' and os.listdir(tmp_path) == ['f.txt']
    held = _ENGINE['ops'].cache.get(str(tmp_path), 'f.txt')
    assert held is None or held[2] != content.encode()


@pytest.mark.skipif(os.geteuid() == 0, reason='root reads any file')
def test_an_edit_of_a_file_that_cannot_be_read_says_it_could_not_be_read_not_that_it_could_not_be_written(tmp_path):
    """The failure was the read that every edit starts with; the answer used to say the file `could not be written`."""
    (tmp_path / 'f.txt').write_text('a = 1\n')
    os.chmod(tmp_path / 'f.txt', 0o200)
    _, _, shown = do('edit_file', {'path': 'f.txt', 'old_string': 'a = 1', 'new_string': 'a = 2'}, tmp_path)
    text = shown[1]['content']
    assert denial.refused(shown[1]) and '`f.txt` could not be read: Permission denied' in text and 'written' not in text
    os.chmod(tmp_path / 'f.txt', 0o600)
    assert (tmp_path / 'f.txt').read_text() == 'a = 1\n'


def test_a_path_too_long_to_carry_is_refused_before_anything_is_sent(tmp_path):
    long = 'd/' * 40_000 + 'x.txt'
    tc, done, shown = do('write_file', {'path': long, 'content': 'x'}, tmp_path)
    assert denial.refused(shown[1]) and 'cannot be carried to the harness' in shown[1]['content'] and len(command_of(tc)) < 400   # a no-op call, not the path


def test_a_restart_between_the_read_and_the_write_loses_nothing(tmp_path):
    """cria is killed after the harness ran the read and before the next request: the ledger on disk is the only state. A fresh engine
    verifies the history against the key and the ledger, plans the write again from the read's frames and lands it."""
    (tmp_path / 'f.txt').write_text('one\ntwo\nthree\n')
    tc = lower([call('edit_file', {'path': 'f.txt', 'old_string': 'two', 'new_string': 'TWO'}, 'e1')], root=str(tmp_path))[0]
    assert 'fsha' in command_of(tc)                                          # cold: the first call is the read
    done = run(tc, tmp_path)
    _ENGINE['ops'] = Ops()                                                   # a new process: nothing in memory (no cache, no pending plans), same key and ledger
    msgs = [{'role': 'assistant', 'tool_calls': [tc]}, {'role': 'tool', 'tool_call_id': tc['id'], 'content': 'Output:\n' + done.stdout}]
    shown = settle(msgs, tmp_path)
    assert denial.landed(shown[1]) and (tmp_path / 'f.txt').read_text() == 'one\nTWO\nthree\n'


def test_two_writers_of_one_file_lose_no_update(tmp_path):
    """Two operations (two sessions, two turns) each read the same bytes and each edit a different line. The first write lands; the
    second finds the file changed (compare-and-swap), reads it again and applies its edit to what is there: both edits are in the file."""
    (tmp_path / 'f.txt').write_text('a = 1\nb = 2\n')
    first = lower([call('edit_file', {'path': 'f.txt', 'old_string': 'a = 1', 'new_string': 'a = 10'}, 'e1')], root=str(tmp_path))[0]
    second = lower([call('edit_file', {'path': 'f.txt', 'old_string': 'b = 2', 'new_string': 'b = 20'}, 'e2')], root=str(tmp_path))[0]
    reads = [run(first, tmp_path), run(second, tmp_path)]                    # both read the file as it is
    one = settle([{'role': 'assistant', 'tool_calls': [first]}, {'role': 'tool', 'tool_call_id': first['id'], 'content': reads[0].stdout}], tmp_path)
    assert denial.landed(one[1]) and (tmp_path / 'f.txt').read_text() == 'a = 10\nb = 2\n'
    two = settle([{'role': 'assistant', 'tool_calls': [second]}, {'role': 'tool', 'tool_call_id': second['id'], 'content': reads[1].stdout}], tmp_path)
    assert denial.landed(two[1]) and (tmp_path / 'f.txt').read_text() == 'a = 10\nb = 20\n'


@pytest.mark.parametrize('case', ['dir_link_inside', 'dir_link_outside'])
def test_a_link_in_the_path_is_followed_by_cria_only_inside_the_workspace_and_roots(tmp_path, case):
    outside = tmp_path / 'outside'
    outside.mkdir()
    ws = tmp_path / 'ws'
    (ws / 'real').mkdir(parents=True)
    os.symlink('real', ws / 'ln')
    os.symlink(outside, ws / 'esc')
    path = 'esc/f.txt' if case == 'dir_link_outside' else 'ln/f.txt'
    _, _, shown = do('write_file', {'path': path, 'content': 'x = 1\n'}, ws, external_dir_permission='none')
    if case == 'dir_link_outside':
        assert denial.refused(shown[1]) and 'outside the project directory' in shown[1]['content'] and not list(outside.iterdir())
    else:
        assert denial.landed(shown[1]) and (ws / 'real' / 'f.txt').read_text() == 'x = 1\n'


def _links(ws, outside):
    (ws / 'real' / 'deeper').mkdir(parents=True)
    (ws / 'real' / 'target.txt').write_text('OLD\n')
    (ws / 'twin.txt').write_text('OLD\n')
    os.symlink('real', ws / 'ln')                                  # a directory link
    os.symlink('twin.txt', ws / 'same_dir_link')                   # a file link whose target is beside it
    os.symlink('real/deeper/../target.txt', ws / 'other_dir_link')  # a file link whose target is in another directory
    os.symlink(outside / 'out.txt', ws / 'out_link')               # a file link that leaves the workspace
    os.symlink(outside, ws / 'esc')                                # a directory link that leaves it


@pytest.mark.parametrize('path,landed_in', [('ln/new.txt', 'real/new.txt'), ('ln/target.txt', 'real/target.txt'), ('same_dir_link', 'twin.txt'),
                                            ('other_dir_link', 'real/target.txt')],
                         ids=['through a directory link', 'through one onto an existing file', 'a file link beside its target', 'a file link to another directory'])
def test_a_payload_over_one_command_through_a_link_inside_the_workspace_lands_at_the_links_target_and_leaves_nothing_behind(tmp_path, path, landed_in):
    """A whole write over 45,000 bytes is staged beside its target by `put`, which follows no link. It was refused with words that were
    false (`Not a directory` through a directory link; a link "to another directory" for a link beside its target) and the model was
    sent to write 100 KB again. cria resolves the link itself, stages where the target is and lands the write; the staging file left
    in the link's directory (when that is another) is removed; the link is still a link."""
    ws, outside = tmp_path / 'ws', tmp_path / 'outside'
    ws.mkdir(), outside.mkdir()
    _links(ws, outside)
    content = body(100_000).decode()
    ran = []
    tc = lower([call('write_file', {'path': path, 'content': content}, 'w')], root=str(ws), external_dir_permission='none')[0]
    first = run(tc, ws)
    shown = settle([{'role': 'assistant', 'tool_calls': [tc]}, {'role': 'tool', 'tool_call_id': tc['id'], 'content': first.stdout}], ws, ran=ran)
    assert denial.landed(shown[1]), shown[1]['content'][:300]
    assert (ws / landed_in).read_text() == content and (ws / path.split('/')[0]).is_symlink()
    assert not [p for p in ws.rglob('.ctx*')] and not list(outside.iterdir())
    assert all(len(c.encode()) < 64 * 1024 for c in [command_of(tc)] + ran)               # and nothing past the budget was sent to get there


@pytest.mark.parametrize('path', ['esc/f.txt', 'out_link'])
def test_a_payload_over_one_command_through_a_link_that_leaves_the_workspace_is_refused_in_the_words_for_that_and_nothing_is_sent_or_left(tmp_path, path):
    ws, outside = tmp_path / 'ws', tmp_path / 'outside'
    ws.mkdir(), outside.mkdir()
    _links(ws, outside)
    tc, done, shown = do('write_file', {'path': path, 'content': body(100_000).decode()}, ws, external_dir_permission='none')
    text = shown[1]['content']                                      # (the refused draft itself follows, as for every refused write: the F15 policy)
    assert denial.refused(shown[1]) and 'outside the project directory' in text and 'Not a directory' not in text and 'another directory' not in text
    assert not list(outside.iterdir()) and not list(ws.rglob('.ctx*'))


@pytest.mark.skipif(not shutil.which('ruby'), reason='no ruby')
def test_a_ruby_candidate_is_checked_by_the_harness_with_the_checkers_own_words_before_it_lands(tmp_path):
    """One extra round trip (the run stub on a copy of the candidate): a replacement that does not parse over a file that does is refused with
    ruby's own words and the offending line; the path is the file's, never the harness's private directory; nothing is left behind there."""
    (tmp_path / 'r.rb').write_text('def a\n  1\nend\n')
    tc, done, shown = do('write_file', {'path': 'r.rb', 'content': 'def a(\n  1\nend\n'}, tmp_path)
    text = shown[1]['content']
    assert denial.refused(shown[1]) and 'r.rb:' in text and 'syntax error' in text and 'cand.rb' not in text and '.ctx-run-' not in text
    assert 'Line 2 of the content you sent is: 1' in text and (tmp_path / 'r.rb').read_text() == 'def a\n  1\nend\n'
    scratch = tmp_path.parent / (tmp_path.name + '.scratch')
    assert not [n for n in os.listdir(scratch) if n.startswith('.ctx-run-')]
    assert denial.landed(do('write_file', {'path': 'r.rb', 'content': 'def a\n  2\nend\n'}, tmp_path, cid='ok')[2][1])


@pytest.mark.parametrize('name,source,broken,good', [
    ('ruby', 'r.rb', ''.join(f'def m{i}(\n  x = = 1\nend\n' for i in range(200)), 'def a\n  1\nend\n'),
    ('gofmt', 'g.go', 'package p\n' + ''.join(f'func f{i}( {{ x = = 1 }}\n' for i in range(200)), 'package p\n\nfunc a() {}\n')], ids=['ruby', 'go'])
def test_a_checker_that_says_more_than_the_run_stub_answers_inline_is_read_to_the_end_and_its_directory_is_removed(tmp_path, name, source, broken, good):
    """`ruby -c` says ~43 KB about 200 broken methods and `gofmt -e` ~49 KB about 200 broken functions (it does not stop at ten errors); the
    run stub answers the first 6,000 bytes and keeps its directory. The refusal carried the first 6,000 bytes, cut mid-line and unlabelled, and
    the directory (which holds the whole candidate) stayed in the harness's temporary directory for good. cria now pages the rest of the
    output with `read` and removes the directory with `rm`: the whole of what the checker said reaches the refusal."""
    if not shutil.which(name):
        pytest.skip(f'no {name}')
    (tmp_path / source).write_text(good)
    scratch = tmp_path.parent / (tmp_path.name + '.scratch')
    ran = []
    tc = lower([call('write_file', {'path': source, 'content': broken}, 'w')], root=str(tmp_path))[0]
    first = run(tc, tmp_path)
    msgs = [{'role': 'assistant', 'tool_calls': [tc]}, {'role': 'tool', 'tool_call_id': tc['id'], 'content': first.stdout}]
    shown = settle(msgs, tmp_path, ran=ran)
    wholly = subprocess.run(['sh', '-c', syntaxcheck.script(source, broken.encode()).replace('$(dirname "$0")', str(scratch))], capture_output=True, text=True,
                            cwd=scratch if scratch.exists() else tmp_path)            # the checker's own words, all of them, as an oracle
    said = syntaxcheck.interpret(source, 1, 0, (wholly.stdout + wholly.stderr).encode(), str(scratch))
    text = shown[1]['content']
    assert len(said) > 40_000 and denial.refused(shown[1]) and said in text and (tmp_path / source).read_text() == good
    assert len(stubs(ran, 'read')) >= 3 and len(stubs(ran, 'rm')) == 1                        # the pages, then the one removal
    assert not [n for n in os.listdir(scratch) if n.startswith('.ctx-run-')]


# A checker that fails only on a candidate that says BAD, with 20,000 bytes of words (more than the run stub's 6,000 inline), then lingers if asked to.
def _wordy_checker(monkeypatch, linger=False):
    monkeypatch.setitem(syntaxcheck.HARNESS, '.rb', "sh -c 'if grep -q BAD \"$1\"; then head -c 20000 /dev/zero | tr \"\\0\" x; echo; "
                                                      + ("sleep 30; " if linger else "") + "exit 1; fi' sh")


def _written_through_a_wordy_checker(tmp_path, fault=None, cut_first=False):
    (tmp_path / 'r.rb').write_text('def a\n  1\nend\n')
    tc = lower([call('write_file', {'path': 'r.rb', 'content': 'BAD\n'}, 'w')], root=str(tmp_path))[0]
    first = run(tc, tmp_path).stdout
    ran = []
    shown = settle([{'role': 'assistant', 'tool_calls': [tc]}, {'role': 'tool', 'tool_call_id': tc['id'], 'content': first[:len(first) // 2] if cut_first else first}],
                   tmp_path, fault=fault, ran=ran)
    return shown, ran, tmp_path.parent / (tmp_path.name + '.scratch')


def test_a_checkers_whole_output_is_paged_in_even_when_the_harness_cuts_a_page_and_nothing_is_left_behind(tmp_path, monkeypatch):
    _wordy_checker(monkeypatch)
    cut = {'n': 0}

    def fault(tc):                       # the harness cuts the reply of the first page that is read
        if "/out'" in command_of(tc) or '/out ' in command_of(tc):
            cut['n'] += 1
            return (lambda text: text[:len(text) // 2]) if cut['n'] == 1 else None
    shown, ran, scratch = _written_through_a_wordy_checker(tmp_path, fault)
    text = shown[1]['content']
    assert denial.refused(shown[1]) and 'x' * 20_000 in text and 'REFUSED' in text and cut['n'] >= 2
    assert (tmp_path / 'r.rb').read_text() == 'def a\n  1\nend\n'
    assert not [n for n in os.listdir(scratch) if n.startswith('.ctx-run-')]


@pytest.mark.parametrize('what', ['the first reply is cut', 'the checker is killed at its deadline after 20,000 bytes of words'])
def test_a_run_directory_is_removed_when_the_checker_never_gave_a_verdict(tmp_path, monkeypatch, what):
    """No verdict is UNKNOWN, which never refuses (the write lands); the harness's directory with the candidate in it goes either way."""
    _wordy_checker(monkeypatch, linger=what.startswith('the checker'))
    monkeypatch.setattr(syntaxcheck, 'TIMEOUT', 1)
    shown, ran, scratch = _written_through_a_wordy_checker(tmp_path, cut_first=what.startswith('the first'))
    assert denial.landed(shown[1]) and (tmp_path / 'r.rb').read_text() == 'BAD\n'
    assert not [n for n in os.listdir(scratch) if n.startswith('.ctx-run-')] and len(stubs(ran, 'rm')) >= 1


@pytest.mark.parametrize('name,args', [('write_file', {'path': 'n.txt', 'content': 'hi\n'}), ('edit_file', {'path': 'm.txt', 'old_string': 'a', 'new_string': 'b'})],
                         ids=['a new file: the write is the first call', 'an edit: the survey follows the landing write'])
def test_the_workspace_survey_cria_asks_after_a_landing_write_reaches_the_view(tmp_path, name, args):
    """After the write that lands the bytes cria asks for the survey on its own (no call carries it), and the inbound pass applies it right after
    that write's result: the view that knew nothing of the workspace now holds its tree, post-write, and the model is shown nothing of it."""
    from cria import wsview
    (tmp_path / 'm.txt').write_text('a\n')
    (tmp_path / 'other.py').write_text('x = 1\n')
    view = wsview.View(str(tmp_path), 'sid')
    token = wsview.bind(view)
    try:
        assert not view.surveyed
        tc = lower([call(name, args, 'w1')], root=str(tmp_path))[0]
        done = run(tc, tmp_path)
        ran = []
        shown = settle([{'role': 'assistant', 'tool_calls': [tc]}, {'role': 'tool', 'tool_call_id': tc['id'], 'content': 'Output:\n' + done.stdout}], tmp_path,
                       ran=ran, survey=True)
        assert denial.landed(shown[1]) and 'survey' not in shown[1]['content'] and 'CTX1' not in shown[1]['content'] and len(shown) == 2
        asked = [c for c in ran if c.startswith('# workspace survey')]
        assert asked and all('/usr/bin/env -i PATH=' in c and len(c) < 3_000 for c in asked)             # a primitive call each: 2.1 KB, no program riding on anything
        assert view.surveyed and view.isfile('other.py') is True and view.isfile(args['path']) is True
    finally:
        wsview.unbind(token)
