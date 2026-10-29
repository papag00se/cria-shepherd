import json
import random
import subprocess

from cria import denial, resultpacket, prompts

from cria import filecommands as f


def run(tmp_path, args, read_instead=False):
    with denial.receipt_scope('a' * 16):
        cmd = f._read_in_place_of_write('input', 'input already exists.') if read_instead else f._read_command(args)
    p = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, check=True)
    assert len(p.stdout) <= 10000
    rec = resultpacket.read_record(p.stdout.decode(), 0, 'a' * 16)
    assert rec is not None
    return rec, p.stdout


def test_large_incompressible_is_refused_with_usable_range(tmp_path):
    raw = b''.join(f'{i}: '.encode() + random.Random(i).randbytes(90).hex().encode() + b'\n' for i in range(1000))
    (tmp_path / 'input').write_bytes(raw)
    rec, out = run(tmp_path, {'path': 'input'})
    assert rec.kind == denial.REFUSED and rec.body is None
    note = out[rec.end:].decode()
    assert 'No file content was returned' in note
    suggested = json.loads(note.split('Next read_file arguments: ', 1)[1].splitlines()[0])
    result, _ = run(tmp_path, suggested)
    assert result.kind == denial.RAN and result.observe == 'range' and result.body


def test_small_and_compressible_remain_complete(tmp_path):
    for raw in [b'a\r\n', b'a' * 40000, '界\n'.encode() * 8000]:
        (tmp_path / 'input').write_bytes(raw)
        rec, _ = run(tmp_path, {'path': 'input'})
        assert rec.kind == denial.RAN and rec.body == raw and rec.observe == 'whole'


def test_large_single_line_refuses_without_fake_range(tmp_path):
    (tmp_path / 'input').write_bytes(random.Random(7).randbytes(14000).hex().encode())
    rec, out = run(tmp_path, {'path': 'input', 'start_line': 1, 'end_line': 1})
    assert rec.kind == denial.REFUSED and rec.body is None
    assert b'No file content was returned' in out
    assert b'Next read_file arguments:' not in out


def test_read_instead_does_not_claim_it_returned_file(tmp_path):
    (tmp_path / 'input').write_bytes(random.Random(9).randbytes(14000).hex().encode())
    rec, out = run(tmp_path, {}, read_instead=True)
    assert rec.kind == denial.REFUSED and rec.body is None
    assert '⟦ctx:read-instead⟧' not in out.decode()
    assert b'No file content was returned' in out
