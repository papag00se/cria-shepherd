"""Scenario: the returned-history notes (dependency surface, missing dependency, empty dependency-source search) and the rejected-draft
collapse, driven with a recording event log: each arm that stays silent, each arm that writes one note and the event it emits, and the
session state a request leaves behind (anchor, abstain countdown, withheld pointer)."""
import json
import stat

import pytest

from cria import depsurface as ds, returnedpolicies as rp
from cria.toolcontracts import ReturnedHistory
from research_discovery_helpers import disk_view, write  # noqa: F401

pytestmark = pytest.mark.usefixtures("disk_view")
EMPTY = "Chunk ID: abc\nProcess exited with code 1\nOutput:\n"
MOD, VER = "github.com/acme/alpha", "v1.0.0"


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [k for k, _ in self.events]


def tool(cid, content="ok"):
    return {"role": "tool", "tool_call_id": cid, "content": content}


def history(msgs, ws, own=None, session="cov5-s", log=None, window=None):
    return ReturnedHistory(msgs, own or {}, str(ws) if ws else None, session, True, log, window)


@pytest.fixture
def go_world(tmp_path, monkeypatch):
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    write(home, f"go/pkg/mod/{MOD}@{VER}/p.go", "package p\n")
    doc = bin_dir / "go"
    doc.write_text("#!/bin/sh\ncat " + str(tmp_path / "doc.txt") + "\n")
    doc.chmod(0o755 | stat.S_IEXEC)
    ws = tmp_path / "ws"
    write(ws, "go.mod", f"module app\nrequire {MOD} {VER}\n")
    (tmp_path / "doc.txt").write_text("package p\n\nTYPES\n\n" + "".join(f"func Member{i:03d}(a int) error\n" for i in range(5)))
    return ws, tmp_path / "doc.txt"


def test_a_dependency_surface_request_walks_every_arm_and_logs_what_it_did(go_world):
    ws, doc = go_world
    key = ("go", MOD, VER)
    log = Log()
    only_user = [{"role": "user", "content": "go"}, {"role": "assistant", "content": "hi"}]
    rp._note_dependency_surface(history(only_user, ws, log=log))      # no tool result at all: nothing to anchor to
    no_id = [tool(None, "ok")]
    no_id[0].pop("tool_call_id")
    rp._note_dependency_surface(history(no_id, ws, log=log))          # a result without a stable id is never anchored to
    assert only_user[-1] == {"role": "assistant", "content": "hi"} and no_id[0]["content"] == "ok" and not log.events
    assert ds.anchor_state("cov5-s", key) is None and not ds.is_withheld("cov5-s", key)

    doc.write_text("")                                                 # the real tool printed nothing: abstain for a while, silently
    msgs = [tool("c1")]
    rp._note_dependency_surface(history(msgs, ws, log=log))
    assert msgs[0]["content"] == "ok" and ds._ABSTAINED["cov5-s"][key] == ds._ABSTAIN_RETRY_EVERY and not log.events
    doc.write_text("package p\n\nTYPES\n\nfunc Member000(a int) error\n")
    rp._note_dependency_surface(history(msgs, ws, log=log))            # the countdown has not elapsed: not even re-gathered
    assert msgs[0]["content"] == "ok" and ds._ABSTAINED["cov5-s"][key] == ds._ABSTAIN_RETRY_EVERY - 1
    ds._ABSTAINED["cov5-s"][key] = 1
    rp._note_dependency_surface(history(msgs, ws, log=log))            # elapsed: gathered for real, anchored, abstain cleared
    assert "Member000(a int) error" in msgs[0]["content"] and key not in ds._ABSTAINED["cov5-s"]
    assert log.kinds() == ["writeproxy.dependency_surface"] and log.events[0][1]["members"] >= 1
    assert ds.anchor_state("cov5-s", key)[0] == "c1"

    compacted = [tool("c9")]                                           # the anchor's message is gone: one re-anchor, logged
    rp._note_dependency_surface(history(compacted, ws, log=log))
    assert "Member000(a int) error" in compacted[0]["content"] and log.kinds()[-1] == "writeproxy.dependency_surface_reanchored"
    assert ds.anchor_state("cov5-s", key)[0] == "c9"


def test_a_surface_that_does_not_fit_the_total_budget_is_withheld_with_a_log_and_an_anchored_note_that_does_not_fit_stops_the_pass(go_world, tmp_path):
    ws, doc = go_world
    doc.write_text("package p\n\nTYPES\n\n" + "".join(f"func Member{i:03d}(a int, b string) (Result{i}, error)\n" for i in range(55)))
    for name in ("beta", "gamma"):
        write(tmp_path / "home", f"go/pkg/mod/github.com/acme/{name}@{VER}/p.go", "package p\n")
    write(ws, "go.mod", "module app\n" + "".join(f"require github.com/acme/{n} {VER}\n" for n in ("alpha", "beta", "gamma")))
    log = Log()
    msgs = [tool("c1")]
    rp._note_dependency_surface(history(msgs, ws, session="cov5-w", log=log, window=8192))
    assert ds.is_withheld("cov5-w", ("go", "github.com/acme/gamma", VER)) and "writeproxy.dependency_surface_withheld_new" in log.kinds()
    assert "will NOT appear automatically" in msgs[0]["content"]
    ds.set_anchor_state("cov5-w2", ("go", MOD, VER), "c1", "X" * 40_000)          # an anchored note larger than the whole budget
    big = [tool("c1")]
    rp._note_dependency_surface(history(big, ws, session="cov5-w2", log=log, window=8192))
    assert "XXXX" not in big[0]["content"] and "github.com/acme/beta" in big[0]["content"]   # the oversize anchor is skipped, a new coordinate still lands


