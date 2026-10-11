"""K2 — `edit_file` with an EMPTY old_string "matched 191 places — add surrounding lines" (phi4 A4 CALL 0024:
191 = len(file)+1, every boundary of an empty string). The diagnosis is false and sent the coder inventing
text, four times. An empty old_string names no text: the lowering refuses it as a call that did not run, says
so, and authors nothing.
"""
import json
import subprocess
from pathlib import Path

from cria import denial
from cria.writeproxy import translate_outbound

TC = json.loads((Path(__file__).parent / "fixtures" / "phi4_java_a4" / "0019-empty-old-string-edit.json").read_text())["tool_call"]
_SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}


def _lowered(tool_call):
    comp = {"choices": [{"message": {"tool_calls": [json.loads(json.dumps(tool_call))]}}]}
    translate_outbound(comp, _SHELL, injected={"edit_file"}, workspace_root="/ws")
    return json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["cmd"]


def _run(cmd, cwd):
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True)


def test_the_real_a4_call_is_refused_without_touching_the_file(tmp_path):
    (tmp_path / "pom.xml").write_text("<dependencies>\n</dependencies>\n")
    args = json.loads(TC["function"]["arguments"])
    assert args["old_string"] == "" and args["new_string"]
    cmd = _lowered({**TC, "function": {**TC["function"], "arguments": json.dumps({**args, "path": str(tmp_path / "pom.xml")})}})
    out = _run(cmd, tmp_path)
    text = out.stdout + out.stderr
    assert out.returncode != 0 and denial.is_denied(text)         # a call that did not run
    assert "EMPTY `old_string`" in text and "Nothing was changed" in text
    assert "matches" not in text and "surrounding" not in text     # the false diagnosis is gone
    assert (tmp_path / "pom.xml").read_text() == "<dependencies>\n</dependencies>\n"
    assert args["new_string"][:40] not in text                    # cria authors nothing


def test_a_non_empty_old_string_is_still_an_edit(tmp_path):
    (tmp_path / "a.txt").write_text("hello world\n")
    cmd = _lowered({"id": "c", "type": "function", "function": {
        "name": "edit_file", "arguments": json.dumps({"path": str(tmp_path / "a.txt"), "old_string": "world", "new_string": "there"})}})
    _run(cmd, tmp_path)
    assert (tmp_path / "a.txt").read_text() == "hello there\n"
