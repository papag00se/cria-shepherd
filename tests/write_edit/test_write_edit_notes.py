"""What cria adds to, withholds from, or protects around tool results it returns: notes, ledgers, the advertised menu, secrets."""
import json
import os
import shutil
import subprocess

import pytest

from cria import denial, depsurface, research, webfetch, writeproxy, wsview
from write_edit_helpers import call, do, harness_env, surveyed_view, write_edit_workspace_view  # noqa: F401


def shell_result(command, code, output=""):
    raw = f"Chunk ID: 805c35\nWall time: 0.1 seconds\nProcess exited with code {code}\nOriginal token count: 0\nOutput:\n{output}"
    return writeproxy.represent_inbound([{"role": "assistant", "tool_calls": [call("exec_command", {"command": command})]},
                                         {"role": "tool", "tool_call_id": "c1", "content": raw}])[1]["content"]


def test_an_empty_filtered_failure_and_an_empty_search_say_what_they_measured_and_nothing_else_does():
    """`pytest | grep passed` on a collection error printed NOTHING and gemma4 re-ran it blind for eleven turns; a `grep Quantize` with no match
    was read as 'the command did not work' six times (it WAS the answer). Only: own filter pipe + non-zero + silent; grep exit 1 + silent."""
    assert "WITHOUT the pipe" in shell_result("python3 -m pytest -q 2>&1 | grep -E 'passed|failed'", 1)
    assert "matched nothing" in shell_result('grep -n "Quantize" decimal.go', 1) and "not a failed command" in shell_result("grep -n x a.go", 1)
    for command, code, out in [("grep -E passed log.txt", 1, "x"), ("pytest | grep failed", 1, "3 failed\n"), ("pytest | grep passed", 0, ""),
                               ("grep -n x nope.go", 2, ""), ("go build ./...", 1, ""), ("grep -n x a.go", 0, "12: x\n")]:
        text = shell_result(command, code, out)
        assert "WITHOUT the pipe" not in text and "matched nothing" not in text, (command, code)


def test_a_read_that_returned_no_bytes_is_refused_and_never_enters_the_read_ledger(tmp_path):
    """A bare `cat` of a missing path handed back bash's error as a result; the ledger recorded 'Importer.java — 261 chars read' for a path
    holding only directories and a judge ruled the reading step DONE. The read owner answers 'did not run' (exit != 0, no raw bash error)."""
    (tmp_path / "real.txt").write_text("actual content\n")
    (tmp_path / "adir").mkdir()
    for path, hint in (("Importer.java", "is not there"), ("adir", "list_dir")):
        _, done, msgs = do("read_file", {"path": path}, tmp_path, injected=("read_file",))
        assert done.returncode != 0 and denial.refused(msgs[1]) and hint in msgs[1]["content"] and "No such file or directory" not in done.stdout
        assert research.files_read(msgs) == []
    _, done, msgs = do("read_file", {"path": "real.txt"}, tmp_path, cid="ok", injected=("read_file",))
    assert msgs[1]["content"] == "actual content\n" and [p for p, _n in research.files_read(msgs)] == ["real.txt"]


def advertised(*names, **kw):
    body = {"tools": [{"type": "function", "function": {"name": n, "parameters": {"type": "object"}}} for n in names]}
    injected = writeproxy.advertise(body, **kw)
    return injected, {t["function"]["name"] for t in body["tools"]}


def test_the_menu_is_extended_only_where_the_harness_lacks_the_tool_and_a_shell_exists():
    """A shell-only harness gets the lean set (edit_file included); a harness's native tool is never shadowed; no shell, no translation;
    the raw Brave tool is presented as web_search, and web_search is synthesized only when a key exists."""
    tools = lambda *n: [{"type": "function", "function": {"name": x}} for x in n]
    assert writeproxy.needs_translation(tools("shell")) and writeproxy.needs_translation(tools("shell", "write_file")) is None
    assert writeproxy.needs_translation(tools("read_file")) is None
    injected, names = advertised("shell")
    assert {"write_file", "edit_file", "read_file", "list_dir", "web_fetch"} <= names and "edit_file" in injected
    injected, _ = advertised("shell", "read_file", "edit_file")
    assert not {"read_file", "edit_file"} & injected
    _, names = advertised("shell", "local_web_search")
    assert "web_search" in names and "local_web_search" not in names
    assert "web_search" not in advertised("shell", brave_key=None)[1] and "web_search" in advertised("shell", brave_key="sk-brave")[0]


