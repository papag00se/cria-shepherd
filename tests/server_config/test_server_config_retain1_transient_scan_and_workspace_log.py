"""Retained-state leftovers on a real filesystem: the credentialed scratch directories killed lowered programs leave in the harness temp
directory (`--kind transient`), the image scan that must not re-validate sessions the age already excludes, an ambiguous session prefix,
and the workspace-image read provenance that is an append-only log read once per session."""
import hashlib, io, json, os, subprocess, sys, time

import pytest
from cria import completionmarks, editsequence, gatecleanup, imagepersist, ownedfiles, retention
from cria.imageprotocol import ImageUnavailable
from cria.imageworkspace import ImageWorkspace, WorkspaceImageTool
from cria.imagestore import ImageStore
from test_server_config_cov_ops import DAY, IMAGE, age, home, image, record, run  # noqa: F401

CRED = 'a1b2c3d4e5f6a7b8c9d0e1f2'


def make_scratch(tmp, prefix, credential, *files):
    """A directory exactly as the lowered programs create it: the real `_owned_open` of `ownedfiles.DIRECTORY_PROGRAM` writes the
    certificate; `files` are then added by name (a name ending '/' is a directory, 'aux/x' a file inside one)."""
    program = ownedfiles.DIRECTORY_PROGRAM + f"\nctx = _owned_open({credential!r}, {prefix!r}, [], time.monotonic() + 5)\n"
    subprocess.run([sys.executable, '-c', program], check=True, env={**os.environ, 'TMPDIR': str(tmp)})
    root = tmp / (prefix + credential)
    for name in files:
        target = root / name
        if name.endswith('/'):
            target.mkdir(mode=0o700)
        else:
            target.write_bytes(b'payload ' + name.encode()); target.chmod(0o600)
    return root


def old(path, days=9):
    t = time.time() - days * DAY
    for p in [path, *path.rglob('*')]:
        if not p.is_symlink():
            os.utime(p, (t, t))
    return path


def trun(tmp_path, *argv):
    out = io.StringIO(); code = retention.main([argv[0], '--home', str(tmp_path / 'home'), '--tmp', str(tmp_path / 't'), *argv[1:]], out=out)
    return code, out.getvalue()


def test_the_scratch_an_earlier_release_left_is_swept_by_exact_shape_and_nothing_else(tmp_path):
    """Done marks, edit-sequence markers and gate scratch under both prefix generations are listed with their size and removed by age; a
    prefix look-alike without a matching certificate, a loose-mode directory, a symlink, foreign contents, a symlink inside gate
    `aux/` and an unrelated directory all survive, and `all` never scans the temp directory."""
    t = tmp_path / 't'; t.mkdir(); (tmp_path / 'home').mkdir(mode=0o700)
    done = make_scratch(t, completionmarks.DIR_PREFIX, CRED, 'm-r1-n1', '.t-m-r1-n1')
    earlier_done = make_scratch(t, '.cria-done-', CRED[::-1], 'm-r2-n2')
    edits = make_scratch(t, '.cria-edits-', 'turn-0123456789ab', '0', '1')
    gate = make_scratch(t, '.gate-private-', CRED[:12] * 2, 'request.json', 'survey.sh', '.cria-gate-x-cmd.sh', 'aux/', 'aux/out.txt')
    (gate / 'aux' / 'deeper').mkdir(); (gate / 'aux' / 'deeper' / 'f').write_text('x')
    good = [done, earlier_done, edits, gate]
    stranger = make_scratch(t, '.ctx-done-', 'b' * 24, 'm-x-y')
    (stranger / '.owner').write_text(json.dumps({'credential': 'c' * 24, 'namespace': '.ctx-done-'}))    # a certificate for another name
    bare = t / ('.cria-done-' + 'd' * 24); bare.mkdir(mode=0o700); (bare / 'precious').write_text('mine')
    loose = make_scratch(t, '.ctx-edits-', 'loose', '0'); loose.chmod(0o755)
    foreign = make_scratch(t, '.ctx-edits-', 'foreign', '0'); (foreign / 'sub').mkdir()                 # a directory where only files belong
    nested_link = make_scratch(t, '.ctx-private-', 'e' * 24, 'aux/'); (nested_link / 'aux' / 'l').symlink_to(t)
    link = t / '.cria-edits-linked'; link.symlink_to(done)
    odd = t / '.cria-done-has.dot'; odd.mkdir(mode=0o700)
    unrelated = t / 'work'; unrelated.mkdir(); (unrelated / 'f').write_text('keep')
    for p in (*good, stranger, bare, loose, foreign, nested_link):
        old(p)
    code, text = trun(tmp_path, 'list', '--kind', 'transient', '--json'); data = json.loads(text); by_id = {e['id']: e for e in data['entries']}
    assert code == 0 and set(by_id) == {p.name for p in (*good, stranger, bare, loose, foreign, nested_link)} | {link.name}
    assert data['ignored'] == ['transient/' + odd.name]
    assert {p.name: by_id[p.name]['label'] for p in good} == {done.name: 'completion marks', earlier_done.name: 'completion marks',
                                                              edits.name: 'edit-sequence markers', gate.name: 'gate scratch'}
    assert by_id[gate.name]['size'] > len(b'payload request.json') and not any(by_id[p.name]['refused'] for p in good)
    assert all(by_id[p.name]['refused'] for p in (stranger, bare, loose, foreign, nested_link)) and by_id[link.name]['refused']
    assert json.loads(trun(tmp_path, 'list', '--json')[1])['entries'] == []                              # `all` never scans the harness temp directory
    assert trun(tmp_path, 'prune', '--kind', 'transient', '--apply')[0] == 2 and all(p.exists() for p in good)
    young = make_scratch(t, '.ctx-done-', 'f' * 24, 'm-z-z')                                              # freshly made: not old enough
    code, text = trun(tmp_path, 'prune', '--kind', 'transient', '--older-than', '1d')
    assert 'would remove 4 entries' in text and all(p.exists() for p in good)                            # dry run
    code, text = trun(tmp_path, 'prune', '--kind', 'transient', '--older-than', '1d', '--apply')
    assert code == 0 and text.count('removed transient') == 4 and not any(p.exists() for p in good)
    assert all(p.exists() for p in (young, stranger, loose, foreign, nested_link, odd, unrelated)) and (bare / 'precious').read_text() == 'mine'
    assert link.is_symlink() and (nested_link / 'aux' / 'l').is_symlink() and t.exists()
    code, text = trun(tmp_path, 'prune', '--kind', 'transient', '--session', young.name[:12], '--apply')  # a name, never a prefix
    assert 'removed' not in text and young.exists()
    assert trun(tmp_path, 'prune', '--kind', 'transient', '--session', young.name, '--apply')[0] == 0 and not young.exists()


