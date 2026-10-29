"""Multipart producer contracts through actual harness-like shell/PTY transport."""
import base64
import hashlib
import json
import os
import pty
import random
import subprocess

import pytest

from cria import callformats, denial, filecommands as f, prompts, resultpacket, toolwire


def run_page(tmp_path, spec, offset):
    master, slave = pty.openpty()
    process = subprocess.Popen(['bash', '-c', f.build_multipart_page(spec, offset)],
                               cwd=tmp_path, stdout=slave, stderr=subprocess.PIPE)
    os.close(slave)
    data = bytearray()
    while True:
        try:
            chunk = os.read(master, 16384)
        except OSError:
            break
        if not chunk:
            break
        data.extend(chunk)
    os.close(master)
    assert process.wait(timeout=10) == 0, process.stderr.read()
    assert len(data) <= 10000 and data.endswith(b'\r\n')
    return bytes(data), json.loads(data)


def spec(args, *, name='read_file', pre='', not_read='', read_instead=False):
    return f.make_multipart_read_spec('call', name, json.dumps(args), 'token',
                                      pre=pre, not_read=not_read, read_instead=read_instead)


def assemble(tmp_path, read):
    parts, identity, pages = [], None, []
    offset = 0
    while True:
        wire, page = run_page(tmp_path, read, offset)
        identity_now = tuple(page[k] for k in ('source_length', 'source_sha256', 'stream_length',
                                              'stream_sha256', 'outcome', 'exit_code', 'write_outcome'))
        assert identity is None or identity == identity_now
        identity = identity_now
        assert page['token'] == read.token and page['offset'] == offset
        chunk = base64.b64decode(page['data'], validate=True)
        assert len(chunk) == page['length'] and hashlib.sha256(chunk).hexdigest() == page['page_sha256']
        if offset + len(chunk) < page['stream_length']:
            longer = chunk + b'x'
            bigger = {**page, 'length': len(longer), 'data': base64.b64encode(longer).decode(),
                      'page_sha256': hashlib.sha256(longer).hexdigest()}
            assert len((json.dumps(bigger, separators=(',', ':')) + '\r\n').encode()) > 10000
        pages.append((wire, page))
        parts.append(chunk)
        offset += len(chunk)
        if offset == page['stream_length']:
            stream = b''.join(parts)
            assert hashlib.sha256(stream).hexdigest() == page['stream_sha256']
            return stream, pages
        assert chunk and offset < page['stream_length']


def test_whole_read_page_budget_and_binary_integrity(tmp_path):
    data = random.Random(24).randbytes(35000) + b'\r\n\xe2\x9f\xa6ctx:denied\xe2\x9f\xa7'
    (tmp_path / 'input').write_bytes(data)
    request = spec({'path': 'input'})
    stream, pages = assemble(tmp_path, request)
    assert len(pages) > 2 and pages[0][1]['length'] > 6000
    assert all(p['source_sha256'] == hashlib.sha256(data).hexdigest()
               and p['source_length'] == len(data) for _, p in pages)
    rec = resultpacket.read_record(stream.decode('ascii'), 0, request.receipt)
    assert rec.kind == 'ran' and rec.observe == 'whole' and rec.body == data


def test_range_preserves_source_identity_and_numbering(tmp_path):
    lines = [random.Random(i).randbytes(80).hex().encode() for i in range(320)]
    data = b'\n'.join(lines)
    (tmp_path / 'input').write_bytes(data)
    request = spec({'path': 'input', 'start_line': 10, 'end_line': 300})
    stream, pages = assemble(tmp_path, request)
    record = resultpacket.read_record(stream.decode('ascii'), 0, request.receipt)
    assert record.observe == 'range'
    assert record.body == b''.join(b'%d: %s\n' % (i + 1, lines[i]) for i in range(9, 300))
    assert len(pages) > 1 and all(p['source_sha256'] == hashlib.sha256(data).hexdigest() for _, p in pages)


def test_different_source_outside_requested_range_changes_page_identity(tmp_path):
    data = b'first-line\n' + random.Random(5).randbytes(20000).hex().encode() + b'\n'
    path = tmp_path / 'input'; path.write_bytes(data)
    request = spec({'path': 'input', 'start_line': 2, 'end_line': 2})
    _, first = run_page(tmp_path, request, 0)
    path.write_bytes(data.replace(b'first-line', b'changed!!!'))
    _, second = run_page(tmp_path, request, first['length'])
    assert first['source_sha256'] != second['source_sha256']
    assert first['stream_sha256'] == second['stream_sha256']


