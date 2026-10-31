"""A write over an unread file is answered with the file; a fragment that would gut a file is held with measured facts; a removal lands with facts."""
import json
from types import SimpleNamespace

import pytest

from cria import denial, loop, wsview
from write_edit_helpers import (call, do, shrink_services, surveyed_view, write_edit_workspace_view)  # noqa: F401

POM = "".join(f"<l{i}>{i}</l{i}>\n" for i in range(29))


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "pom.xml").write_text(POM)
    (tmp_path / "sub/pom.xml").write_text("<other/>\n")
    view = surveyed_view(tmp_path, ("pom.xml", len(POM)), ("sub/pom.xml", 9))
    token = wsview.bind(view)
    yield tmp_path
    wsview.unbind(token)


def unread(ws, messages=(), written=None, ledger_read=False):
    """The lowering's `unread_target` callback, built from the real fact owner over a session record."""
    sess = SimpleNamespace(read_files={"pom.xml": (len(POM), "29 lines")} if ledger_read else {}, written_files=written or {})
    return lambda path: loop.unread_target_fact(sess, wsview.current(str(ws)), path, list(messages))


def shell_ran(cmd, result=POM, cid="s1"):
    return [{"role": "assistant", "tool_calls": [call("exec_command", {"cmd": cmd}, cid)]},
            {"role": "tool", "tool_call_id": cid, "content": result}]


def read_of(ws, cid="r1", **args):
    return do("read_file", {"path": "pom.xml", **args}, ws, cid=cid, injected=("read_file",))[2]


def write_pom(ws, messages=(), **kw):
    """Is a whole write of pom.xml held (answered with the file) or did it land? ``(landed, shown messages, disk)``."""
    _, done, msgs = do("write_file", {"path": "pom.xml", "content": "<project/>\n"}, ws, cid="w",
                       unread_target=unread(ws, messages, **kw))
    return denial.landed(msgs[1]), msgs, (ws / "pom.xml").read_text()


def test_a_write_over_an_unread_existing_file_is_answered_with_the_file_and_counts_as_its_read(ws):
    """phi4 / Java A2+A3: pom.xml (never shown) was overwritten with placeholders seven times. The answer is a typed 'did not run' whose
    body IS the file; it is the coder's read of it (so the retry is not held), never a write of N bytes; any content is held, however spelled."""
    for content in ("<content_of_pom.xml_with_added_dependency>", "<project/>", "x" * 4000):
        _, done, msgs = do("write_file", {"path": "pom.xml", "content": content}, ws, unread_target=unread(ws))
        assert (ws / "pom.xml").read_text() == POM
        assert denial.refused(msgs[1]) and denial.read_payload(msgs[1]) == POM and msgs[1]["content"].endswith(POM)
        assert "pom.xml already exists on disk" in msgs[1]["content"] and "This write_file call was not run" in msgs[1]["content"]
    assert "pom.xml" in loop._extract_reads(msgs) and loop._extract_writes(msgs) == {}
    assert denial.unlanded_call_ids(msgs) == {"c1"}
    landed, _, disk = write_pom(ws, messages=msgs)                         # the answer lifted the hold
    assert landed and disk == "<project/>\n"


def test_the_hold_is_per_path_for_existing_surveyed_files_only(ws):
    """A new file is written; another existing file is held; an unsurveyed workspace says nothing (unknown is not 'exists')."""
    _, _, new = do("write_file", {"path": "REVIEW.md", "content": "n"}, ws, unread_target=unread(ws))
    assert denial.landed(new[1]) and (ws / "REVIEW.md").read_text() == "n"
    _, _, other = do("write_file", {"path": "sub/pom.xml", "content": "<n/>"}, ws, unread_target=unread(ws), cid="o")
    assert denial.refused(other[1]) and (ws / "sub/pom.xml").read_text() == "<other/>\n"
    token = wsview.bind(wsview.View(str(ws), "unsurveyed"))
    try:
        assert write_pom(ws)[0]
    finally:
        wsview.unbind(token)


# (id, how the coder looked at pom.xml, is the file now seen?)
LOOKS = [
    ("whole read", lambda ws: read_of(ws), True),
    ("a window that runs into EOF", lambda ws: read_of(ws, start_line=1, end_line=90), True),
    ("ranges 1-10 then 11-90 to EOF", lambda ws: read_of(ws, "r1", start_line=1, end_line=10) + read_of(ws, "r2", start_line=11, end_line=90), True),
    # phi4 A4 call 0047: lines 1-8 of 29 were read, then the whole file was overwritten with an invented pom
    ("prefix 1-8 of 29", lambda ws: read_of(ws, start_line=1, end_line=8), False),
    ("an end-only range", lambda ws: read_of(ws, end_line=8), False),
    ("a gap between ranges", lambda ws: read_of(ws, "r1", start_line=1, end_line=10) + read_of(ws, "r2", start_line=15, end_line=90), False),
    ("a plain cat", lambda ws: shell_ran("cat -n ./pom.xml && echo done"), True),
    ("head", lambda ws: shell_ran("head -8 pom.xml"), False),
    ("a pipe", lambda ws: shell_ran("cat pom.xml | head -5"), False),
    ("a redirect", lambda ws: shell_ran("cat pom.xml > /tmp/x"), False),
    ("a cat after cd", lambda ws: shell_ran("cd sub && cat pom.xml"), False),
    ("another file's name", lambda ws: shell_ran("cat sub/pom.xml") + shell_ran("cat pom.xml.bak", cid="s2"), False),
    ("a cat that printed nothing", lambda ws: shell_ran("cat pom.xml", result="  "), False),
]


