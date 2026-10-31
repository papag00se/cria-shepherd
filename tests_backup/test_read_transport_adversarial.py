"""Transport paths must remain bounded, typed, and honest under adversarial input."""
import errno
import os
import pty
import random
import subprocess

from cria import denial, filecommands, resultpacket


def test_oversize_refusal_survives_actual_pty(tmp_path):
    (tmp_path / 'input').write_bytes(random.Random(42).randbytes(20000).hex().encode())
    with denial.receipt_scope('a' * 16):
        cmd = filecommands._read_command({'path': 'input'})
    master, slave = pty.openpty()
    p = subprocess.Popen(['bash', '-c', cmd], cwd=tmp_path, stdout=slave, stderr=slave)
    os.close(slave)
    chunks = []
    try:
        while True:
            try:
                chunk = os.read(master, 65536)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(master)
    output = b''.join(chunks)
    assert p.wait() == 0
    assert len(output) <= 10000
    rec = resultpacket.read_record(output.decode().replace('\r\n', '\n'), 0, 'a' * 16)
    assert rec and rec.kind == denial.REFUSED and rec.body is None
    assert b'No file content was returned' in output


def test_enormous_missing_path_produces_bounded_typed_failure(tmp_path):
    with denial.receipt_scope('a' * 16):
        cmd = filecommands._read_command({'path': 'x' * 12000})
    p = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True)
    assert p.returncode != 0
    assert len(p.stdout) + p.stdout.count(b'\n') <= 10000
    rec = resultpacket.read_record(p.stdout.decode(), 0, 'a' * 16)
    assert rec and rec.kind == denial.REFUSED and rec.body is None


def test_nonmonotonic_candidate_sizes_still_yield_a_measured_range(tmp_path, monkeypatch):
    import json
    original = filecommands._read_program
    # Model a nonmonotonic codec: line 1 fits, lines 2..5 do not, line 6 fits,
    # and larger windows do not. Only emitted suggestions must be proven fits;
    # binary search is not permitted to claim its answer is the maximum.
    inject = '''\n_original_record = _record\ndef _record(receipt, kind, raw, observe, pre=''):\n    count = raw.count(b"\\n")\n    if observe == 'range' and count > 1 and count != 6:\n        return b'x' * 10001\n    return _original_record(receipt, kind, raw, observe, pre)\n'''
    monkeypatch.setattr(filecommands, '_read_program', lambda body: original(inject + body))
    data = b''.join(random.Random(i).randbytes(800).hex().encode() + b'\n' for i in range(20))
    (tmp_path / 'input').write_bytes(data)
    with denial.receipt_scope('a' * 16):
        cmd = filecommands._read_command({'path': 'input'})
    out = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, check=True).stdout
    rec = resultpacket.read_record(out.decode(), 0, 'a' * 16)
    assert rec and rec.kind == denial.REFUSED
    assert b'first line alone' not in out
    args = json.loads(out[rec.end:].decode().split('Next read_file arguments: ')[1].splitlines()[0])
    with denial.receipt_scope('a' * 16):
        cmd = filecommands._read_command(args)
    next_out = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, check=True).stdout
    next_rec = resultpacket.read_record(next_out.decode(), 0, 'a' * 16)
    assert next_rec and next_rec.kind == denial.RAN and next_rec.body
    assert len(next_out) + next_out.count(b'\n') <= 10000


def test_huge_inverted_range_refusal_is_bounded_and_typed(tmp_path):
    with denial.receipt_scope('a' * 16):
        cmd = filecommands._read_command({'path': 'x' * 12000, 'start_line': 10**3000, 'end_line': 10**2999})
    p = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True)
    assert p.returncode != 0
    assert len(p.stdout) + p.stdout.count(b'\n') <= 10000
    rec = resultpacket.read_record(p.stdout.decode(), 0, 'a' * 16)
    assert rec and rec.kind == denial.REFUSED and rec.body is None
    assert b'inverted' in p.stdout


def test_long_unicode_path_retains_actionable_bounded_next_range(tmp_path):
    import json
    parent = tmp_path
    for _ in range(15):
        parent = parent / ('😀' * 60)
        parent.mkdir()
    path = parent / 'input'
    path.write_bytes(b''.join(random.Random(i).randbytes(100).hex().encode() + b'\n' for i in range(150)))
    with denial.receipt_scope('a' * 16):
        cmd = filecommands._read_command({'path': str(path)})
    p = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, check=True)
    assert len(p.stdout) + p.stdout.count(b'\n') <= 10000
    rec = resultpacket.read_record(p.stdout.decode(), 0, 'a' * 16)
    assert rec and rec.kind == denial.REFUSED and rec.body is None
    assert b'Retry read_file with the same path, start_line=1, end_line=' in p.stdout
    end = int(p.stdout.decode().split('end_line=')[1].split('.')[0])
    with denial.receipt_scope('a' * 16):
        next_cmd = filecommands._read_command({'path': str(path), 'start_line': 1, 'end_line': end})
    next_result = subprocess.run(['bash', '-c', next_cmd], cwd=tmp_path, capture_output=True, check=True)
    next_rec = resultpacket.read_record(next_result.stdout.decode(), 0, 'a' * 16)
    assert next_rec and next_rec.kind == denial.RAN and next_rec.observe == 'range'
    assert len(next_result.stdout) + next_result.stdout.count(b'\n') <= 10000


def test_enormous_write_fact_gives_bounded_refusal_without_duplicate_record(tmp_path):
    (tmp_path / 'input').write_bytes(random.Random(21).randbytes(18000).hex().encode())
    with denial.receipt_scope('a' * 16):
        cmd = filecommands._read_in_place_of_write('input', 'f' * 20000)
    p = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, check=True)
    assert len(p.stdout) + p.stdout.count(b'\n') <= 10000
    rec = resultpacket.read_record(p.stdout.decode(), 0, 'a' * 16)
    assert rec and rec.kind == denial.REFUSED and rec.body is None
    assert b'This write_file call was not run' in p.stdout
    assert b'No file content was returned' in p.stdout
    assert p.stdout.count(b'"v":1') == 1
