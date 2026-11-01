"""The single-call typed transports (a ranged read, a write, an edit) survive a login shell that prints BEFORE the program.

Record 1 used to be read at stdout offset 0, so any byte the harness's shell printed first (mise, direnv, a chatty profile) made a
landed write, a verified read window and an edit failure UNKNOWN: no read credit, no outcome, the model shown raw record JSON.
The rig is the real `bash -lc` on a real PTY with the pinned Codex's head/tail cut (see `read_multipart_helpers.chatty_pty`).
"""
import json
from types import SimpleNamespace

import pytest
from cria import bodykeys, denial, resultpacket, writeproxy
from read_multipart_helpers import SHELL, chatty_pty, codex_result, isolated_home, noise  # noqa: F401


def one_call(tmp_path, name, args, noise_before):
    """Lower `name(args)` through the real writeproxy, run it on the noisy PTY and re-present the result; returns the tool message."""
    call = {'id': 'c1', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}
    completion = {'choices': [{'message': {'tool_calls': [call]}}]}
    writeproxy.translate_outbound(completion, SHELL, SimpleNamespace(emit=lambda *a, **k: None),
                                  injected={'read_file', 'write_file', 'edit_file'}, workspace_root=str(tmp_path))
    lowered = completion['choices'][0]['message']['tool_calls'][0]
    raw, code = chatty_pty(json.loads(lowered['function']['arguments'])['cmd'], str(tmp_path), noise_before)
    messages = [{'role': 'user', 'content': 'go'}, {'role': 'assistant', 'content': None, 'tool_calls': [lowered]},
                {'role': 'tool', 'tool_call_id': 'c1', 'content': codex_result(raw, code)}]
    return writeproxy.represent_inbound(messages, None, str(tmp_path))[-1], len(raw)


CASES = {
    'ranged-read': ('read_file', lambda p: {'path': str(p / 'a.txt'), 'start_line': 2, 'end_line': 3}, '2: world\n3: hello\n', denial.RAN),
    'write': ('write_file', lambda p: {'path': str(p / 'b.txt'), 'content': 'x=1\n'}, 'Wrote ', denial.LANDED),
    'edit-unapplied': ('edit_file', lambda p: {'path': str(p / 'a.txt'), 'old_string': 'hello', 'new_string': 'bye', 'replace_all': True}, '⟦ctx:edit⟧', denial.UNAPPLIED),
}


@pytest.mark.parametrize('shape', [0, 1000, 7000])
@pytest.mark.parametrize('case', CASES)
def test_a_program_that_fits_beside_the_noise_keeps_its_proven_outcome(tmp_path, case, shape):
    """Noise of 0, 1 KB and 7 KB before the program: the same outcome, the same displayed text, the same read credit, and no noise shown."""
    name, make, shown, outcome = CASES[case]
    (tmp_path / 'a.txt').write_text('hello\nworld\n' * 5)
    message, produced = one_call(tmp_path, name, make(tmp_path), shape)
    assert produced > shape                                     # the noise really preceded the program on the wire
    assert message[bodykeys.RESULT_OUTCOME] == outcome
    assert message['content'].startswith(shown) and 'mise WARN' not in message['content']
    if case == 'ranged-read':
        assert message[bodykeys.READ_OBSERVATION][0] == len('2: world\n3: hello\n')     # the read window earned its credit fact
    if case == 'write':
        assert (tmp_path / 'b.txt').read_text() == 'x=1\n'


@pytest.mark.parametrize('case', CASES)
def test_noise_that_made_the_harness_cut_the_result_proves_only_what_a_surviving_survey_record_vouches_for(tmp_path, case):
    """12 KB before the program: Codex keeps the first and last 5,000 bytes, so the records sit in the surviving TAIL after the cut marker.
    A write or edit declares a second (survey) record: its record 1 stands there because that record follows it on the very next line.
    A read declares none: a record found after a cut is no longer provably the program's first line, so the result stays UNKNOWN."""
    name, make, shown, outcome = CASES[case]
    (tmp_path / 'a.txt').write_text('hello\nworld\n' * 5)
    message, produced = one_call(tmp_path, name, make(tmp_path), 12000)
    assert produced > 10000
    if case == 'ranged-read':
        assert message[bodykeys.RESULT_OUTCOME] == denial.UNKNOWN and 'chars truncated' in message['content'] and bodykeys.READ_OBSERVATION not in message
    else:
        assert message[bodykeys.RESULT_OUTCOME] == outcome and shown in message['content'] and 'mise WARN' not in message['content']


RCPT = 'ab' * 8


