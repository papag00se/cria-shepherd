"""A read that cannot be delivered says what SHAPE the file has, and names a route only when the tool menu holds one.
ornith1.5_9b: a 586 KB one-line JSON got `grep -n`/`head`/`sed -n` advice that returns the whole line (a circle); a 100 KB PNG
replayed 142k tokens of encoded pages against a 49k window and killed the session."""
import json
import random
from cria import bodykeys, readshape
from cria.multipart_bridge import Bridge
from read_multipart_helpers import HEX, MENU, READ_ONLY_MENU, isolated_home, page_through, pty_run, start  # noqa: F401

LEGACY = ('⟦ctx:read-not-delivered⟧ The read was verified, but the complete file ({n} bytes) was not delivered: the measured complete '
          'request did not fit the context window, so none of it counts as read. The transport pages that carried it are omitted because '
          'they are encoded pages, not file content. Do not repeat the whole-file read. Read the file in narrower pieces instead (a line '
          'range on a read tool, `sed -n \'START,ENDp\'`, `grep -n`, `head` or `tail`) and continue.')
UNKNOWN_PARAM = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object', 'properties': {
    'path': {'type': 'string'}, 'byte_offset': {'type': 'integer'}}}}}]

def overflow_note(bridge, messages, tools):
    page_through(bridge, messages, tools); bridge.withhold_for_fit('s', ['original'], 'overflow')
    projected, calls, _ = bridge.incoming('s', messages, tools=tools)
    assert calls == []
    return next(m for m in projected if m.get('role') == 'tool')['content']

def one_line_json(n=1500):
    r = random.Random(3)
    return json.dumps({'rows': [{'id': i, 'tag': 'x%05d' % r.randrange(10**5)} for i in range(n)]}, separators=(',', ':')).encode()

def test_overflow_of_a_one_line_file_states_its_measured_shape_and_a_route_only_from_the_menu(tmp_path):
    """The note's facts come from the verified bytes; the byte route is derived from the menu (shell → head/tail -c; read-only → none;
    unrecognised parameter or unknown menu → no claim); and the suggested command really reads part of the line."""
    data = one_line_json(); bridge, messages, path = start(tmp_path, data, name="it's data.json")
    note = overflow_note(bridge, messages, MENU); size = f'{len(data):,}'
    assert f'({len(data)} bytes)' in note and f'{size} bytes in 1 line(s)' in note and f'is {size} bytes' in note and 'exec_command' in note
    quoted = "'" + str(path).replace("'", "'\"'\"'") + "'"
    assert f"sed -n '1p' {quoted} | head -c 4000" in note and f'tail -c +10001 {quoted} | head -c 4000' in note
    assert 'narrower pieces' not in note and 'return whole lines' in note and '"source_sha256"' not in note
    cmd = next(c for c in (p.strip(' `') for p in note.split('`')) if c.startswith("sed -n '1p'"))
    assert pty_run(cmd).encode() == data[:4000]
    for menu, absent, present in [(READ_ONLY_MENU, ('exec_command', 'head -c', 'sed -n', 'grep -o'), 'no tool you hold reads part of a line'),
                                  (UNKNOWN_PARAM, ('head -c', 'no tool you hold'), ''), (None, ('head -c', 'no tool you hold'), '')]:
        b, m, _ = start(tmp_path, data, name='m%d' % id(menu)); n = overflow_note(b, m, menu)
        assert f'{size} bytes in 1 line(s)' in n and present in n and not any(a in n for a in absent)

def test_a_requested_range_that_is_one_long_line_is_measured_as_that_range_and_ordinary_overflow_keeps_the_original_note(tmp_path):
    """Range measured as the range; a multi-line file, or a long line under half the file, still gets the original note word for word."""
    data = b'short\n' + one_line_json(600) + b'\nshort\n'
    bridge, messages, _ = start(tmp_path, data, {'start_line': 2, 'end_line': 2}); note = overflow_note(bridge, messages, MENU)
    assert 'the requested lines of ' in note and f'is {len(data.split(b"\n")[1]):,} bytes' in note and 'line 2, the longest' in note and "sed -n '2p'" in note
    many = HEX.encode()
    minor = HEX.encode() + b'z' * 20000 + b'\n'
    for i, (blob, menu) in enumerate([(many, MENU), (many, READ_ONLY_MENU), (many, None), (minor, MENU)]):
        b, m, _ = start(tmp_path, blob, name='n%d' % i)
        assert overflow_note(b, m, menu).strip() == LEGACY.format(n=len(blob))

def test_a_binary_read_is_not_replayed_as_pages_names_a_byte_route_and_survives_restart(tmp_path):
    """A non-UTF-8 body fails as a short fact-note (no encoded pages, no credit); the `od` route runs and shows the header; no shell → no route."""
    r = random.Random(9); data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + bytes(r.getrandbits(8) for _ in range(40000))
    storage = str(tmp_path / 'state'); bridge, messages, path = start(tmp_path, data, name='logo.png', storage=storage)
    projected, facts = page_through(bridge, messages, MENU); note = next(m for m in projected if m.get('role') == 'tool')
    c = note['content']
    assert len(c) < 1500 and '"source_sha256"' not in c and f'({len(data):,} bytes) is not valid UTF-8 text' in c and '⟦ctx:read-not-delivered⟧' in c
    assert bodykeys.MULTIPART_UNVERIFIED in note and facts == ()
    cmd = next(x for x in (p.strip(' `') for p in c.split('`')) if x.startswith('od '))
    assert f'od -A d -t x1z -N 256 {path}' in c and '89 50 4e 47 0d 0a 1a 0a' in pty_run(cmd)
    projected, calls, facts = Bridge(storage).incoming('s', messages, tools=MENU)
    assert calls == [] and facts == () and next(m for m in projected if m.get('role') == 'tool')['content'] == c
    for menu, claim in ((READ_ONLY_MENU, True), (None, False)):          # unknown menu → the fact, never a claim about routes
        b, m, _ = start(tmp_path, data, name='ro%s.png' % claim); p2, _ = page_through(b, m, menu)
        c2 = next(x for x in p2 if x.get('role') == 'tool')['content']
        assert ('no tool you hold reads bytes' in c2) == claim and 'od ' not in c2 and 'exec_command' not in c2 and 'is not valid UTF-8' in c2

def test_plain_text_is_read_whole_and_measure_counts_lines_and_bytes(tmp_path):
    """A text file gets no shape note; measure() counts lines/longest by bytes (numbered windows by the file's own line numbers); line-bound is strictly > half."""
    assert (lambda m: (m.size, m.lines, m.longest, m.longest_line))(readshape.measure(b'ab\nlonger line\n\nz')) == (17, 4, 11, 2) and readshape.measure(b'').lines == 0
    w = readshape.measure(b'10: ab\n11: abcdef\n12: x\n', numbered=True); assert (w.lines, w.longest, w.longest_line) == (3, 6, 11)
    text = b''.join(b'%08x\n' % i for i in range(3000)); _, facts = page_through(*start(tmp_path, text)[:2], MENU)
    assert facts[0].exact_body == text
    assert [readshape.line_bound(readshape.measure(b'a' * k + b'\n' + b'b' * 48 + b'\n')) for k in (51, 50, 47)] == [True, False, False]
