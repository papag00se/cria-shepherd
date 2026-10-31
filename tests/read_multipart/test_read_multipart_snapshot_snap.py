"""A multipart read is atomic with respect to writers: the first page takes a private snapshot, later pages are served from it,
and a source that changed since is labelled to the coder, never delivered as current. Real bash on a real PTY plays the harness;
writers race the pages (rewrite in place, append, truncate, replace by rename, change and revert).
Incident: the page programs re-read the path on every page, so a concurrent writer made a read unrecoverable (every retry
raced again) and a change-and-revert between pages was invisible."""
import hashlib
import json
import os
import random
import stat
import threading
import time

import pytest

from cria import denial, filecommands, wsview, writeproxy
from cria.multipart_bridge import Bridge
from read_multipart_helpers import HEX, isolated_home, page_through, run_call, start  # noqa: F401

NOTE = '⟦ctx:read-source-changed⟧'
ORIGINAL = HEX.encode()


@pytest.fixture(autouse=True)
def harness_tmp(tmp_path, monkeypatch):
    """The harness's $TMPDIR, where the snapshot lives, is the test's own directory."""
    (tmp_path / 'tmp').mkdir()
    monkeypatch.setenv('TMPDIR', str(tmp_path / 'tmp'))
    return tmp_path / 'tmp'


def litter(tmp):
    return sorted(p.name for p in tmp.iterdir() if p.name.startswith(filecommands.MULTIPART_SNAPSHOT_DIR))


def failing_run(call):
    """The harness as it reports a page that exits non-zero (the shared PTY rig asserts success)."""
    try:
        return run_call(call)
    except AssertionError:
        return 'Wall time: 1 seconds\nProcess exited with code 2\nOutput:\n'


def read_racing(bridge, messages, hook, restart=None, run=run_call):
    """Answer each private continuation on the PTY; `hook(n)` runs before page n (n >= 1) - the writer's move."""
    n = 0
    while True:
        projected, calls, facts = bridge.incoming('s', messages)
        if not calls:
            return projected, facts
        n += 1
        hook(n)
        messages += [{'role': 'assistant', 'tool_calls': [calls[0]]},
                     {'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': run(calls[0])}]
        if restart:
            bridge = restart()


def delivered(tmp_path, path, projected):
    """What the coder is shown for the original call, and what the workspace view credits as read."""
    view = wsview.View(str(tmp_path), 'sid:snap'); wsview.bind(view)
    message = next(m for m in writeproxy.represent_inbound(projected, workspace_root=str(tmp_path)) if m.get('tool_call_id') == 'original')
    return message, view.read_observed(str(path))


def rewrite(path, offset=20000, data=b'ZZZZZZZZ'):
    with open(path, 'r+b') as f:
        f.seek(offset); f.write(data)

def append(path):
    with open(path, 'ab') as f: f.write(b'appended after the read began\n')

def truncate(path):
    os.truncate(path, 1000)

def rename(path):
    other = path.with_name('replacement'); other.write_bytes(b'a different file entirely\n' * 3000); os.replace(other, path)


WRITERS = {'rewrite-in-place': rewrite, 'append': append, 'truncate': truncate, 'replace-by-rename': rename}


@pytest.mark.parametrize('writer', WRITERS)
def test_a_writer_between_pages_cannot_change_the_read_and_the_change_is_labelled(tmp_path, writer):
    """Every writer that touches the path after the first page: the read still completes verified with EXACTLY the first page's file,
    the coder is told the file changed since the read began, and the changed read earns no read credit; the snapshot is gone."""
    bridge, messages, path = start(tmp_path, HEX)
    projected, facts = read_racing(bridge, messages, lambda n: WRITERS[writer](path) if n == 2 else None)
    message, credit = delivered(tmp_path, path, projected)
    assert message['content'].startswith(HEX) and NOTE in message['content'] and f'({len(ORIGINAL)} bytes)' in message['content']
    assert facts == () and credit is None and denial.read_payload(message) is None      # shown, labelled, never current read credit
    assert litter(tmp_path / 'tmp') == []


