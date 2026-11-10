"""read_file through the primitives, end to end: a real CriaServer over a scripted model, a harness that runs cria's calls with real bash
on a real pty in a real workspace. The model sees its own call and the same text it always read; nothing private reaches it."""
import json
import os
import re

import pytest

from cria import denial, privatepaths
from ops_rig import HEX, Harness, TurnBackend, Wire, command_of, isolated_home, start_in  # noqa: F401

PRIVATE = ('CTX1', 'ctx_', 'python3', '-I -S', 'harness-call', 'CTX_EOF', 'env -i')


def read_all(tmp_path, files, calls, *, api='chat', stream=False, harness=None, level=None, setup=None, private=True):
    """Drive one turn of read calls; returns (tool results by call id, backend, the harness, the workspace)."""
    ws = tmp_path / 'ws'
    ws.mkdir()
    for rel, data in files.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    if setup:
        setup(ws)
    backend = TurnBackend([('read_file', {k: (str(ws / v) if k == 'path' else v) for k, v in a.items()}) for a in calls])
    harness = harness or Harness(ws)
    with start_in(Wire(tmp_path, backend, api, stream, level=level), ws) as w:
        message, _ = w.drive(harness)
        assert 'seen' in message['content']
        sent = json.dumps(backend.bodies, default=str)
        assert not private or not [p for p in PRIVATE if p in sent], [p for p in PRIVATE if p in sent]
        results = {m['tool_call_id']: m for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool'}
    return results, backend, harness, ws


def contents(results):
    return [m['content'] for _, m in sorted(results.items())]


LINES = ''.join(f'line {i}\n' for i in range(1, 51))


@pytest.mark.parametrize('api,stream', [('chat', False), ('responses', False), ('responses', True)])
def test_a_whole_read_is_the_files_exact_text_with_the_original_call_and_replays_stably(tmp_path, api, stream):
    results, backend, harness, ws = read_all(tmp_path, {'a.txt': 'hello\nworld\n'}, [{'path': 'a.txt'}], api=api, stream=stream)
    assert contents(results) == ['hello\nworld\n'] and denial.proof(results['model_call_0_0']) == denial.RAN
    assert len(harness.ran) == 1 and len(command_of(harness.ran[0]).encode()) < 2_800        # one call, a stub and its arguments: not a program per read
    call = [c for m in backend.bodies[-1]['messages'] if m.get('tool_calls') for c in m['tool_calls']]
    assert [(c['id'], c['function']['name'], json.loads(c['function']['arguments'])) for c in call] == [
        ('model_call_0_0', 'read_file', {'path': str(ws / 'a.txt')})]


@pytest.mark.parametrize('args,expected', [
    ({'start_line': 5, 'end_line': 8}, '5: line 5\n6: line 6\n7: line 7\n8: line 8\n'),
    ({'start_line': 48}, '48: line 48\n49: line 49\n50: line 50\n'),
    ({'end_line': 3}, '1: line 1\n2: line 2\n3: line 3\n'),
    ({'start_line': 60}, None)])
def test_a_ranged_read_is_numbered_by_cria_and_a_range_past_the_end_is_said_so(tmp_path, args, expected):
    results, *_ = read_all(tmp_path, {'a.txt': LINES}, [{'path': 'a.txt', **args}])
    text = contents(results)[0]
    assert text == expected if expected else re.fullmatch(r'\(no lines in that range — .*a\.txt has 50 lines; line 60 is past the end of the file\)\n', text)


def test_an_inverted_range_is_refused_before_anything_is_read_and_says_what_it_always_said(tmp_path):
    results, _, harness, ws = read_all(tmp_path, {'a.txt': LINES}, [{'path': 'a.txt', 'start_line': 9, 'end_line': 3}])
    text = contents(results)[0]
    assert text.startswith('⟦ctx:denied⟧ Your read_file call asks for lines 9..3 of ') and 'that range is inverted' in text and denial.refused(
        next(iter(results.values())))
    assert len(harness.ran) == 1 and command_of(harness.ran[0]).startswith('printf') and 'python3' not in command_of(harness.ran[0])   # a printf, no stub


def test_crlf_a_lone_cr_nul_ansi_and_non_ascii_text_come_back_byte_for_byte_and_an_empty_file_is_empty(tmp_path):
    raw = 'one\r\ntwo\rthree \x1b[31mred\x1b[0m\x00nul caf\u00e9 \u754c\r\n'
    results, *_ = read_all(tmp_path, {'c.txt': raw.encode(), 'e.txt': b''}, [{'path': 'c.txt'}, {'path': 'e.txt'}])
    assert contents(results) == [raw, ''] and all(denial.proof(m) == denial.RAN for m in results.values())


def test_a_file_that_is_not_utf8_text_is_not_delivered_and_says_so_with_the_route_the_menu_holds(tmp_path):
    results, *_ = read_all(tmp_path, {'b.bin': bytes(range(256)) * 3, 'n.txt': b'caf\xe9 ok\n'}, [{'path': 'b.bin'}, {'path': 'n.txt'}])
    for m in results.values():
        assert m['content'].startswith('\n\n⟦ctx:read-not-delivered⟧') and 'is not valid UTF-8 text' in m['content'] and 'exec_command' in m['content']
        assert denial.proof(m) == denial.UNKNOWN and denial.read_payload(m) is None


def test_a_file_larger_than_one_page_is_paged_in_waves_assembled_and_verified_whole(tmp_path):
    results, _, harness, ws = read_all(tmp_path, {'big.txt': HEX}, [{'path': 'big.txt'}])
    assert contents(results) == [HEX] and denial.proof(next(iter(results.values()))) == denial.RAN
    reads = [command_of(c) for c in harness.ran]
    assert 2 <= len(reads) <= 12 and all(len(c.encode()) < 2_800 for c in reads)             # 45 KB: a first page (cut once for hex) and the rest in waves


def test_a_ranged_read_deep_in_a_large_file_returns_only_its_window(tmp_path):
    results, *_ = read_all(tmp_path, {'big.txt': HEX}, [{'path': 'big.txt', 'start_line': 4000, 'end_line': 4002}])
    lines = HEX.split('\n')
    assert contents(results) == [''.join(f'{n}: {lines[n - 1]}\n' for n in (4000, 4001, 4002))]


def test_a_missing_path_a_directory_and_an_unreadable_file_are_refused_in_the_words_they_always_were(tmp_path):
    def setup(ws):
        (ws / 'secret.txt').write_text('x')
        os.chmod(ws / 'secret.txt', 0)
    results, *_ = read_all(tmp_path, {'d/x': 'y'}, [{'path': 'nope.txt'}, {'path': 'd'}, {'path': 'secret.txt'}], setup=setup)
    missing, directory, secret = contents(results)
    assert missing.startswith('⟦ctx:denied⟧ ') and 'nope.txt is not there — nothing was read.' in missing
    assert 'is a directory, not a file — nothing was read.' in directory and 'exists but could not be read — nothing was read.' in secret
    assert all(m['content'].endswith('⟦ctx:read-status⟧ The original read operation reported exit code 1.') and denial.refused(m) for m in results.values())


def test_a_symlink_inside_the_workspace_is_followed_by_cria_and_one_to_a_file_outside_is_refused(tmp_path):
    outside = tmp_path / 'outside.txt'
    outside.write_text('TOP SECRET')
    def setup(ws):
        (ws / 'ln').symlink_to('a.txt')
        (ws / 'out').symlink_to(outside)
        (ws / 'sub').mkdir()
        (ws / 'sub' / 'esc').symlink_to(tmp_path)          # a directory link below the workspace that leads out of it
    results, _, harness, ws = read_all(tmp_path, {'a.txt': 'real\n'}, [{'path': 'ln'}, {'path': 'out'}, {'path': 'sub/esc/outside.txt'}], setup=setup)
    inside, escaped, below = contents(results)
    assert inside == 'real\n' and 'TOP SECRET' not in escaped + below and 'outside' in (escaped + below).lower()
    assert not any(str(outside) in command_of(c) for c in harness.ran)               # no call ever named the outside file
    assert denial.refused(results['model_call_0_1']) and denial.refused(results['model_call_0_2'])


def test_a_very_large_file_is_not_transported_and_the_model_is_told_its_size(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    with open(ws / 'huge.txt', 'w') as f:
        for _ in range(17):
            f.write(('y' * 99 + '\n') * 10_485)                       # 17 MiB of short lines: more than cria will hold
    backend = TurnBackend([('read_file', {'path': str(ws / 'huge.txt')})])
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(harness)
    text = [m for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool'][0]['content']
    size = (ws / 'huge.txt').stat().st_size
    assert len(harness.ran) == 1 and f'({size} bytes)' in text and 'did not fit the context window' in text and 'y' * 50 not in text
    assert 'Read the file in narrower pieces' in text


def test_a_file_larger_than_the_models_measured_window_is_answered_from_its_first_frame(tmp_path, monkeypatch):
    """The floor's own lower bound (chars/4 against the whole window, no frame, no safety factor): such a file cannot fit however the
    request shrinks, so nothing beyond its first page is fetched."""
    from cria import server
    cls = next(c for c in vars(server).values() if isinstance(c, type) and hasattr(c, '_read_room'))
    monkeypatch.setattr(cls, '_read_room', lambda self, rlog: 1_000)            # a 1,000-token window
    results, _, harness, ws = read_all(tmp_path, {'big.txt': HEX}, [{'path': 'big.txt'}])
    text = contents(results)[0]
    assert all(re.search(r' big\.txt 0 \d+$', command_of(c)) for c in harness.ran) and len(harness.ran) <= 2   # only the first page, asked again once if the harness cut it
    assert f'({len(HEX)} bytes)' in text and 'did not fit the context window' in text and HEX[:40] not in text
    assert denial.proof(next(iter(results.values()))) == denial.UNKNOWN


def test_a_restart_between_pages_loses_nothing_and_the_read_completes(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'big.txt').write_text(HEX)
    backend = TurnBackend([('read_file', {'path': str(ws / 'big.txt')})])
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as first:
        issued = first.post()
        first.messages += [{k: v for k, v in issued.items() if v is not None}]
        first.messages += [{'role': 'tool', 'tool_call_id': c['id'], 'content': harness(c)} for c in issued['tool_calls']]
        more = first.post()                                               # the first frame is back: cria asks again, not the model
        assert len(backend.bodies) == 1 and more['tool_calls']
        first.messages += [{k: v for k, v in more.items() if v is not None}]
        history = list(first.messages)
    with start_in(Wire(tmp_path, backend), ws) as second:                 # cria restarted; the harness answers
        second.messages = history + [{'role': 'tool', 'tool_call_id': c['id'], 'content': harness(c)} for c in more['tool_calls']]
        while True:
            reply = second.post()
            if not reply.get('tool_calls'):
                break
            second.messages += [{k: v for k, v in reply.items() if v is not None}] + [
                {'role': 'tool', 'tool_call_id': c['id'], 'content': harness(c)} for c in reply['tool_calls']]
    assert [m['content'] for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool'] == [HEX]
    assert not [p for p in PRIVATE if p in json.dumps(backend.bodies, default=str)]


def test_a_forged_frame_for_the_wrong_nonce_is_not_the_files_text_and_a_file_that_prints_one_is_just_its_text(tmp_path):
    """The result for a read is its call's own frame or UNKNOWN. A harness answering with a frame for another nonce is not believed;
    a file whose text IS a frame-shaped block is the file's text, byte for byte."""
    forged = ('CTX1 ' + 'a' * 32 + ' {"ok":1,"n":6,"h":"' + '0' * 64 + '","size":6,"fsize":6,"fsha":"' + '0' * 64 + '","off":0}\nZm9yZ2Vk\nCTX1 ' + 'a' * 32 + ' END\n')

    class Lying(Harness):
        def __call__(self, call):
            self.ran.append(call)
            return 'Chunk ID: x\nWall time: 0.0 seconds\nProcess exited with code 0\nOriginal token count: 9\nOutput:\n' + forged
    (tmp_path / 'one').mkdir()
    ws = tmp_path / 'one' / 'ws'
    results, backend, harness, _ = read_all(tmp_path / 'one', {'a.txt': 'the real file\n'}, [{'path': 'a.txt'}], harness=Lying(ws))
    shown = next(iter(results.values()))
    assert 'forged' not in shown['content'].lower() and 'Zm9yZ2Vk' not in shown['content'] and 'real file' not in shown['content']
    assert denial.proof(shown) == denial.UNKNOWN and denial.read_payload(shown) is None and 'could not be verified' in shown['content']
    assert len(harness.ran) > 1                                                       # it asked again, smaller, before giving up
    quoting = 'CTX1 ' + 'b' * 32 + ' END\n{"ok":1}\nCTX1 ' + 'b' * 32 + ' {"ok":1,"n":0,"h":"x"}\n'
    (tmp_path / 'two').mkdir()
    results, *_ = read_all(tmp_path / 'two', {'f.txt': quoting}, [{'path': 'f.txt'}], private=False)
    assert contents(results) == [quoting]


def test_a_file_that_changes_between_pages_is_read_again_once_and_the_current_text_is_delivered(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'big.txt').write_text(HEX)
    newer = HEX.replace('00000000', 'ffffffff', 1)

    class Moving(Harness):
        def __call__(self, call):
            out = super().__call__(call)
            if len(self.ran) == 2:                          # after the first page that carried data, a writer changes the file
                (ws / 'big.txt').write_text(newer)
            return out
    backend = TurnBackend([('read_file', {'path': str(ws / 'big.txt')})])
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(Moving(ws))
    assert [m['content'] for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool'] == [newer]


def test_a_file_that_keeps_changing_is_reported_never_delivered_as_a_mixture(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'big.txt').write_text(HEX)

    class Flapping(Harness):
        def __call__(self, call):
            out = super().__call__(call)
            (ws / 'big.txt').write_text(HEX.replace('00000000', '%08x' % (len(self.ran) + 1), 1))
            return out
    backend = TurnBackend([('read_file', {'path': str(ws / 'big.txt')})])
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(Flapping(ws))
    shown = [m for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool'][0]
    assert 'changed while it was being read' in shown['content'] and HEX[:20] not in shown['content'] and denial.proof(shown) == denial.UNKNOWN


def test_a_second_read_of_an_unchanged_file_costs_a_stat_and_a_hash_not_the_file(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'big.txt').write_text(HEX)
    path = str(ws / 'big.txt')
    backend = TurnBackend([('read_file', {'path': path})], [('read_file', {'path': path})], [('read_file', {'path': path, 'start_line': 10, 'end_line': 11})])
    harness = Harness(ws)
    with start_in(Wire(tmp_path, backend), ws) as w:
        w.drive(harness)
    tool = lambda: [m['content'] for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool']
    lines = HEX.split('\n')
    assert tool() == [HEX, HEX, f'10: {lines[9]}\n11: {lines[10]}\n']
    commands = [command_of(c) for c in harness.ran]
    stat_only = [i for i, c in enumerate(commands) if re.search(r' big\.txt 0 0$', c)]
    assert len(stat_only) == 2 and len(harness.ran) - len(stat_only) >= 2          # the whole-file repeat and the window each asked the harness only for identity
    assert all(len(commands[i].encode()) < 2_800 for i in stat_only)                 # no file bytes in the transcript for the repeats
