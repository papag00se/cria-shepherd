"""Complete owned stdout, including records and PTY expansion, survives transport."""
import errno
import json
import os
from pathlib import Path
import pty
import subprocess

import pytest

from cria import denial, externalization, resultpacket, webfetch, writeproxy


RECEIPT = 'a' * 16


def run(command, root, *, terminal=False):
    env = dict(os.environ, PATH=str(root / 'bin') + ':/usr/bin:/bin')
    if not terminal:
        p = subprocess.run(['bash', '-c', command], cwd=root, env=env, capture_output=True)
        assert p.returncode == 0, p.stderr
        return p.stdout
    master, slave = pty.openpty()
    p = subprocess.Popen(['bash', '-c', command], cwd=root, env=env, stdout=slave, stderr=slave)
    os.close(slave)
    parts = []
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
            parts.append(chunk)
    finally:
        os.close(master)
    assert p.wait(timeout=10) == 0
    return b''.join(parts)


def fake(root, name, text):
    (root / 'bin').mkdir(exist_ok=True)
    path = root / 'bin' / name
    path.write_text('#!/usr/bin/python3\nimport sys\nsys.stdout.buffer.write(' + repr(text.encode()) + ')\n')
    path.chmod(0o755)


def check(output, root, expected):
    assert len(output) + output.count(b'\n') <= 10000
    rec = resultpacket.read_record(output.decode(), 0, RECEIPT)
    assert rec is not None
    stored = [p.read_bytes() for p in (root / webfetch.SPILL_DIR).glob('stdout-*.txt')]
    assert expected in stored
    return rec


def test_listing_counts_record_and_newline_expansion(tmp_path):
    body = 'x\n' * 3500
    fake(tmp_path, 'ls', body)
    with denial.receipt_scope(RECEIPT):
        command = writeproxy._list_command({'path': '.'})
        expected = (denial.frame(denial.RAN) + body.rstrip('\n') + '\n').encode()
    check(run(command, tmp_path), tmp_path, expected)


@pytest.mark.parametrize('offer', [False, True])
def test_search_error_is_lossless_and_bounded(tmp_path, offer):
    error = {'message': '診断\n' * 6000}
    fake(tmp_path, 'curl', json.dumps(error))
    offered = externalization.SearchOffer(webfetch.search_spill_name('query'),
                                         externalization.DEFINITION.search_program(9000)) if offer else None
    with denial.receipt_scope(RECEIPT):
        command = writeproxy._search_command({'query': 'query'}, 'offline', search_offer=offered,
                                             operation='op')
    output = run(command, tmp_path)
    assert len(output) + output.count(b'\n') <= 10000
    assert resultpacket.read_record(output.decode(), 0, RECEIPT)
    saved = list((tmp_path / webfetch.SPILL_DIR).glob('stdout-*.txt'))
    assert saved and ('search API error: ' + json.dumps(error['message'])).encode() in saved[0].read_bytes()


@pytest.mark.parametrize('terminal', [False, True])
def test_fetch_preserves_framed_output_and_facts(tmp_path, monkeypatch, terminal):
    body = 'fetch line\n' * 1000
    facts = {'url': 'https://example.test/doc', 'status': '200', 'observed': '',
             'routes': [], 'catalog': [], 'shapes': []}
    monkeypatch.setattr(webfetch, 'fetch_nav_result', lambda *a, **k: (body, False, 200, facts))
    with denial.receipt_scope(RECEIPT):
        command = writeproxy._fetch_command({'url': facts['url']})
        expected = (denial.frame(denial.RAN, rep={'fx': facts}) + body).encode()
    output = run(command, tmp_path, terminal=terminal)
    if terminal:
        assert len(output) <= 10000
        output = output.replace(b'\r\n', b'\n')
    rec = check(output, tmp_path, expected)
    assert rec.rep['fx'] == facts


def test_spill_pointer_and_reports_share_the_limit(tmp_path):
    pointer = 'pointer\n' * 3000
    with denial.receipt_scope(RECEIPT):
        command = writeproxy._spill_command('./tmp/read-only/document.txt', 'whole document', pointer,
                                            operation='op')
    output = run(command, tmp_path)
    assert len(output) + output.count(b'\n') <= 10000
    rec = resultpacket.read_record(output.decode(), 0, RECEIPT)
    assert rec and rec.rep['st']['byte_count'] == len(b'whole document')
    assert (tmp_path / 'tmp/read-only/document.txt').read_bytes() == b'whole document'
    saved = list((tmp_path / webfetch.SPILL_DIR).glob('stdout-*.txt'))
    assert saved and saved[0].read_bytes().endswith(pointer.encode())


