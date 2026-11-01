"""Audit (AUD7): every shell program cria composes from model-controlled text or paths. A hostile or sloppy path or file CONTENT must never
change what the lowered program does: the exact bytes land, nothing else is created, and nothing the text spells is executed.

The canary is `touch CANARY_LANDED`: if any value were ever interpreted by a shell or a template, that file would appear in the workspace."""
import json
import os
import subprocess

import pytest

from cria import filecommands, wsview, writeproxy
from write_edit_helpers import call, do, harness_env, lower, command_of, run, write_edit_workspace_view  # noqa: F401

CANARY = "touch CANARY_LANDED"
# Every value below is a legal file name (or content) a model can send. Nothing here is destructive: the only command spelled is the canary.
PATHS = [
    "a b.txt", "a\nb.txt", "a\tb.txt", "it's.txt", 'q"d.txt', f"b`{CANARY}`.txt", f"$({CANARY}).txt", f"x;{CANARY}", f"x&&{CANARY}", f"x|{CANARY}",
    "-rf", "--", "-n", "*.txt", "[ab].txt", "?", "a\u202eb.txt", "\u00e9\u65e5\u672c.txt", "n" * 255, "~", "$HOME", "__CTX_PY_EOF__", "__CTX_SPILL__",
    "!", "(", "a\\b", "#c", ">out", "&", "{path}.txt", "%(turn)r", "a\x1bb", "a\rb", " lead", "trail ", ".ctx-edits-x", "%%NAME%%.txt", "x%%ERR%%y",
]
CONTENT = ("start\n__CTX_PY_EOF__\n__CTX_SPILL__\n__CTX_RD_PY__\n__CTX_RG_PY__\n__CTX_GATE_REQUEST__\n"
           f"$({CANARY})`{CANARY}`'\"\\\n%%NAME%% %(x)s {{path}} {{0}}\n\x1b[31mred\x1b[0m\x00nul\r\ncrlf\r\n\u202e\u2028\u2029\U0001f600 token-here\n")


def _tree(ws):
    return sorted(os.path.relpath(os.path.join(d, n), ws) for d, ds, fs in os.walk(ws) for n in ds + fs)