def test_the_inline_budget_defaults_to_the_reference_and_a_first_line_longer_than_it_is_still_shown():
    long = "func B(" + "x int, " * 40 + ") int"
    surface = ds.DependencySurface("go", "x/p v1", "/root", ("p.go",), ("func A() int", long), "read_file /root", False)
    default = rp._render_dependency_surface(surface, "go")                   # no budget given: the reference one, everything fits
    assert "func A() int" in default and long in default and "THE VERSION OF x/p v1 DECLARED IN go.mod" in default
    tiny = rp._render_dependency_surface(surface, "go", 5)                    # nothing fits: the first real line is still shown, never nothing
    assert "func A() int" in tiny and long not in tiny and "read_file /root" in tiny


def test_a_rejected_draft_loses_only_its_big_payload_and_says_so_in_the_log_and_odd_arguments_are_left_alone():
    big = "x" * 500
    call = {"id": "c1", "function": {"name": "write_file", "arguments": json.dumps({"path": "a.py", "content": big, "mode": "w"})}}
    log = Log()
    draft = rp.preserve_rejected_draft(call, "a.py", log)
    assert json.loads(draft.call["function"]["arguments"]) == {"path": "a.py", "mode": "w"} and big in draft.note and "a.py" in draft.note
    assert log.events == [("writeproxy.rejected_payload_dropped", {"level": "info", "path": "a.py", "keys": ["content"], "chars": 500})]
    small = {"id": "c2", "function": {"name": "write_file", "arguments": json.dumps({"content": "tiny"})}}
    assert rp.preserve_rejected_draft(small, "a.py", log).call is small
    for args in ("[1, 2]", "not json", None):
        odd = {"id": "c3", "function": {"name": "write_file", "arguments": args}}
        kept = rp.preserve_rejected_draft(odd, "a.py", log)
        assert kept.call is odd and kept.note == ""
    assert len(log.events) == 1


def test_a_missing_dependency_note_goes_on_the_newest_result_once_is_logged_and_defers_to_the_gate_and_the_projects_own_file(tmp_path):
    ws, log = tmp_path / "ws", Log()
    write(ws, "requirements.txt", "")
    write(ws, "localmod.py", "")
    err = lambda name: f"Traceback\nModuleNotFoundError: No module named '{name}'"  # noqa: E731
    msgs = [tool("a", err("requests")), tool("b", "all fine"), tool("c", err("requests"))]
    rp._note_missing_dependency(history(msgs, ws, log=log))
    assert msgs[0]["content"] == err("requests") and msgs[1]["content"] == "all fine"       # only the LAST occurrence is annotated
    assert msgs[2]["content"].startswith(err("requests")) and "requests" in msgs[2]["content"][len(err("requests")):]
    assert log.events == [("writeproxy.dependency_note", {"level": "info", "ecosystem": "python", "name": "requests"})]
    again = msgs[2]["content"]
    rp._note_missing_dependency(history(msgs, ws, log=log))                                     # the same note is never stacked
    assert msgs[2]["content"] == again and len(log.events) == 1
    own, gated, quiet = [tool("a", err("localmod"))], [tool("a", "___CTX_GATE_x\n" + err("requests"))], [tool("a", "fine")]
    before = gated[0]["content"]
    for case in (own, gated, quiet):                                                            # own module / gate result / nothing missing: silent
        rp._note_missing_dependency(history(case, ws, log=log))
    assert own[0]["content"] == err("localmod") and gated[0]["content"] == before and quiet[0]["content"] == "fine" and len(log.events) == 1


def test_an_empty_dependency_source_search_is_answered_once_with_a_log_and_other_shapes_leave_the_result_alone(tmp_path, monkeypatch):
    home, ws, log = tmp_path / "home", tmp_path / "ws", Log()
    monkeypatch.setenv("HOME", str(home))
    (home / ".cargo/registry/src").mkdir(parents=True)
    write(ws, "Cargo.toml", "[package]\nname='x'\n")
    find = f"find {ws}/.cargo/registry/src -name value.rs"
    rp._note_dependency_search(history([], ws, log=log))                                        # no messages at all
    msgs = [{"role": "user", "content": "go"}, tool("a", EMPTY), tool("b", EMPTY)]
    msgs[1]["content"] = 7                                                                      # a non-text result is skipped, not parsed
    rp._note_dependency_search(history(msgs, ws, own={"a": find, "b": find}, log=log))
    assert msgs[1]["content"] == 7 and msgs[2]["content"].startswith(EMPTY) and str(home / ".cargo/registry/src") in msgs[2]["content"]
    assert log.events == [("writeproxy.dependency_source_note", {"level": "info", "ecosystem": "rust", "root": str(home / ".cargo/registry/src"), "searched": f"{ws}/.cargo/registry/src"})]
    done = msgs[2]["content"]
    rp._note_dependency_search(history(msgs, ws, own={"a": find, "b": find}, log=log))
    assert msgs[2]["content"] == done and len(log.events) == 1                                  # never stacked
