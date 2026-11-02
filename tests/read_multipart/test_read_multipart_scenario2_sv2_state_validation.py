"""Persisted multipart state is trusted only after it validates: one real saved session, then one field at a time corrupted on disk. Every corruption is a BridgeError
('corrupt'/'unreadable'/'not private') on reload - never a half-restored session that could execute or credit a read - while the pristine file still restores."""
import json

import pytest

from cria.multipart_bridge import Bridge, BridgeError
from read_multipart_helpers import HEX, isolated_home, start  # noqa: F401


def entry(o):
    return o["entries"][0]



def setter(*keys, value):
    def edit(o):
        node = o
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = value
    return edit


def delete(*keys):
    def edit(o):
        node = o
        for key in keys[:-1]:
            node = node[key]
        del node[keys[-1]]
    return edit


ROWS = {
    "version": setter("v", value=2),
    "version-bool": setter("v", value=True),
    "other-session": setter("session", value="someone-else"),
    "extra-top-key": setter("extra", value=1),
    "entries-not-list": setter("entries", value={}),
    "entry-missing-key": delete("entries", 0, "settled"),
    "entry-extra-key": setter("entries", 0, "surprise", value=1),
    "shell-not-dict": setter("entries", 0, "shell", value="sh"),
    "pending-not-str": setter("entries", 0, "pending", value=5),
    "received-value-not-str": setter("entries", 0, "received", value={"original": 5}),
    "private-not-list": setter("entries", 0, "private", value="x"),
    "private-duplicates": setter("entries", 0, "private", value=["a", "a"]),
    "spec-read-instead-int": setter("entries", 0, "spec", "read_instead", value=1),
    "spec-path-not-str": setter("entries", 0, "spec", "path", value=7),
    "spec-token-changed": setter("entries", 0, "spec", "token", value="0" * 32),
    "spec-unknown-field": setter("entries", 0, "spec", "mystery", value=1),
    "original-id-mismatch": setter("entries", 0, "original", "id", value="other"),
    "offered-not-bool": setter("entries", 0, "offered", value="yes"),
    "settled-not-bool": setter("entries", 0, "settled", value=1),
    "fallback-kind-unknown": setter("entries", 0, "fallback_kind", value="bogus"),
    "fallback-without-result": setter("entries", 0, "fallback_kind", value="unknown"),
    "failure-kind-without-id": setter("entries", 0, "failure_kind", value="cut"),
    "failure-id-not-received": setter("entries", 0, "failure_id", value="ghost"),
    "pending-not-a-call": setter("entries", 0, "pending", value="ghost"),
    "first-call-not-logical": setter("entries", 0, "calls", value={"other": {"id": "other"}}),
    "private-mismatch": setter("entries", 0, "private", value=["ghost"]),
    "call-command-edited": setter("entries", 0, "calls", "original", "function", "arguments", value=json.dumps({"cmd": "touch stolen"})),
    "duplicate-logical-call": lambda o: o["entries"].append(json.loads(json.dumps(o["entries"][0]))),
    "cache-not-dict": setter("cache", value="x"),
    "cache-extra-key": setter("cache", value={"fingerprint": "00" * 32, "x": 1}),
    "cache-short-fingerprint": setter("cache", value={"fingerprint": "00" * 8}),
    "cache-not-hex": setter("cache", value={"fingerprint": "zz" * 32}),
    "initial-not-dict": setter("initial", value=[]),
    "initial-empty-calls": setter("initial", value={"fingerprint": "00" * 32, "calls": []}),
    "initial-foreign-call": setter("initial", value={"fingerprint": "00" * 32, "calls": [{"id": "ghost"}]}),
    "initial-short-fingerprint": setter("initial", value={"fingerprint": "00", "calls": [{"id": "original"}]}),
}


ENDS_THE_READ_UNVERIFIED = {"spec-token-changed"}


@pytest.mark.parametrize("name", sorted(ROWS))
def test_every_single_field_corruption_of_saved_state_is_refused_on_reload(tmp_path, name):
    """Saved state is re-derived, not believed: each corrupted field raises BridgeError and nothing is restored; the same file, uncorrupted, restores and replays the identical call."""
    storage = str(tmp_path / "state")
    bridge, messages, _ = start(tmp_path, HEX, storage=storage)
    first = bridge.incoming("s", messages)
    state = next((tmp_path / "state").glob("*.json"))
    good = state.read_text()
    obj = json.loads(good)
    ROWS[name](obj)
    state.write_text(json.dumps(obj))
    if name in ENDS_THE_READ_UNVERIFIED:
        # Not the file's structure: this one read's pages do not take under the stored token, so it ends unverified and the
        # session lives.
        calls = Bridge(storage).incoming("s", messages)[1]
        assert calls == []
        assert Bridge(storage).continuation_state("s").pending == ()
    else:
        # An edited stored call is refused outright (corrupt on reload, or no longer the call the history holds); it is never handed out.
        with pytest.raises(BridgeError, match="multipart session state is (corrupt|unreadable)|changed known call"):
            Bridge(storage).incoming("s", messages)
    state.write_text(good)
    assert Bridge(storage).incoming("s", messages)[1] == first[1]


def test_unreadable_roots_and_files_are_refused_not_ignored(tmp_path):
    """Invalid UTF-8, a directory where the state file should be, a world-writable file and a missing session each get the right outcome: errors for the first three, an empty fresh session for the last."""
    storage = tmp_path / "state"
    bridge, messages, _ = start(tmp_path, HEX, storage=str(storage))
    bridge.incoming("s", messages)
    state = next(storage.glob("*.json"))
    good = state.read_bytes()
    state.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(BridgeError, match="unreadable"):
        Bridge(str(storage)).incoming("s", messages)
    state.unlink()
    state.mkdir()
    with pytest.raises(BridgeError):
        Bridge(str(storage)).incoming("s", messages)
    state.rmdir()
    state.write_bytes(good)
    state.chmod(0o666)
    with pytest.raises(BridgeError, match="not private"):
        Bridge(str(storage)).incoming("s", messages)
    assert Bridge(str(tmp_path / "fresh")).continuation_state("never-seen").pending == ()
