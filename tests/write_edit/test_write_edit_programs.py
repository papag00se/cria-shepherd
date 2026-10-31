"""The lowered write/edit PROGRAMS, executed in bash: what lands on disk and what the coder is told."""
import json
import os
import shutil

import pytest

from cria import denial, editrecovery
from write_edit_helpers import do, first_record, write_edit_workspace_view  # noqa: F401  (the fixture binds the workspace view)

TRICKY = "line1\n\ttabbed 'q' \"dq\" $VAR `bt` \\n \u2603\r\nend-without-newline"


@pytest.mark.parametrize("content", [TRICKY, "", "0", "x" * 20_000], ids=["tricky", "empty", "falsy", "20KB"])
def test_a_whole_write_lands_exactly_the_bytes_sent_and_replays_as_the_models_own_call(tmp_path, content):
    """Whole write: byte-exact (shell metachars, CRLF, empty, falsy, 20 KB in ONE call), atomic, no litter, re-presented unchanged."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a/f.txt").write_bytes(b"before")
    tc, done, msgs = do("write_file", {"path": "a/f.txt", "content": content}, tmp_path)
    assert (tmp_path / "a/f.txt").read_bytes() == content.encode()
    assert first_record(done.stdout)[0] == denial.LANDED and denial.landed(msgs[1])
    assert json.loads(msgs[0]["tool_calls"][0]["function"]["arguments"]) == {"path": "a/f.txt", "content": content}
    assert os.listdir(tmp_path / "a") == ["f.txt"]


@pytest.mark.parametrize("args", [{"path": "keep.py"}, {"path": "keep.py", "content": None}])
def test_a_write_with_no_content_is_refused_not_written_as_an_empty_file(tmp_path, args):
    """A cut-off call (content absent/null) is answered 'did not run'; the file keeps its bytes. (`content or ""` once emptied files.)"""
    (tmp_path / "keep.py").write_text("before = 1\n")
    tc, done, msgs = do("write_file", args, tmp_path)
    assert (tmp_path / "keep.py").read_text() == "before = 1\n"
    assert first_record(done.stdout)[0] == denial.REFUSED and "cut off" in msgs[1]["content"]
    assert denial.is_denied(msgs[1]["content"]) and not denial.landed(msgs[1])


def test_a_write_that_cannot_land_leaves_the_old_bytes_and_no_temp(tmp_path):
    """A read-only directory (and a directory target, and a file in the parent chain) never leaves a half-written file or a stray temp."""
    (tmp_path / "ro").mkdir()
    (tmp_path / "ro/a.py").write_text("x = 1\n")
    (tmp_path / "dir").mkdir()
    (tmp_path / "plain").write_text("i am a file")
    os.chmod(tmp_path / "ro", 0o555)
    try:
        for path in ("ro/a.py", "dir", "plain/child.py"):
            tc, done, msgs = do("write_file", {"path": path, "content": "y = 2\n"}, tmp_path)
            assert denial.landed(msgs[1]) is False, path
            assert path == "ro/a.py" or denial.is_denied(msgs[1]["content"]), path      # a statement, not a traceback
    finally:
        os.chmod(tmp_path / "ro", 0o755)
    assert (tmp_path / "ro/a.py").read_text() == "x = 1\n" and os.listdir(tmp_path / "ro") == ["a.py"]
    assert os.listdir(tmp_path / "dir") == [] and (tmp_path / "plain").read_text() == "i am a file"


# (name, currently valid bytes, replacement that does not parse, fixing replacement)
BREAKERS = [
    ("a.py", "def f():\n    return 1\n", "def f(:\n", "def f():\n    return 2\n"),
    ("c.toml", "[a]\nx = 1\n", "[a]\nx = = 1\n", "[a]\nx = 2\n"),
    ("d.json", '{"a": 1}', '{"a": }', '{"a": 2}'),
    ("e.xml", "<a><b/></a>", "<a><b></a>", "<a><c/></a>"),
    pytest.param("r.rb", "def a\n  1\nend\n", "def a(\n  1\nend\n", "def a\n  2\nend\n",
                 marks=pytest.mark.skipif(not shutil.which("ruby"), reason="no ruby")),
    pytest.param("g.go", "package p\n", "package p\nfunc (\n", "package q\n",
                 marks=pytest.mark.skipif(not shutil.which("gofmt"), reason="no gofmt")),
]


@pytest.mark.parametrize("name,valid,broken,fixed", BREAKERS)
def test_a_write_never_breaks_a_file_that_parses_but_may_fix_or_create_one(tmp_path, name, valid, broken, fixed):
    """Regression-only validation across languages: refuse valid->broken (nothing written), allow broken->broken, broken->fixed and new files.
    (The validator once saw only py/json/toml, so every other language's refusal branch was unreachable.)"""
    path = tmp_path / name
    path.write_text(valid)
    tc, done, msgs = do("write_file", {"path": name, "content": broken}, tmp_path)
    assert path.read_text() == valid and not denial.landed(msgs[1])
    assert denial.is_denied(msgs[1]["content"]) and "REFUSED" in msgs[1]["content"]
    assert denial.landed(do("write_file", {"path": "new_" + name, "content": broken}, tmp_path, cid="n")[2][1])
    path.write_text(broken)
    assert denial.landed(do("write_file", {"path": name, "content": broken + "\n"}, tmp_path, cid="b")[2][1])
    assert denial.landed(do("write_file", {"path": name, "content": fixed}, tmp_path, cid="f")[2][1])
    assert path.read_text() == fixed


def test_a_refusal_carries_the_checkers_whole_diagnostic_even_under_a_deep_path(tmp_path):
    """shipping-rates-rb / ternary-bonsai call 0026: the refusal read `:36: s` because the long workspace path ate the 200-char cap.
    The coder cannot re-read its rejected payload, so the message and the offending line must arrive."""
    if not shutil.which("ruby"):
        pytest.skip("no ruby")
    deep = tmp_path / ("d" * 120) / "lib"
    deep.mkdir(parents=True)
    (deep / "rates.rb").write_text("module S\nend\n")
    bad = 'module S\n  def z(c)\n    Country[]("#{c}")\n  end\nend\n'
    tc, done, msgs = do("write_file", {"path": f"{'d' * 120}/lib/rates.rb", "content": bad}, tmp_path)
    text = msgs[1]["content"]
    assert "syntax error" in text and "rates.rb:" in text and "Line 3 of the content you sent is: Country[](" in text
    assert str(tmp_path) not in text


# (id, file now, old, new, expected file after | None = untouched, expected failure mode)
EDITS = [
    ("exact", "foo\nbar\n", "foo", "FOO", "FOO\nbar\n", None),
    ("blank-line drift", "a = 1\n\nb = 2\n", "a = 1\n\n\nb = 2", "a = 1\n\nc = 3", "a = 1\n\nc = 3\n", None),
    ("indent drift keeps the file's indent", "    x = 1\n", "x = 1", "x = 2", "    x = 2\n", None),
    ("bare old inherits the block indent", "    if a:\n        x = 1\n", "x = 1", "x = 2", "    if a:\n        x = 2\n", None),
    ("mid-line flexible match eats nothing", "v = alpha +  beta\n", "alpha  +  beta", "gamma", "v = gamma\n", None),
    # mellum2 1786196176: an old_string carrying the real 12-space indent plus a whitespace-only line landed 24 spaces
    # ("unexpected indent"), then told the coder its correct new_string was wrong; 91 escalations followed.
    ("indented old_string never doubles the indent",
     "if t:\n    with p() as m:\n        m.a = 1\n        \n        # c\n        m.a = 2\n",
     "        m.a = 1\n        # c\n        m.a = 2", "        m.b = [1, 2]", "if t:\n    with p() as m:\n        m.b = [1, 2]\n", None),
    ("two matches are ambiguous", "x\nx\n", "x", "y", None, "multi"),
    ("two whitespace-flexible matches are ambiguous", "x = 1  +  2\nx = 1   +   2\n", "x = 1 + 2", "y", None, "multi_flex"),
    ("an explicit empty new_string deletes", "foo(x)\nbar\n", "foo(x)\n", "", "bar\n", None),
    ("a miss reports the file's real text", "def r(h):\n    y = 2\n", "def r(h):\n    x = 1", "z", None, "anchor"),
    ("a no-op edit", "    x = 1\n", "    x = 1", "    x = 1", None, "identical"),
    ("nothing resembles old", '[project]\nname = "x"\n', "[tool.s]\npackage-dir = 1", "z", None, "no_anchor"),
    ("a near miss", "    timeout = 30\n", "    timeoutt = 30", "    timeout = 60", None, "close"),
    # the model re-fixes a line that already reads as its new_string
    ("already done", '    x = get(f"{base_url}/h")\n', '    x = get(f"{base_user}/h")', '    x = get(f"{base_url}/h")', None, "phantom"),
    # Go 0217: a bare require is a PREFIX of the versioned one, which is not "already done"
    ("a proposed prefix is not done", 'require d/x "v1.5.0"\n', 'require d/x "1.5.0"', "require d/x", None, "close"),
]


@pytest.mark.parametrize("label,before,old,new,after,mode", EDITS, ids=[e[0] for e in EDITS])
def test_an_edit_applies_only_on_one_match_and_reports_facts_otherwise(tmp_path, label, before, old, new, after, mode):
    """Edit executor: whitespace-flexible unique match lands; 0/many matches/no-ops/phantoms never write and carry typed facts."""
    (tmp_path / "f.py").write_text(before)
    tc, done, msgs = do("edit_file", {"path": "f.py", "old_string": old, "new_string": new}, tmp_path)
    kind, rec = first_record(done.stdout)
    if mode is None:
        assert (tmp_path / "f.py").read_text() == after and kind == denial.LANDED and done.returncode == 0
        return
    assert (tmp_path / "f.py").read_text() == before and kind == "unapplied" and done.returncode != 0
    report = editrecovery.decode_report(rec["rep"]["ef"])
    assert report["mode"] == mode
    assert denial.unlanded(msgs[1]) and not denial.landed(msgs[1])


def test_an_edit_that_would_break_a_parsing_file_is_held_but_fixing_a_broken_one_lands(tmp_path):
    """Edit validation is regression-only: `would_break` leaves the valid file alone; a fix of a broken file applies."""
    (tmp_path / "f.py").write_text("x = 1\ny = 2\n")
    tc, done, _ = do("edit_file", {"path": "f.py", "old_string": "y = 2", "new_string": "y = (2"}, tmp_path)
    assert editrecovery.decode_report(first_record(done.stdout)[1]["rep"]["ef"])["mode"] == "would_break"
    assert (tmp_path / "f.py").read_text() == "x = 1\ny = 2\n"
    (tmp_path / "g.py").write_text("def h(:\n    pass\n")
    _, done, _ = do("edit_file", {"path": "g.py", "old_string": "def h(:", "new_string": "def h():"}, tmp_path, cid="g")
    assert first_record(done.stdout)[0] == denial.LANDED and "def h():" in (tmp_path / "g.py").read_text()


def test_an_edit_is_written_through_a_symlink_and_a_failed_edit_leaves_no_temp(tmp_path):
    """The link stays a link and its target gets the bytes; an unwritable directory is a typed 'did not run' with nothing left behind."""
    (tmp_path / "real.py").write_text("x = 1\n")
    os.symlink("real.py", tmp_path / "lnk.py")
    do("edit_file", {"path": "lnk.py", "old_string": "x = 1", "new_string": "x = 3"}, tmp_path)
    assert os.path.islink(tmp_path / "lnk.py") and (tmp_path / "real.py").read_text() == "x = 3\n"
    (tmp_path / "ro").mkdir()
    (tmp_path / "ro/a.py").write_text("x = 1\n")
    os.chmod(tmp_path / "ro", 0o555)
    try:
        _, done, msgs = do("edit_file", {"path": "ro/a.py", "old_string": "x = 1", "new_string": "x = 2"}, tmp_path, cid="r")
    finally:
        os.chmod(tmp_path / "ro", 0o755)
    assert denial.unlanded(msgs[1]) and "Permission denied" in msgs[1]["content"]
    assert (tmp_path / "ro/a.py").read_text() == "x = 1\n" and os.listdir(tmp_path / "ro") == ["a.py"]


DEFECT = "source defect reported to Main (write_file path), not fixed here"


@pytest.mark.parametrize("case", [pytest.param("symlink", marks=pytest.mark.xfail(strict=True, reason=DEFECT)),
                                  pytest.param("unwritable", marks=pytest.mark.xfail(strict=True, reason=DEFECT))])
def test_a_whole_write_follows_a_symlink_and_an_unwritable_directory_is_a_statement_like_the_edit_path(tmp_path, case):
    """The edit executor writes THROUGH a symlink and says 'could not be written: Permission denied'; the whole-write program replaces the link
    with a regular file and prints a raw Python traceback (with the survey record ahead of it) for a read-only directory."""
    (tmp_path / "ro").mkdir()
    (tmp_path / "real.py").write_text("x = 1\n")
    (tmp_path / "ro/a.py").write_text("x = 1\n")
    os.symlink("real.py", tmp_path / "lnk.py")
    os.chmod(tmp_path / "ro", 0o555)
    try:
        if case == "symlink":
            do("write_file", {"path": "lnk.py", "content": "y = 2\n"}, tmp_path)
            assert os.path.islink(tmp_path / "lnk.py") and (tmp_path / "real.py").read_text() == "y = 2\n"
        else:
            _, _, msgs = do("write_file", {"path": "ro/a.py", "content": "y = 2\n"}, tmp_path)
            assert denial.unlanded(msgs[1]) and "Traceback" not in msgs[1]["content"]
    finally:
        os.chmod(tmp_path / "ro", 0o755)
