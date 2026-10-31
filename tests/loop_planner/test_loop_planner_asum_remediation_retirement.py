"""Planner ON, opted in explicitly (planning is OFF by policy; nothing here is the default system): a remediation armed for a missing
REPORT.md survives the coder writing it through a shell redirect that exits 0, because cria's own `Wrote PATH` confirmation never
appears for it. The real `_work_item` retires it on the next turn only from a harness fact - a fresh complete survey listing the exact
file, or a whole read of it - and never from the exit code, and never approves the step."""
import json
import subprocess

import pytest

from cria import assistruntime, loop, wsview
from cria.loop import Loop, LoopContext, LoopStore, PlanSession
from cria.plan import Plan, PlanItem

from loop_planner_helpers import Rlog

TASK = "Implement the cart, then add `REPORT.md` describing remaining risks."
SUBJECT = "REPORT.md"


def redirect_turn(root, command):
    """The coder's own exec_command, run for real, with the harness's exec envelope around its result."""
    run = subprocess.run(["bash", "-c", command], cwd=root, capture_output=True, text=True)
    return [{"role": "assistant", "content": None, "tool_calls": [{"id": "r1", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"cmd": command})}}]},
            {"role": "tool", "tool_call_id": "r1", "content": f"Process exited with code {run.returncode}\nOutput:\n{run.stdout}{run.stderr}"}]


def survey_into(view, root):
    out = subprocess.run(["bash", "-lc", wsview.survey_command("asum", cd=str(root))], capture_output=True, text=True).stdout
    assert wsview.apply_survey(view, wsview.strip_survey(out)[1])


class Turn:
    """Runs `_work_item` with the coder stubbed, so the only thing that can retire the remediation is cria's own settle."""
    def __init__(self, root, view):
        self.root, self.view = root, view
        runtime = assistruntime.AssistRuntime.select(level=5, experimental_planning=True)
        self.drv = Loop(LoopContext(planner=None, coder_chat=lambda *a: b"{}", reasoner_chat=lambda *a: b"{}", runs_dir="",
                                    workspace_root=str(root), planner_enabled=True, self_compact=False, focus_trim=False,
                                    pilot_runtime=runtime), LoopStore())
        assert self.drv._ctx.planner_enabled is True                              # explicit opt-in, as the policy requires
        self.sess = PlanSession(plan=Plan(id="t", task=TASK, created="now", items=[PlanItem("Write REPORT.md")]), workspace_root=str(root))
        self.sess.plan.status = "in_progress"

    def arm(self):
        with assistruntime.bound(self.drv._ctx.pilot_runtime):
            loop._arm_completion_remediation(self.sess, SUBJECT, "REPORT.md is missing")

    def run(self, messages):
        log, offered = Rlog(), []
        self.drv._coder_turn = lambda sess, framed, raw, **k: offered.append(framed) or loop._completion_toolcalls(
            [{"id": "i", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}])
        token = wsview.bind(self.view)
        try:
            with assistruntime.bound(self.drv._ctx.pilot_runtime):
                self.drv._work_item(self.sess, "sid:asum", {"messages": messages, "tools": []}, log, self.sess.plan.items[0], 0)
        finally:
            wsview.unbind(token)
        return log, offered


@pytest.fixture
def armed_turn(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    view = wsview.View(str(tmp_path), "asum")
    survey_into(view, tmp_path)
    turn = Turn(tmp_path, view)
    turn.arm()
    base = [{"role": "user", "content": TASK}]
    turn.run(base)
    assert turn.sess.completion_remediation_subject == SUBJECT                    # armed and surviving a turn that wrote nothing
    return turn, base


@pytest.mark.parametrize("command,resurvey,retired", [
    ("echo risks > REPORT.md", True, True),                  # the Lifecycle-frontier case: exit 0, no `Wrote PATH`, file exists
    ("echo risks > REPORT.md", False, False),                # the same exit 0 with no survey since proves nothing about the disk
    ("echo risks > OTHER.md", True, False),                  # different file
    ("echo risks > nodir/REPORT.md", True, False),           # the redirect failed
    ("ls", True, False),                                     # unrelated success
])
def test_a_shell_redirect_retires_a_plan_on_remediation_only_through_a_fresh_survey_of_the_exact_file(armed_turn, command, resurvey, retired):
    turn, base = armed_turn
    messages = base + redirect_turn(turn.root, command)
    turn.view.note_a_mutator_ran()
    if resurvey:
        survey_into(turn.view, turn.root)
    log, offered = turn.run(messages)
    assert (turn.sess.completion_remediation_subject == "") is retired
    assert ("loop.completion_remediation_present" in log.kinds()) is retired
    assert not turn.sess.plan.items[0].done and turn.sess.plan.status == "in_progress"      # retirement is not completion
    assert len(offered) == 1                                                                  # the coder is still driven, never handed back


def test_a_whole_read_of_the_subject_after_the_redirect_retires_it_too(armed_turn):
    turn, base = armed_turn
    messages = base + redirect_turn(turn.root, "echo risks > REPORT.md")
    turn.view.note_a_mutator_ran()
    turn.view.note_read(str(turn.root / SUBJECT), "risks\n")
    turn.run(messages)
    assert turn.sess.completion_remediation_subject == ""