def test_the_same_read_with_no_writer_is_delivered_unlabelled_with_read_credit(tmp_path):
    """Control: no writer, same multipage file: exact bytes, no label, a protected read fact and workspace read credit."""
    bridge, messages, path = start(tmp_path, HEX)
    assert len(litter(tmp_path / 'tmp')) == 1                                  # the snapshot exists while pages remain
    projected, facts = page_through(bridge, messages)
    message, credit = delivered(tmp_path, path, projected)
    assert len(facts) == 1 and facts[0].exact_body == ORIGINAL and NOTE not in message['content']
    assert credit == HEX and litter(tmp_path / 'tmp') == []


def test_change_and_revert_between_pages_is_visible_and_the_bytes_are_still_the_first_pages(tmp_path):
    """A writer that changes the file and puts it back between pages used to be invisible. Now the read is the first page's bytes and the
    changed identity (modification time) is reported; a writer that also restores the mtime leaves nothing to report and the bytes
    ARE the file's, so that read is delivered unlabelled."""
    for restore_mtime, labelled in ((False, True), (True, False)):
        bridge, messages, path = start(tmp_path, HEX, name='cr%d' % restore_mtime)
        before = path.stat()
        def hook(n):
            if n == 2: rewrite(path)
            if n == 3:
                path.write_bytes(ORIGINAL)
                if restore_mtime: os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        projected, facts = read_racing(bridge, messages, hook)
        message, _ = delivered(tmp_path, path, projected)
        assert message['content'].startswith(HEX) and (NOTE in message['content']) is labelled and bool(facts) is not labelled


def test_a_concurrent_writer_thread_never_makes_a_started_read_unrecoverable_or_mixed(tmp_path):
    """A real thread replaces each file as fast as it can while that file's pages run on the PTY. Every read whose first page succeeded finishes
    verified as one whole version the writer produced (never a mix), and is labelled when the path moved on."""
    versions = [ORIGINAL] + [HEX.replace('0', c).encode() for c in 'abcdefg']
    targets, stop, rng = [], threading.Event(), random.Random(5)
    def writer():
        while not stop.is_set():
            for path in list(targets):
                other = path.with_name(path.name + '.w'); other.write_bytes(rng.choice(versions)); os.replace(other, path)
            time.sleep(0.001)
    thread = threading.Thread(target=writer); thread.start()
    try:
        runs = []
        for i in range(6):
            bridge, messages, path = start(tmp_path, HEX, name='race%d' % i); targets.append(path)
            projected, facts = read_racing(bridge, messages, lambda n: time.sleep(0.01))
            runs.append((bridge.sessions['s']['original'], path, projected, facts))
    finally:
        stop.set(); thread.join()
    assert litter(tmp_path / 'tmp') == []
    for entry, path, projected, facts in runs:
        assert entry.assembly.snapshot[0] == 'snapshot' and entry.result is not None and entry.failure_id is None
        shown = delivered(tmp_path, path, projected)[0]['content']
        assert shown.split('\n\n' + NOTE)[0].encode() in versions
        assert (NOTE in shown) is bool(entry.assembly.source_changed) and bool(facts) is not (NOTE in shown)