def test_a_scratch_directory_swapped_between_listing_and_removal_is_left_alone(tmp_path):
    """The removal re-proves identity and certificate: the listed directory replaced by another one of the same name is not touched."""
    t = tmp_path / 't'; t.mkdir()
    victim = old(make_scratch(t, '.ctx-edits-', 'turn-1', '0'))
    tmp_fd = os.open(t, os.O_RDONLY | os.O_DIRECTORY)
    try:
        entries, _ = retention._scan_transient(tmp_fd)
        [entry] = entries
        os.rename(victim, t / 'moved'); victim.mkdir(mode=0o700); (victim / 'keep').write_text('theirs')
        with pytest.raises(OSError):
            retention._delete_transient(tmp_fd, entry)
        assert (victim / 'keep').read_text() == 'theirs'
    finally:
        os.close(tmp_fd)


def test_the_real_programs_scratch_names_are_swept_in_both_generations(tmp_path):
    """The prefixes the sweep knows are the ones the programs use now (a renamed constant fails here, not silently in the field)."""
    known = {p for p, _, _ in retention._TRANSIENT_SHAPES}
    assert {completionmarks.DIR_PREFIX, editsequence.EDIT_SEQ_DIR, gatecleanup.PRIVATE_PREFIX} <= known


def counting_restore(monkeypatch):
    calls = []
    original = ImageStore.restore_session
    monkeypatch.setattr(ImageStore, 'restore_session', lambda self, handle, **kw: calls.append(handle['directory']) or original(self, handle, **kw))
    return calls


def test_an_image_session_the_age_already_excludes_is_not_opened_and_re_hashed(home, monkeypatch):
    """`prune --older-than` validates only the sessions old enough to be selected; `list` (no age) still validates all of them."""
    a = image(home, 'sid:old'); b = image(home, 'sid:young'); a._hold.close(); b._hold.close()
    for p in a._root.rglob('*'):
        os.utime(p, (time.time() - 9 * DAY,) * 2)
    os.utime(a._root, (time.time() - 9 * DAY,) * 2); os.utime(str(a._root) + '.owner.json', (time.time() - 9 * DAY,) * 2)
    calls = counting_restore(monkeypatch)
    assert run(home, 'list')[0] == 0 and sorted(calls) == sorted([a._root.name, b._root.name])
    calls.clear()
    code, text = run(home, 'prune', '--older-than', '1d', '--apply')
    assert code == 0 and set(calls) == {a._root.name} and not a._root.exists() and b._root.exists()   # (the old one: scanned, then removed through the store)


def first_shared_prefix():
    seen = {}
    for n in range(300000):
        session = f'sid:{n}'; d = hashlib.sha256(session.encode()).hexdigest()
        if d[:8] in seen:
            return seen[d[:8]], session
        seen[d[:8]] = session
    raise AssertionError('no shared 8-hex prefix in 300000 sessions')


