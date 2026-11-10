"""Writes and edits through the harness primitives, executed by real stubs in bash: what lands on disk and what the coder is told."""
import hashlib
import json
import os
import shutil
import subprocess

import pytest

from cria import denial, editrecovery
from write_edit_helpers import command_of, do, write_edit_workspace_view  # noqa: F401  (the fixture binds the workspace view)

TRICKY = "line1\n\ttabbed 'q' \"dq\" $VAR `bt` \\n \u2603\r\nend-without-newline"


def test_a_write_and_an_edit_send_the_fixed_stub_and_only_their_own_bytes(tmp_path):
    """The harness is shown a short constant program and the bytes that change: a 2 KB write is about 6.0 KB of command, and an edit of a
    file of 300 KB (read once, so cria holds it) is about 3.8 KB however large the file is."""
    big = "".join(f"line {i} of a large file\n" for i in range(12_000))
    (tmp_path / "big.txt").write_text(big)
    tc, done, msgs = do("write_file", {"path": "new.txt", "content": "x" * 2000}, tmp_path)
    assert done.returncode == 0 and denial.landed(msgs[1]) and len(command_of(tc).encode()) < 6_400
    do("read_file", {"path": "big.txt"}, tmp_path, cid="r", injected=("read_file",))
    tc, done, msgs = do("edit_file", {"path": "big.txt", "old_string": "line 6000 of", "new_string": "LINE 6000 of"}, tmp_path, cid="e")
    assert denial.landed(msgs[1]) and (tmp_path / "big.txt").read_text() == big.replace("line 6000 of", "LINE 6000 of")
    assert len(command_of(tc).encode()) < 3_900, len(command_of(tc).encode())


def test_large_write_payload_is_carried_once_and_round_trips(tmp_path):
    content = ''.join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(400))
    tc, done, msgs = do('write_file', {'path': 'a.txt', 'content': content}, tmp_path)
    command = json.loads(tc['function']['arguments'])['cmd']
    assert len(command.encode()) < 40_000       # the 25 KB of content once, as base64 (34 KB), the 2.7 KB stub and, on a first call, the workspace survey's ride
    assert done.returncode == 0, done.stderr
    assert (tmp_path / 'a.txt').read_text() == content
    assert json.loads(msgs[0]['tool_calls'][0]['function']['arguments']) == {'path': 'a.txt', 'content': content}
    assert denial.landed(msgs[1])
    replacement = content[::-1]
    tc, done, msgs = do('edit_file', {'path': 'a.txt', 'old_string': content, 'new_string': replacement}, tmp_path)
    command = json.loads(tc['function']['arguments'])['cmd']
    assert len(command.encode()) < 40_000       # the edit's own bytes once (the 25 KB replacement), not the file's too (its 25 KB are not resent)
    assert done.returncode == 0, done.stderr
    assert (tmp_path / 'a.txt').read_text() == replacement
    assert json.loads(msgs[0]['tool_calls'][0]['function']['arguments']) == {'path': 'a.txt', 'old_string': content, 'new_string': replacement}
    assert denial.landed(msgs[1])