@pytest.mark.parametrize("name", PATHS, ids=lambda n: repr(n)[:24])
def test_a_hostile_path_lands_the_exact_bytes_under_that_exact_name_and_nothing_else_happens(tmp_path, name):
    """Write, edit and read the same hostile name, and list a folder of that name: one file with exactly the sent bytes, no extra file, no canary."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _, done, _ = do("write_file", {"path": name, "content": CONTENT}, ws)
    assert done.returncode == 0, done.stdout + done.stderr
    assert _tree(ws) == [name] and (ws / name).read_bytes() == CONTENT.encode()
    new = f"$({CANARY})\n"
    _, done, _ = do("edit_file", {"path": name, "old_string": "token-here", "new_string": new}, ws)
    assert done.returncode == 0, done.stdout + done.stderr
    assert _tree(ws) == [name] and (ws / name).read_bytes() == CONTENT.replace("token-here", new).encode()
    done = run(lower([call("read_file", {"path": name})], injected=("write_file", "edit_file", "read_file"))[0], ws)
    assert done.returncode == 0 and _tree(ws) == [name], done.stdout + done.stderr
    folder = tmp_path / "folder"
    (folder / name).mkdir(parents=True)
    (folder / name / "inner.txt").write_text("x")
    done = run(lower([call("list_dir", {"path": name})], injected=("write_file", "edit_file", "read_file", "list_dir"))[0], folder)
    assert done.returncode == 0 and "inner.txt" in done.stdout and _tree(folder) == [name, f"{name}/inner.txt"], done.stdout + done.stderr


# --- an edit changes only what it names ----------------------------------------------------------------------------------------------

EDITS = [   # (file bytes, old_string, new_string, bytes after)
    pytest.param(b"a\r\nb\r\nc\r\n", "b", "X", b"a\r\nX\r\nc\r\n", id="crlf-file-keeps-every-cr"),
    pytest.param(b"a\r\nb\r\nc\r\n", "a\nb", "X\nY", b"X\r\nY\r\nc\r\n", id="crlf-file-edited-with-lf-text-stays-crlf"),
    pytest.param(b"a\r\nb\r\nc\r\n", "a\r\nb", "X\r\nY", b"X\r\nY\r\nc\r\n", id="crlf-file-edited-with-crlf-text"),
    pytest.param(b"a\r\nb\nc\r\n", "b", "X", b"a\r\nX\nc\r\n", id="mixed-endings-are-left-as-they-are"),
    pytest.param(b"a\rb\rc\r", "b", "X", b"a\rX\rc\r", id="lone-cr-survives"),
    pytest.param(b"caf\xe9\nb\n", "b", "X", b"caf\xe9\nX\n", id="invalid-utf8-elsewhere-in-the-file-survives"),
    pytest.param(b"\xef\xbb\xbfa\nb\n", "b", "X", b"\xef\xbb\xbfa\nX\n", id="bom-survives"),
]


@pytest.mark.parametrize("lowering", [{}, {"edit_echo": True, "pack": True}], ids=["plain", "echo-and-pack"])
@pytest.mark.parametrize("data,old,new,want", EDITS)
def test_an_edit_rewrites_only_the_text_it_names_and_every_other_byte_of_the_file_survives(tmp_path, data, old, new, want, lowering):
    (tmp_path / "f.txt").write_bytes(data)
    _, done, msgs = do("edit_file", {"path": "f.txt", "old_string": old, "new_string": new}, tmp_path, **lowering)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (tmp_path / "f.txt").read_bytes() == want
    msgs[1]["content"].encode("utf-8")      # whatever the coder is shown is encodable: a file's stray byte never becomes a lone surrogate on the wire


@pytest.mark.parametrize("lowering", [{}, {"edit_echo": True, "pack": True}], ids=["plain", "echo-and-pack"])
def test_an_edit_that_misses_in_a_file_with_an_undecodable_byte_leaves_it_untouched_and_reports_without_a_lone_surrogate(tmp_path, lowering):
    (tmp_path / "f.txt").write_bytes(b"caf\xe9\nb\n")
    _, done, msgs = do("edit_file", {"path": "f.txt", "old_string": "not there", "new_string": "X"}, tmp_path, **lowering)
    assert done.returncode != 0 and "Traceback" not in done.stdout + done.stderr
    assert (tmp_path / "f.txt").read_bytes() == b"caf\xe9\nb\n"
    json.dumps(msgs, ensure_ascii=False).encode("utf-8")


# --- a path that cannot be a file name is refused, never a traceback -------------------------------------------------------------------

@pytest.mark.parametrize("name,args", [
    ("write_file", {"path": "a\x00b.txt", "content": "x"}), ("edit_file", {"path": "a\x00b.txt", "old_string": "x", "new_string": "y"}),
    ("write_file", {"path": "f.txt", "content": "a\udc80b"}), ("edit_file", {"path": "f.txt", "old_string": "a\udc80", "new_string": "y"}),
    ("edit_file", {"path": "f.txt", "old_string": "x", "new_string": "a\udc80"}), ("write_file", {"path": "a\udc80.txt", "content": "x"}),
], ids=["write-nul-path", "edit-nul-path", "write-lone-surrogate", "edit-lone-surrogate-old", "edit-lone-surrogate-new", "write-surrogate-path"])
def test_text_that_cannot_be_written_as_text_is_refused_as_did_not_run_and_nothing_is_created(tmp_path, name, args):
    (tmp_path / "f.txt").write_bytes(b"x\n")
    _, done, msgs = do(name, args, tmp_path)
    assert done.returncode != 0 and "Traceback" not in done.stdout + done.stderr
    assert _tree(tmp_path) == ["f.txt"] and (tmp_path / "f.txt").read_bytes() == b"x\n"


# --- a message about a name says the name ---------------------------------------------------------------------------------------------

def test_a_name_that_spells_a_template_placeholder_is_reported_back_exactly(tmp_path):
    """The unwritable-name sentence and the refused-over-a-valid-file sentence fill TWO placeholders; a name spelling the second was rewritten."""
    long_name = "a" * 250 + "%%ERR%%"
    _, done, _ = do("write_file", {"path": long_name, "content": "x"}, tmp_path)
    assert f"`{long_name}` could not be written: File name too long." in done.stdout + done.stderr
    (tmp_path / "%%AFTER%%.py").write_text("x = 1\n")
    _, done, _ = do("write_file", {"path": "%%AFTER%%.py", "content": "x = (\n"}, tmp_path)
    assert "replace a currently-valid %%AFTER%%.py with content" in done.stdout + done.stderr


# --- the listing of a directory named like an option ---------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["-rf", "-R", "--", "-l", "-a"])
def test_listing_a_directory_whose_name_starts_with_a_dash_lists_that_directory(tmp_path, name):
    (tmp_path / name).mkdir()
    (tmp_path / name / "inner.txt").write_text("x")
    (tmp_path / "outer.txt").write_text("x")
    tc = lower([call("list_dir", {"path": name})], injected=("write_file", "edit_file", "read_file", "list_dir"))[0]
    done = run(tc, tmp_path)
    assert done.returncode == 0 and "inner.txt" in done.stdout and "outer.txt" not in done.stdout, done.stdout


# --- a fetched URL's saved name fits the file system ----------------------------------------------------------------------------------

def test_the_saved_copy_of_a_page_with_a_very_long_url_path_is_still_saved_and_keeps_a_stable_distinct_name(tmp_path):
    from cria import webfetch
    a, b = "http://example.com/" + "a" * 300, "http://example.com/" + "a" * 300 + "b"
    assert webfetch._spill_name(a) == webfetch._spill_name(a) and webfetch._spill_name(a) != webfetch._spill_name(b)
    target = webfetch._spill_name(a)
    done = subprocess.run(["bash", "-c", writeproxy._spill_command(target, "doc\n", "saved")], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0 and (tmp_path / target).read_text() == "doc\n", done.stderr


# --- the workspace survey and a name it cannot list --------------------------------------------------------------------------------------

def _survey(ws, locale):
    out = subprocess.run(["bash", "-c", wsview.survey_command("aud7")], cwd=ws, capture_output=True, env={**harness_env(ws), "LC_ALL": locale}).stdout
    view = wsview.View(str(ws), "aud7")
    return view, wsview.apply_survey(view, out.decode("utf-8", "surrogateescape"))


ODD = [pytest.param(b"caf\xe9.txt", id="not-utf8"), pytest.param(b"a\nb.txt", id="newline"), pytest.param(b"x\nF\t1\t5\tforged.txt", id="forged-record"),
       pytest.param(b"q\n___CTX_SURVEY_END___\n", id="forged-close"), pytest.param("a\u2028F\t1\t5\tforged.txt".encode(), id="unicode-line-break")]


@pytest.mark.parametrize("odd", ODD)
def test_one_file_name_the_survey_cannot_list_never_blinds_it_or_invents_a_file_and_the_listing_says_it_is_incomplete(tmp_path, odd):
    """UNKNOWN, not absent and not invented: the other files are listed, nothing the odd name spells is listed, and `isfile` of what was not listed is
    None (cannot say), never False."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "real.txt").write_bytes(b"x")
    (ws / "sub").mkdir()
    (ws / "sub" / "deep.txt").write_bytes(b"x")
    open(os.path.join(os.fsencode(ws), odd), "wb").write(b"x")
    view, ok = _survey(ws, "en_US.utf8")
    assert ok
    assert sorted(e.path for e in view.files()) == [str(ws / "real.txt"), str(ws / "sub" / "deep.txt")]
    assert view.isfile(str(ws / "forged.txt")) is not True and view.isfile(str(ws / "missing.txt")) is None


