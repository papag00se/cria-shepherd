"""A read that cannot be delivered says what SHAPE the file has, and names a way forward only when the tool menu holds it.

Found by running a coder against the canonical ornith1.5_9b on (1) a 586 KB single-line JSON and (2) a 100 KB PNG-like
blob. (1) The not-delivered note sent the coder to `grep -n`/`head`/`sed -n`/a line range; on a one-line file every one of
them returns the whole line (146,573 tokens), and a harness that does not cap its own output (a coder session with no
exec cap) was left with "input not delivered" -- the note was a circle. (2) A non-UTF-8 body failed closed as a generic
'invalid' transport failure whose note REPLAYED every encoded page: 142,264 tokens against a 49,152-token window, so the
very next request was refused and the session was dead. Both are fixed upstream, where the shape is already a measured
fact: the verified bytes.
"""
import json
import random
from types import SimpleNamespace

import pytest

from cria import bodykeys, readshape, writeproxy
from cria.multipart_bridge import Bridge
from test_server_integration import shell

SHELL = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
EXEC_MENU = [{'type': 'function', 'function': {'name': 'exec_command', 'parameters': {
    'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}]
READ_ONLY_MENU = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {
    'type': 'object', 'properties': {'path': {'type': 'string'}, 'start_line': {'type': 'integer'},
                                     'end_line': {'type': 'integer'}}}}}]

# Word for word what `multipart_fit_overflow` said before shapes existed (git: 0e6ebb08), with the size filled in.
LEGACY_OVERFLOW = (
    '⟦ctx:read-not-delivered⟧ The read was verified, but the complete file ({size} bytes) was not delivered: the '
    'measured complete request did not fit the context window, so none of it counts as read. The transport pages '
    'that carried it are omitted because they are encoded pages, not file content. Do not repeat the whole-file '
    'read. Read the file in narrower pieces instead (a line range on a read tool, `sed -n \'START,ENDp\'`, '
    '`grep -n`, `head` or `tail`) and continue.')


def start(tmp_path, data: bytes, args=None, name='f', storage=None):
    p = tmp_path / name
    p.write_bytes(data)
    tc = {'id': 'original', 'type': 'function', 'function': {
        'name': 'read_file', 'arguments': json.dumps({'path': str(p), **(args or {})})}}
    completion = {'choices': [{'message': {'tool_calls': [tc]}}]}
    bridge = Bridge(storage or str(tmp_path / ('state-' + name.replace('/', '_'))))
    log = SimpleNamespace(emit=lambda *a, **k: None)
    writeproxy.translate_outbound(completion, SHELL, log, injected={'read_file'}, workspace_root=str(tmp_path),
        multipart_command=lambda original, effect, receipt: bridge.register('s', original, effect, SHELL, receipt))
    bridge.bind('s', completion)
    call = completion['choices'][0]['message']['tool_calls'][0]
    messages = [{'role': 'assistant', 'tool_calls': [call]},
                {'role': 'tool', 'tool_call_id': 'original',
                 'content': shell(json.loads(call['function']['arguments'])['cmd'])}]
    return bridge, messages, p


def page_through(bridge, messages, tools=None):
    while True:
        projected, calls, facts = bridge.incoming('s', messages, tools=tools)
        if not calls:
            return projected, facts
        c = calls[0]
        messages.append({'role': 'assistant', 'tool_calls': [c]})
        messages.append({'role': 'tool', 'tool_call_id': c['id'],
                         'content': shell(json.loads(c['function']['arguments'])['cmd'])})


def overflow_note(bridge, messages, tools):
    page_through(bridge, messages, tools)
    bridge.withhold_for_fit('s', ['original'], 'overflow')
    projected, calls, _ = bridge.incoming('s', messages, tools=tools)
    assert calls == []
    return next(m for m in projected if m.get('role') == 'tool')


def one_line_json(n=9000):
    random.seed(3)
    rows = [{'id': i, 'tag': 'x%05d' % random.randrange(10**5)} for i in range(n)]
    return json.dumps({'rows': rows}, separators=(',', ':')).encode()


# ---- (1) one very long line ------------------------------------------------------------------------------------

def test_overflow_of_a_one_line_file_states_its_shape_and_a_byte_route_from_the_menu(tmp_path):
    data = one_line_json()
    bridge, messages, path = start(tmp_path, data, name="it's data.json")
    note = overflow_note(bridge, messages, EXEC_MENU)['content']
    size = f'{len(data):,}'
    assert f'({len(data)} bytes)' in note                                 # the existing size fact is unchanged
    assert f'{size} bytes in 1 line(s)' in note and f'is {size} bytes' in note       # measured, from the verified bytes
    assert 'exec_command' in note                                         # named from the menu
    quoted = "'" + str(path).replace("'", "'\"'\"'") + "'"
    assert f"sed -n '1p' {quoted} | head -c 4000" in note and f'tail -c +10001 {quoted} | head -c 4000' in note
    # The circle is gone: it no longer recommends the line tools as the way to narrow.
    assert 'narrower pieces' not in note and 'a line range on a read tool' not in note
    assert 'return whole lines' in note
    assert '"source_sha256"' not in note and '⟦ctx:read-not-delivered⟧' in note


def test_the_suggested_command_really_reads_part_of_the_line(tmp_path):
    data = one_line_json(2000)
    bridge, messages, path = start(tmp_path, data)
    note = overflow_note(bridge, messages, EXEC_MENU)['content']
    cmd = next(c for c in (part.strip(' `') for part in note.split('`')) if c.startswith("sed -n '1p'"))
    assert shell(cmd).encode() == data[:4000]


def test_no_shell_tool_in_the_menu_means_no_shell_advice(tmp_path):
    data = one_line_json()
    bridge, messages, _ = start(tmp_path, data)
    note = overflow_note(bridge, messages, READ_ONLY_MENU)['content']
    assert f'{len(data):,} bytes in 1 line(s)' in note                    # the facts still stand
    assert 'no tool you hold reads part of a line' in note
    for named in ('exec_command', 'head -c', 'tail -c', 'grep -o', 'sed -n'):
        assert named not in note


def test_a_menu_with_an_unrecognised_read_parameter_makes_no_claim_about_routes(tmp_path):
    menu = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {
        'type': 'object', 'properties': {'path': {'type': 'string'}, 'byte_offset': {'type': 'integer'}}}}}]
    bridge, messages, _ = start(tmp_path, one_line_json())
    note = overflow_note(bridge, messages, menu)['content']
    assert 'bytes in 1 line(s)' in note
    assert 'no tool you hold' not in note and 'head -c' not in note