def test_small_fetch_is_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setattr(webfetch, 'fetch_nav_result', lambda *a, **k: ('exact\n', False, 200, None))
    with denial.receipt_scope(RECEIPT):
        command = writeproxy._fetch_command({'url': 'https://example.test/'})
        expected = (denial.frame(denial.RAN) + 'exact\n').encode()
    assert run(command, tmp_path) == expected


@pytest.mark.parametrize('size', [9999, 10000, 10001])
def test_complete_fetch_exact_transport_boundary(tmp_path, monkeypatch, size):
    with denial.receipt_scope(RECEIPT):
        prefix = denial.frame(denial.RAN)
        body = 'x' * (size - len(prefix.encode()) - prefix.count('\n'))
        monkeypatch.setattr(webfetch, 'fetch_nav_result', lambda *a, **k: (body, False, 200, None))
        command = writeproxy._fetch_command({'url': 'https://example.test/'})
    expected = (prefix + body).encode()
    output = run(command, tmp_path)
    assert len(output) + output.count(b'\n') <= 10000
    if size <= 10000:
        assert output == expected
    else:
        check(output, tmp_path, expected)


def test_search_brief_and_storage_record_are_measured_together(tmp_path):
    response = {'web': {'results': [{'title': 'x\n' * 3500, 'url': 'https://example.test/',
                                     'description': 'complete description'}]}}
    fake(tmp_path, 'curl', json.dumps(response))
    target = webfetch.search_spill_name('newline query')
    offered = externalization.SearchOffer(target, externalization.DEFINITION.search_program(9000))
    with denial.receipt_scope(RECEIPT):
        command = writeproxy._search_command({'query': 'newline query'}, 'offline',
                                             search_offer=offered, operation='op')
    output = run(command, tmp_path)
    assert len(output) + output.count(b'\n') <= 10000
    rec = resultpacket.read_record(output.decode(), 0, RECEIPT)
    stored = (tmp_path / target).read_bytes()
    assert rec.rep['st']['byte_count'] == len(stored)
    assert b'complete description' in stored
    assert list((tmp_path / webfetch.SPILL_DIR).glob('stdout-*.txt'))


def test_untransportable_fetch_record_is_retained_without_inline_claims(tmp_path, monkeypatch):
    facts = {'url': 'https://example.test/', 'status': '200', 'observed': '',
             'routes': ['/' + '界' * 2000], 'catalog': [], 'shapes': []}
    monkeypatch.setattr(webfetch, 'fetch_nav_result', lambda *a, **k: ('body', False, 200, facts))
    with denial.receipt_scope(RECEIPT):
        command = writeproxy._fetch_command({'url': facts['url']})
        expected = (denial.frame(denial.RAN, rep={'fx': facts}) + 'body').encode()
    rec = check(run(command, tmp_path), tmp_path, expected)
    assert rec.kind == denial.REFUSED and rec.rep is None


def test_real_lowering_and_representation_keep_search_storage_facts(tmp_path):
    fake(tmp_path, 'curl', json.dumps({'web': {'results': [
        {'title': 'x\n' * 3500, 'url': 'https://example.test/', 'description': 'method()'}]}}))
    call = {'id': 'bounded-search', 'type': 'function', 'function': {
        'name': 'web_search', 'arguments': json.dumps({'query': 'newline query'})}}
    completion = {'choices': [{'message': {'tool_calls': [call]}}]}
    shell = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
    from cria import assistruntime
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        writeproxy.translate_outbound(completion, shell, injected={'web_search'}, brave_key='offline',
                                      workspace_root=str(tmp_path))
    lowered = completion['choices'][0]['message']['tool_calls'][0]
    output = run(writeproxy._command_of(lowered['function']['arguments']), tmp_path)
    assert len(output) + output.count(b'\n') <= 10000
    shown = writeproxy.represent_inbound([
        {'role': 'assistant', 'tool_calls': [lowered]},
        {'role': 'tool', 'tool_call_id': lowered['id'], 'content': output.decode()}],
        workspace_root=str(tmp_path))
    assert shown[0]['tool_calls'][0]['function']['name'] == 'web_search'
    assert not denial.refused(shown[1])
    assert 'stdout-' in shown[1]['content']


