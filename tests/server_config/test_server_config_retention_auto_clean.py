"""Operator-authorized automatic prune (`[retention] auto_prune_after`): off unless configured, then the CLI's own selection and
safety on a schedule, in a thread that can never reach a request. Real filesystem, real Bridge/ImageStore, real thread."""
import fcntl, json, os, time
import pytest
from cria import retention
from cria.config import Config, RetentionConfig, ServerConfig
from cria.events import EventLog
from cria.multipart_bridge import Bridge, BridgeError
from cria.server import CriaServer
from cria.upstream import Upstream
from test_server_config_cov_ops import DAY, age, home, image, record  # noqa: F401

class Events:
    def __init__(self): self.rows = []
    def __call__(self, kind, **fields): self.rows.append((kind, fields))
    def kinds(self, kind): return [f for k, f in self.rows if k == kind]

def pruner(home, events, after=14 * DAY, **kw): return retention.AutoPruner(home, after, 3600, events, **kw)

def tree_names(home): return sorted(str(p.relative_to(home)) for p in home.rglob('*') if p.is_file())

def test_nothing_is_removed_when_auto_prune_is_not_configured(home, tmp_path):
    """Default config: starting the server's retention step does nothing, however old the state; it does not even import the prune code."""
    rec = record(home, tmp_path, 'sid:ancient'); s = image(home, 'ancient'); s._hold.close(); age(home, 400); before = tree_names(home)
    cfg = Config(server=ServerConfig(port=0))
    assert cfg.retention.after_seconds is None
    log = EventLog(dir=str(tmp_path / 'logs'), console=False)
    srv = CriaServer(cfg, log, Upstream(cfg.upstream.base_url))
    try:
        assert srv.start_retention(home=home) is None and srv.retention is None
        time.sleep(0.3)
    finally: srv.server_close(); log.close()
    assert rec.exists() and tree_names(home) == before

def test_configured_prune_removes_old_unleased_entries_and_keeps_young_live_and_corrupt_ones(home, tmp_path):
    """Old multipart record + old closed-out image removed (one event each); a young entry, a live image holder and a corrupt old record stay and are announced as skips."""
    old = record(home, tmp_path, 'sid:old'); gone = image(home, 'old-idle'); gone._hold.close()
    held = image(home, 'old-live'); bad = record(home, tmp_path, 'sid:bad'); bad.write_text('{"truncated"')
    age(home, 20)
    young = record(home, tmp_path, 'sid:young'); fresh = image(home, 'young-idle'); fresh._hold.close(); os.utime(home / 'multipart', None)
    ev = Events(); result = pruner(home, ev).run_once()
    assert result == {'removed': 2, 'skipped': 2, 'failed': 0}
    assert not old.exists() and not gone._root.exists() and not (home / 'images' / (gone._root.name + '.owner.json')).exists()
    assert young.exists() and fresh._root.exists() and held._root.exists() and bad.exists()
    removed = {(f['entry_kind'], f['label'] or f['entry_id']) for f in ev.kinds('retention.auto_prune.removed')}
    assert removed == {('multipart', 'sid:old'), ('image', 'old-idle')}
    skips = {f['entry_id']: f['why'] for f in ev.kinds('retention.auto_prune.skip')}
    assert skips[held._root.name] == 'skipped: held by a live cria process' and skips[bad.stem].startswith('skipped: corrupt')
    held._hold.close()

def test_restart_is_idempotent_and_a_skip_is_announced_once_per_process_but_again_after_a_restart(home, tmp_path):
    """A second run, and a fresh pruner (restart), remove nothing more; the repeated skip is logged once per process, and again by the new one."""
    record(home, tmp_path, 'sid:old'); held = image(home, 'live'); age(home, 30)
    first = Events(); p = pruner(home, first)
    assert p.run_once()['removed'] == 1 and p.run_once() == {'removed': 0, 'skipped': 1, 'failed': 0}
    assert len(first.kinds('retention.auto_prune.skip')) == 1 and len(first.kinds('retention.auto_prune.removed')) == 1
    survivors = tree_names(home); second = Events()
    assert pruner(home, second).run_once() == {'removed': 0, 'skipped': 1, 'failed': 0} and tree_names(home) == survivors
    assert len(second.kinds('retention.auto_prune.skip')) == 1 and not second.kinds('retention.auto_prune.removed')
    held._hold.close()
    assert pruner(home, Events()).run_once()['removed'] == 1 and not list((home / 'images').glob('image-session-*'))