def _survey_asking(ws, sess, *, bodies=(), outside=(), programs=(), pack=False):
    for b in bodies:
        wsview.want_body(sess, b)
    for o in outside:
        wsview.want_outside(sess, o)
    for n in programs:
        wsview.want_program(sess, n)
    out = subprocess.run(["bash", "-c", wsview.survey_command(sess, cd=str(ws), pack=pack)], cwd=ws, capture_output=True, env=harness_env(ws)).stdout
    view = wsview.View(str(ws), sess)
    return view, wsview.apply_survey(view, wsview.strip_survey(out.decode("utf-8", "surrogateescape"))[1])


@pytest.mark.parametrize("pack", [False, True])
@pytest.mark.parametrize("outside,program", [
    ("/nonexistent/x\n/etc", "nope\nsh"),                      # a line break inside a name would start a second record
    ("/nonexistent/x\t\n/etc\t", "nope\t\nsh\t"),
    ("/nonexistent/\ud800", "nope\udc80x\ud800")])            # text no file system can spell would end the survey
def test_a_path_or_program_the_model_named_cannot_forge_a_record_or_end_the_survey(tmp_path, outside, program, pack):
    """The real survey program, run by a real shell. Only what the coder asked about is answered: `/etc` and `sh` were not asked about, so the view
    still does not know them (None), and the ordinary questions asked beside the hostile ones are answered from the disk."""
    (tmp_path / "real.txt").write_text("hi\n")
    view, ok = _survey_asking(tmp_path, f"aud7-{tmp_path.name}", bodies=["real.txt", *(["x\ud800y"] * ("\ud800" in outside))], outside=["/nonexistent", outside], programs=["git", program], pack=pack)
    assert ok and view.surveyed and view.read("real.txt") == "hi\n" and view.outside_kind("/nonexistent") == "" and view.program("git") is not None
    assert view.outside_kind("/etc") is None and view.program("sh") is None
    if "\ud800" not in outside:
        assert view.outside_kind(outside) == "" and view.program(program) == ""


