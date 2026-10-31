"""Wave 10 AUD2 audit of the image store / retention lease code: failures that used to leak the multipart state lock, abort a scan,
leave a directory per failed attempt, or grow the pruner's memory. Real filesystem, real Bridge / ImageStore."""
import errno, fcntl, os
import pytest
from cria import imagepersist, retention
from cria.imagestore import ImageStore
from cria.multipart_bridge import Bridge
from test_server_config_cov_ops import DAY, age, home, image, record  # noqa: F401

class Events:
    def __init__(self): self.rows = []
    def __call__(self, kind, **fields): self.rows.append((kind, fields))
    def kinds(self, kind): return [f for k, f in self.rows if k == kind]

def lock_is_free(home):
    fd = os.open(home / 'multipart' / '.lock', os.O_RDWR)
    try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); return True
    except OSError: return False
    finally: os.close(fd)

def test_a_non_object_image_marker_neither_aborts_the_prune_nor_leaves_the_multipart_state_lock_held(home, tmp_path):
    """A session directory whose owner marker is valid JSON of the wrong shape is reported corrupt and left alone; the old multipart
    record is still pruned and, above all, the exclusive multipart lock is released (a leaked lock hangs every later multipart request)."""
    rec = record(home, tmp_path, 'sid:old'); s = image(home, 'k'); s._hold.close()
    marker = home / 'images' / (s._root.name + '.owner.json'); marker.write_text('[]'); age(home, 30); ev = Events()
    result = retention.AutoPruner(home, DAY, 3600, ev).run_once()
    assert result['failed'] == 0 and not ev.kinds('retention.auto_prune.error')
    assert not rec.exists() and s._root.exists() and marker.exists()
    assert 'not a JSON object' in ev.kinds('retention.auto_prune.skip')[0]['why']
    assert lock_is_free(home)
    bridge = Bridge(str(home / 'multipart'))
    with bridge._transaction('sid:request'): pass       # would block forever on a leaked lock

def test_an_unexpected_scan_failure_of_one_kind_is_a_note_and_leaves_the_other_kind_pruned_and_the_lock_free(home, tmp_path, monkeypatch):
    """Whatever a scan raises (not only the exceptions it was written for) is contained per kind: the image kind is still pruned,
    the failure is a once-announced note, and the multipart lock taken before the failure is not leaked."""
    record(home, tmp_path, 'sid:old'); gone = image(home, 'idle'); gone._hold.close(); age(home, 30)
    monkeypatch.setattr(retention, '_scan_multipart', lambda *a: (_ for _ in ()).throw(RuntimeError('recursion in a record')))
    ev = Events(); pruner = retention.AutoPruner(home, DAY, 3600, ev); result = pruner.run_once()
    assert result['removed'] == 1 and not gone._root.exists()
    assert [f['note'] for f in ev.kinds('retention.auto_prune.note')] == ['multipart: scan failed: RuntimeError: recursion in a record']
    pruner.run_once(); assert len(ev.kinds('retention.auto_prune.note')) == 1
    assert lock_is_free(home)

def test_a_name_that_vanishes_between_listing_and_stat_does_not_abort_the_size_scan(home, monkeypatch):
    """A live session replaces its state file atomically, so a listed name can be gone a moment later: the size/age scan skips it."""
    s = image(home, 'live'); real = os.listdir
    def listing(fd): names = real(fd); return names + ['.image-state-gone'] if isinstance(fd, int) else names
    monkeypatch.setattr(retention.os, 'listdir', listing)
    dirfd = os.open(s._root, os.O_RDONLY | os.O_DIRECTORY)
    try: size, newest = retention._du(dirfd)
    finally: os.close(dirfd)
    assert size > 0 and newest > 0
    s._hold.close()

@pytest.mark.parametrize('failing', ['write_state', 'create_marker'])
def test_a_session_that_cannot_be_created_leaves_no_directory_behind_per_attempt(home, monkeypatch, failing):
    """Full disk while creating a session: every request retries session creation, and each failed attempt used to leave an unmarked
    directory that retention will never remove on its own."""
    root = home / 'images'
    store = ImageStore(root, close_authority=object())
    def full(*a, **k): raise OSError(errno.ENOSPC, 'No space left on device')
    monkeypatch.setattr(imagepersist, failing, full)
    for _ in range(3):
        with pytest.raises(OSError): store.session('sid:full')
    assert list(root.iterdir()) == []
    monkeypatch.undo()
    assert store.session('sid:full')._root.exists()

def test_the_announced_skip_table_does_not_outlive_its_entries(home):
    """A skipped entry is remembered only while it is still being skipped; the table of announcements must not grow for a week."""
    held = image(home, 'live'); age(home, 30); ev = Events(); p = retention.AutoPruner(home, DAY, 3600, ev)
    p.run_once(); assert len(p._announced) == 1
    held._hold.close(); p.run_once()
    assert p._announced == {} and not (home / 'images' / held._root.name).exists()
