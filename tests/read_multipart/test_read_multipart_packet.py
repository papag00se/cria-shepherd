"""The result-packet codec: lossless and verified, strict about what a record may be and where it may sit."""
import base64
import json
import os
import zlib
import pytest
from cria import resultpacket as rp

R = '0123456789abcdef'

@pytest.mark.parametrize('raw', [b'', b'caf\xc3\xa9 \r\n tail', bytes(range(256)), os.urandom(4000), b'x' * 100_000])
def test_every_body_round_trips_exactly_as_one_ascii_line_and_tolerates_a_pty_crlf(raw):
    """Whatever codec wins (text/base64/zlib), bytes incl. ESC/NUL/non-UTF-8 come back exact; the record is one line, so a PTY cannot split it."""
    line = rp.line(R, rp.RAN, body=raw, observe=rp.WHOLE)
    assert line.count('\n') == 1 and line.isascii()
    for text in (line, line.replace('\n', '\r\n')):
        rec = rp.read_record(text, 0, R)
        assert rec.body == raw and rec.observe == rp.WHOLE
    assert rp.read_record(rp.line(R, rp.REFUSED, pre='⟦ctx:denied⟧ x\n', body=b'a\r\nb'), 0, R).pre == '⟦ctx:denied⟧ x\n'

def _good():
    return json.loads(rp.line(R, rp.RAN, body=b'verified original\n', observe=rp.WHOLE))

MUTATIONS = {
    'foreign receipt': lambda d: {**d, 'r': 'ffffffffffffffff'}, 'version': lambda d: {**d, 'v': 2}, 'survey kind in record 1': lambda d: {**d, 'k': 'survey'},
    'unknown kind': lambda d: {**d, 'k': 'bogus'}, 'unknown observation': lambda d: {**d, 'o': 'partial'},
    'whole read without body': lambda d: {k: v for k, v in d.items() if k != 'b'}, 'length does not verify': lambda d: {**d, 'b': {**d['b'], 'n': d['b']['n'] + 1}},
    'digest does not verify': lambda d: {**d, 'b': {**d['b'], 'h': '0' * 64}}, 'unknown codec': lambda d: {**d, 'b': {**d['b'], 'c': 'q'}},
    'unknown body field': lambda d: {**d, 'b': {**d['b'], 'extra': 1}},
    'zlib trailing data': lambda d: {**d, 'b': {**d['b'], 'c': 'z', 'd': base64.b64encode(zlib.compress(b'verified original\n') + b'TRAILING').decode()}},
}

@pytest.mark.parametrize('name', MUTATIONS)
def test_a_malformed_or_foreign_first_record_is_not_a_record(name):
    """Each shape declares the same body yet must be rejected; a lenient decoder once accepted them (independent review)."""
    assert rp.read_record(json.dumps(MUTATIONS[name](_good()), separators=(',', ':')) + '\n', 0, R) is None
    text = json.dumps(_good(), separators=(',', ':'))
    for bad in (text.replace('"v":1', '"v":true', 1), text.replace('"v":1', '"v":1.0', 1), text.replace('"k":"ran"', '"k":"refused","k":"ran"', 1)):
        assert rp.read_record(bad + '\n', 0, R) is None
    assert rp.read_record(text + '\n', 0, R) is not None

def test_a_record_is_read_only_at_the_position_asked_never_searched_for_and_reports_are_validated():
    """Authority comes from position: a record after any prefix, with a wrong receipt, or unterminated is nothing; survey records only where asked;
    wire_cost is a true worst-case bound that max_text_for_wire inverts."""
    line = rp.line(R, rp.REFUSED)
    assert rp.read_record('x' + line, 0, R) is None and rp.read_record('\n' + line, 0, R) is None and rp.read_record(line, 0, R[::-1]) is None
    assert rp.read_record(rp.line('', rp.REFUSED), 0, '') is None and rp.read_record(line[:-1], 0, R) is None and rp.read_record(line + line, len(line), R) is not None
    s = rp.line(R, rp.SURVEY, body=b'block')
    assert rp.read_record(s, 0, R, survey=True).body == b'block' and rp.read_record(s, 0, R) is None and rp.read_record(line, 0, R, survey=True) is None
    for n in (0, 1, 999, 5000, 9000): assert len(rp.line(R, rp.SURVEY, body=os.urandom(n))) <= rp.wire_cost(n)
    for wire in (500, 1000, 5000, 6900):
        n = rp.max_text_for_wire(wire); assert rp.wire_cost(n) <= wire < rp.wire_cost(n + 3)
