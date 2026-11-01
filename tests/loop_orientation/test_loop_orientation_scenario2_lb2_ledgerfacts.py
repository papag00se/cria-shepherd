"""The facts the coder is shown about files it read: a line count is dated against the workspace's own copy, the orienter's listing comes
from this request's survey, and a fact block lands in the protected head after the system turns."""
import pytest

from cria import loop, prompts, wsview
from cria.loop import _Counted, _Unestablished

NOW = "3 lines now"
CHANGED = " — 3 lines when you last read or wrote it, so the file has changed since"


@pytest.fixture
def disk(tmp_path):
    (tmp_path / "a.py").write_text("a\nb\nc\n")                         # 6 bytes, 3 lines
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    yield str(tmp_path / "a.py"), wsview.current(str(tmp_path))
    wsview.unbind(token)


def dated(view, rel, nbytes, label):
    return loop._dated_count(view, rel, nbytes, label, prompts.load_map("fetched_facts_sections"))


def test_a_line_count_is_restated_only_as_far_as_the_workspaces_own_copy_vouches_for_it(disk):
    rel, view = disk
    assert dated(view, rel, 6, "3 lines") == "3 lines" and dated(view, rel, 7, "3 lines") == "3 lines"      # the read tool's stripped newline
    assert dated(view, rel, None, "3 lines") == "3 lines"
    assert dated(view, rel, 20, "9 lines") == f"{NOW} — 9 lines when you last read or wrote it, so the file has changed since"
    assert dated(view, rel, 6, "lines 1-2 only — 2 lines") == "lines 1-2 only — 2 lines"                    # a window claims nothing of the whole
    assert dated(None, rel, 20, "9 lines") == "9 lines"                                                       # nothing known of the workspace
    assert dated(view, rel, None, _Counted("3 lines")) == "3 lines" and dated(view, rel, 6, _Counted("1 lines")).startswith(NOW + " — 1 lines")
    assert dated(None, rel, None, _Counted("1 lines")) == "1 lines"
    assert dated(view, rel, None, _Unestablished("9 lines")) == NOW                                            # the latest touch left no size: only now
    assert dated(None, rel, None, _Unestablished("9 lines")) == "line count when you last read or edited it not established"
    view.note_a_mutator_ran()                                   # a command that may have changed files: the body may be behind the disk
    assert dated(view, rel, 20, "9 lines") == "9 lines when you last read or wrote it — the file has changed since"
    assert dated(view, rel, None, _Counted("1 lines")) == "1 lines" and dated(view, rel, None, _Unestablished("9 lines")) == \
        "line count when you last read or edited it not established"
    assert loop._current_line_count(view, rel) is None and loop._current_line_count(None, rel) is None


def test_the_orienter_is_given_this_requests_survey_and_otherwise_none(tmp_path):
    (tmp_path / "Importer.java").write_text("class Importer {}\n")
    root, log = str(tmp_path), type("L", (), {"events": [], "emit": lambda s, k, **kw: s.events.append((k, kw))})()
    sess = type("S", (), {"workspace_root": root})()
    token = wsview.bind(wsview.DirectView(root))
    try:
        assert "Importer.java" in loop._reorientation_inventory(sess, log)
    finally:
        wsview.unbind(token)
    token = wsview.bind(wsview.View(root, "s"))                 # a rebuilt, unsurveyed view: compaction removed every survey
    try:
        assert loop._reorientation_inventory(sess, log) == ""
    finally:
        wsview.unbind(token)
    assert [kw["source"] for _k, kw in log.events] == ["current", "none"]


def test_a_fact_block_goes_after_the_leading_system_turns():
    msgs = [{"role": "system", "content": "s"}, {"role": "developer", "content": "d"}, {"role": "user", "content": "u"}]
    anchor = {"role": "user", "content": "facts"}
    assert loop._insert_after_system(msgs, anchor) == msgs[:2] + [anchor] + msgs[2:]
    assert loop._insert_after_system([], anchor) == [anchor] and loop._insert_after_system(msgs[2:], anchor)[0] is anchor
