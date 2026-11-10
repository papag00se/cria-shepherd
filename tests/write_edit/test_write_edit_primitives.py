"""The write route's engine against the real stubs on a real directory: payload size classes (one command, staged, waves), a path that cannot be
carried, a restart between steps, two writers of one file (compare-and-swap: no update lost), links in the path, and a harness checker."""
import os
import shutil

import pytest

from cria import denial
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


@pytest.mark.parametrize('case', ['dir_link_inside', 'dir_link_outside', 'staged_through_link'])
def test_a_link_in_the_path_is_followed_by_cria_only_inside_the_workspace_and_roots(tmp_path, case):
    outside = tmp_path / 'outside'
    outside.mkdir()
    ws = tmp_path / 'ws'
    (ws / 'real').mkdir(parents=True)
    os.symlink('real', ws / 'ln')
    os.symlink(outside, ws / 'esc')
    content = 'x = 1\n' if case != 'staged_through_link' else body(100_000).decode()
    path = 'esc/f.txt' if case == 'dir_link_outside' else 'ln/f.txt'
    _, _, shown = do('write_file', {'path': path, 'content': content}, ws, external_dir_permission='none')
    if case == 'dir_link_outside':
        assert denial.refused(shown[1]) and 'outside the project directory' in shown[1]['content'] and not list(outside.iterdir())
    elif case == 'dir_link_inside':
        assert denial.landed(shown[1]) and (ws / 'real' / 'f.txt').read_text() == content
    else:    # a payload past one command is staged beside the target by `put`, which follows no link: said (did not run), nothing half-written
        assert denial.unlanded(shown[1]) and not list((ws / 'real').iterdir()) and not [n for n in os.listdir(ws) if n.startswith('.ctx')]


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
