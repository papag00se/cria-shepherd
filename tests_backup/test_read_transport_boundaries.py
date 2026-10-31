import base64
import json
import random
import subprocess

from cria import denial, resultpacket
from cria import filecommands as f


def invoke(tmp_path, args):
    with denial.receipt_scope('a'*16):
        cmd = f._read_command(args)
    return subprocess.run(['bash', '-c', cmd], cwd=tmp_path, check=True, capture_output=True).stdout


def test_exact_serialized_record_boundary_includes_pty_newline(tmp_path):
    rng = random.Random(982)
    data = base64.b64encode(rng.randbytes(12000))
    for n in range(9700, 10001):
        sample = data[:n]
        rec = resultpacket.line('a'*16, 'ran', body=sample, observe='whole').encode()
        if len(rec) in (9999, 10000):
            (tmp_path/'input').write_bytes(sample)
            actual = invoke(tmp_path, {'path':'input'})
            parsed = resultpacket.read_record(actual.decode(), 0, 'a'*16)
            if len(rec) == 9999:
                assert parsed.body == sample
            else:
                assert parsed.kind == 'refused' and parsed.body is None
            assert len(actual.replace(b'\n', b'\r\n')) <= 10000
    assert any(len(resultpacket.line('a'*16, 'ran', body=data[:n], observe='whole').encode()) == 9999 for n in range(9700, 10001))


def test_range_suggests_valid_requested_prefix_and_crlf_bytes(tmp_path):
    raw = b''.join(random.Random(i).randbytes(120).hex().encode() + b'\r\n' for i in range(250))
    (tmp_path/'input').write_bytes(raw)
    out = invoke(tmp_path, {'path':'input','start_line':10,'end_line':200})
    rec = resultpacket.read_record(out.decode(), 0, 'a'*16)
    assert rec.kind == 'refused'
    suggest = json.loads(out[rec.end:].decode().split('Next read_file arguments: ')[1].splitlines()[0])
    assert suggest['start_line'] == 10 and 10 <= suggest['end_line'] < 200
    p = resultpacket.read_record(invoke(tmp_path, suggest).decode(), 0, 'a'*16)
    lines = raw.split(b'\n')
    assert p.body == b''.join(b'%d: %s\n' % (i+1, lines[i]) for i in range(9,suggest['end_line']))