def test_an_in_flight_multipart_request_holding_the_state_lock_is_not_pruned_under_and_a_pruned_continuation_fails_closed(home, tmp_path):
    """While a request is inside the bridge's transaction the whole multipart root is skipped (noted); once pruned, a continuation of that read gets the bridge's existing typed unavailable error, not a fabricated read."""
    rec = record(home, tmp_path, 'sid:flight'); age(home, 30); bridge = Bridge(str(home / 'multipart')); ev = Events()
    with bridge._transaction('sid:flight'):
        assert pruner(home, ev).run_once()['removed'] == 0 and rec.exists()
    assert any('held by a live cria process' in f['note'] for f in ev.kinds('retention.auto_prune.note'))
    assert pruner(home, ev).run_once()['removed'] == 1 and not rec.exists()
    carrier = [{'role': 'tool', 'tool_call_id': 'ctxread_abc', 'content': 'page 2 of 3'}]
    with pytest.raises(BridgeError, match='unavailable'): bridge.incoming('sid:flight', carrier)

def test_the_multipart_lock_is_released_before_image_removal_so_a_request_is_never_held_up_by_it(home, tmp_path, monkeypatch):
    """Image deletion can be slow; while it runs the multipart lock is already free (a request can take it)."""
    record(home, tmp_path, 'sid:old'); gone = image(home, 'idle'); gone._hold.close(); age(home, 30); seen = []
    real = retention._delete_image
    def spy(root, entry, authority, *, force):
        fd = os.open(home / 'multipart' / '.lock', os.O_RDWR)
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); seen.append('lock free')
        except OSError: seen.append('lock held')
        finally: os.close(fd)
        return real(root, entry, authority, force=force)
    monkeypatch.setattr(retention, '_delete_image', spy)
    assert pruner(home, Events()).run_once()['removed'] == 2 and seen == ['lock free']

def test_a_failing_scan_removal_or_logger_never_escapes_run_once_and_the_thread_keeps_cycling(home, tmp_path, monkeypatch):
    """Every failure is contained and reported; with a broken collect AND a broken logger the thread still survives, runs again, and an unrelated request-side bridge call works."""
    record(home, tmp_path, 'sid:old'); age(home, 30); ev = Events()
    monkeypatch.setattr(retention.os, 'unlink', lambda *a, **k: (_ for _ in ()).throw(OSError('disk says no')))
    assert pruner(home, ev).run_once() == {'removed': 0, 'skipped': 0, 'failed': 1} and 'disk says no' in ev.kinds('retention.auto_prune.failed')[0]['error']
    monkeypatch.undo()
    calls = []
    def boom(*a, **k): calls.append(1); raise RuntimeError('collect exploded')
    def broken_logger(*a, **k): raise ValueError('logger exploded')
    monkeypatch.setattr(retention, 'collect', boom)
    ev = Events(); assert pruner(home, ev).run_once() == {'removed': 0, 'skipped': 0, 'failed': 1} and calls == [1]
    assert ev.kinds('retention.auto_prune.error') == [{'level': 'error', 'error': 'RuntimeError: collect exploded'}]
    assert retention.AutoPruner(home, DAY, 1, broken_logger).run_once()['failed'] == 1     # not even a broken logger escapes
    calls.clear()
    p = retention.AutoPruner(home, DAY, 0.05, broken_logger); p.start()
    deadline = time.time() + 5
    while len(calls) < 3 and time.time() < deadline: time.sleep(0.02)
    other = Bridge(str(home / 'multipart'))
    with other._transaction('sid:request'): pass          # request-side bridge use is unaffected
    assert len(calls) >= 3 and p._thread.is_alive(); p.stop(); assert not p._thread.is_alive()