def test_a_session_prefix_naming_two_sessions_is_refused_and_listed_never_applied(home, tmp_path):
    """Two sessions share their first 8 hex of digest: that prefix removes nothing (not even with --apply) and lists both; the full
    digest, or the raw session identity, removes exactly one."""
    s1, s2 = first_shared_prefix(); r1 = record(home, tmp_path, s1); r2 = record(home, tmp_path, s2); age(home, 3)
    prefix = hashlib.sha256(s1.encode()).hexdigest()[:8]
    code, text = run(home, 'prune', '--session', prefix, '--apply')
    assert code == 2 and 'ambiguous' in text and s1 in text and s2 in text and r1.exists() and r2.exists()
    assert run(home, 'prune', '--session', hashlib.sha256(s1.encode()).hexdigest(), '--apply')[0] == 0 and not r1.exists() and r2.exists()
    assert run(home, 'prune', '--session', prefix, '--apply')[0] == 0 and not r2.exists()   # one entry left: the prefix is unambiguous again


# ------------------------------------------------------------------ workspace image read provenance

class CountingMessage(dict):
    reads = 0
    def get(self, key, default=None):
        CountingMessage.reads += 1
        return super().get(key, default)


def workspace_rig(home):
    session = image(home, 'sid:ws')
    ws = ImageWorkspace(WorkspaceImageTool('view_image', 'path'))
    tools = [{'type': 'function', 'function': {'name': 'view_image', 'parameters': {
        'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}}]
    return session, ws, tools


def issue(ws, session, tools, path):
    reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'o', 'type': 'function', 'function': {'name': 'view_image', 'arguments': json.dumps({'path': path})}}]}}]}
    return ws.register(session, reply, tools)['choices'][0]['message']['tool_calls'][0]


def exchange(call, content):
    return [{'role': 'assistant', 'content': None, 'tool_calls': [call]}, {'role': 'tool', 'tool_call_id': call['id'], 'content': content}]


def test_a_registered_read_is_appended_not_the_whole_provenance_rewritten(home):
    """Each read adds one line to the log and leaves every earlier byte as it was; an earlier release's whole file is never written."""
    session, ws, tools = workspace_rig(home); log = session._root / 'workspace-reads.log'; seen = b''
    for n in range(5):
        issue(ws, session, tools, f'/w/{n}.png'); data = log.read_bytes()
        assert data.startswith(seen) and data.count(b'\n') == n + 1 and (log.stat().st_mode & 0o777) == 0o600
        seen = data
    assert not (session._root / 'workspace-reads.json').exists()


def test_resolve_looks_at_each_message_a_constant_number_of_times_however_many_reads_were_registered(home):
    """60 registered reads, 40 of them answered: the work is one pass over the messages (the walk per read made it reads x messages)."""
    session, ws, tools = workspace_rig(home); calls = [issue(ws, session, tools, f'/w/{n}.png') for n in range(60)]
    messages = [{'role': 'user', 'content': 'look'}]
    for call in calls[:40]:
        messages += exchange(call, [IMAGE])
    messages = [CountingMessage(m) for m in messages]; CountingMessage.reads = 0
    sources = ws.resolve(session, messages)
    assert len(sources) == 40 and sources[(2, 0)] == '/w/0.png' and CountingMessage.reads <= 6 * len(messages)


def test_provenance_survives_a_restart_a_torn_tail_and_an_earlier_releases_whole_file(home):
    """A fresh load (no in-memory state) sees the reads and the first result's digest, so a changed result is still refused; an
    unterminated last line (a crash inside an append) is dropped and the next append repairs it; the earlier whole file is the base."""
    session, ws, tools = workspace_rig(home); call = issue(ws, session, tools, '/w/a.png'); messages = exchange(call, [IMAGE])
    assert ws.resolve(session, messages) == {(1, 0): '/w/a.png'}
    del session._workspace_reads                                                                    # a restart: nothing in memory
    changed = exchange(call, [{**IMAGE, 'image_url': {'url': 'data:image/png;base64,ZZZZ'}}])
    with pytest.raises(ImageUnavailable):
        ws.resolve(session, changed)
    assert ws.resolve(session, messages) == {(1, 0): '/w/a.png'}
    log = session._root / 'workspace-reads.log'
    with open(log, 'ab') as out:
        out.write(b'{"generation": "torn')
    second = issue(ws, session, tools, '/w/b.png')
    del session._workspace_reads
    assert ws.resolve(session, exchange(second, [IMAGE])) == {(1, 0): '/w/b.png'} and ws.resolve(session, messages) == {(1, 0): '/w/a.png'}
    assert all(json.loads(line) for line in log.read_bytes().splitlines())
    legacy = {'generation': session._generation, 'reads': {'old': {'call': {'id': 'old'}, 'path': '/w/o.png', 'origin_ref': None, 'result_digest': None}}}
    (session._root / 'workspace-reads.json').write_text(json.dumps(legacy)); del session._workspace_reads
    assert ws._state(session)['reads'].keys() == {call['id'], second['id'], 'old'}
    (session._root / 'workspace-reads.log').write_bytes(b'not json\n'); del session._workspace_reads
    with pytest.raises(ImageUnavailable):
        ws._state(session)
