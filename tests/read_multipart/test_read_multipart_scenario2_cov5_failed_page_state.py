"""Scenario: a continuation page came back failed (still running / exited non-zero / no status / not a result at all) and the bridge saved that. On reload every failure kind must
still be PROVEN by the saved page bytes: change the bytes or the kind so the page no longer declares what the state claims and the session is refused as corrupt - a failed
page is never silently re-read as a good one - while the pristine state restores to the same continuation."""
import json

import pytest

from cria.multipart_bridge import Bridge, BridgeError
from read_multipart_helpers import HEX, isolated_home, start  # noqa: F401

PAGES = {
    "running": "Wall time: 0.1 seconds\nProcess running with session ID 7\nOutput:\n",
    "nonzero": "Chunk ID: a\nWall time: 0.1 seconds\nProcess exited with code 3\nOutput:\nboom",
    "unknown": "Chunk ID: a\nWall time: 0.1 seconds\nOutput:\nxx",
    "nonzero1": "Chunk ID: a\nWall time: 0.1 seconds\nProcess exited with code 1\nOutput:\nboom",         # exit 1 is the most common failure there is
    "cut": "Wall time: 0.1 seconds\nProcess exited with code 0\nOutput:\nWarning: truncated output\nno record survived\n",   # asked again until the re-fetches run out
}
CLEAN_EXIT = "Chunk ID: a\nWall time: 0.1 seconds\nProcess exited with code 0\nOutput:\nnot a page"


def failed_state(tmp_path, kind):
    storage = str(tmp_path / "state")
    bridge, messages, _ = start(tmp_path, HEX, storage=storage)
    history = list(messages)
    _, calls, _ = bridge.incoming("s", history)
    while True:       # every kind fails on the first answer except a cut one, which the bridge asks for again until its re-fetches are used up
        history += [{"role": "assistant", "tool_calls": calls}, {"role": "tool", "tool_call_id": calls[0]["id"], "content": PAGES[kind]}]
        out = bridge.incoming("s", history)
        if not out[1]:
            return storage, history, next((tmp_path / "state").glob("*.json")), out
        calls = out[1]


@pytest.mark.parametrize("kind, edit", [
    ("running", lambda e, cid: e["received"].update({cid: CLEAN_EXIT})),                        # the page no longer says it is still running
    ("nonzero", lambda e, cid: e["received"].update({cid: CLEAN_EXIT})),                        # ... no longer exits non-zero
    ("nonzero", lambda e, cid: e.update(failure_code=4)),                                       # ... exits with a different code than the state claims
    ("unknown", lambda e, cid: e["received"].update({cid: PAGES["nonzero"]})),                  # ... now has an exit code, so "no status" is false
    ("unknown", lambda e, cid: e["received"].update({cid: PAGES["running"]})),
    ("running", lambda e, cid: e.update(failure_kind="binary")),                                # a binary verdict needs a completed, verified body
    ("nonzero", lambda e, cid: e["received"].update({cid: PAGES["running"]})),                  # ... is now still running
    ("nonzero", lambda e, cid: (e["received"].update({cid: CLEAN_EXIT}), e.update(failure_code=0))),   # a clean exit is never a non-zero failure, even when the state agrees with it
    ("cut", lambda e, cid: e["received"].update({cid: CLEAN_EXIT})),                            # the page no longer says the harness cut it
    ("cut", lambda e, cid: e["received"].update({cid: PAGES["running"]})),
    ("running", lambda e, cid: e.update(pending="original")),                                   # the failed page must be the pending, last one
], ids=["running-bytes-edited", "nonzero-bytes-edited", "nonzero-code-edited", "unknown-gains-exit-code", "unknown-becomes-running", "kind-claims-binary",
        "nonzero-becomes-running", "nonzero-clean-exit-code-zero", "cut-bytes-edited", "cut-becomes-running", "failed-page-not-pending"])
def test_a_saved_failed_page_must_still_declare_its_failure_or_the_session_is_refused(tmp_path, kind, edit):
    storage, history, state, first = failed_state(tmp_path, kind)
    good = state.read_text()
    obj = json.loads(good)
    entry = obj["entries"][0]
    edit(entry, entry["failure_id"])
    state.write_text(json.dumps(obj))
    with pytest.raises(BridgeError, match="multipart session state is (corrupt|unreadable)"):
        Bridge(storage).incoming("s", history)
    state.write_text(good)
    assert Bridge(storage).incoming("s", history) == first                                      # control: the same state, unedited, restores to the identical projection


@pytest.mark.parametrize("kind", sorted(PAGES))
def test_every_failed_page_kind_restores_to_the_same_continuation(tmp_path, kind):
    """Exit code 1 and a cut result are failures too: the saved state must reload (a validator that only accepted code 3 would strand the session)."""
    storage, history, _, first = failed_state(tmp_path, kind)
    assert Bridge(storage).incoming("s", history) == first
