"""Image store across a process restart and an interrupted cleanup: what was observed survives, and nothing is deleted without the full close protocol."""
import json
import shutil
import pytest
from cria import imagepersist
from cria.imageprotocol import CoderRoute, ImageUnavailable
from cria.imagestore import ImageStore
from test_read_multipart_image import IMAGE, TASK, delivered


def test_a_restarted_process_recovers_refs_and_observations_and_cleanup_needs_every_lease_drained(tmp_path, monkeypatch):
    """Restart: the new store restores the session from its handle, binds the replayed history to the SAME ref with the stored account
    and no pixels, refuses a pre-restart attempt; cleanup stays blocked until recovered leases drain; an interrupted rmtree is finished
    by the sealed marker; a tampered original, bad handle or duplicate identity is an explicit error that keeps the files."""
    root = tmp_path / 'private'; old = ImageStore(root, close_authority=object()); s = old.session('one')
    route = CoderRoute(object(), 'm', 'sig', True); s.select_route(route)
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': TASK}, IMAGE]}]
    ref = s.prepare(messages, TASK).bindings[0].ref; attempt = s.begin(ref, TASK, route, {'model': 'm'}); s.complete(attempt, delivered(attempt, route))
    expected = s.render(s.prepare(messages, TASK)); handle = json.loads(json.dumps(s.retention_handle()))
    s._hold.close()                                                                   # the old process exited

    new = ImageStore(root, close_authority=object())
    with pytest.raises(ImageUnavailable): new.restore_session({**handle, 'directory': '../x'}, recovered_leases=())
    with pytest.raises(ImageUnavailable): new.restore_session({**handle, 'owner': 'other'}, recovered_leases=())
    r = new.restore_session(handle, recovered_leases=(('h1', 'handler'), ('o1', 'image-observation')))
    with pytest.raises(ImageUnavailable, match='already active'): new.restore_session(handle, recovered_leases=())
    assert r.reinspect(ref) == IMAGE and r.pending_leases == 2 and r.pending_observations == 1
    view = r.prepare(messages, TASK); assert view.bindings[0].ref == ref and r.render(view) == expected and 'data:image' not in str(r.render(view))
    with pytest.raises(ImageUnavailable): r.complete(attempt, delivered(attempt, route))                  # no route authority survives a restart
    with pytest.raises(ImageUnavailable, match='authority'): r.confirm_close(object())
    r.confirm_close(new._authority)
    with pytest.raises(ImageUnavailable, match='drained'): r.cleanup_descriptor()
    with pytest.raises(ImageUnavailable): r.recovered_lease('nope')
    r.recovered_lease('h1').release(); r.recovered_lease('o1').release()
    with pytest.raises(ImageUnavailable, match='descriptor'): r.close()                                  # close without the durable queue descriptor
    descriptor = r.cleanup_descriptor(); real = shutil.rmtree
    monkeypatch.setattr(shutil, 'rmtree', lambda p: (_ for _ in ()).throw(OSError('crash mid-delete')))
    with pytest.raises(OSError): new.release(r)
    monkeypatch.setattr(shutil, 'rmtree', real)
    assert imagepersist.read_marker(r._root)['closed'] == descriptor['closed']
    with pytest.raises(ImageUnavailable, match='stale'): new.retry_closed({**descriptor, 'closed': 'forged'})
    new.retry_closed(descriptor)
    assert not r._root.exists() and imagepersist.read_marker(r._root) is None
    new.retry_closed(descriptor)                                                                          # idempotent once gone

    t = old.session('two'); t.select_route(route); tref = t.prepare(messages, TASK).bindings[0].ref; t._hold.close()
    (t._root / (tref + '.json')).write_text(json.dumps({**IMAGE, 'tampered': 1}))
    with pytest.raises(ImageUnavailable): ImageStore(root, close_authority=object()).restore_session(t.retention_handle(), recovered_leases=())
    assert (t._root / (tref + '.json')).exists()


def test_lifecycle_guards_keep_private_state_until_the_exact_close_protocol_is_followed(tmp_path):
    """The store needs an owned 0700 directory; a framed view that lost the image cannot be projected; a foreign or still-open session is
    never released or expired; corrupt state/seal files are explicit errors (never read as 'nothing retained')."""
    loose = tmp_path / 'loose'; loose.mkdir(mode=0o755)
    with pytest.raises(ImageUnavailable): ImageStore(loose, close_authority=object())
    authority_ = object(); store = ImageStore(tmp_path / 'private', close_authority=authority_); s = store.session('k')
    route = CoderRoute(object(), 'm', 'sig', True); s.select_route(route)
    prepared = s.prepare([{'role': 'user', 'content': [{'type': 'text', 'text': TASK}, IMAGE]}], TASK)
    with pytest.raises(ImageUnavailable, match='missing or ambiguous'): s.project(prepared, [{'role': 'user', 'content': 'image gone'}])
    with pytest.raises(ImageUnavailable, match='task scope'): s.begin(prepared.bindings[0].ref, 'a different task', route, {'model': 'm'})
    with pytest.raises(ValueError): store.expire_closed(s, ttl_seconds=-1)
    assert store.expire_closed(s, ttl_seconds=0) is False
    with pytest.raises(ImageUnavailable, match='not confirmed'): store.release(s)
    with pytest.raises(ImageUnavailable, match='not owned'): store.release(ImageStore(tmp_path / 'other', close_authority=object()).session('k'))
    s.confirm_close(authority_); s.cleanup_descriptor()
    assert store.expire_closed(s, ttl_seconds=3600) is False and store.expire_closed(s, ttl_seconds=0) is True and not s._root.exists()
    store.release(s)                                                                                      # already cleaned: a no-op
    live = store.session('live'); (live._root / imagepersist.STATE_NAME).write_text('{')
    with pytest.raises(ImageUnavailable): imagepersist.read_state(live._root)
    imagepersist._marker(live._root).write_text('not json')
    with pytest.raises(ImageUnavailable): imagepersist.read_marker(live._root)
    with pytest.raises(ImageUnavailable): imagepersist.seal_marker(live._root, 'wrong-generation', 'x')
