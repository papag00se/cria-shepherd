"""A write whose reply was lost is no longer an unknown pending write once its executor-side completion mark is read back."""
import json
import os
import subprocess
import sys

import pytest

from cria import completionmarks, loop, writeobservation, wsview, writeproxy
from gates_completion_helpers import gates_completion_view  # noqa: F401

SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
ENVELOPE = "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOriginal token count: 9\nOutput:\n"


def lowered(calls, cwd):
    comp = {"choices": [{"message": {"tool_calls": [
        {"id": cid, "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": path, "content": text})}}
        for cid, path, text in calls]}}]}
    writeproxy.translate_outbound(comp, SHELL, injected={"write_file"}, session="gate-lost-reply", workspace_root=str(cwd))
    return comp["choices"][0]["message"]["tool_calls"]


def execute(tc, cwd):
    scratch = str(cwd) + ".scratch"
    os.makedirs(scratch + "/bin", exist_ok=True)
    if not os.path.exists(scratch + "/bin/python3"):
        os.symlink(os.path.realpath(sys.executable), scratch + "/bin/python3")
    env = {"PATH": f"{scratch}/bin:/usr/bin:/bin", "HOME": str(cwd), "TMPDIR": scratch, "LC_ALL": "C"}
    return subprocess.run(["bash", "-c", json.loads(tc["function"]["arguments"])["cmd"]], cwd=str(cwd), env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30).stdout


def represent(messages, cwd):
    token = wsview.bind(wsview.View(str(cwd), "we"))
    try:
        return writeproxy.represent_inbound(messages, workspace_root=str(cwd))
    finally:
        wsview.unbind(token)


def coder(tcs):
    return {"choices": [{"message": {"tool_calls": tcs}}]}


@pytest.mark.parametrize("target, ran, settled, unlanded", [
    ("dir", True, True, True),         # the program refused: it changed nothing, so it was never an edit
    ("f.txt", True, True, False),      # the program landed: finished, and still a write the gate must count
    ("h.txt", False, False, False),    # no mark (never started / killed / running): STILL pending
], ids=["refused", "landed", "never-started"])
def test_a_lost_reply_write_is_pending_until_its_mark_is_read_back(tmp_path, target, ran, settled, unlanded):
    """ornith1.5_9b / Java: a write sent before a gate verdict whose reply never came back was 'pending' for the rest of the
    session, so no green check could outrank it and the rumination notice could not say nothing changed. Its mark, read back by
    the next program, settles it - to *did not change anything* only when the program itself says so."""
    completionmarks._reset()
    (tmp_path / "dir").mkdir()
    gs = loop.GuardState()
    (x,) = lowered([("x", target, "AAA\n")], tmp_path)
    if ran:
        assert execute(x, tmp_path).startswith(("{", "\u27e6"))                 # the program ran to its end; its reply is dropped
    before = [{"role": "assistant", "tool_calls": [x]}]
    loop._record_dispatch(gs, coder([x]), [])
    loop.track_gate_progress(gs, "tests failing", before)                       # the verdict is read with x outstanding
    assert "x" in gs.gate_pending_write_ids and not loop.gate_unedited(gs)
    (y,) = lowered([("y", "g.txt", "G\n")], tmp_path)
    history = represent(before + [{"role": "assistant", "tool_calls": [y]},
                                  {"role": "tool", "tool_call_id": "y", "content": ENVELOPE + execute(y, tmp_path)}], tmp_path)
    loop._record_dispatch(gs, coder([y]), before)
    loop._observe_history(gs, history)
    assert ("x" in writeobservation.answered_ids(gs, gs.write_result_ids)) is settled
    assert ("x" in writeobservation.unlanded_ids(gs)) is unlanded