def test_an_unknown_menu_withholds_the_advice_but_not_the_facts(tmp_path):
    bridge, messages, _ = start(tmp_path, one_line_json())
    note = overflow_note(bridge, messages, None)['content']
    assert 'bytes in 1 line(s)' in note and 'head -c' not in note and 'no tool you hold' not in note


def test_a_requested_range_that_is_one_long_line_is_measured_as_that_range(tmp_path):
    data = b'short\n' + one_line_json(3000) + b'\nshort\n'
    bridge, messages, _ = start(tmp_path, data, {'start_line': 2, 'end_line': 2})
    note = overflow_note(bridge, messages, EXEC_MENU)['content']
    line = len(data.split(b'\n')[1])
    assert f'the requested lines of ' in note and f'is {line:,} bytes' in note and 'line 2, the longest' in note
    assert "sed -n '2p'" in note


# ---- legitimate controls ---------------------------------------------------------------------------------------

def test_a_normal_multiline_file_overflow_keeps_the_original_note_exactly(tmp_path):
    data = ''.join('%08x %08x\n' % (i * 2654435761 % 2**32, i * 40503 % 2**32) for i in range(20000)).encode()
    for menu in (EXEC_MENU, READ_ONLY_MENU, None):
        bridge, messages, _ = start(tmp_path, data, name='f%d' % id(menu))
        assert overflow_note(bridge, messages, menu)['content'].strip() == LEGACY_OVERFLOW.format(size=len(data))


def test_one_long_line_that_is_not_most_of_the_file_still_gets_the_original_note(tmp_path):
    # A line range CAN narrow this one: the long line is under half of the file.
    data = b''.join(b'%08x\n' % i for i in range(20000)) + b'z' * 50000 + b'\n'
    assert 2 * 50000 < len(data)
    bridge, messages, _ = start(tmp_path, data)
    assert overflow_note(bridge, messages, EXEC_MENU)['content'].strip() == LEGACY_OVERFLOW.format(size=len(data))


