"""The workspace survey: "absent" is only ever said from a complete-and-current look; every bound or doubt reads as UNKNOWN."""
import base64
import subprocess

import pytest

from cria import groundtruth, prompts, wsview
from compaction_handoff_helpers import TREE, survey, survey_text

L = prompts.load_map("workspace_inventory")

@pytest.mark.parametrize("flavor", ("briefing", "coder"))
def test_the_decisive_clause_is_printed_only_for_a_complete_current_survey_and_the_filter_is_always_named(flavor):
    """674 prompts were told 'a file not listed does not exist' by a survey that predated the install that made the file (2026-08-22); a survey that hit its own bound never reached everywhere; excluded build output (target/) was never looked at."""
    fresh = survey_text(flavor=flavor)
    assert (L["complete"] in fresh) is (flavor != "coder") and "pom.xml (980 B)" in fresh
    for complete, changed in ((False, False), (True, True), (False, True)):
        out = survey_text(TREE + "D\ttarget\nF\t9\t1\ttarget/out.bin\n", complete=complete, changed=changed, flavor=flavor)
        assert "pom.xml" in out and "out.bin" not in out and "filtered inventory" in out and "not proof" in out      # what it saw stays named; omissions stay named
        assert L["complete"] not in out and "a file not listed here does not exist" not in out
        assert (L["stale"] in out) is changed and (L["partial"] in out) is (not complete)      # a bound and an overtaking are different sentences, and both can hold
        if flavor == "coder":
            assert L["coder_note"] in out                                                                          # the read-the-disk instruction survives either doubt

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

def _survey_of(root, budget=None):
    out = subprocess.run(["bash", "-lc", wsview.survey_command("t", cd=str(root), budget=budget)], capture_output=True, text=True, timeout=120).stdout
    view = wsview.View(str(root), "t")
    assert wsview.apply_survey(view, wsview.strip_survey(out)[1]), "the survey itself is well-formed"
    return view

def test_a_survey_that_hit_its_own_bound_reads_unknown_and_never_empty_or_complete(tmp_path):
    """A budget stop popped the directory with no X record and `complete` stayed 1: isfile() said False for files that exist and every judge was told the list was complete; a 420-file root read 'the workspace has no files'."""
    (tmp_path / "pkg").mkdir()
    for i in range(61):
        (tmp_path / "pkg" / f"file_{i}.py").write_text("x = 1\n")
    bounded = _survey_of(tmp_path, wsview.TREE_MIN_BYTES)
    assert len(bounded._files) < 61 and bounded.isfile("pkg/file_60.py") is None and not bounded.listed_everything()
    whole = _survey_of(tmp_path)
    assert whole.listed_everything() and whole.isfile("pkg/file_1.py") is True and whole.isfile("pkg/nope.py") is False
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

def test_a_cut_or_foreign_survey_is_refused_and_a_known_answer_is_never_emptied_by_it():
    """A survey cut in transit or of another tree is refused and never empties what is known; before any survey the answer is unknown, not no."""
    whole = survey("F\t0\t3\ta.py\nF\t0\t3\tb.py", root="/ws")
    view = wsview.View("/ws", "s")
    for broken in (whole[:whole.index(wsview._SEC_PREFIX + "done")], whole.replace("entries\t2", "entries\t9"), whole.replace(wsview.SURVEY_CLOSE, "")):
        assert not wsview.apply_survey(view, broken) and not view.surveyed          # a cut listing is indistinguishable from a smaller repo
    assert wsview.apply_survey(view, whole) and view.isfile("a.py") is True
    assert not wsview.apply_survey(view, survey("", root="/ws").replace(wsview._SEC_PREFIX + "tree", "x")) and view.isfile("a.py") is True
    assert not wsview.apply_survey(wsview.View("/some/other/repo", "s"), whole)      # a survey of another tree answers nothing
    assert wsview.View("/ws", "s2").isfile("a.py") is None                           # before anything is gathered: unknown, not no

def _blob(rel, raw):
    return "@" + base64.b64encode(rel.encode()).decode() + "\n" + base64.b64encode(raw).decode()

def test_a_remembered_body_is_dropped_when_it_was_cut_in_transit_or_the_file_changed_unobserved_and_never_crosses_roots():
    """Walked three times in L5 cells <60: a base64 body cut mid-line decoded into a wrong-length soup that a steer author read as 'the file is binary'; `go get` rewrote v1.4.0 to v1.5.0 at the same width and the cached body delivered the WRONG version's API as fact."""
    body = b"hello world, this is the real file\n" * 4
    cut = wsview.View("/w")
    assert wsview.apply_survey(cut, survey(f"F\t0\t{len(body)}\thello.py", root="/w", blob=_blob("hello.py", body)[:-40]))
    assert "hello.py" not in cut._bodies                                    # length disagrees with the listing: not the file
    ok = wsview.View("/w")
    assert wsview.apply_survey(ok, survey(f"F\t0\t{len(body)}\thello.py", root="/w", blob=_blob("hello.py", body))) and ok._bodies["hello.py"] == body
    old, new = 'require other.com/pkg v1.4.0\n', 'require other.com/pkg v1.5.0\n'
    tree = lambda mtime: f"F\t{mtime}\t{len(old)}\tgo.mod"
    wsview._BODY_CACHE.clear()
    first = wsview.View("/workspace", "sess-same-size")
    assert wsview.apply_survey(first, survey(tree(1000), root="/workspace", blob=_blob("go.mod", old.encode())))
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
    assert wsview.apply_survey(view, survey(tree(1000), root="/workspace"))      # the write's own survey rides the same result
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


def test_a_packed_survey_ride_unpacks_to_exactly_what_the_unpacked_ride_carries(tmp_path):
    """N2 / 03b28a42: the survey (66 KB over 59 results on phi4/Java A6) rides home zlib-packed and verified; the unpacked packed block kept a
    trailing newline the legacy path never had, so the coder-visible text and the view's survey differed by one byte."""
    for i in range(80):
        (tmp_path / f"mod_{i:02}.py").write_text("x = 1\n" * 40)
    rides = {}
    for pack in (False, True):
        wsview.want_body("n2-pack", "mod_00.py")
        rides[pack] = subprocess.run(["bash", "-lc", wsview.survey_command("n2-pack", cd=str(tmp_path), budget=9000, pack=pack)],
                                     capture_output=True, text=True, timeout=120).stdout
    assert wsview.SURVEY_PACKED in rides[True] and len(rides[True]) * 2 < len(rides[False])
    assert wsview.strip_survey("⟦ctx:wrote⟧\n" + rides[True]) == wsview.strip_survey("⟦ctx:wrote⟧\n" + rides[False])
    assert wsview.strip_survey("⟦ctx:wrote⟧\n" + rides[True])[0] == "⟦ctx:wrote⟧"
