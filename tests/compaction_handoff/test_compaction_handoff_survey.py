"""The workspace survey: "absent" is only ever said from a complete-and-current look; every bound or doubt reads as UNKNOWN."""
import pytest
from survey_fixtures import survey_of_disk

from cria import groundtruth, prompts, wsview
from compaction_handoff_helpers import TREE, survey, survey_text

L = prompts.load_map("workspace_inventory")

@pytest.mark.parametrize("flavor", ("briefing", "coder"))
def test_the_decisive_clause_is_printed_only_for_a_complete_current_survey_and_the_filter_is_always_named(flavor):
    """674 prompts were told 'a file not listed does not exist' by a survey that predated the install that made the file (2026-08-22); a survey that hit its own bound never reached everywhere; excluded build output (target/) was never looked at."""
    fresh = survey_text(flavor=flavor)
    assert (L["complete"] in fresh) is (flavor != "coder") and "pom.xml (980 B)" in fresh
    if flavor == "coder":
        assert "excluded directories" in fresh and "folded" in fresh
        assert "node_modules" not in fresh and "Use read_file" not in fresh
    for complete, changed in ((False, False), (True, True), (False, True)):
        out = survey_text(TREE + "D\ttarget\nF\t9\t1\ttarget/out.bin\n", complete=complete, changed=changed, flavor=flavor)
        assert "pom.xml" in out and "out.bin" not in out and "filtered inventory" in out
        assert ("excluded directories" in out if flavor == "coder" else "not proof" in out)
        assert L["complete"] not in out and "a file not listed here does not exist" not in out
        assert (L["stale"] in out) is changed and (L["partial"] in out) is (not complete)      # a bound and an overtaking are different sentences, and both can hold

def test_a_folded_install_tree_is_one_counted_line_but_committed_vendor_source_is_still_listed(tmp_path):
    """shipping-rates-rb x qwen35 (-60 pts): ~1,950 vendor/bundle files made a 65,801-token inventory against a 49,152 window; the server refused it six times."""
    (tmp_path / "vendor/bundle/gems").mkdir(parents=True)
    (tmp_path / "vendor/mycompany").mkdir(parents=True)
    (tmp_path / "vendor/mycompany/real_source.rb").write_text("committed")
    for i in range(300):
        (tmp_path / f"vendor/bundle/gems/g{i}.yaml").write_text("x")
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        out = groundtruth.workspace_inventory(str(tmp_path))
    finally:
        wsview.unbind(token)
    assert "vendor/bundle/ — 300 files" in out and "g7.yaml" not in out and "vendor/mycompany/real_source.rb" in out and L["complete"] in out

def _survey_of(root, bound=None):
    if bound is not None:
        wsview.TREE_MAX_ENTRIES, saved = bound, wsview.TREE_MAX_ENTRIES
    try:
        found = survey_of_disk(root, session="t")
    finally:
        if bound is not None:
            wsview.TREE_MAX_ENTRIES = saved
    view = wsview.View(str(root), "t")
    assert wsview.apply_survey(view, found), "the survey itself is applied"
    return view

def test_a_survey_that_hit_its_own_bound_reads_unknown_and_never_empty_or_complete(tmp_path):
    """A budget stop popped the directory with no X record and `complete` stayed 1: isfile() said False for files that exist and every judge was told the list was complete; a 420-file root read 'the workspace has no files'."""
    (tmp_path / "pkg/sub").mkdir(parents=True)
    (tmp_path / "pkg/sub/deep.py").write_text("x = 2\n")
    for i in range(61):
        (tmp_path / "pkg" / f"file_{i}.py").write_text("x = 1\n")
    bounded = _survey_of(tmp_path, 20)                  # the walk stops after the entries it has: the directory it had queued is named, not walked
    assert bounded.isfile("pkg/file_60.py") is True and bounded.isfile("pkg/sub/deep.py") is None and bounded.isdir("pkg/sub") is True
    assert not bounded.listed_everything() and not bounded.complete
    whole = _survey_of(tmp_path)
    assert whole.listed_everything() and whole.isfile("pkg/file_1.py") is True and whole.isfile("pkg/nope.py") is False and whole.isfile("pkg/sub/deep.py") is True
    for sub, name in (("", "main.py"), ("vendored", "main.py")):                    # a root too big to walk, and a folded subdirectory
        root = tmp_path / ("big" + sub)
        (root / sub).mkdir(parents=True)
        for i in range(wsview.FOLD_AT + 20):
            (root / sub / f"f{i:04}.py").write_text("x\n")
        (root / name).write_text("print(1)\n")
        folded = _survey_of(root)
        token = wsview.bind(folded)
        try:
            out = groundtruth.workspace_inventory(str(root))
        finally:
            wsview.unbind(token)
        assert (folded.isfile(str(root / "main.py")) is None) is (sub == "") and (not folded.complete) is (sub == "")
        assert "has no files" not in out and "is empty" not in out and "This list is complete" not in out and L["complete"] not in out
        assert ("NOT complete" in out and "main.py" in out) or not sub

