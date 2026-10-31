"""Oversize listings show no partial entries and keep full actionable recovery."""
import errno
import os
import pty
import re
import subprocess

import pytest

from cria import denial, filecommands, resultpacket, webfetch, writeproxy


RECEIPT = 'c' * 16


def execute(command, root, terminal=False):
    env = dict(os.environ, PATH='/usr/bin:/bin', LC_ALL='C')
    if not terminal:
        process = subprocess.run(['bash', '-c', command], cwd=root, env=env, capture_output=True)
        return process.returncode, process.stdout
    master, slave = pty.openpty()
    process = subprocess.Popen(['bash', '-c', command], cwd=root, env=env, stdout=slave, stderr=slave)
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
    return process.wait(timeout=10), b''.join(chunks)


@pytest.mark.parametrize('terminal', [False, True])
def test_oversize_real_listing_pointer_has_listing_recovery_not_web_instructions(tmp_path, terminal):
    directory = tmp_path / 'listed'
    directory.mkdir()
    names = [f'entry-{i:03}-' + 'x' * 190 for i in range(65)]
    for name in names:
        (directory / name).touch()
    env = dict(os.environ, PATH='/usr/bin:/bin', LC_ALL='C')
    listing = subprocess.run(['ls', '-la', str(directory)], env=env,
                             capture_output=True, check=True).stdout
    with denial.receipt_scope(RECEIPT):
        expected = denial.frame(denial.RAN).encode() + listing
        command = writeproxy._list_command({'path': str(directory)})
    status, output = execute(command, tmp_path, terminal)
    assert status == 0
    assert (len(output) if terminal else len(output) + output.count(b'\n')) <= 10000
    output = output.replace(b'\r\n', b'\n') if terminal else output
    record = resultpacket.read_record(output.decode(), 0, RECEIPT)
    assert record and record.kind == denial.RAN
    pointer = output[record.end:].decode()
    assert not any(name in pointer for name in names), 'No partial listing may be presented inline'
    paths = re.findall(re.escape(webfetch.SPILL_DIR) + r'/stdout-[0-9a-f]{64}\.txt', pointer)
    assert paths, 'The model must have an actual complete-result recovery path'
    saved = tmp_path / paths[0]
    assert saved.read_bytes() == expected
    assert 'directory' in pointer.lower() and 'full' in pointer.lower()
    assert 'read_file' in pointer and 'start_line' in pointer and 'end_line' in pointer
    assert 'grep' in pointer
    assert not any(word in pointer.lower() for word in ('document', 'web_fetch', 'url', 'find='))
    # Recover the actual saved result through bounded typed reads. The first
    # stored record stays opaque file data rather than becoming read authority.
    lines = expected.splitlines(keepends=True)
    for start in range(1, len(lines) + 1, 8):
        end = min(start + 7, len(lines))
        with denial.receipt_scope('d' * 16):
            read = filecommands._read_command({'path': paths[0], 'start_line': start, 'end_line': end})
        read_status, read_output = execute(read, tmp_path)
        assert read_status == 0
        answer = resultpacket.read_record(read_output.decode(), 0, 'd' * 16)
        assert answer and answer.observe == resultpacket.RANGE
        assert answer.body == b''.join(str(n).encode() + b': ' + lines[n - 1] for n in range(start, end + 1))


def test_small_listing_still_returns_the_complete_original_result(tmp_path):
    directory = tmp_path / 'small'
    directory.mkdir()
    (directory / 'one-file').touch()
    listing = subprocess.run(['ls', '-la', str(directory)], env=dict(os.environ, LC_ALL='C'),
                             capture_output=True, check=True).stdout
    with denial.receipt_scope(RECEIPT):
        expected = denial.frame(denial.RAN).encode() + listing
        command = writeproxy._list_command({'path': str(directory)})
    status, output = execute(command, tmp_path)
    assert status == 0 and output == expected
    assert not list((tmp_path / webfetch.SPILL_DIR).glob('stdout-*.txt'))


def test_missing_listing_retains_its_failure_status_and_diagnostic(tmp_path):
    with denial.receipt_scope(RECEIPT):
        command = writeproxy._list_command({'path': 'missing-directory'})
    status, output = execute(command, tmp_path)
    record = resultpacket.read_record(output.decode(), 0, RECEIPT)
    assert status == 2 and record and record.kind == denial.REFUSED
    assert b'missing-directory' in output


def test_oversize_listing_error_is_saved_whole_and_stays_failed(tmp_path):
    path = 'missing-' + 'x' * 11000
    failed = subprocess.run(['ls', '-la', path], cwd=tmp_path, env=dict(os.environ, LC_ALL='C'),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert failed.returncode == 2
    with denial.receipt_scope(RECEIPT):
        expected = denial.frame(denial.REFUSED).encode() + failed.stdout
        command = writeproxy._list_command({'path': path})
    status, output = execute(command, tmp_path)
    assert status == 2 and len(output) + output.count(b'\n') <= 10000
    record = resultpacket.read_record(output.decode(), 0, RECEIPT)
    assert record and record.kind == denial.REFUSED
    pointer = output[record.end:].decode()
    assert 'directory' in pointer.lower() and 'web_fetch' not in pointer
    saved = list((tmp_path / webfetch.SPILL_DIR).glob('stdout-*.txt'))
    assert len(saved) == 1 and saved[0].read_bytes() == expected
