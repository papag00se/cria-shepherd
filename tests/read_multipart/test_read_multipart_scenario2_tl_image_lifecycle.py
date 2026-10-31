"""An image session's working life around the observation: harness tool images need provenance, a task change re-opens the observation, a cancelled/duplicate/closing
session refuses stale work, replacement retires the old one, a fresh workspace read re-retains, and the cleanup queue rejects every malformed descriptor."""
import json

import pytest

from cria.imageprotocol import CoderRoute, ImageUnavailable
from cria.imagestore import FreshWorkspaceRead, ImageStore
from test_read_multipart_image import IMAGE, TASK, delivered

USER = [{'role': 'user', 'content': [{'type': 'text', 'text': TASK}, IMAGE]}]
TOOL = [{'role': 'tool', 'content': [IMAGE]}]


def test_a_session_runs_its_image_through_provenance_task_change_cancel_and_fresh_read(tmp_path):
    store = ImageStore(tmp_path / 'p', close_authority=object())
    with pytest.raises(ImageUnavailable, match='identity'): store.session('')
    s = store.session('k'); route = CoderRoute(object(), 'm', 'sig', True)
    assert store.session('k') is s and s.ready_to_close is False
    with pytest.raises(ImageUnavailable, match='provenance'): s.prepare(TOOL, TASK)                  # a tool image must name the harness read that produced it
    ref = s.prepare(TOOL, TASK, workspace_sources={(0, 0): 'shots/a.png'}).bindings[0].ref
    assert s.reinspect(ref) == FreshWorkspaceRead(ref, 'shots/a.png')                                 # the workspace file is never opened
    with pytest.raises(ImageUnavailable, match='provenance changed'): s.prepare(TOOL, TASK, workspace_sources={(0, 0): 'shots/b.png'})
    with pytest.raises(ImageUnavailable, match='unavailable in this session'): s.reinspect('img_nope')
    with pytest.raises(ImageUnavailable, match='provenance is required'): s.retain_fresh_workspace_read(ref, IMAGE, TASK, event_id='')
    fresh = s.retain_fresh_workspace_read(ref, IMAGE, TASK, event_id='ev1')
    assert fresh != ref and s.reinspect(fresh) == FreshWorkspaceRead(fresh, 'shots/a.png')
    with pytest.raises(ImageUnavailable, match='provenance is required'): s.retain_fresh_workspace_read(s.prepare(USER, TASK).bindings[0].ref, IMAGE, TASK, event_id='e')

    s.select_route(route); uref = s.prepare(USER, TASK).bindings[0].ref
    first = s.begin(uref, TASK, route, {'model': 'm'}); assert s.pending_observations == 1 and s.pending_leases == 1
    s.complete(first, delivered(first, route)); assert s.pending_observations == 0
    assert s.prepare(USER, 'a new task').bindings[0].ref == uref and s.begin(uref, 'a new task', route, {'model': 'm'}).ref == uref   # new task: same ref, observation re-opened
    with pytest.raises(ImageUnavailable, match='Coder route'): s.begin(uref, 'a new task', CoderRoute(object(), 'other', 'sig', True), {'model': 'm'})
    attempt = s.begin(uref, 'a new task', route, {'model': 'm'}); assert s.pending_leases == 2
    s.cancel(attempt); s.cancel(attempt)                                                              # cancelling twice is harmless
    assert s.pending_leases == 1
    bad = delivered(first, route); s.cancel(attempt)
    with pytest.raises(ImageUnavailable, match='stale'): s.complete(attempt, bad)                     # a cancelled attempt cannot be completed
    with s.acquire(): assert s.pending_leases == 2
    assert s.pending_leases == 1


def test_replacement_retires_the_old_session_and_closure_refuses_everything_afterwards(tmp_path):
    authority = object(); ticks = iter(range(100)); store = ImageStore(tmp_path / 'p', close_authority=authority, clock=lambda: next(ticks))
    old = store.session('k'); new = store.session('k', replace=True)
    assert new is not old
    for call in (lambda: old.prepare(USER, TASK), old.acquire, lambda: old.select_route(None)):
        with pytest.raises(ImageUnavailable, match='closed, closing or replaced'): call()
    new.prepare(USER, TASK); lease = new.acquire()
    new.confirm_close(authority); stamp = new._confirmed_at; new.confirm_close(authority)
    assert new._confirmed_at == stamp                                                                 # the TTL runs from the FIRST confirmation
    assert not new.ready_to_close
    with pytest.raises(ImageUnavailable, match='closed, closing'): new.prepare(USER, TASK)
    with pytest.raises(ImageUnavailable, match='drained'): new.cleanup_descriptor()
    lease.release(); lease.release()
    assert new.ready_to_close and new.pending_leases == 0
    with pytest.raises(ExceptionGroup) as grouped: store.close()                                     # nothing is deleted implicitly: one session unsealed, the retired one never confirmed
    assert sorted(str(e) for e in grouped.value.exceptions) == ['Image cleanup requires its owner-issued durable queue descriptor', 'Image session is not confirmed closed and drained']


@pytest.mark.parametrize("change", [
    {'closed': ''}, {'closed': 7}, {'owner': 'x'}, {'directory': 'image-session-a/../b'}, {'directory': 5}, {'generation': 'XYZ'}, {'generation': 3},
])
def test_the_cleanup_queue_rejects_every_malformed_descriptor_and_handle(tmp_path, change):
    store = ImageStore(tmp_path / 'p', close_authority=object())
    good = {'owner': 'session-images', 'directory': 'image-session-abc', 'generation': 'a' * 32, 'closed': 'seal'}
    for bad in (None, [], {'owner': 'session-images'}):
        with pytest.raises(ImageUnavailable, match='Invalid image cleanup'): store.retry_closed(bad)
    with pytest.raises(ImageUnavailable, match='Invalid closed image generation'): store.retry_closed({**good, **change})
    handle = {k: v for k, v in {**good, **change}.items() if k != 'closed'}
    if 'closed' not in change:
        with pytest.raises(ImageUnavailable, match='Invalid owned image retention handle'): store.restore_session(handle, recovered_leases=())
    store.retry_closed(good)                                                                          # a descriptor for a directory that is already gone is a settled no-op
    with pytest.raises(ImageUnavailable, match='Invalid owned'): store.restore_session(None, recovered_leases=())
