"""Whole reads of ./tmp/reference spill files (saved search results, oversized fetches) return the file's exact bytes."""
import json, subprocess

import pytest

from cria import denial, resultpacket, writeproxy

SHELL = {"name": "shell", "parameters": {"properties": {"command": {"type": "string"}}, "required": ["command"]}}
MAX = writeproxy.READ_INLINE_MAX


def lower_and_run(tool, ws, **args):
    """The coder's call through the real outbound entry point, then the lowered shell command executed in the workspace."""
    comp = {"choices": [{"message": {"tool_calls": [{"id": "c", "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]}}]}
    writeproxy.translate_outbound(comp, SHELL, injected={tool}, workspace_root=str(ws))
    cmd = json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    cmd = cmd.get("command") or cmd.get("cmd")
    cmd = cmd[-1] if isinstance(cmd, list) else cmd
    return cmd, subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, cwd=ws)


@pytest.mark.parametrize("size,path", [(6630, "./tmp/reference/search.txt"), (MAX + 4, "./tmp/reference/search.txt"),
                                       (1024, "/tmp/reference/search.txt")])
def test_a_whole_read_of_a_spilled_file_succeeds_with_the_exact_bytes_at_any_size(tmp_path, size, path):
    """Five saved search results (6.6-8.4 KB) were refused with 'reading it whole gets truncated' - false for them;
    the root-absolute spelling reaches the same branch. Exit 0 and the file's bytes, always."""
    (tmp_path / "tmp/reference").mkdir(parents=True)
    (tmp_path / "tmp/reference/search.txt").write_text("a" * size)
    cmd, done = lower_and_run("read_file", tmp_path, path=path)
    record = resultpacket.read_record(done.stdout, 0, writeproxy.receipt_of(cmd))
    assert done.returncode == 0 and record.kind == denial.RAN and record.body.decode() + done.stdout[record.end:] == "a" * size


def test_a_missing_spilled_file_is_reported_missing_and_reference_material_is_never_editable(tmp_path):
    """A missing file is not an empty one (the coder crawled forever on silent empties); reference material is read-only."""
    (tmp_path / "tmp/reference").mkdir(parents=True)
    (tmp_path / "tmp/reference/a.json").write_text("x")
    _, missing = lower_and_run("read_file", tmp_path, path="./tmp/reference/nope.txt")
    assert "is not there" in missing.stdout and missing.returncode != 0 and denial.is_denied(missing.stdout)
    _, edit = lower_and_run("edit_file", tmp_path, path="./tmp/reference/a.json", old_string="x", new_string="y")
    assert edit.returncode == writeproxy.REFUSED_EXIT_CODE and (tmp_path / "tmp/reference/a.json").read_text() == "x"
