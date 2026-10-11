"""K1 — H1 (a whole-file write to a file the coder has not SEEN is answered with the file) counted ANY recorded
read as seen. phi4 A4 CALL 0047: `pom.xml` lines 1-8 of 29 were read, then the whole file was overwritten
with an invented pom (the hold never fired). Only a WHOLE read whose text is in the conversation, or the
coder's own whole write, lifts the hold; a shell command lifts it only when it is a plain `cat` of the file.
"""
import json
from pathlib import Path

import pytest

from cria import loop, wsview
from cria.writeproxy import translate_outbound
from tests.test_loop import _single_loop, _synth
from tests.wsfixture import survey

FIX = json.loads((Path(__file__).parent / "fixtures" / "phi4_java_a4" / "0047-partial-read-then-write.json").read_text())
ROOT = "/home/jesse/suite-runs/suite-feed-pipeline-java_phi4_codex_poff_1791705464-r09m6ths"
_SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}


@pytest.fixture
def view():
    v = wsview.View(ROOT, "k1")
    assert wsview.apply_survey(v, survey("F\t1\t773\tpom.xml", root=ROOT, complete=True))
    token = wsview.bind(v)
    yield v
    wsview.unbind(token)


def _result(messages, reply=None, path="pom.xml"):
    reply = json.loads(json.dumps(reply or FIX["reply"]))
    sess = _synth()
    lp = _single_loop(lambda b, r: b"{}", workspace_root=ROOT)
    lp._store.put("k1", sess)
    translate_outbound(reply, _SHELL, injected={"write_file"}, workspace_root=ROOT,
                       unread_target=lp.unread_target_check("k1", messages, ROOT))
    args = json.loads(reply["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    return args["cmd"]


def _read(start=None, end=None, body=None, rid="r1"):
    args = {"path": "pom.xml", **({"start_line": start} if start else {}), **({"end_line": end} if end else {})}
    return [{"role": "assistant", "tool_calls": [{"id": rid, "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps(args)}}]},
            {"role": "tool", "tool_call_id": rid, "content": body}]


def test_the_a4_prefix_read_does_not_lift_the_hold(view):
    """The real exchange: pom.xml lines 1-8 of 29, then the whole-file write the coder sent."""
    cmd = _result(FIX["read_exchange"])
    assert "write_bytes" not in cmd and "already exists on disk" in cmd


def test_a_whole_read_lifts_it(view):
    assert "write_bytes" in _result(_read(body="<project>\n</project>"))


def test_a_window_that_runs_into_the_end_of_the_file_is_the_whole_file(view):
    body = "\n".join(f"{i}: l{i}" for i in range(1, 6))
    assert "write_bytes" in _result(_read(1, 50, body))      # asked for 50, got 5: EOF reached
    assert "write_bytes" in _result(_read(1, None, body))    # start_line=1 alone reads to the end


def test_a_window_that_stops_where_it_was_told_to_is_not(view):
    body = "\n".join(f"{i}: l{i}" for i in range(1, 9))
    assert "write_bytes" not in _result(_read(1, 8, body))
    assert "write_bytes" not in _result(_read(5, 50, "5: a\n6: b"))     # does not open at line 1
    assert "write_bytes" not in _result(_read(None, 8, body))          # an end-only range is a prefix


def test_a_ledger_entry_without_text_in_the_window_is_not_a_read(view):
    """seg-10: the durable ledger said `pom.xml` was read; the harness had compacted the text away."""
    sess = _synth()
    sess.read_files = {f"{ROOT}/pom.xml": (773, "29 lines")}
    lp = _single_loop(lambda b, r: b"{}", workspace_root=ROOT)
    lp._store.put("k1", sess)
    assert "already exists" in lp.unread_target_check("k1", [], ROOT)("pom.xml")


def test_the_coders_own_whole_write_is_seen_even_after_compaction(view):
    sess = _synth()
    sess.written_files = {"pom.xml": (100, "5 lines")}
    lp = _single_loop(lambda b, r: b"{}", workspace_root=ROOT)
    lp._store.put("k1", sess)
    assert lp.unread_target_check("k1", [], ROOT)("pom.xml") == ""


@pytest.mark.parametrize("command,whole", [
    ("cat pom.xml", True), ("cat -n ./pom.xml", True), (f"cat {ROOT}/pom.xml", True),
    ("mvn -q compile && cat pom.xml", True), ("bash -lc 'cat pom.xml'", True),
    ("head -8 pom.xml", False), ("sed -n 1,8p pom.xml", False), ("cat pom.xml | head", False),
    ("grep -n artifactId pom.xml", False), ("cat pom.xml > /tmp/p", False), ("cd sub && cat pom.xml", False),
    ("cat pom.xml.bak", False), ("cat 'unterminated pom.xml", False),
])
def test_only_a_plain_cat_of_the_file_is_a_shell_read(command, whole):
    assert loop._prints_whole_file(command, "pom.xml") is whole


def test_extract_whole_reads_ignores_refused_and_empty_results():
    from cria import denial
    assert loop._extract_whole_reads(_read(body=denial.mark("too large"))) == set()
    assert loop._extract_whole_reads(_read(body="  ")) == set()