def test_a_foreign_or_empty_survey_is_refused_and_a_known_answer_is_never_emptied_by_it():
    """A survey of another tree, or one that never listed the root, is refused and never empties what is known; before any survey the answer is unknown, not no."""
    whole = survey("F\t0\t3\ta.py\nF\t0\t3\tb.py", root="/ws")
    view = wsview.View("/ws", "s")
    assert not wsview.apply_survey(view, survey("", root="/ws", listed=False)) and not view.surveyed       # a survey without a listing is no survey
    assert wsview.apply_survey(view, whole) and view.isfile("a.py") is True
    assert not wsview.apply_survey(view, survey("", root="/ws", listed=False)) and view.isfile("a.py") is True
    assert not wsview.apply_survey(wsview.View("/some/other/repo", "s"), whole)      # a survey of another tree answers nothing
    assert wsview.View("/ws", "s2").isfile("a.py") is None                           # before anything is gathered: unknown, not no

def test_a_remembered_body_is_dropped_when_its_size_disagrees_or_the_file_changed_unobserved_and_never_crosses_roots():
    """Walked three times in L5 cells <60: a base64 body cut mid-line decoded into a wrong-length soup that a steer author read as 'the file is binary'; `go get` rewrote v1.4.0 to v1.5.0 at the same width and the cached body delivered the WRONG version's API as fact."""
    body = b"hello world, this is the real file\n" * 4
    cut = wsview.View("/w")
    assert wsview.apply_survey(cut, survey(f"F\t0\t{len(body)}\thello.py", root="/w", blobs={"hello.py": body[:-40]}))
    assert "hello.py" not in cut._bodies                                    # length disagrees with the listing: not the file
    ok = wsview.View("/w")
    assert wsview.apply_survey(ok, survey(f"F\t0\t{len(body)}\thello.py", root="/w", blobs={"hello.py": body})) and ok._bodies["hello.py"] == body
    old, new = 'require other.com/pkg v1.4.0\n', 'require other.com/pkg v1.5.0\n'
    tree = lambda mtime: f"F\t{mtime}\t{len(old)}\tgo.mod"
    wsview._BODY_CACHE.clear()
    first = wsview.View("/workspace", "sess-same-size")
    assert wsview.apply_survey(first, survey(tree(1000), root="/workspace", blobs={"go.mod": old.encode()}))
    same = wsview.View("/workspace", "sess-same-size")
    assert wsview.apply_survey(same, survey(tree(1000), root="/workspace")) and same.read("go.mod") == old       # unchanged file: still reused
    edited = wsview.View("/workspace", "sess-same-size")
    assert wsview.apply_survey(edited, survey(tree(2000), root="/workspace"))
    assert edited.read("go.mod") is None and "go.mod" in wsview.pending("sess-same-size")[0]                    # newer mtime: unknown, and re-asked
    assert wsview.View("/elsewhere", "sess-same-size").read("go.mod") is None                                    # another root never inherits this one's cache


def test_a_written_body_is_rechecked_on_mtime_by_later_surveys_and_a_crlf_body_is_never_reconstructed_by_an_edit():
    """C38b follow-up (69e4136c): a replayed write (`note_written`) left no mtime check at all, so `go get` bumping go.mod's version at the
    same width was read back as the pre-bump body forever; it is now tree-corroborated exactly when the known tree agrees on size.
    35af2a86: the edit executor normalises CRs, so a byte replace on a CRLF body would hold bytes that are not the disk."""
    old = 'require other.com/pkg v1.4.0\n'
    tree = lambda mtime: f"F\t{mtime}\t{len(old)}\tgo.mod"
    wsview._BODY_CACHE.clear()
    view = wsview.View("/workspace", "sess-replayed-write")
    assert wsview.apply_survey(view, survey(tree(1000), root="/workspace"))      # a survey cria asked for after the writes the same result
    view.note_written("go.mod", old)
    assert view.read("go.mod") == old                                           # trusted the moment cria watched it land
    assert wsview.apply_survey(view, survey(tree(1000), root="/workspace")) and view.read("go.mod") == old       # unchanged: still reused
    assert wsview.apply_survey(view, survey(tree(2000), root="/workspace"))
    assert view.read("go.mod") is None and "go.mod" in wsview.pending("sess-replayed-write")[0]     # unobserved same-size edit: dropped, re-asked
    crlf = wsview.View("/w")
    assert wsview.apply_survey(crlf, survey("F\t1\t30\ta.java", root="/w"))
    crlf.note_read("a.java", b"import java.a;\r\nclass A {}\r\n")
    assert crlf.note_edited("a.java", "class A", "class B") is False
    lf = wsview.View("/w")
    assert wsview.apply_survey(lf, survey("F\t1\t28\ta.java", root="/w"))
    lf.note_read("a.java", b"import java.a;\nclass A {}\n")
    assert lf.note_edited("a.java", "class A", "class B") is True and lf.read_bytes("a.java") == b"import java.a;\nclass B {}\n"
