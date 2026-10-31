"""Returned-history notes through writeproxy.represent_inbound, selected/deselected by the real runtime.

The dependency-source note was once written, tested and NEVER CALLED (rust-toml-cli x ternary-bonsai: two empty `find` runs under the workspace's
.cargo, then twenty calls guessing TOML syntax while the crate source sat under ~/.cargo/registry/src). These rows drive it from the
public wire entry against a real directory tree, so a note that reaches nothing fails here."""
import json

import pytest

from cria import assistruntime, depsurface, writeproxy, wsview
from research_discovery_helpers import surveyed, write

EMPTY = "Chunk ID: abc\nWall time: 0.1 seconds\nProcess exited with code 1\nOutput:\n"
FOUND = "Chunk ID: abc\nProcess exited with code 0\nOutput:\n/w/vendor/bundle/gems/x/lib/x.rb\n"


@pytest.fixture
def rust_ws(tmp_path, monkeypatch):
    """A Cargo workspace whose crate cache lives under HOME, bound to the real disk."""
    home, ws = tmp_path / "home", tmp_path / "ws"
    monkeypatch.setenv("HOME", str(home))
    (home / ".cargo/registry/src").mkdir(parents=True)
    write(ws, "Cargo.toml", "[package]\nname='x'\n")
    token = wsview.bind(wsview.DirectView())
    yield ws, home
    wsview.unbind(token)


def results(ws, *runs, off=()):
    msgs = []
    for i, (cmd, out) in enumerate(runs):
        msgs += [{"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}", "type": "function", "function": {
                    "name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]},
                 {"role": "tool", "tool_call_id": f"c{i}", "content": out}]
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, disabled=off)):
        return [m["content"] for m in writeproxy.represent_inbound(msgs, None, str(ws)) if m["role"] == "tool"]


def test_an_empty_search_of_the_workspaces_package_cache_is_answered_with_the_real_root_only_where_it_applies(rust_ws):
    ws, home = rust_ws
    wrong = f"find {ws}/.cargo/registry/src -name value.rs"
    note, = results(ws, (wrong, EMPTY))
    assert "you looked in the wrong root" in note and str(home / ".cargo/registry/src") in note
    for cmd, out in [("find /w/vendor/bundle -name x.rb", FOUND),            # it found something: nothing to answer
                     (f"find {home}/.cargo/registry/src/toml-0.5.0 -name value.rs", EMPTY),   # already INSIDE the real root: the note would be false
                     ("find ~/.cargo/registry/src -name value.rs", EMPTY),    # already in the home root: noise
                     ("cargo build", EMPTY)]:                                 # not a search for dependency source
        got, = results(ws, (cmd, out))
        assert "wrong root" not in got and got.endswith(out), cmd
    first, second, last = results(ws, *[(wrong.replace("value", f"a{i}"), EMPTY) for i in range(3)])
    assert "wrong root" not in first + second and "wrong root" in last      # only the LAST empty search is annotated


def test_with_no_source_root_on_the_machine_it_says_so_instead_of_inventing_one(rust_ws):
    ws, home = rust_ws
    (home / ".cargo/registry/src").rmdir()
    note, = results(ws, (f"find {ws}/.cargo/registry/src -name value.rs", EMPTY))
    assert "no installed source root can be found" in note and "Search there instead" not in note


def test_a_question_the_harness_has_not_answered_is_not_answered_with_a_false_no_root():
    """shipping-rates-rb: 14 notes said 'no installed source root can be found' from a ~ directory cria had never asked about."""
    token = wsview.bind(surveyed("/work", ["F\t0\t1\tCargo.toml"]))
    try:
        got, = results("/work", ("find /work/.cargo/registry/src -name value.rs", EMPTY))
    finally:
        wsview.unbind(token)
    assert got == EMPTY


def test_a_deselected_dependency_source_note_leaves_the_tools_bytes_alone(rust_ws):
    ws, _ = rust_ws
    out, = results(ws, (f"find {ws}/.cargo/registry/src -name value.rs", EMPTY), off=("dependency-source-note",))
    assert out == EMPTY


def test_deselected_history_stages_touch_no_session_dependency_state(monkeypatch):
    """Dependency-API anchors and abstention counters are session history: a request run with the stage off must neither read declarations
    nor re-anchor, and the selected stage anchors the cached evidence without gathering again."""
    coordinate = ("go", "example.invalid/pkg", "v1")
    session = "arcc-anchor"
    anchors, counters = {session: {coordinate: ("old", "cached exact evidence")}}, {session: {coordinate: 7}}
    declared, gathered = [], []
    monkeypatch.setattr(depsurface, "_ANCHOR", anchors)
    monkeypatch.setattr(depsurface, "_ABSTAINED", counters)
    monkeypatch.setattr(depsurface, "declared_coordinates", lambda *a, **k: declared.append(a) or [coordinate])
    monkeypatch.setattr(depsurface, "gather", lambda *a, **k: gathered.append(a))
    monkeypatch.setattr(writeproxy.dirguard, "dependency_roots", lambda *a, **k: {})
    tool = lambda cid: [{"role": "tool", "tool_call_id": cid, "content": "payload"}]
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, disabled=("dependency-api-evidence",))):
        off = writeproxy.represent_inbound(tool("new"), workspace_root="/fake", sess_key=session)
    assert off == tool("new") and not declared
    assert anchors[session][coordinate] == ("old", "cached exact evidence") and counters[session][coordinate] == 7
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        on = writeproxy.represent_inbound(tool("new"), workspace_root="/fake", sess_key=session)
    assert on[0]["content"].endswith("cached exact evidence") and writeproxy.payload_of(on[0], on[0]["content"]) == "payload"
    assert anchors[session][coordinate] == ("new", "cached exact evidence") and not gathered
