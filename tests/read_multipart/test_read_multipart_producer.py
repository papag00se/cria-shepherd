"""The lowered read program as the harness runs it (real bash): a body rides ONE record that fits the 10,000-byte PTY result, else the
program refuses with a range that is proven to fit. Nothing is ever clipped."""
import base64
import json
import random
import subprocess
import pytest
from cria import denial, filecommands, resultpacket
from read_multipart_helpers import pty_run

RC = 'a' * 16

def run(tmp_path, args, instead=None):
    with denial.receipt_scope(RC):
        cmd = filecommands._read_in_place_of_write(*instead) if instead else filecommands._read_command(args)
    out = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, check=True).stdout
    assert len(out) + out.count(b'\n') <= 10000               # what the PTY will make of it
    rec = resultpacket.read_record(out.decode(), 0, RC); assert rec is not None
    return rec, out

def hexlines(n, size=100, seed=0):
    return b''.join(random.Random(seed + i).randbytes(size).hex().encode() + b'\n' for i in range(n))

@pytest.mark.parametrize('raw', [b'no final newline', b'one\n', b'three\n\n\n', b'a\r\n', b'a' * 40000, '界\n'.encode() * 8000], ids=range(6))
def test_a_file_that_fits_is_returned_whole_byte_for_byte_including_its_final_newlines(tmp_path, raw):
    """Cargo.toml (no EOF newline), Importer.java (one), item.2.go (three): a whole read neither strips nor adds a newline; compressible big files fit."""
    (tmp_path / 'input').write_bytes(raw); rec, _ = run(tmp_path, {'path': 'input'})
    assert rec.kind == denial.RAN and rec.observe == 'whole' and rec.body == raw

def test_a_file_too_big_for_one_result_is_refused_with_a_range_that_works_and_never_a_fake_one(tmp_path):
    """ornith1.5_9b / Java run 1: 54 refused whole reads. Refusal returns no content, says so, and its suggested args (incl. a requested
    start line and CRLF bytes) really read; a single huge line or a read-instead answer offers no fake range and claims no file."""
    (tmp_path / 'input').write_bytes(hexlines(1000, 90))
    rec, out = run(tmp_path, {'path': 'input'}); note = out[rec.end:].decode()
    assert rec.kind == denial.REFUSED and rec.body is None and 'No file content was returned' in note
    nxt, _ = run(tmp_path, json.loads(note.split('Next read_file arguments: ', 1)[1].splitlines()[0]))
    assert nxt.kind == denial.RAN and nxt.observe == 'range' and nxt.body
    raw = b''.join(random.Random(i).randbytes(120).hex().encode() + b'\r\n' for i in range(250)); (tmp_path / 'crlf').write_bytes(raw)
    rec, out = run(tmp_path, {'path': 'crlf', 'start_line': 10, 'end_line': 200})
    args = json.loads(out[rec.end:].decode().split('Next read_file arguments: ')[1].splitlines()[0]); lines = raw.split(b'\n')
    assert args['start_line'] == 10 and 10 <= args['end_line'] < 200
    assert run(tmp_path, args)[0].body == b''.join(b'%d: %s\n' % (i + 1, lines[i]) for i in range(9, args['end_line']))
    (tmp_path / 'one').write_bytes(random.Random(7).randbytes(14000).hex().encode())
    for rec, out in (run(tmp_path, {'path': 'one', 'start_line': 1, 'end_line': 1}), run(tmp_path, None, ('one', 'one already exists.'))):
        assert rec.kind == denial.REFUSED and rec.body is None and b'No file content was returned' in out
        assert b'Next read_file arguments:' not in out and '⟦ctx:read-instead⟧' not in out.decode()

def test_the_record_boundary_counts_the_ptys_added_newline_and_a_real_pty_keeps_the_bytes(tmp_path):
    """A record of 9,999 bytes rides whole; 10,000 (the PTY turns its LF into CRLF, 10,001) is refused instead of cut; through a real PTY it round-trips."""
    data = base64.b64encode(random.Random(982).randbytes(12000)); seen = set()
    for n in range(9700, 10001):
        size = len(resultpacket.line(RC, 'ran', body=data[:n], observe='whole').encode())
        if size in (9999, 10000) and size not in seen:
            seen.add(size); (tmp_path / 'input').write_bytes(data[:n]); rec, _ = run(tmp_path, {'path': 'input'})
            assert (rec.kind, rec.body) == (('ran', data[:n]) if size == 9999 else ('refused', None))
    assert seen == {9999, 10000}
    (tmp_path / 'esc').write_bytes(b'\x1b[31m\x00 CRLF\r\n caf\xc3\xa9\n')
    with denial.receipt_scope(RC): out = pty_run(filecommands._read_command({'path': 'esc'}), cwd=tmp_path)
    assert resultpacket.read_record(out, 0, RC).body == b'\x1b[31m\x00 CRLF\r\n caf\xc3\xa9\n'

def test_pathological_read_arguments_give_bounded_typed_refusals(tmp_path):
    """Enormous path, absurd inverted range and an enormous write fact never overflow the result or leave it untyped."""
    for args, word in (({'path': 'x' * 12000}, b''), ({'path': 'x' * 12000, 'start_line': 10**3000, 'end_line': 10**2999}, b'inverted')):
        with denial.receipt_scope(RC): cmd = filecommands._read_command(args)
        p = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True)
        rec = resultpacket.read_record(p.stdout.decode(), 0, RC)
        assert p.returncode != 0 and len(p.stdout) + p.stdout.count(b'\n') <= 10000 and rec.kind == denial.REFUSED and word in p.stdout
    (tmp_path / 'input').write_bytes(random.Random(21).randbytes(18000).hex().encode())
    rec, out = run(tmp_path, None, ('input', 'f' * 20000))
    assert rec.kind == denial.REFUSED and b'This write_file call was not run' in out and out.count(b'"v":1') == 1