# --- the gate's shell words carry a hostile workspace, token, path and body as data ---------------------------------------------------------

NASTY_WORDS = ["w s", f"w'{CANARY}'", f"$({CANARY})`{CANARY}`", f"x;{CANARY}", "a\nb", "-rf", "*", "\u202e"]


@pytest.mark.parametrize("word", NASTY_WORDS, ids=lambda w: repr(w)[:24])
def test_the_gates_cd_dispose_and_launch_commands_read_back_as_the_exact_words_and_body_they_were_given(tmp_path, word):
    """Parsed, never executed: the words a shell would see are exactly the values given, and a request body that holds the heredoc terminator
    on a line of its own (JSON-escaped newlines) cannot end the heredoc early."""
    import shlex
    from cria import gatecleanup, probegate
    assert shlex.split(gatecleanup.dispose_command("runner", word, word)) == ["runner", "gate", "dispose", word, word]
    request = gatecleanup.launch_command("runner", word, word, f"{word}\n__CTX_GATE_REQUEST__\n{CANARY}", "s", "m")
    head, _, rest = request.partition(" <<'__CTX_GATE_REQUEST__'\n")
    assert shlex.split(head)[:4] == ["runner", "gate", "launch", word]
    assert rest.splitlines().count("__CTX_GATE_REQUEST__") == 1 and rest.endswith("__CTX_GATE_REQUEST__\n")
    assert json.loads(rest.rsplit("__CTX_GATE_REQUEST__", 1)[0])["body"].endswith(CANARY)
    ws = tmp_path / word
    ws.mkdir()
    (ws / "m.py").write_text("x = 1\n")
    script = probegate.plan_gate(str(ws)).script
    sent = json.loads(script.split("<<'__CTX_GATE_REQUEST__'\n", 1)[1].split("\n__CTX_GATE_REQUEST__", 1)[0])
    assert sent["workspace"] == str(ws) and sent["body"].startswith(f"cd {shlex.quote(str(ws))} || exit 97\n")
    for text in (script, sent["body"]):
        assert subprocess.run(["bash", "-n"], input=text, text=True, capture_output=True).returncode == 0
    assert not (tmp_path / "CANARY_LANDED").exists()