def test_the_real_server_starts_the_background_prune_once_at_start_and_removes_old_state(home, tmp_path):
    """Config -> CriaServer.start_retention -> thread: an old record disappears without any request, a young one stays, a second start is a no-op, and the log shows the enabling and the removal."""
    rec = record(home, tmp_path, 'sid:old'); age(home, 30); young = record(home, tmp_path, 'sid:young')
    cfg = Config(server=ServerConfig(port=0), retention=RetentionConfig(auto_prune_after='14d', auto_prune_every='1h'))
    log = EventLog(dir=str(tmp_path / 'logs'), console=False); srv = CriaServer(cfg, log, Upstream(cfg.upstream.base_url))
    try:
        p = srv.start_retention(home=home); assert p is not None and srv.start_retention(home=home) is None
        deadline = time.time() + 10
        while rec.exists() and time.time() < deadline: time.sleep(0.02)
        assert not rec.exists() and young.exists()
    finally: srv.retention.stop(); srv.server_close(); log.close()
    kinds = [json.loads(l)['kind'] for f in (tmp_path / 'logs').glob('cria-*.jsonl') for l in f.read_text().splitlines()]
    assert 'retention.auto_prune.enabled' in kinds and 'retention.auto_prune.removed' in kinds

def test_auto_prune_never_touches_symlinked_or_foreign_entries_or_snapshots(home, tmp_path):
    """Same refusals as the CLI: a symlinked record and a symlinked image dir are reported refused and their targets survive."""
    outside = tmp_path / 'outside'; outside.mkdir(); victim = outside / 'v.json'; victim.write_text('{}')
    images, mp = home / 'images', home / 'multipart'; images.mkdir(mode=0o700); mp.mkdir(mode=0o700)
    (images / 'image-session-link').symlink_to(outside); (mp / ('a' * 64 + '.json')).symlink_to(victim)
    for p in (images / 'image-session-link', mp / ('a' * 64 + '.json')): os.utime(p, (1, 1), follow_symlinks=False)
    ev = Events(); assert pruner(home, ev).run_once()['removed'] == 0
    assert victim.exists() and (images / 'image-session-link').is_symlink() and all(f['why'].startswith('refused') for f in ev.kinds('retention.auto_prune.skip'))

def test_multipart_images_and_retention_all_use_the_one_cria_home_constant(tmp_path, monkeypatch):
    """Changing CRIA_HOME moves the multipart bridge, the image store and the retention default together (the bridge once hard-coded ~/.cria/multipart, so a relocated home was pruned in one place and written in another)."""
    from cria import privatepaths
    moved = tmp_path / 'moved-home'; moved.mkdir(mode=0o700); monkeypatch.setattr(privatepaths, 'CRIA_HOME', moved)
    cfg = Config(server=ServerConfig(port=0), retention=RetentionConfig(auto_prune_after='14d'))
    log = EventLog(dir=str(tmp_path / 'logs'), console=False); srv = CriaServer(cfg, log, Upstream(cfg.upstream.base_url))
    try:
        assert srv.multipart_bridge.storage_dir == str(moved / 'multipart')
        rec = record(moved, tmp_path, 'sid:moved'); age(moved, 30)
        stored = srv.multipart_bridge._dirfd(); os.close(stored)
        assert srv.start_retention() is not None                        # no home argument: the default is the same constant
        deadline = time.time() + 10
        while rec.exists() and time.time() < deadline: time.sleep(0.02)
        assert not rec.exists()
        srv.image_workflow.capture('sid:img', {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}]}]})
        assert (moved / 'images').is_dir() and list((moved / 'images').glob('image-session-*'))
    finally: srv.retention.stop(); srv.server_close(); log.close()