def test_a_source_over_the_snapshot_cap_or_a_snapshot_that_cannot_be_made_pages_live_with_a_typed_reason(tmp_path, monkeypatch, harness_tmp):
    """No snapshot: the old detect-and-fail-closed paging, with the reason in the typed record. Unwritten: a read completes and is
    exact; a writer between pages makes it unverified (no credit), never a stale file. Survives a bridge restart (the rebuilt page
    commands must still be the live ones)."""
    rows = []
    monkeypatch.setattr(filecommands, 'MULTIPART_SNAPSHOT_MAX_BYTES', 10_000)
    rows.append(('over_cap', None))
    rows.append(('unavailable', lambda: monkeypatch.setenv('TMPDIR', str(harness_tmp / 'missing'))))
    for reason, prepare in rows:
        monkeypatch.setattr(filecommands, 'MULTIPART_SNAPSHOT_MAX_BYTES', 10_000 if reason == 'over_cap' else filecommands.windowcaps.REFERENCE_WINDOW * 4)
        if prepare: prepare()
        storage = str(tmp_path / ('state-' + reason))
        bridge, messages, path = start(tmp_path, HEX, name=reason, storage=storage)
        projected, facts = read_racing(bridge, messages, lambda n: None, restart=lambda: Bridge(storage))
        assert facts[0].exact_body == ORIGINAL and NOTE not in next(m for m in projected if m.get('tool_call_id') == 'original')['content']
        bridge, messages, path = start(tmp_path, HEX, name=reason + '2', storage=storage + '2')
        bridge.incoming('s', messages)
        assert bridge.sessions['s']['original'].assembly.snapshot == ('live', reason, None)
        projected, facts = read_racing(bridge, messages, lambda n: rewrite(path) if n == 2 else None, restart=lambda: Bridge(storage + '2'))
        message, credit = delivered(tmp_path, path, projected)
        assert facts == () and credit is None and 'could not be verified' in message['content'] and HEX not in message['content']


def test_a_tampered_snapshot_is_never_served_and_the_read_fails_closed(tmp_path, harness_tmp):
    """Every page reports the digest of the bytes it was served from and the consumer compares it with the first page's: bytes someone
    altered in the snapshot (or removed it) fail the read as unverified instead of being delivered."""
    for damage in ('alter', 'remove'):
        bridge, messages, path = start(tmp_path, HEX, name=damage)
        (directory,) = [p for p in harness_tmp.iterdir() if p.name.startswith(filecommands.MULTIPART_SNAPSHOT_DIR)
                        and (p / 'snap').exists() and hashlib.sha256((p / 'snap').read_bytes()).hexdigest() == hashlib.sha256(ORIGINAL).hexdigest()]
        def hook(n):
            if n == 2:
                if damage == 'alter':
                    with open(directory / 'snap', 'r+b') as f: f.write(b'ALTERED!')
                else:
                    (directory / 'snap').unlink()
        projected, facts = read_racing(bridge, messages, hook, run=failing_run)
        message, credit = delivered(tmp_path, path, projected)
        assert facts == () and credit is None and 'could not be verified' in message['content'] and 'ALTERED!' not in message['content']


def test_the_snapshot_is_private_owned_and_exact_while_pages_remain(tmp_path, harness_tmp):
    """Mid-read the harness TMPDIR holds one authenticated owned directory (0700, certificate, 0600 files) whose snapshot is the file's
    bytes; a one-page read makes none."""
    bridge, messages, path = start(tmp_path, HEX, name='mid')
    (directory,) = [harness_tmp / n for n in litter(harness_tmp)]
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700 and sorted(p.name for p in directory.iterdir()) == ['.owner', 'meta', 'snap']
    assert (directory / 'snap').read_bytes() == ORIGINAL and stat.S_IMODE((directory / 'snap').stat().st_mode) == 0o600
    meta = json.loads((directory / 'meta').read_text()); st = path.stat()
    assert meta['taken'] == [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]
    page_through(bridge, messages)
    assert litter(harness_tmp) == []
    start(tmp_path, 'one short page\n', name='short')
    assert litter(harness_tmp) == []


def test_snapshot_paging_keeps_every_byte_exact_and_every_page_under_the_transport_limit(tmp_path):
    """ESC, NUL, CRLF and multibyte UTF-8 across many snapshot-served pages (run_call asserts each PTY result <= 10,000 bytes)."""
    body = ('\x1b[31mred\x1b[0m\x00 CRLF\r\n caf\u00e9 \u754c\n' * 1500 + 'no final newline').encode()
    bridge, messages, path = start(tmp_path, body, name='exact')
    projected, facts = page_through(bridge, messages)
    assert len(facts) == 1 and facts[0].exact_body == body
    message, credit = delivered(tmp_path, path, projected)
    assert denial.read_payload(message) == body.decode() and credit == body.decode()