def test_read_instead_long_fact_and_failure_remain_truthful(tmp_path):
    fact = 'source-owned: ' + '🪿 arbitrary facts; ' * 400
    pre, not_read = f.read_instead_prose(fact)
    labels = prompts.load_map('write_unread_target')
    with denial.unframed():
        assert pre == denial.mark(prompts.fill(labels['read'], fact=fact))
        assert not_read == denial.mark(prompts.fill(labels['not_read'], fact=fact))
    request = spec({'path': 'input', 'content': 'new'}, name='write_file', pre=pre,
                   not_read=not_read, read_instead=True)
    path = tmp_path / 'input'; path.write_bytes(b'original\n')
    stream, pages = assemble(tmp_path, request)
    record = resultpacket.read_record(stream.decode(), 0, request.receipt)
    assert record.kind == 'refused' and record.pre == pre and record.body == b'original\n'
    assert pages[-1][1]['write_outcome'] == 'not_run' and path.read_bytes() == b'original\n'
    path.unlink()
    stream, pages = assemble(tmp_path, request)
    record = resultpacket.read_record(stream.decode(), 0, request.receipt)
    assert record.kind == 'refused' and not_read in stream.decode()[record.end:]
    assert pages[-1][1]['exit_code'] == 1 and pages[-1][1]['write_outcome'] == 'not_run'


def test_legacy_read_instead_still_caps_long_fact(tmp_path):
    path = tmp_path / 'input'; path.write_bytes(b'old')
    fact = 'unique-' + 'x' * 2000
    with denial.receipt_scope('1234567890123456'):
        command = f._read_in_place_of_write('input', fact)
    result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, check=True)
    record = resultpacket.read_record(result.stdout.decode(), 0, '1234567890123456')
    assert fact not in record.pre
    assert prompts.load_map('read_transport_oversize')['fact_omitted'] in record.pre


def test_missing_and_inverted_return_original_refusal(tmp_path):
    for args in ({'path': 'missing'}, {'path': 'missing', 'start_line': 9, 'end_line': 2}):
        request = spec(args)
        stream, pages = assemble(tmp_path, request)
        with denial.receipt_scope(request.receipt):
            cmd = f._read_command(args)
        before = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True)
        assert (pages[-1][1]['exit_code'], stream) == (before.returncode, before.stdout)
        assert pages[-1][1]['outcome'] == 'error'


def test_known_command_limit_explicitly_refuses_without_truncation():
    request = spec({'path': 'input', 'content': 'x'}, name='write_file',
                   pre='x' * 200000, not_read='not read', read_instead=True)
    with pytest.raises(f.MultipartCommandTooLarge, match='not started'):
        f.build_multipart_page(request, 0, command_max_bytes=131071)
    assert len(f.build_multipart_page(request, 0).encode()) > 131071


@pytest.mark.parametrize('args', [{'file_path': 'x', 'start': '2', 'end': '4'},
                                  {'path': 'x', 'end': '4'},
                                  {'path': 'x', 'start_line': 0, 'end_line': 4},
                                  {'path': 'x', 'start_line': 9, 'end_line': 2}])
def test_alias_uses_canonical_args_and_new_receipt(monkeypatch, args):
    seen = []
    def capture(normalized):
        seen.append(f.canonical_read_args(normalized))
        return f._read_command(normalized)
    monkeypatch.setattr(callformats, '_wp_read_command', capture)
    command = callformats._read_command(args)
    original = toolwire._read_sentinel(command)
    assert original == {'name': 'read_file', 'arguments': json.dumps(seen[0])}
    assert not toolwire.receipt_of(command, 'call')
    request = f.make_multipart_read_spec('call', 'read_file', json.dumps(seen[0]), 'token')
    declaration = toolwire._sentinel('read_file', json.dumps(seen[0]), request.receipt)
    assert toolwire.receipt_of(declaration + '\n', 'call') == request.receipt
    assert not toolwire.receipt_of(declaration + '\n', 'different')