def test_cria_credentials_are_scrubbed_from_every_shape_a_leak_can_take():
    """The Brave key leaked through a harness-echoed curl in a RESULT, assistant content and tool-call args; the model then reused it as a fake api-key."""
    key = "BSAnwLmCmt454A0U3WnT7fzIVFRAKM2"
    msgs = [{"role": "tool", "content": f"curl -H 'X-Subscription-Token: {key}' ...\n5 results"},
            {"role": "assistant", "content": f"api-key {key}", "tool_calls": [call("exec_command", {"cmd": f"curl -H api-key:{key}"})]},
            {"role": "user", "content": [{"type": "text", "text": f"token {key}"}]}]
    out = writeproxy.redact_secrets(msgs, [key])
    assert key not in json.dumps(out) and "***" in out[0]["content"]
    assert writeproxy.redact_secrets(msgs, [""]) == msgs


def test_the_dependency_surface_note_is_grounded_on_the_declared_version_stable_and_withdrawn_on_a_bump(tmp_path, monkeypatch):
    """C40: a result carries a note of the REAL exported surface of the version the manifest declares (read from the local module cache, never memory);
    it is the same text on every later request; a same-length version bump withdraws the old note and delivers the new; no manifest, no cache, or no
    session means silence."""
    home, ws = tmp_path / "home", tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home) + p[1:] if p.startswith("~") else p)
    for name in ("_ANCHOR", "_WITHHELD", "_ABSTAINED"):                  # session-global note state: fresh for this test, restored after
        monkeypatch.setattr(depsurface, name, {})

    def manifest(version, cache=True):
        (ws / "go.mod").write_text(f"module example.com/cart\n\ngo 1.21\n\nrequire example.invalid/x {version}\n")
        if cache:
            d = home / "go/pkg/mod" / f"example.invalid/x@{version}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "d.go").write_text("package d\n\nfunc NewFromString(v string) int {\n\treturn 1\n}\n")

    def request(sess="s1"):
        return writeproxy.represent_inbound([{"role": "tool", "tool_call_id": "c1", "content": "build ok"}], workspace_root=str(ws),
                                            sess_key=sess, tools_present=True)[0]["content"]
    manifest("v1.4.0", cache=False)
    assert request() == "build ok"
    manifest("v1.4.0")
    first = request()
    assert first.startswith("build ok") and "THE VERSION OF example.invalid/x v1.4.0 DECLARED IN go.mod" in first
    assert "func NewFromString(v string) int {" in first and request() == first and request(sess="") == "build ok"
    shutil.rmtree(home / "go")                                  # the anchored note outlives its source while the manifest still declares it
    assert request() == first
    manifest("v1.5.0")
    bumped = request()
    assert "v1.5.0 DECLARED IN go.mod" in bumped and "v1.4.0" not in bumped


def test_a_spill_lands_a_whole_document_exactly_and_cuts_an_oversize_one_while_saying_so(tmp_path):
    """handles-cli-node / nemotron-elastic: a 122 KB spill command was refused by the harness yet cria told the model for 26 turns the file was on disk.
    The command is budgeted on its ENCODED size (base64 + wrapping), so a max document fits and lands byte for byte; a bigger one is cut with a disclosure
    that says what is missing — never silently."""
    for name, size, whole in (("doc.txt", writeproxy.SPILL_CONTENT_MAX, True), ("big.txt", writeproxy.SPILL_CONTENT_MAX * 3, False)):
        doc = "y" * size
        command = writeproxy._spill_command(f"./tmp/read-only/{name}", doc, "saved it")
        assert len(command) <= writeproxy.COMMAND_ARG_BUDGET
        done = subprocess.run(["bash", "-c", command], cwd=tmp_path, env=harness_env(tmp_path), capture_output=True, text=True)
        saved = (tmp_path / "tmp/read-only" / name).read_text()
        assert done.returncode == 0 and (saved == doc) is whole
        assert whole or ("could not be delivered" in saved and "first" in saved and "y" * 1000 in saved and len(saved) < size)


def test_a_spilled_document_is_claimed_to_exist_only_while_the_workspace_listing_says_so():
    """The claim 'its full text is on disk at ...' was recorded at compose time, before the exec ran. Unknown (no listing yet), a listing that omits
    the file, and another workspace all withdraw it; a listing that names it keeps it."""
    url, path = "https://api.handle.me/handles", "/ws/tmp/reference/api.handle.me_handles.txt"
    webfetch.note_fetch_spill("s", url, path)
    token = wsview.bind(wsview.View("/ws", "s"))
    try:
        assert wsview.current().isfile(path) is None and not webfetch.already_spilled("s", url, "/ws")     # nobody has looked yet
        wsview.unbind(token)
        token = wsview.bind(surveyed_view("/ws", ("tmp/reference/other.txt", 9)))
        assert not webfetch.already_spilled("s", url, "/ws")
        wsview.unbind(token)
        token = wsview.bind(surveyed_view("/ws", ("tmp/reference/api.handle.me_handles.txt", 400)))
        assert webfetch.already_spilled("s", url, "/ws") and not webfetch.already_spilled("s", url, "/other-workspace")
    finally:
        wsview.unbind(token)
        webfetch.clear_cache()                                                 # the spill ledger is process-global
