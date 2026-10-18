"""K1 — H1 (a whole-file write to a file the coder has not SEEN is answered with the file) counted ANY recorded
read as seen. phi4 A4 CALL 0047: `pom.xml` lines 1-8 of 29 were read, then the whole file was overwritten
with an invented pom (the hold never fired). Only a WHOLE read whose text is in the conversation, or the
coder's own whole write, lifts the hold; a shell command lifts it only when it is a plain `cat` of the file.
"""
import json
import subprocess
from pathlib import Path

import pytest

from cria import loop, wsview
from cria.writeproxy import translate_outbound
from tests.test_loop import _single_loop, _synth
from tests.wsfixture import survey
from tests.lowering_assertions import write_did_run

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
    assert not write_did_run(cmd) and "already exists on disk" in cmd


def test_a_whole_read_lifts_it(view):
    assert write_did_run(_result(_read(body="<project>\n</project>")))


def test_a_window_that_runs_into_the_end_of_the_file_is_the_whole_file(view):
    body = "\n".join(f"{i}: l{i}" for i in range(1, 6))
    assert write_did_run(_result(_read(1, 50, body)))      # asked for 50, got 5: EOF reached
    assert write_did_run(_result(_read(1, None, body)))    # start_line=1 alone reads to the end


def test_a_window_that_stops_where_it_was_told_to_is_not(view):
    body = "\n".join(f"{i}: l{i}" for i in range(1, 9))
    assert not write_did_run(_result(_read(1, 8, body)))
    assert not write_did_run(_result(_read(5, 50, "5: a\n6: b")))     # does not open at line 1
    assert not write_did_run(_result(_read(None, 8, body)))          # an end-only range is a prefix


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
    # a path that merely ENDS in the name is another file
    ("cat sub/pom.xml", False), ("cat ../other/pom.xml", False), ("cat /tmp/pom.xml", False),
    (f"cat {ROOT}/sub/pom.xml", False), ("cat ./sub/../pom.xml", False),
])
def test_only_a_plain_cat_of_the_file_is_a_shell_read(command, whole, view):
    assert loop._prints_whole_file(command, "pom.xml", view) is whole


def test_without_a_view_only_the_relative_spellings_are_the_file():
    assert loop._prints_whole_file("cat pom.xml", "pom.xml") and loop._prints_whole_file("cat ./pom.xml", "pom.xml")
    assert not loop._prints_whole_file(f"cat {ROOT}/pom.xml", "pom.xml")


def test_a_cat_of_another_directorys_pom_does_not_lift_the_hold(view):
    for command in ("cat sub/pom.xml", "cat ../other/pom.xml", "cat /tmp/pom.xml"):
        msgs = [{"role": "assistant", "tool_calls": [{"id": "s1", "type": "function", "function": {
                    "name": "exec_command", "arguments": json.dumps({"cmd": command})}}]},
                {"role": "tool", "tool_call_id": "s1", "content": "<project/>"}]
        assert not write_did_run(_result(msgs)), command


def test_extract_whole_reads_ignores_refused_and_empty_results():
    from cria import denial
    assert loop._extract_whole_reads(_read(body=denial.mark("too large"))) == set()
    assert loop._extract_whole_reads(_read(body="  ")) == set()


# ── a file over one read's byte limit can only be read in ranges ────────────────────────────────

def _big_file(tmp_path, lines=200):
    from cria import writeproxy
    body = "".join(f"line {i:03d} " + "x" * 80 + "\n" for i in range(1, lines + 1))
    assert len(body) > writeproxy.READ_INLINE_MAX * 1.5
    (tmp_path / "Big.java").write_text(body)
    return len(body)


def _run_read(tmp_path, **args):
    """The REAL lowered read command, run in a shell — its output is what the coder's result holds."""
    from cria import writeproxy
    out = subprocess.run(["bash", "-c", writeproxy._read_command({"path": "Big.java", **args})],
                         cwd=tmp_path, capture_output=True, text=True)
    return out.stdout + out.stderr


def _exchange(tmp_path, n, **args):
    return [{"role": "assistant", "tool_calls": [{"id": f"b{n}", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": "Big.java", **args})}}]},
            {"role": "tool", "tool_call_id": f"b{n}", "content": _run_read(tmp_path, **args)}]


def _big_view(size):
    v = wsview.View(ROOT, "k1-big")
    assert wsview.apply_survey(v, survey(f"F\t1\t{size}\tBig.java", root=ROOT, complete=True))
    return v


def _held(view, messages):
    sess = _synth()
    lp = _single_loop(lambda b, r: b"{}", workspace_root=ROOT)
    lp._store.put("k1", sess)
    return lp.unread_target_check("k1", messages, ROOT)("Big.java")


def test_a_big_file_read_in_ranges_to_the_end_is_read(tmp_path):
    """Reviewer repro: a 200-line file over the byte limit; the whole read is refused ("N lines … read a line
    range"), then 1-90, 91-180, 181-200 — every window REAL output of the lowered command."""
    size = _big_file(tmp_path)
    view = _big_view(size)
    token = wsview.bind(view)
    try:
        refused = _exchange(tmp_path, 0)
        assert "200 lines" in refused[1]["content"]                       # the real refusal
        assert _held(view, refused)                                       # a refused read is not a read
        wins = [m for n, (a, b) in enumerate([(1, 90), (91, 180)], 1)
                for m in _exchange(tmp_path, n, start_line=a, end_line=b)]
        assert _held(view, refused + wins)                                # 1-180 of 200: not yet
        last = _exchange(tmp_path, 3, start_line=181, end_line=200)
        assert _held(view, wins + last) != ""                             # no refusal in view, end unknown…
        assert _held(view, refused + wins + last) == ""                   # …with it, 1..200 covers the file
    finally:
        wsview.unbind(token)


def test_a_window_that_runs_short_of_its_request_proves_the_end(tmp_path):
    view = _big_view(_big_file(tmp_path))
    token = wsview.bind(view)
    try:
        msgs = [m for n, (a, b) in enumerate([(1, 90), (91, 180), (181, 250)], 1)
                for m in _exchange(tmp_path, n, start_line=a, end_line=b)]
        assert _held(view, msgs) == ""
    finally:
        wsview.unbind(token)


def test_a_gap_or_a_missing_start_leaves_the_hold(tmp_path):
    view = _big_view(_big_file(tmp_path))
    token = wsview.bind(view)
    try:
        gap = [m for n, (a, b) in enumerate([(1, 90), (100, 250)], 1)
               for m in _exchange(tmp_path, n, start_line=a, end_line=b)]
        assert _held(view, gap)
        no_start = [m for n, (a, b) in enumerate([(5, 100), (101, 250)], 1)
                    for m in _exchange(tmp_path, n, start_line=a, end_line=b)]
        assert _held(view, no_start)
    finally:
        wsview.unbind(token)


def test_the_fact_does_not_say_a_range_is_no_read_while_the_steer_says_to_read_a_range():
    from cria import prompts
    text = prompts.load_map("unread_target_fact")["sized"]
    assert "line ranges that together run from line 1 to the end" in text
    assert "a line range, " not in text and "the coder has not" not in text
