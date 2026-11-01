"""Operator/ops seams: cria.retention (operator-run cleanup of private retained state: dry run by default, explicit selectors, live holders
skipped, symlinks never followed, corrupt entries removed only when named, interrupted deletes retryable) and cria.heartbeat (SSE keepalive)."""
import fcntl, hashlib, io, json, os, time
from pathlib import Path
from types import SimpleNamespace
import pytest
from cria import imagepersist, retention, writeproxy
from cria.heartbeat import Heartbeat
from cria.imageprotocol import CoderRoute
from cria.imagestore import ImageStore
from cria.multipart_bridge import Bridge

SHELL = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
IMAGE = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA', 'detail': 'high'}}
DAY = 86400

@pytest.fixture
def home(tmp_path):
    h = tmp_path / 'home'; h.mkdir(mode=0o700); return h

def run(home, *argv):
    out = io.StringIO(); code = retention.main([argv[0], '--home', str(home), *argv[1:]], out=out); return code, out.getvalue()

def record(home, tmp_path, session):
    """A registered multipart read persisted exactly as the bridge does (record + call association)."""
    f = tmp_path / ('f-' + hashlib.sha256(session.encode()).hexdigest()[:6]); f.write_text('x' * 40000)
    tc = {'id': 'orig-' + f.name, 'type': 'function', 'function': {'name': 'read_file', 'arguments': json.dumps({'path': str(f)})}}
    comp = {'choices': [{'message': {'tool_calls': [tc]}}]}; bridge = Bridge(str(home / 'multipart'))
    writeproxy.translate_outbound(comp, SHELL, SimpleNamespace(emit=lambda *a, **k: None), injected={'read_file'}, workspace_root=str(tmp_path),
                                  multipart_command=lambda o, e, r: bridge.register(session, o, e, SHELL, r))
    bridge.bind(session, comp)
    return home / 'multipart' / (hashlib.sha256(session.encode()).hexdigest() + '.json')

def image(home, key):
    s = ImageStore(home / 'images', close_authority=object()).session(key)
    s.select_route(CoderRoute(object(), 'm', 'r', True)); s.prepare([{'role': 'user', 'content': [IMAGE]}], 'Read the labels.')
    return s

def age(home, days, *, skip=()):
    t = time.time() - days * DAY
    for p in home.rglob('*'):
        if not p.is_symlink() and p not in skip: os.utime(p, (t, t))

def tree(home): return sorted((str(p.relative_to(home)), p.lstat().st_mtime_ns) for p in home.rglob('*'))

def test_prune_needs_a_selector_dry_runs_by_default_and_apply_removes_only_what_is_old_enough(home, tmp_path):
    """A bare prune can never select everything; without --apply nothing changes; --older-than 1w keeps a 6-day entry and removes an 8-day one."""
    old = record(home, tmp_path, 'sid:old'); age(home, 8); seen = set(home.rglob('*')); new = record(home, tmp_path, 'sid:new'); age(home, 6, skip=seen)
    assert run(home, 'prune')[0] == 2 and run(home, 'prune', '--apply')[0] == 2
    before = tree(home); code, text = run(home, 'prune', '--older-than', '1w')
    assert code == 0 and 'DRY RUN' in text and 'would remove 1 entry' in text and 'nothing was removed' in text and tree(home) == before
    code, text = run(home, 'prune', '--older-than', '1w', '--apply')
    assert code == 0 and text.index('APPLY') < text.index('removed multipart') and not old.exists() and new.exists()
    assert run(home, 'prune', '--older-than', 'soon')[0] == 2

def test_an_image_session_held_by_a_live_process_is_skipped_even_when_selected_and_pruned_once_it_exits(home):
    """A live holder (flock) means active: never deleted; after the holder is gone the same command removes it and its owner marker."""
    s = image(home, 'live'); age(home, 60)
    code, text = run(home, 'prune', '--older-than', '1d', '--apply')
    assert 'held by a live cria process' in text and s._root.exists() and 'active' in run(home, 'list')[1]
    s._hold.close()
    assert run(home, 'prune', '--older-than', '1d', '--apply')[0] == 0
    assert not s._root.exists() and not (home / 'images' / (s._root.name + '.owner.json')).exists()

