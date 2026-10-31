"""wsview on a REAL surveyed tree: the harness-side survey program runs in bash over a tmp tree (plain and packed), the view ingests
it, and every answer is compared with the disk it came from: fold (one counted line, interior UNKNOWN), budget (a bound reads
UNKNOWN, never absent), unknown (not delivered / refused size), stale (writes, edits, mutators), rejected surveys, and re-rooting."""
import os
import subprocess

import pytest

from cria import wsview

SESS = "wsv"


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "src/pkg/a.py").write_text("print(1)\n")
    (tmp_path / "README.md").write_text("hi\n")
    (tmp_path / "big").mkdir()
    for i in range(wsview.FOLD_AT + 5):
        (tmp_path / "big" / f"f{i:04}.txt").write_text("x")
    (tmp_path / "many").mkdir()
    for i in range(61):
        (tmp_path / "many" / f"file_{i}.py").write_text("x = 1\n")
    (tmp_path / "huge.bin").write_bytes(b"0" * (wsview.BLOB_FILE_MAX + 10))
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/tool").write_text("#!/bin/sh\n")
    os.chmod(tmp_path / "bin/tool", 0o755)
    yield tmp_path
    for table in (wsview._BODY_MISSES, wsview._BODY_CACHE):
        table.clear()


def survey_of(root, **kw):
    out = subprocess.run(["bash", "-lc", wsview.survey_command(SESS, cd=str(root), **kw)], capture_output=True, text=True, timeout=120).stdout
    return wsview.strip_survey(out)[1]


def ask(*bodies, outside=(), programs=()):
    for b in bodies:
        wsview.want_body(SESS, b)
    for o in outside:
        wsview.want_outside(SESS, o)
    for p in programs:
        wsview.want_program(SESS, p)


@pytest.mark.parametrize("pack", [False, True])
def test_a_surveyed_view_answers_what_the_disk_holds_and_unknown_where_it_did_not_look(tree, pack):
    v = wsview.View(str(tree), SESS)
    assert v.read("README.md") is None and not v.surveyed
    ask("README.md", "src/pkg/a.py", "huge.bin", outside=("/etc", "/etc/hostname", "/nonexistent/zz"), programs=("sh", "no-such-prog-xyz"))
    assert wsview.apply_survey(v, survey_of(tree, pack=pack)) and v.surveyed and v.complete and v.usable
    assert v.isfile("README.md") and v.size("README.md") == 3 and v.isdir("src/pkg") and v.exists("src") and v.mtime("README.md")
    assert v.isfile("nope") is False and v.exists("nope") is False and v.rel(str(tree / "src")) == "src" and v.rel("../x") is None and v.rel("/else/x") is None
    assert v.abs("src") == f"{v.root}/src" and v.abs("") == v.root
    assert v.read("README.md") == "hi\n" and v.read_bytes("src/pkg/a.py") == b"print(1)\n"
    # budget/fold: a delivered-too-large body is refused (known size, unknown content); a folded directory is one counted line
    assert v.read_bytes("huge.bin") is None and v.undeliverable == ["huge.bin"] and not v.body_pending("huge.bin") and v.size("huge.bin") == wsview.BLOB_FILE_MAX + 10
    assert v.folded == ["big"] and v.listdir("big") is None and v.isfile("big/f0001.txt") is None and v.exists("big/f0001.txt") is None
    assert v.listdir(".") == sorted(os.listdir(tree)) and v.listdir("src") == ["pkg"] and v.listdir("nope") is None
    assert [e.name for e in v.scandir("src")] == ["pkg"] and v.scandir("big") is None
    assert [(r, sorted(d), sorted(f)) for r, d, f in v.walk(".")][0][2:] == (["README.md", "huge.bin"],) and len(v.files()) == 65
    assert (v.outside_kind("/etc"), v.outside_kind("/etc/hostname"), v.outside_kind("/nonexistent/zz")) == ("d", "f", "")
    assert v.program("sh") and not v.program("no-such-prog-xyz")
    sub = v.reroot("src")
    assert sub.root == f"{v.root}/src" and sub.listdir(".") == ["pkg"] and sub.isfile("pkg/a.py") and sub.read("pkg/a.py") == "print(1)\n"
    assert v.reroot("/else/elsewhere").listdir(".") is None and v.reroot("big").isfile("f0001.txt") is None and not v.reroot("big").complete and v.listed_everything("src")
    # the same questions asked of the disk itself agree for everything the survey looked at
    d = wsview.DirectView(str(tree))
    assert all(d.isfile(v.abs(p)) == v.isfile(p) and d.size(v.abs(p)) == v.size(p) for p in ("README.md", "huge.bin", "src/pkg/a.py", "nope"))
    assert d.listdir(v.abs("src")) == v.listdir("src") and d.read(v.abs("README.md")) == "hi\n" and d.outside_kind("/etc") == "d"
    assert d.reroot("/nowhere/x") is d and d.read(v.abs("src/pkg/a.py")) == "print(1)\n"