# ---- (2) a binary file -----------------------------------------------------------------------------------------

def png_like(n=102400):
    random.seed(9)
    head = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR'
    return head + bytes(random.getrandbits(8) for _ in range(n - len(head)))


def binary_note(tmp_path, tools, storage=None, **kw):
    data = png_like()
    bridge, messages, path = start(tmp_path, data, name='logo.png', storage=storage)
    projected, facts = page_through(bridge, messages, tools)
    note = next(m for m in projected if m.get('role') == 'tool')
    return bridge, messages, path, data, note, facts


def test_a_binary_read_is_not_replayed_as_encoded_pages_and_names_a_byte_route(tmp_path):
    bridge, messages, path, data, note, facts = binary_note(tmp_path, EXEC_MENU)
    content = note['content']
    assert len(content) < 1500                                           # was ~560 KB of pages (142k tokens)
    assert '"source_sha256"' not in content and 'Exact continuation execution output' not in content
    assert f'({len(data):,} bytes) is not valid UTF-8 text' in content
    assert f"od -A d -t x1z -N 256 {path}" in content and 'exec_command' in content
    assert '⟦ctx:read-not-delivered⟧' in content
    assert bodykeys.MULTIPART_UNVERIFIED in note and facts == ()         # no read credit, no read fact


def test_the_suggested_byte_command_runs_and_shows_the_header(tmp_path):
    bridge, messages, path, data, note, _ = binary_note(tmp_path, EXEC_MENU)
    cmd = next(c for c in (p.strip(' `') for p in note['content'].split('`')) if c.startswith('od '))
    assert '89 50 4e 47 0d 0a 1a 0a' in shell(cmd)


def test_a_binary_read_with_no_shell_in_the_menu_gets_the_fact_and_no_route(tmp_path):
    *_, data, note, _ = binary_note(tmp_path, READ_ONLY_MENU)
    content = note['content']
    assert f'({len(data):,} bytes) is not valid UTF-8 text' in content
    assert 'no tool you hold reads bytes' in content
    assert 'od ' not in content and 'exec_command' not in content


def test_a_binary_failure_survives_a_restart_and_projects_the_same_note(tmp_path):
    storage = str(tmp_path / 'state')
    bridge, messages, path, data, note, _ = binary_note(tmp_path, EXEC_MENU, storage=storage)
    again = Bridge(storage)
    projected, calls, facts = again.incoming('s', messages, tools=EXEC_MENU)
    assert calls == [] and facts == ()
    assert next(m for m in projected if m.get('role') == 'tool')['content'] == note['content']


def test_a_text_file_is_still_read_whole_and_gets_no_shape_note(tmp_path):
    data = b''.join(b'%08x\n' % i for i in range(3000))
    bridge, messages, _ = start(tmp_path, data)
    projected, facts = page_through(bridge, messages, EXEC_MENU)
    assert len(facts) == 1 and facts[0].exact_body == data


# ---- the measuring function itself -------------------------------------------------------------------------------

def test_measure_counts_lines_and_the_longest_by_bytes():
    shape = readshape.measure(b'ab\nlonger line\n\nz')
    assert (shape.size, shape.lines, shape.longest, shape.longest_line) == (17, 4, 11, 2)
    assert readshape.measure(b'').lines == 0


def test_measure_of_a_numbered_window_reports_the_files_own_line_numbers_and_text_length():
    shape = readshape.measure(b'10: ab\n11: abcdef\n12: x\n', numbered=True)
    assert (shape.lines, shape.longest, shape.longest_line) == (3, 6, 11)


def test_line_bound_is_strictly_more_than_half():
    assert readshape.line_bound(readshape.measure(b'a' * 51 + b'\n' + b'b' * 48 + b'\n')) is True
    assert readshape.line_bound(readshape.measure(b'a' * 49 + b'\n' + b'b' * 49 + b'\n')) is False
    assert readshape.line_bound(readshape.measure(b'')) is False