def test_a_session_selector_removes_only_the_entry_it_names_and_an_unknown_one_removes_nothing(home):
    """--session matches an image by directory name or session key (never as a wildcard); other sessions and unknown names are untouched."""
    a, b = image(home, 'keep-me'), image(home, 'drop-me'); a._hold.close(); b._hold.close(); age(home, 30)
    assert 'removed' not in run(home, 'prune', '--session', 'no-such-session', '--apply')[1] and a._root.exists() and b._root.exists()
    assert run(home, 'prune', '--session', 'drop-me', '--apply')[0] == 0 and a._root.exists() and not b._root.exists()

def test_a_multipart_state_lock_held_by_a_live_process_skips_everything_until_released(home, tmp_path):
    """The bridge's own lock file is the liveness signal for multipart state: held -> skipped (retry later), free -> removed."""
    rec = record(home, tmp_path, 'sid:x'); age(home, 30)
    fd = os.open(home / 'multipart' / '.lock', os.O_RDWR); fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert 'lock is held by a live cria process' in run(home, 'prune', '--older-than', '1d', '--apply')[1] and rec.exists()
    finally: os.close(fd)
    assert run(home, 'prune', '--older-than', '1d', '--apply')[0] == 0 and not rec.exists()

def test_symlinked_entries_and_roots_are_refused_and_their_targets_never_touched(home, tmp_path):
    """Hostile names/links under either root (and a symlinked root) are reported, never followed or deleted; stray files are ignored."""
    outside = tmp_path / 'outside'; outside.mkdir(); (outside / 'precious').write_text('keep'); victim = outside / 'victim.json'; victim.write_text('{}')
    images, mp = home / 'images', home / 'multipart'; images.mkdir(mode=0o700); mp.mkdir(mode=0o700)
    (images / 'image-session-link').symlink_to(outside); (mp / ('a' * 64 + '.json')).symlink_to(victim); (mp / 'notes.txt').write_text('stray')
    for p in (images / 'image-session-link', mp / ('a' * 64 + '.json')): os.utime(p, (1, 1), follow_symlinks=False)
    texts = [run(home, 'prune', '--older-than', '1d', '--apply')[1], run(home, 'prune', '--session', 'a' * 64, '--apply')[1]]
    assert all('removed' not in t for t in texts) and 'refused' in ''.join(texts) and 'ignored' in run(home, 'list')[1]
    assert (outside / 'precious').read_text() == 'keep' and victim.exists() and (images / 'image-session-link').is_symlink() and (mp / 'notes.txt').exists()
    real = tmp_path / 'real'; real.mkdir(mode=0o700); (real / ('b' * 64 + '.json')).write_text('{}'); mp2 = tmp_path / 'home2' / 'multipart'
    mp2.parent.mkdir(mode=0o700); mp2.symlink_to(real)
    assert 'refused' in run(mp2.parent, 'prune', '--older-than', '0s', '--apply')[1] and (real / ('b' * 64 + '.json')).exists()

@pytest.mark.parametrize('kind', ['multipart', 'image'])
def test_a_corrupt_entry_is_reported_and_removed_only_by_an_explicit_session(home, tmp_path, kind):
    """Age alone never deletes what cria cannot validate; naming it with --session --apply does (and leaves no marker behind)."""
    if kind == 'multipart': path = record(home, tmp_path, 'sid:bad'); path.write_text('{"truncated"'); name = 'sid:bad'
    else:
        s = image(home, 'bad'); s._hold.close(); path = s._root; (path / imagepersist.STATE_NAME).write_text('{"version":1}'); name = path.name
    age(home, 40)
    assert 'corrupt' in run(home, 'list')[1]
    assert 'skipped: corrupt' in run(home, 'prune', '--older-than', '1d', '--apply')[1] and path.exists()
    assert run(home, 'prune', '--session', name if kind == 'image' else path.stem, '--apply')[0] == 0 and not path.exists()
    assert not list(home.rglob('*.owner.json'))

