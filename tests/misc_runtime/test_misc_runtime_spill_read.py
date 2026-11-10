"""Whole reads of ./tmp/reference spill files (saved search results, oversized fetches) return the file's exact bytes, through the
engine and the harness primitives."""
import json
import subprocess

import pytest

from cria import denial, privatepaths, writeproxy
from cria.ops import Ops

SHELL = {"name": "shell", "parameters": {"properties": {"command": {"type": "string"}}, "required": ["command"]}}
MAX = writeproxy.READ_INLINE_MAX


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    (tmp_path.parent / (tmp_path.name + ".home")).mkdir()
    monkeypatch.setattr(privatepaths, "CRIA_HOME", tmp_path.parent / (tmp_path.name + ".home") / ".cria")


def lower_and_settle(tool, ws, **args):
    """The coder's call through the real outbound entry point, then cria's engine answered by real primitives run in the workspace;
    returns what the model reads (the tool result message)."""
    engine = Ops()
    comp = {"choices": [{"message": {"tool_calls": [{"id": "c", "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]}}]}
    writeproxy.translate_outbound(comp, SHELL, injected={tool}, workspace_root=str(ws), issue_read=lambda call, a, instead: engine.issue_read(
        "s", SHELL, call, a, workspace_root=str(ws), level="write", instead=instead))
    call = comp["choices"][0]["message"]["tool_calls"][0]
    messages = []
    while True:
        messages.append({"role": "assistant", "tool_calls": [call]})
        cmd = json.loads(call["function"]["arguments"])
        cmd = cmd.get("command") or cmd.get("cmd")
        cmd = cmd[-1] if isinstance(cmd, list) else cmd
        done = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, cwd=ws)
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": done.stdout})
        taken = engine.incoming("s", messages)
        if not taken.calls:
            return next(m for m in taken.messages if m.get("role") == "tool"), taken.outcomes
        messages, call = taken.messages, taken.calls[0]


@pytest.mark.parametrize("size,path", [(6630, "./tmp/reference/search.txt"), (MAX + 4, "./tmp/reference/search.txt"),
                                       (1024, "/tmp/reference/search.txt")])
def test_a_whole_read_of_a_spilled_file_succeeds_with_the_exact_bytes_at_any_size(tmp_path, size, path):
    """Five saved search results (6.6-8.4 KB) were refused with 'reading it whole gets truncated' - false for them;
    the root-absolute spelling reaches the same branch. The file's bytes, always."""
    (tmp_path / "tmp/reference").mkdir(parents=True)
    (tmp_path / "tmp/reference/search.txt").write_text("a" * size)
    shown, outcomes = lower_and_settle("read_file", tmp_path, path=path)
    assert shown["content"] == "a" * size and outcomes == {"c": denial.RAN}


def test_a_missing_spilled_file_is_reported_missing_and_reference_material_is_never_editable(tmp_path):
    """A missing file is not an empty one (the coder crawled forever on silent empties); reference material is read-only."""
    (tmp_path / "tmp/reference").mkdir(parents=True)
    (tmp_path / "tmp/reference/a.json").write_text("x")
    missing, outcomes = lower_and_settle("read_file", tmp_path, path="./tmp/reference/nope.txt")
    assert "is not there" in missing["content"] and outcomes == {"c": denial.REFUSED} and denial.is_denied(missing["content"])
    comp = {"choices": [{"message": {"tool_calls": [{"id": "e", "type": "function", "function": {"name": "edit_file", "arguments": json.dumps(
        {"path": "./tmp/reference/a.json", "old_string": "x", "new_string": "y"})}}]}}]}
    writeproxy.translate_outbound(comp, SHELL, injected={"edit_file"}, workspace_root=str(tmp_path))
    cmd = json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    edit = subprocess.run(["bash", "-c", cmd.get("command") or cmd.get("cmd")], capture_output=True, text=True, cwd=tmp_path)
    assert edit.returncode == writeproxy.REFUSED_EXIT_CODE and (tmp_path / "tmp/reference/a.json").read_text() == "x"