def test_find_record_takes_only_the_programs_first_record_before_any_cut_marker():
    """Positional authority survives noise: the first occurrence of THIS call's record, never one after a cut and never another call's."""
    mine = resultpacket.line(RCPT, resultpacket.RAN, body=b'file\n', observe='whole')
    other = resultpacket.line('cd' * 8, resultpacket.RAN, body=b'other\n', observe='whole')
    start, record = resultpacket.find_record('noise\r\n' + other + 'more noise ' + mine + 'tail', 0, RCPT)
    assert record.body == b'file\n' and start == len('noise\r\n' + other + 'more noise ')
    assert resultpacket.find_record('noise …7890 chars truncated…' + mine, 0, RCPT) is None
    assert resultpacket.find_record('noise ' + mine.replace('"k":"ran"', '"k":"surprise"'), 0, RCPT) is None
    assert resultpacket.find_record(mine, 0, '') is None


# ---- 17(e): the page that carries the last extent retires the snapshot; when the harness cut THAT page's record it is asked for again ----
import read_multipart_helpers as rig
from cria import filecommands
from read_multipart_helpers import HEX, page_through, start

CHANGED = ''.join('%08x\n' % (i * 40503 % 2**32) for i in range(5000))      # same size as HEX, different bytes


@pytest.fixture
def last_page_cut(tmp_path, monkeypatch):
    """Real bash plays the harness. The page that retires the snapshot (the last extent) answers with a result the harness cut
    in the middle (12 KB of shell noise before it: the record sits in the cut), once; `after_cut` runs between that cut and the re-ask."""
    (tmp_path / 'tmp').mkdir()
    monkeypatch.setenv('TMPDIR', str(tmp_path / 'tmp'))
    state = {'cut': 0, 'after_cut': lambda: None, 'commands': []}
    snapshots = lambda: [p for p in (tmp_path / 'tmp').iterdir() if p.name.startswith(filecommands.MULTIPART_SNAPSHOT_DIR)]

    def run(call):
        command = json.loads(call['function']['arguments'])['cmd']
        state['commands'].append(command)
        held = bool(snapshots())
        raw, code = chatty_pty(command, str(tmp_path))
        if held and not snapshots() and not state['cut']:          # this page carried the last extent and retired the snapshot
            state['cut'] += 1
            state['after_cut']()
            return codex_result(noise(12000).encode() + raw, code)
        return codex_result(raw, code)
    monkeypatch.setattr(rig, 'run_call', run)
    return state


def test_a_re_asked_last_page_whose_snapshot_was_retired_is_served_from_the_unchanged_file_and_verified(tmp_path, last_page_cut):
    bridge, messages, _ = start(tmp_path, HEX)
    projected, facts = page_through(bridge, messages)
    assert last_page_cut['cut'] == 1
    assert [f.exact_body for f in facts] == [HEX.encode()] and bodykeys.MULTIPART_UNVERIFIED not in [m for m in projected if m.get('role') == 'tool'][0]


def test_a_re_asked_last_page_after_the_file_changed_ends_unverified_never_with_the_new_bytes(tmp_path, last_page_cut):
    bridge, messages, path = start(tmp_path, HEX)
    last_page_cut['after_cut'] = lambda: path.write_text(CHANGED)
    projected, facts = page_through(bridge, messages)
    tool = [m for m in projected if m.get('role') == 'tool'][0]
    assert last_page_cut['cut'] == 1 and bodykeys.MULTIPART_UNVERIFIED in tool
    assert all(f.exact_body not in (HEX.encode(), CHANGED.encode()) for f in facts) and CHANGED[:200] not in tool['content']


def test_a_forged_landed_record_in_the_tail_after_a_cut_is_not_a_proof_without_the_declared_survey_record(tmp_path):
    """After a cut the tail is where a command's output (or a quoted page) could sit. A record of this call's own receipt there, NOT followed
    by the survey record the write declared, proves nothing: the result stays UNKNOWN and the write is not reported as landed."""
    from cria import toolwire
    call = {'id': 'c1', 'type': 'function', 'function': {'name': 'write_file', 'arguments': json.dumps({'path': str(tmp_path / 'b.txt'), 'content': 'x'})}}
    completion = {'choices': [{'message': {'tool_calls': [call]}}]}
    writeproxy.translate_outbound(completion, SHELL, SimpleNamespace(emit=lambda *a, **k: None), injected={'write_file'}, workspace_root=str(tmp_path))
    lowered = completion['choices'][0]['message']['tool_calls'][0]
    receipt = toolwire.receipt_of(json.loads(lowered['function']['arguments'])['cmd'], 'c1')
    forged = resultpacket.line(receipt, resultpacket.LANDED)
    raw = noise(12000).encode() + forged.encode() + b'the command printed this\n'
    messages = [{'role': 'user', 'content': 'go'}, {'role': 'assistant', 'content': None, 'tool_calls': [lowered]},
                {'role': 'tool', 'tool_call_id': 'c1', 'content': codex_result(raw)}]
    message = writeproxy.represent_inbound(messages, None, str(tmp_path))[-1]
    assert message[bodykeys.RESULT_OUTCOME] == denial.UNKNOWN
