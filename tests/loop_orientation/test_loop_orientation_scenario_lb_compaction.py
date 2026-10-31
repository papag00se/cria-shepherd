"""A harness compaction mid-session: what the coder is handed afterwards, and what the harness is told.

The coder read a.py, the file then grew on disk (4 -> 6 lines), and the harness replaced the history with a summary.
Through the real plan-off Loop (only the model server is fake) the next coder frame must carry the re-anchor notice, a
read ledger that DATES the old line count against the workspace's own copy, and the file's current text; the outgoing
completion says the session was re-anchored.
"""
import json

from cria import bodykeys, denial
from cria.loop import Loop, LoopContext, LoopStore, PlanSession
from cria.plan import Plan, PlanItem
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401

TASK = "Fix a.py."
TOOLS = [{"type": "function", "function": {"name": name, "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}} for name in ("read_file", "write_file")]


def test_after_a_compaction_the_coder_is_re_anchored_with_a_dated_ledger_and_the_current_file_text(tmp_path):
    path = str(tmp_path / "a.py")
    tmp_path.joinpath("a.py").write_text("l1\nl2\nl3\nl4\n")
    call = {"id": "r1", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": path})}}
    seen = []

    def coder(body, rlog):
        seen.append(body["messages"])
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": None,
                                                                          "tool_calls": [dict(call, id="next")]}}]}).encode()
    driver = Loop(LoopContext(planner=None, coder_chat=coder, reasoner_chat=None, runs_dir="", workspace_root=str(tmp_path)), LoopStore())
    driver._put_session("sid:k", PlanSession(plan=Plan(id="p", task=TASK, created="c", items=[PlanItem(TASK)]), synthetic=True, plan_off=True))
    first = [{"role": "user", "content": TASK}, {"role": "assistant", "content": None, "tool_calls": [call]},
             {"role": "tool", "tool_call_id": "r1", "content": "l1\nl2\nl3\nl4"},
             {"role": "assistant", "content": None, "tool_calls": [{"id": "w1", "type": "function", "function": {
                 "name": "write_file", "arguments": json.dumps({"path": str(tmp_path / "b.py"), "content": "b1\nb2\n"})}}]},
             {"role": "tool", "tool_call_id": "w1", "content": "Wrote b.py", bodykeys.RESULT_OUTCOME: denial.LANDED}]
    tmp_path.joinpath("b.py").write_text("b1\nb2\n")
    driver.drive({"messages": first, "tools": TOOLS, "stream": True}, "sid:k", None, Log())
    assert "cria_notes" not in driver.drive({"messages": first, "tools": TOOLS, "stream": True}, "sid:k", None, Log())
    tmp_path.joinpath("a.py").write_text("l1\nl2\nl3\nl4\nl5\nl6\n")                  # the file moves on
    compacted = [{"role": "user", "content": TASK}, {"role": "user", "content": "[CONTEXT COMPACTION] Summary: you read a.py."}]
    log = Log()
    out = driver.drive({"messages": compacted, "tools": TOOLS, "stream": True}, "sid:k", None, log)
    frame = [m["content"] for m in seen[-1] if m["role"] == "user"]
    assert out["cria_notes"] == ["re-anchored after a harness compaction"] and "loop.history_rewritten" in log.kinds()
    assert any(t.startswith("⟦ctx:steer⟧ context notice: the harness just compacted") for t in frame)
    ledger = next(t for t in frame if t.startswith("⟦ctx:facts⟧"))
    assert f"{path} (6 lines now — 4 lines when you last read or wrote it, so the file has changed since)" in ledger
    current = next(t for t in frame if t.startswith("⟦ctx:current⟧"))
    assert f"----- {path} -----\nl1\nl2\nl3\nl4\nl5\nl6" in current
    assert f"----- {tmp_path}/b.py -----\nb1\nb2\n" in current and current.index("b.py") < current.index("a.py")   # its own landed write too, newest first