@pytest.mark.parametrize('size', [10000, 10001])
def test_search_without_offer_charges_the_shell_owned_record(tmp_path, size):
    with denial.receipt_scope(RECEIPT):
        prefix = denial.frame(denial.RAN)
        fixed = 'search API error: ""\n'
        message = 'x' * (size - len(prefix.encode()) - prefix.count('\n')
                         - len(fixed.encode()) - fixed.count('\n'))
        fake(tmp_path, 'curl', json.dumps({'message': message}))
        command = writeproxy._search_command({'query': 'query'}, 'offline')
    output = run(command, tmp_path)
    assert len(output) + output.count(b'\n') <= 10000
    assert output.count(b'"v":1') == 1
    if size == 10000:
        assert output == (prefix + 'search API error: ' + json.dumps(message) + '\n').encode()
    else:
        saved = list((tmp_path / webfetch.SPILL_DIR).glob('stdout-*.txt'))
        assert saved and saved[0].read_bytes() == ('search API error: ' + json.dumps(message) + '\n').encode()


def test_large_fetch_refusal_stays_refused_and_nonzero(tmp_path, monkeypatch):
    body = 'refusal detail\n' * 1200
    monkeypatch.setattr(webfetch, 'fetch_nav_result', lambda *a, **k: (body, True, None, None))
    with denial.receipt_scope(RECEIPT):
        command = writeproxy._fetch_command({'url': 'https://example.test/'})
    p = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True)
    assert p.returncode == 1
    assert len(p.stdout) + p.stdout.count(b'\n') <= 10000
    rec = resultpacket.read_record(p.stdout.decode(), 0, RECEIPT)
    assert rec and rec.kind == denial.REFUSED
    assert list((tmp_path / webfetch.SPILL_DIR).glob('stdout-*.txt'))


def real_listing(root, wanted):
    """Tune real filenames, not ls output, to an exact listing-byte boundary."""
    root.mkdir()
    files = []
    for i in range(50):
        path = root / (f'f{i:03}-' + 'x' * 80)
        path.touch()
        files.append(path)
    for _ in range(100):
        raw = subprocess.run(['ls', '-la', str(root)], capture_output=True, check=True).stdout
        difference = wanted - len(raw)
        if not difference:
            return raw
        for i, path in enumerate(files):
            change = min(difference, 255 - len(path.name)) if difference > 0 else max(difference, 5 - len(path.name))
            if change:
                replacement = root / (path.name + 'x' * change if change > 0 else path.name[:change])
                path.rename(replacement)
                files[i] = replacement
                break
        else:
            raise AssertionError('filename capacity exhausted')
    raise AssertionError('real listing length did not settle')


@pytest.mark.parametrize('boundary', ['9001', 'exact', 'over', 'large'])
@pytest.mark.parametrize('terminal', [False, True])
def test_real_listing_uses_complete_10000_byte_boundary(tmp_path, monkeypatch, boundary, terminal):
    monkeypatch.setenv('LC_ALL', 'C')
    with denial.receipt_scope(RECEIPT):
        prefix = denial.frame(denial.RAN).encode()
        # total, dot, dot-dot, and fifty real files each occupy one LF line.
        edge = 10000 - externalization.stdout_size(prefix) - 53
        wanted = {'9001': 9001, 'exact': edge, 'over': edge + 1, 'large': 13000}[boundary]
        listing = real_listing(tmp_path / 'listing', wanted)
        command = writeproxy._list_command({'path': str(tmp_path / 'listing')})
    expected = prefix + listing
    assert len(listing) == wanted and listing.count(b'\n') == 53
    output = run(command, tmp_path, terminal=terminal)
    assert (len(output) if terminal else externalization.stdout_size(output)) <= 10000
    if terminal:
        output = output.replace(b'\r\n', b'\n')
    if externalization.stdout_size(expected) <= 10000:
        assert output == expected
        assert not list((tmp_path / webfetch.SPILL_DIR).glob('stdout-*.txt'))
    else:
        check(output, tmp_path, expected)


def test_missing_listing_preserves_failure_and_diagnostic(tmp_path):
    with denial.receipt_scope(RECEIPT):
        command = writeproxy._list_command({'path': 'does-not-exist'})
    result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True)
    assert result.returncode == 2
    record = resultpacket.read_record(result.stdout.decode(), 0, RECEIPT)
    assert record and record.kind == denial.REFUSED
    assert b'does-not-exist' in result.stdout