@pytest.mark.parametrize("content", [TRICKY, "", "0", "x" * 20_000], ids=["tricky", "empty", "falsy", "20KB"])
def test_a_whole_write_lands_exactly_the_bytes_sent_and_replays_as_the_models_own_call(tmp_path, content):
    """Whole write: byte-exact (shell metachars, CRLF, empty, falsy, 20 KB in ONE call), atomic, no litter, re-presented unchanged."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a/f.txt").write_bytes(b"before")
    tc, done, msgs = do("write_file", {"path": "a/f.txt", "content": content}, tmp_path)
    assert (tmp_path / "a/f.txt").read_bytes() == content.encode()
    assert denial.landed(msgs[1])
    assert json.loads(msgs[0]["tool_calls"][0]["function"]["arguments"]) == {"path": "a/f.txt", "content": content}
    assert os.listdir(tmp_path / "a") == ["f.txt"]


@pytest.mark.parametrize("args", [{"path": "keep.py"}, {"path": "keep.py", "content": None}])
def test_a_write_with_no_content_is_refused_not_written_as_an_empty_file(tmp_path, args):
    """A cut-off call (content absent/null) is answered 'did not run'; the file keeps its bytes. (`content or ""` once emptied files.)"""
    (tmp_path / "keep.py").write_text("before = 1\n")
    tc, done, msgs = do("write_file", args, tmp_path)
    assert (tmp_path / "keep.py").read_text() == "before = 1\n"
    assert denial.refused(msgs[1]) and "cut off" in msgs[1]["content"]
    assert denial.is_denied(msgs[1]["content"]) and not denial.landed(msgs[1])


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
    ("a new_string's own final newline is written as sent", "a = 1\nz\n", "a = 1", "a = 1\nb = 2\n", "a = 1\nb = 2\n\nz\n", None),
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
    if mode is None:
        assert (tmp_path / "f.py").read_bytes().decode() == after and denial.landed(msgs[1])       # bytes: read_text would fold CRLF
        return
    assert (tmp_path / "f.py").read_bytes().decode() == before and denial.proof(msgs[1]) == denial.UNAPPLIED
    assert denial.report(msgs[1])["ef"]["mode"] == mode                      # the typed facts of the miss (the directive is composed from them)
    assert denial.unlanded(msgs[1]) and not denial.landed(msgs[1])


def test_an_edit_that_would_break_a_parsing_file_is_held_but_fixing_a_broken_one_lands(tmp_path):
    """Edit validation is regression-only: `would_break` leaves the valid file alone; a fix of a broken file applies."""
    (tmp_path / "f.py").write_text("x = 1\ny = 2\n")
    tc, done, msgs = do("edit_file", {"path": "f.py", "old_string": "y = 2", "new_string": "y = (2"}, tmp_path)
    assert denial.report(msgs[1])["ef"]["mode"] == "would_break"
    assert (tmp_path / "f.py").read_text() == "x = 1\ny = 2\n"
    (tmp_path / "g.py").write_text("def h(:\n    pass\n")
    _, done, fixed = do("edit_file", {"path": "g.py", "old_string": "def h(:", "new_string": "def h():"}, tmp_path, cid="g")
    assert denial.landed(fixed[1]) and "def h():" in (tmp_path / "g.py").read_text()


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


@pytest.mark.parametrize("case", ["symlink", "symlink_other_dir", "dangling", "hardlink", "new_dir", "exact_bytes"])
def test_a_whole_write_lands_through_links_like_the_edit_path(tmp_path, case):
    """The write and the edit share ONE landing: a symlink inside the workspace (even to another directory, even dangling) is written
    THROUGH and stays a link; bytes stay exact. A hard-linked file is replaced atomically, like any other file: the name written gets the
    bytes and the other name keeps what it had (the harness `write` stub renames over the name, and a hard link is not a symlink: the
    docs/harness-primitives.md section 3 leaves them to the sandbox; the old program rewrote such a file in place - decision recorded in
    docs/harness-programs.md section 7, Phase 5 result)."""
    (tmp_path / "other").mkdir()
    old = "x = 1  # the old text is LONGER than the new, so a rewrite that does not truncate leaves a tail\n"
    (tmp_path / "real.py").write_text(old)
    (tmp_path / "other/real.py").write_text(old)
    content = "y = 2\n"
    if case == "symlink":
        os.symlink("real.py", tmp_path / "lnk.py"); target = tmp_path / "real.py"
    elif case == "symlink_other_dir":
        os.symlink("other/real.py", tmp_path / "lnk.py"); target = tmp_path / "other/real.py"
    elif case == "dangling":
        os.symlink("other/new.py", tmp_path / "lnk.py"); target = tmp_path / "other/new.py"
    elif case == "hardlink":
        os.link(tmp_path / "real.py", tmp_path / "lnk.py"); target = tmp_path / "real.py"
    elif case == "new_dir":
        target = tmp_path / "fresh/deep/lnk.py"
    else:
        target = tmp_path / "lnk.py"; content = "a\r\nb\u2603\x00c\n"
    path = "fresh/deep/lnk.py" if case == "new_dir" else "lnk.py"
    _, done, msgs = do("write_file", {"path": path, "content": content}, tmp_path)
    assert denial.landed(msgs[1])
    if case == "hardlink":
        assert (tmp_path / "lnk.py").read_bytes() == content.encode() and target.read_text() == old and os.stat(target).st_nlink == 1
    else:
        assert target.read_bytes() == content.encode()
    if case in ("symlink", "symlink_other_dir", "dangling"):
        assert os.path.islink(tmp_path / "lnk.py")
    assert not [n for d in (tmp_path, tmp_path / "other", tmp_path / "fresh/deep") if d.exists() for n in os.listdir(d) if n.startswith(".ctx")]


@pytest.mark.parametrize("case", ["readonly_dir", "readonly_parent_of_new_dir", "link_into_a_file", "directory_target", "file_in_parent_chain"])
def test_a_whole_write_that_cannot_land_is_a_did_not_run_statement_not_a_traceback(tmp_path, case):
    """An unwritable directory (existing file, or a new subdirectory under it), a link whose real parent cannot be a directory, a directory as the
    target, or a file in the parent chain is the plain 'could not be written' result the edit path gives, with nothing changed and no temp left.
    (The write used to print a raw traceback.) Each case is the only one that catches its own defect: a directory target not refused as one, an
    OSError escaping as a traceback."""
    (tmp_path / "ro").mkdir()
    (tmp_path / "ro/a.py").write_text("x = 1\n")
    (tmp_path / "dir").mkdir()
    (tmp_path / "plain").write_text("i am a file")
    os.chmod(tmp_path / "ro", 0o555)
    try:
        path = {"readonly_dir": "ro/a.py", "readonly_parent_of_new_dir": "ro/sub/a.py", "link_into_a_file": "gone/a.py", "directory_target": "dir",
                "file_in_parent_chain": "plain/child.py"}[case]
        if case == "link_into_a_file":
            os.symlink(tmp_path / "plain/x", tmp_path / "gone")     # the link's real parent can never be a directory
        _, _, msgs = do("write_file", {"path": path, "content": "y = 2\n"}, tmp_path)
    finally:
        os.chmod(tmp_path / "ro", 0o755)
    assert denial.unlanded(msgs[1]) and not denial.landed(msgs[1]) and "Traceback" not in msgs[1]["content"], msgs[1]["content"]
    assert denial.is_denied(msgs[1]["content"]) or case.startswith("readonly")                # a statement, not a traceback
    assert (tmp_path / "ro/a.py").read_text() == "x = 1\n" and os.listdir(tmp_path / "ro") == ["a.py"]
    assert os.listdir(tmp_path / "dir") == [] and (tmp_path / "plain").read_text() == "i am a file"

