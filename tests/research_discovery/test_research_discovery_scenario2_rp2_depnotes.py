"""Scenario: declared Go dependencies resolved in the module cache are surfaced onto the newest tool result with the real `go doc`
(a stand-in executable on PATH, counting its own launches): what fits the window-sized budget is anchored, what does not is
WITHHELD for the session with a pointer and never re-gathered, a compacted history re-anchors the same text, and a version bump
or removal stops being named."""
import stat

import pytest

from cria import depsurface as ds, returnedpolicies as rp
from cria.toolcontracts import ReturnedHistory
from research_discovery_helpers import disk_view, write  # noqa: F401

pytestmark = pytest.mark.usefixtures("disk_view")
DOC = "package p // import \"x/p\"\n\nTYPES\n\n" + "".join(f"func Member{i:03d}(a int, b string) (Result{i}, error)\n" for i in range(55))
MODS = {"github.com/acme/alpha": "v1.0.0", "github.com/acme/beta": "v2.1.0", "github.com/acme/gamma": "v0.3.0", "github.com/acme/delta": "v1.1.1"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    for mod, ver in MODS.items():
        write(home, f"go/pkg/mod/{mod}@{ver}/p.go", "package p\n\nfunc Member000() {}\n")
    (bin_dir / "go").write_text(f"#!/bin/sh\necho run >> {tmp_path}/go-launches\ncat <<'EOF'\n{DOC}EOF\n")
    (bin_dir / "go").chmod(0o755 | stat.S_IEXEC)
    ws = tmp_path / "ws"
    manifest = lambda mods: write(ws, "go.mod", "module app\n" + "".join(f"require {m} {v}\n" for m, v in mods.items()))    # noqa: E731
    manifest({m: MODS[m] for m in list(MODS)[:3]})
    return ws, manifest, lambda: len((tmp_path / "go-launches").read_text().split()) if (tmp_path / "go-launches").exists() else 0


def request(ws, last_id, session="dep-s", **kw):
    msgs = [{"role": "user", "content": "go"}, {"role": "assistant", "content": None, "tool_calls": [{"id": last_id, "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": last_id, "content": "ok"}]
    rp._note_dependency_surface(ReturnedHistory(msgs, {}, str(ws), session, kw.pop("tools", True), None, kw.pop("window", 8192)))
    return msgs[-1]["content"]


def test_what_fits_is_anchored_what_does_not_is_withheld_for_good_and_a_compaction_reanchors_the_same_text(world):
    ws, manifest, launches = world
    first = request(ws, "c1")
    assert launches() == 3
    alpha, beta, gamma = ("github.com/acme/" + n for n in ("alpha", "beta", "gamma"))
    assert alpha in first and beta in first and "Member000(a int, b string) (Result0, error)" in first
    assert ds.is_withheld("dep-s", ("go", gamma, "v0.3.0")) and "go doc -all github.com/acme/gamma@v0.3.0" in first and "will NOT appear automatically" in first
    again = request(ws, "c2")                                  # history compacted: the anchor id is gone, the SAME text moves to the newest result
    assert launches() == 3 and again.replace("c2", "c1") == first and ds.anchor_state("dep-s", ("go", alpha, "v1.0.0"))[0] == "c2"
    assert request(ws, "c3", session="other-s", tools=False) == "ok" and request(ws, "c3", session="") == "ok"        # no tools / no identity: abstain
    manifest({alpha: MODS[alpha], beta: "v9.9.9"})             # a bump and a removal: the stale surface and the stale pointer stop being named
    later = request(ws, "c4")
    assert alpha in later and beta not in later and gamma not in later and "will NOT appear" not in later
    assert launches() == 3                                     # the bumped coordinate is declared but not on disk yet: stat calls only, no launch
