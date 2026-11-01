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
def test_noise_that_made_the_harness_cut_the_record_leaves_the_outcome_unknown_never_a_proof(tmp_path, case):
    """12 KB before the program: Codex keeps the first and last 5,000 bytes, so the record sits in the surviving TAIL after the cut
    marker. A record found after a cut is no longer provably the program's first line: the result stays UNKNOWN, with no read credit."""
    name, make, _, _ = CASES[case]
    (tmp_path / 'a.txt').write_text('hello\nworld\n' * 5)
    message, produced = one_call(tmp_path, name, make(tmp_path), 12000)
    assert 'chars truncated' in message['content'] and produced > 10000
    assert message[bodykeys.RESULT_OUTCOME] == denial.UNKNOWN
    assert bodykeys.READ_OBSERVATION not in message


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