def test_an_interrupted_multipart_delete_removes_the_record_first_so_leftovers_fail_closed_and_a_rerun_finishes(home, tmp_path, monkeypatch):
    """The session record goes before its call associations: a crash between them leaves only call associations (anonymous sessions) with no record behind them, which fail closed."""
    rec = record(home, tmp_path, 'anon:half'); age(home, 30); assoc = list((home / 'multipart').glob('call-*.json')); assert assoc
    real = os.unlink
    def crash_on_associations(name, *a, **k):
        if str(name).startswith('call-'): raise OSError('injected crash after the record was removed')
        return real(name, *a, **k)
    monkeypatch.setattr(retention.os, 'unlink', crash_on_associations)
    code, text = run(home, 'prune', '--older-than', '1d', '--apply')
    assert code == 1 and 'safe to re-run' in text and not rec.exists() and list((home / 'multipart').glob('call-*.json'))
    monkeypatch.setattr(retention.os, 'unlink', real)
    assert 'without a session record' in run(home, 'list')[1] and run(home, 'prune', '--older-than', '1d', '--apply')[0] == 0
    assert not list((home / 'multipart').glob('call-*.json'))

class Ticks:
    """Stands in for the beat thread's wait: each wait advances the fake clock one second, runs a scripted action for that second, and stops after `n`."""
    def __init__(self, clock, n, script): self.clock, self.n, self.script, self.i = clock, n, script, 0
    def wait(self, tick):
        self.i += 1; self.clock[0] += 1
        if self.i in self.script: self.script[self.i]()
        return self.i > self.n
    def set(self): self.i = 10**9

def drive(n, script_for, interval=5, **kw):
    """Run the real beat loop on a fake clock; returns [(second, payload)] of every raw write."""
    clock, writes = [0.0], []
    hb = Heartbeat(lambda data: writes.append((clock[0], data)), interval, clock=lambda: clock[0], payload=b'B', **kw)
    hb._stop = Ticks(clock, n, script_for(hb)); hb._run()
    return writes, hb

def test_heartbeats_fill_only_idle_gaps_and_real_content_resets_the_idle_clock():
    """Idle-based keepalive: a beat after `interval` of silence, never while content flows (a write at second 3 moves the next beat from 5 to 8)."""
    assert drive(12, lambda hb: {})[0] == [(5, b'B'), (10, b'B')]
    writes, hb = drive(12, lambda hb: {3: lambda: hb.write(b'DATA')})
    assert writes == [(3, b'DATA'), (8, b'B')] and hb.beats == 1

def test_a_terminal_drain_is_written_once_then_nothing_else_reaches_the_stream():
    """Shutdown drain ends an in-flight SSE with one terminal payload; later content and beats are suppressed, repeat drains are no-ops, a dead socket is tolerated."""
    writes, hb = drive(12, lambda hb: {2: lambda: hb.drain(b'END'), 3: lambda: hb.drain(b'END2'), 4: lambda: hb.write(b'LATE')})
    assert writes == [(2, b'END')]
    dead = Heartbeat(lambda data: (_ for _ in ()).throw(OSError('gone')), 5); dead.drain(b'x'); dead.drain(b'y'); dead.write(b'z')

def test_the_visible_status_tick_runs_outside_the_write_lock_rate_limited_and_never_breaks_the_stream():
    """on_beat gets elapsed seconds at most every beat_status_every (so it may itself write); an exception in it is swallowed."""
    clock, raw = [0.0], []; seen = []
    hb = Heartbeat(lambda data: raw.append(data), 2, clock=lambda: clock[0], payload=b'B', beat_status_every=6,
                   on_beat=lambda elapsed: (seen.append(elapsed), hb.write(b'T'), 1 / 0))
    hb._stop = Ticks(clock, 14, {}); hb._run()
    assert seen == [6.0, 12.0] and raw.count(b'T') == 2 and raw.count(b'B') >= 5
