"""The judge's read-only tools, executed against a real directory through the workspace view: every outcome (including every refusal) is a
factual sentence the judge can read; nothing is clipped; an escape is refused; a thing cria has not been told about is 'could not be read
here', never 'does not exist'."""
import os

import pytest

from cria import prompts, verifytools, wsview

TD = prompts.load_map("verify_tools")


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("a = 1\nb = 2\nc = 3\nd = 4\n")
    (tmp_path / "empty.txt").write_text("")
    (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    (tmp_path / "blob.bin").write_bytes(bytes(range(256)) * 4)
    (tmp_path / "emptydir").mkdir()
    (tmp_path.parent / f"{tmp_path.name}-outside").mkdir(exist_ok=True)
    os.symlink(tmp_path.parent / f"{tmp_path.name}-outside", tmp_path / "escape")
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    yield str(tmp_path)
    wsview.unbind(token)


def run(name, args, root):
    return verifytools.execute(name, args, root)


def test_list_dir_names_entries_with_sizes_and_says_empty_missing_or_outside_plainly(tree):
    listing = run("list_dir", {}, tree).splitlines()
    assert {"pkg/", "emptydir/", "empty.txt (0 B)", "img.png (72 B)"} <= set(listing)
    assert run("list_dir", {"path": "pkg"}, tree) == "mod.py (24 B)" and run("list_dir", {"path": "."}, tree) == "\n".join(listing)
    assert run("list_dir", {"path": "emptydir"}, tree) == "emptydir: empty directory"
    assert run("list_dir", {"path": "nope"}, tree) == prompts.fill(TD["missing"], path="nope")
    for outside in ("../elsewhere", "/etc", "escape"):               # lexically outside, absolute, and a symlink pointing out
        assert run("list_dir", {"path": outside}, tree) == prompts.fill(TD["outside"], path=outside, root=tree), outside


def test_read_file_returns_the_whole_file_or_exactly_the_requested_numbered_lines(tree):
    assert run("read_file", {"path": "pkg/mod.py"}, tree) == "a = 1\nb = 2\nc = 3\nd = 4\n"
    assert run("read_file", {"path": "pkg/mod.py", "start_line": 2, "end_line": 3}, tree) == "2: b = 2\n3: c = 3"
    assert run("read_file", {"path": "pkg/mod.py", "start_line": 3}, tree) == "3: c = 3\n4: d = 4"
    assert run("read_file", {"path": "pkg/mod.py", "end_line": 1}, tree) == "1: a = 1"
    assert run("read_file", {"path": "pkg/mod.py", "start_line": 0, "end_line": 2}, tree) == "1: a = 1\n2: b = 2"       # 0 is clamped to line 1
    assert run("read_file", {"path": "pkg/mod.py", "end_line": 99}, tree) == "1: a = 1\n2: b = 2\n3: c = 3\n4: d = 4"
    past = run("read_file", {"path": "pkg/mod.py", "start_line": 9, "end_line": 12}, tree)
    assert past == prompts.fill(TD["missing"], path="pkg/mod.py lines 9..12")                                      # nothing there is not an empty reply


def test_read_file_states_what_a_path_is_instead_of_guessing(tree):
    assert run("read_file", {"path": "empty.txt"}, tree) == prompts.fill(TD["empty_file"], path="empty.txt")
    assert run("read_file", {"path": "pkg"}, tree) == prompts.fill(TD["is_directory"], path="pkg")
    assert run("read_file", {"path": "gone.py"}, tree) == prompts.fill(TD["missing"], path="gone.py")
    assert run("read_file", {}, tree) == prompts.fill(TD["is_directory"], path="")                                 # no path is the root, which is a directory
    assert run("read_file", {"path": "/etc/passwd"}, tree) == prompts.fill(TD["outside"], path="/etc/passwd", root=tree)
    for blob in ("img.png", "blob.bin"):
        got = run("read_file", {"path": blob}, tree)
        assert "binary" in got.lower() and "\x00" not in got and len(got) < 300, blob
    assert run("frobnicate", {}, tree) == prompts.fill(TD["unknown_tool"], name="frobnicate")


def test_a_directory_cria_was_never_told_about_is_unknown_not_absent(tmp_path):
    """The surveyed view only knows what a survey told it: before any survey a listing and a read are both 'could not be read here' (the
    judge must not conclude the file is missing); an absent root is outside, never an exception."""
    token = wsview.bind(wsview.View(str(tmp_path), "cov4-verify"))
    try:
        assert run("list_dir", {"path": "pkg"}, str(tmp_path)) == prompts.fill(TD["unknown"], path="pkg")
        assert run("read_file", {"path": "pkg/mod.py"}, str(tmp_path)) == prompts.fill(TD["unknown"], path="pkg/mod.py")
        assert run("read_file", {"path": "../x"}, str(tmp_path)) == prompts.fill(TD["outside"], path="../x", root=str(tmp_path))
    finally:
        wsview.unbind(token)


def test_the_forced_answer_text_names_the_key_this_judge_declares_and_the_closing_reason_fills_its_rounds():
    assert '{"verified": true|false' in verifytools.answer_now("verified") and '{"done": true|false' in verifytools.answer_now("")
    assert verifytools.answer_now("k") != verifytools.answer_now("j")
    assert {t["function"]["name"] for t in verifytools.VERIFY_TOOLS} == {"list_dir", "read_file"}
    for key in ("answer_now_steer", "answer_now_consistent"):
        assert verifytools.closing_reason(key, 3) == prompts.fill(TD[key], rounds=3) and verifytools.closing_reason(key) == prompts.fill(TD[key], rounds="")


def test_an_empty_listing_from_a_survey_that_hit_its_budget_is_unknown_not_an_empty_directory(tmp_path):
    """Measured on a 420-file workspace: the bounded survey knew `[]` for a directory it never reached, and the judge was told 'empty
    directory'. The real survey program runs over a real tree with a tiny budget; a directory it did not reach is 'could not be read here',
    while one it listed in full is still named empty on an unbounded survey."""
    import subprocess
    (tmp_path / "many").mkdir()
    for i in range(61):
        (tmp_path / "many" / f"file_{i}.py").write_text("x")
    (tmp_path / "zzz").mkdir()
    (tmp_path / "zzz" / "a").write_text("x")
    (tmp_path / "hollow").mkdir()

    def surveyed(**kw):
        out = subprocess.run(["bash", "-lc", wsview.survey_command("cov4-verify-b", cd=str(tmp_path), **kw)], capture_output=True, text=True, timeout=120).stdout
        view = wsview.View(str(tmp_path), "cov4-verify-b")
        assert wsview.apply_survey(view, wsview.strip_survey(out)[1])
        return view
    token = wsview.bind(surveyed(budget=wsview.TREE_MIN_BYTES))
    try:
        assert run("list_dir", {"path": "zzz"}, str(tmp_path)) == prompts.fill(TD["unknown"], path="zzz")
        assert "file_0.py (1 B)" in run("list_dir", {"path": "many"}, str(tmp_path))
    finally:
        wsview.unbind(token)
    token = wsview.bind(surveyed())
    try:
        assert run("list_dir", {"path": "hollow"}, str(tmp_path)) == "hollow: empty directory"
        assert run("list_dir", {"path": "zzz"}, str(tmp_path)) == "a (1 B)"
    finally:
        wsview.unbind(token)