def test_a_survey_that_hit_its_budget_is_unknown_and_a_cut_foreign_or_unverified_one_is_refused(tree):
    whole = survey_of(tree)
    bounded = wsview.View(str(tree), SESS)
    assert wsview.apply_survey(bounded, survey_of(tree, budget=wsview.TREE_MIN_BYTES))
    assert len(bounded._files) < 65 and bounded.isfile("many/file_60.py") is None and bounded.isfile("nope") is None and not bounded.listed_everything()
    assert wsview.apply_survey(fresh_view := wsview.View(str(tree), SESS), whole) and fresh_view.isfile("many/file_60.py") and fresh_view.isfile("nope") is False
    fresh = lambda: wsview.View(str(tree), SESS)                                                      # noqa: E731
    entries = [ln for ln in whole.splitlines() if ln.startswith("entries\t")][0]
    refusals = [("cut-in-transit", whole.replace(wsview.SURVEY_CLOSE, "")), ("no-entry-count", whole.replace(entries, "x\t1")),
                ("entry-count-mismatch", whole.replace(entries, "entries\t99")), ("entry-count-unparseable", whole.replace(entries, "entries\tmany")),
                ("no-tree-section", whole.replace(wsview._SEC_PREFIX + "tree", "x")), ("packed-unverified", wsview.SURVEY_PACKED + " 5 deadbeef\nAAAA")]
    for reason, text in refusals:
        view = fresh()
        assert not wsview.apply_survey(view, text) and wsview.last_reject()["reason"] == reason and not view.surveyed, reason
    foreign = wsview.View("/some/other/repo", SESS)
    assert not wsview.apply_survey(foreign, whole) and wsview.last_reject()["reason"] == "different-tree" and foreign.isfile("README.md") is None
    rootless = wsview.View(None, SESS)
    assert wsview.apply_survey(rootless, whole) and rootless.root == str(tree) and rootless.isfile("README.md")


def test_writes_edits_and_mutators_make_held_facts_stale_until_the_next_survey_confirms_them(tree):
    v = wsview.View(str(tree), SESS)
    ask("src/pkg/a.py", "README.md")
    assert wsview.apply_survey(v, survey_of(tree)) and not v.may_have_changed
    assert v.note_edited("src/pkg/a.py", "print(1)", "print(2)") and v.read("src/pkg/a.py") == "print(2)\n"
    assert not v.note_edited("src/pkg/a.py", "print(1)", "x") and not v.note_edited("src/pkg/a.py", "", "x") and not v.note_edited("../out", "a", "b")
    v.note_written("src/new.py", "x = 1\n")
    assert v.isfile("src/new.py") and v.read("src/new.py") == "x = 1\n" and v.size("src/new.py") == 6 and "new.py" in v.listdir("src")
    v.note_changed("README.md")                                            # existence survives, the body does not
    assert v.read("README.md") is None and v.isfile("README.md") and "README.md" in v._stale
    v.note_a_mutator_ran()
    assert v.may_have_changed and v.read("src/new.py") is None
    v.note_unknown_mutation()
    assert all(v.read(p) is None for p in ("src/pkg/a.py", "README.md")) and v.isfile("src/pkg/a.py")
    unsurveyed = wsview.View(str(tree), "other-session")
    unsurveyed.note_possible_effect()
    assert not unsurveyed.usable and not unsurveyed.may_have_changed
    v.note_possible_effect()
    assert v.may_have_changed
    # the next survey of the (really edited) disk is what confirms the size and the bytes
    (tree / "src/pkg/a.py").write_text("print(2)\nprint(3)\n")
    ask("src/pkg/a.py")
    assert wsview.apply_survey(v, survey_of(tree)) and v.read("src/pkg/a.py") == "print(2)\nprint(3)\n" and v.size("src/pkg/a.py") == 18