@pytest.mark.parametrize("label,look,seen", LOOKS, ids=[x[0] for x in LOOKS])
def test_only_a_whole_text_in_the_conversation_lifts_the_hold(ws, label, look, seen):
    """K1: a partial/ranged/piped/other-path look, once counted as a read by merely NAMING the file, no longer lifts the hold."""
    assert write_pom(ws, look(ws))[0] is seen


def test_a_read_the_ledger_remembers_but_the_window_lost_is_not_the_text_while_the_coders_own_write_is(ws):
    """seg-10: the durable ledger said pom.xml was read, but the result was compacted away; the coder's own whole write persists."""
    assert write_pom(ws, ledger_read=True)[0] is False
    assert write_pom(ws, written={"pom.xml": (11, "1 lines")})[0] is True


# ── shrink protection ─────────────────────────────────────────────────────────────────────────────
FILE = "".join(f"block {i}:\n    value {i}\n" for i in range(8))          # 16 non-blank lines
FRAGMENT = "<dependencies/>\n"                                              # phi4 A4: a 190-char fragment replaced a whole pom
REMOVAL = "".join(f"new line {i}\n" for i in range(12))                      # phi4 A9: 69 of 114 lines rewritten, three methods gone


def shrink(ws, content, answer="OTHER", current=FILE, baseline=("f.txt",), tools=("write_file", "edit_file"), asked=None, disk=None):
    """Write ``content`` over f.txt: the survey measured ``current``, the disk holds ``disk`` (default the same)."""
    (ws / "f.txt").write_text(current if disk is None else disk)
    svc = shrink_services(current, answer, baseline, asked=asked)
    return do("write_file", {"path": "f.txt", "content": content}, ws, shrink_services=svc, injected=tools)


def test_a_fragment_that_would_gut_a_file_is_held_with_measured_facts_and_nothing_is_written(ws):
    """The held answer: typed did-not-run, the file's measured size, what the candidate keeps, the first removed line, and the edit tool only if on the menu."""
    asked = []
    _, done, msgs = shrink(ws, FRAGMENT, asked=asked)
    text = msgs[1]["content"]
    assert (ws / "f.txt").read_text() == FILE and done.returncode != 0 and denial.refused(msgs[1])
    assert "f.txt exists on disk: 168 bytes, 16 non-blank lines, 16 of them distinct" in text
    assert "repeats 0 of the file's 16 distinct non-blank lines" in text
    assert "This write_file call was not run, so nothing was written and the file is unchanged" in text
    assert "would remove at least 16 of the file's 16 non-blank lines, the first being line 1: `block 0:`" in text
    assert "`edit_file` is on this tool menu" in text and "cria" not in text.lower()
    assert len(asked) == 1 and FRAGMENT.strip() in asked[0] and "168 bytes" in asked[0]
    assert "edit_file" not in shrink(ws, FRAGMENT, tools=("write_file",))[2][1]["content"]


@pytest.mark.parametrize("answer,lands", [("WHOLE_FILE", True), ("whole_file: yes", True), ("OTHER", False), ("", False),
                                          ("WHOLE_FILE_MAYBE", False), ("I think WHOLE_FILE", False)])
def test_only_a_clear_whole_file_ruling_lets_a_fragment_through_and_only_that_is_cached(ws, answer, lands):
    """Undecidable judge = held (fail closed). An affirmative ruling lands and is asked ONCE; a hold is asked again on an identical repeat."""
    asked = []
    svc = shrink_services(FILE, answer, asked=asked)
    outcomes = []
    for n in range(2):
        (ws / "f.txt").write_text(FILE)
        outcomes.append(denial.landed(do("write_file", {"path": "f.txt", "content": FRAGMENT}, ws, cid=f"w{n}",
                                         shrink_services=svc)[2][1]))
    assert outcomes == [lands, lands] and len(asked) == (1 if lands else 2)


def test_a_removal_that_keeps_enough_lines_lands_and_the_facts_ride_on_the_result(ws):
    """A9: a rewrite removing >= half the lines is never asked; it lands and says what it removed. No baseline (file created by the
    coder) or a file that changed since measured: no facts, and the write is never refused on a stale view."""
    asked = []
    _, done, msgs = shrink(ws, REMOVAL, asked=asked)
    assert (ws / "f.txt").read_text() == REMOVAL and denial.landed(msgs[1]) and not asked
    assert "removed at least 16 of the file's 16 non-blank lines" in json.loads(done.stdout.split("\n", 1)[0])["rep"]["rm"]
    assert "removed at least" in msgs[1]["content"]
    for kwargs in ({"baseline": ("other.txt",)}, {"disk": FILE + "changed since the survey\n"}):
        _, done, msgs = shrink(ws, REMOVAL, **kwargs)
        assert denial.landed(msgs[1]) and "removed at least" not in msgs[1]["content"]
    _, _, msgs = shrink(ws, FRAGMENT, disk=FILE + "changed since the survey\n")
    assert denial.landed(msgs[1]) and (ws / "f.txt").read_text() == FRAGMENT


def test_the_measure_triggers_at_exactly_half_the_lines_removed_and_never_on_small_or_additive_rewrites(ws):
    """Bounds: a file under 8 lines, an additive rewrite, and a rewrite removing 7 of 16 lines say nothing; removing 8 of 16 lands WITH facts. None is asked."""
    asked = []
    lines = FILE.splitlines(keepends=True)
    replaced = lambda k: "".join(f"new {j}\n" for j in range(k)) + "".join(lines[k:])
    for current, content, facts in (("a\nb\nc\n", "x\n", False), (FILE, FILE + "extra\n", False), (FILE, replaced(7), False), (FILE, replaced(8), True)):
        _, _, msgs = shrink(ws, content, current=current, asked=asked)
        assert denial.landed(msgs[1]) and ("removed at least" in msgs[1]["content"]) is facts, content
    assert not asked
