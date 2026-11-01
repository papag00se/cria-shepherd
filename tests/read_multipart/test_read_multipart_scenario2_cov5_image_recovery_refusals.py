"""Scenario: a restarted process finds an image session's retained state damaged or inconsistent (a hand edit, a half write, a different generation, bad lease
identities): every case is an explicit ImageUnavailable naming what is wrong - never a session that silently forgot an image - and the retained files stay."""
import json

import pytest

from cria import imagepersist
from cria.imageprotocol import CoderRoute, ImageUnavailable
from cria.imagestore import ImageStore
from test_read_multipart_image import IMAGE, TASK, delivered

MESSAGES = [{'role': 'user', 'content': [{'type': 'text', 'text': TASK}, IMAGE]}]


def damaged(tmp_path, edit):
    """A session that observed one image and exited; ``edit(state)`` rewrites its retained state file; returns (new store, handle)."""
    root = tmp_path / 'private'
    old = ImageStore(root, close_authority=object()); s = old.session('one')
    route = CoderRoute(object(), 'm', 'sig', True); s.select_route(route)
    ref = s.prepare(MESSAGES, TASK).bindings[0].ref
    attempt = s.begin(ref, TASK, route, {'model': 'm'}); s.complete(attempt, delivered(attempt, route))
    handle = json.loads(json.dumps(s.retention_handle())); s._hold.close()
    state = imagepersist.read_state(s._root); edit(state); imagepersist.write_state(s._root, state)
    return ImageStore(root, close_authority=object()), handle


@pytest.mark.parametrize("edit, leases, message", [
    (lambda st: st.update(generation='another-generation'), (), 'generation does not match'),
    (lambda st: st['records'][0].update(ref='not-a-ref'), (), 'Invalid retained image reference'),
    (lambda st: st['records'][0].update(ref=7), (), 'Invalid retained image reference'),
    (lambda st: st['records'][0]['observation'].update(extra='x'), (), 'Invalid retained image observation'),
    (lambda st: st['records'][0]['observation'].update(description=5), (), 'Invalid retained image observation'),
    (lambda st: st['occurrences'][0].__setitem__(2, 'img_' + '0' * 32), (), 'Invalid retained image occurrence'),
    (lambda st: st['occurrences'][0].__setitem__(1, -1), (), 'Invalid retained image occurrence'),
    (lambda st: st['occurrences'][0].__setitem__(1, '0'), (), 'Invalid retained image occurrence'),
    (lambda st: None, (('', 'handler'),), 'Invalid recovered image lease identity'),
    (lambda st: None, ((3, 'handler'),), 'Invalid recovered image lease identity'),
    (lambda st: None, (('dup', 'handler'), ('dup', 'image-observation')), 'Invalid recovered image lease identity'),
], ids=["generation", "ref-shape", "ref-type", "observation-extra-key", "observation-non-text", "occurrence-unknown-ref", "occurrence-negative", "occurrence-not-int",
        "lease-empty", "lease-not-text", "lease-duplicate"])
def test_a_damaged_retained_state_is_refused_by_name_and_the_files_stay(tmp_path, edit, leases, message):
    store, handle = damaged(tmp_path, edit)
    with pytest.raises(ImageUnavailable, match=message):
        store.restore_session(handle, recovered_leases=leases)
    assert any((tmp_path / 'private').rglob('img_*.json'))                           # nothing was deleted to make the refusal go away


def test_an_undamaged_state_restores_with_the_same_edit_machinery(tmp_path):
    """Control: the same damage harness with no damage restores - so the refusals above are the checks, not the harness."""
    store, handle = damaged(tmp_path, lambda st: None)
    restored = store.restore_session(handle, recovered_leases=(('a', 'handler'), ('b', 'image-observation')))
    assert restored.pending_leases == 2 and restored.pending_observations == 1
