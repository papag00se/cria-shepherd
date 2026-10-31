"""Planner-ON whole flows (explicit opt-in in every test): a real Planner + real Loop drive a two-step plan against a real tmp
workspace and a real bash harness; only the model boundaries (planner provider, coder, reasoner) are scripted.

Flow: plan parse -> step 1 work -> repo gate probe -> step critic + disk confirmation -> step 2 -> whole-task satisfaction ->
completed-work briefing embedded in the closing -> a follow-up turn reads that briefing back. The second flow makes the step
critic refuse until the stuck-step rescue re-derives the tail."""
import json
import re
import subprocess
from types import SimpleNamespace

import pytest

from cria import assistruntime, completedwork, loop, planner, wsview
from cria.config import Role

from loop_planner_helpers import Rlog

ROLE = Role(name="reasoner", backend="local")
WRITE = {"report.py": "def report():\n    return 1\n",
         "test_report.py": "from report import report\n\ndef test_report():\n    assert report() == 1\n"}
SUMMARY = "report.py holds report(); test_report.py tests it."
JUDGE_OK = '{"done": true, "reason": "ok"}'
SATISFIED = json.dumps({"satisfied": True, "reason": "both files exist and the checks pass", "proposed_fix": ""})


@pytest.fixture(autouse=True)
def local_view():
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


def completion(text=None, calls=()):
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = [{"id": f"t{n}", "type": "function", "function": {"name": name, "arguments": json.dumps(a)}}
                             for n, (name, a) in enumerate(calls)]
    return json.dumps({"choices": [{"finish_reason": "tool_calls" if calls else "stop", "message": msg}]}).encode()


class Provider:
    """The planner's own model: a gather round that lists the directory, then submit_plan with two steps."""
    def __init__(self):
        self.tools_seen = []

    def chat(self, body, log):
        names = {t["function"]["name"] for t in body.get("tools") or ()}
        system = body["messages"][0]["content"]
        self.tools_seen.append(names)
        if "submit_plan" in names:
            return completion(calls=[("submit_plan", {"steps": ["Write report.py", "Write test_report.py"]})])
        if names:
            return completion("Ready to submit the plan.")
        return completion('{"missing": []}' if '"missing"' in system else '{"lost": ""}' if '"lost"' in system else "NONE")


class Reasoner:
    """Answers each closed question by the prompt it is shown; `judge_says` scripts the step critic's verdicts in order."""
    def __init__(self, judge_says=(), tail='["Write test_report.py"]'):
        self.judge_says, self.tail, self.asked = list(judge_says), tail, []

    def __call__(self, body, log):
        system = body["messages"][0]["content"]
        if "Decide one semantic question" in system:      # "must the tests have executed?" - the pytest tally names no file
            self.asked.append("requirement")
            return completion("NOT_REQUIRED")
        kind = ("confirm" if "VERIFICATION CHECKER" in system else "living" if "LIVING plan" in system else
                "writes" if "creating or changing files" in system else "summary" if "handoff summary" in system else
                "noise" if "list of step numbers" in system else "satisfaction" if "JSON verdict" in system else
                "critic" if "You are a JUDGE" in system else "other")
        self.asked.append(kind)
        if kind == "confirm":      # a confirmation that never looks is refused: look at the directory first
            if not any(m["role"] == "tool" for m in body["messages"]):
                return completion(calls=[("list_dir", {"path": "."})])
            return completion('{"consistent": true, "why": ""}')
        if kind == "critic" and "STEP:" in str(body["messages"][-1]["content"]):      # one step, not the whole task
            return completion(self.judge_says.pop(0) if self.judge_says else JUDGE_OK)
        kind = "satisfaction" if kind == "critic" else kind
        return completion({"living": self.tail, "writes": "YES", "satisfaction": SATISFIED,
                            "summary": SUMMARY}.get(kind, "NONE"))


def coder(body, log):
    """Writes the file named by the current step through the shell tool, then claims it is done."""
    step = re.search(r"\(\d of \d\):\n\n(.*)\n", str(body["messages"][-1]["content"]))
    name = "test_report.py" if step and "test_report" in step.group(1) else "report.py"
    if any(m["role"] == "tool" and f"WROTE {name}" in str(m["content"]) for m in body["messages"]):
        return completion(f"I wrote {name}. Done.")
    cmd = f"printf '{WRITE[name]}' > {name}; echo WROTE {name}".replace("\n", "\\n")
    return completion(calls=[("shell", {"command": cmd})])


def run_plan(tmp_path, reasoner, messages=None, key="sid:flow", turns=40):
    """Drive until the loop answers without a tool call, executing every shell command for real in the workspace."""
    owner = planner.Planner(Provider(), role=ROLE)
    runtime = assistruntime.AssistRuntime.select(level=5, experimental_planning=True)
    driver = loop.Loop(loop.LoopContext(owner, coder, reasoner, reasoner_role=ROLE, runs_dir="", workspace_root=str(tmp_path),
                                        planner_enabled=True, self_compact=False, focus_trim=False, pilot_runtime=runtime),
                       loop.LoopStore())
    msgs = messages or [{"role": "user", "content": f"<environment_context><cwd>{tmp_path}</cwd></environment_context>"},
                        {"role": "user", "content": "Implement report.py and its tests."}]
    tools = [{"type": "function", "function": {"name": "shell", "parameters": {
        "type": "object", "properties": {"command": {"type": "string"}}}}}]
    rlog = Rlog()
    for _ in range(turns):
        out = driver.drive({"messages": msgs, "tools": tools}, key, SimpleNamespace(task_type="coding", engagement="task"), rlog)
        msg = out["choices"][0]["message"]
        if not msg.get("tool_calls"):
            return msg["content"], rlog, driver, msgs
        msgs = msgs + [{"role": "assistant", "content": msg.get("content"), "tool_calls": msg["tool_calls"]}]
        for call in msg["tool_calls"]:
            ran = subprocess.run(["bash", "-c", json.loads(call["function"]["arguments"])["command"]], cwd=tmp_path,
                                 capture_output=True, text=True)
            msgs.append({"role": "tool", "tool_call_id": call["id"], "content": ran.stdout + ran.stderr})
    raise AssertionError("the loop never finished")


def fields(rlog, kind):
    return [kw for k, kw in rlog.events if k == kind]


def test_a_two_step_plan_is_worked_verified_closed_with_a_briefing_and_the_briefing_reaches_the_next_turn(tmp_path):
    final, rlog, driver, msgs = run_plan(tmp_path, Reasoner())
    kinds = rlog.kinds()
    assert [e["steps"] for e in fields(rlog, "plan.drafted")] == [2]
    assert [(e["step"], e["text"]) for e in fields(rlog, "loop.item")][::2] == [(1, "Write report.py"), (2, "Write test_report.py")]
    assert [e["step"] for e in fields(rlog, "loop.step_done")] == [1, 2] and all(e["verified"] for e in fields(rlog, "loop.step_done"))
    assert {p.name for p in tmp_path.iterdir()} >= {"report.py", "test_report.py"}       # the harness really ran the writes
    assert kinds.index("loop.step_done") < kinds.index("loop.task_review") < kinds.index("loop.compacted") < kinds.index("loop.done")
    assert "plan complete — all 2 steps verified" in final and completedwork.BRIEFING_OPEN in final
    assert fields(rlog, "loop.task_review")[0]["satisfied"] is True
    briefing = completedwork.read_history(msgs + [{"role": "assistant", "content": final},
                                                  {"role": "user", "content": "now add a README"}])
    assert briefing.status is completedwork.HistoryStatus.PRESENT and briefing.text == SUMMARY
    assert briefing.followup().planner_prior_work == SUMMARY and briefing.followup("rewritten").planner_prior_work == ""


def test_a_critic_that_keeps_refusing_a_step_renudges_then_rederives_the_tail_and_the_plan_still_closes(tmp_path):
    """Four refusals of step 1 is the stuck-step trigger: the living plan is re-derived from the evidence, step 1 is dropped from the
    tail as already covered, and step 2 is driven to a verified close."""
    nope = '{"done": false, "reason": "report.py has no tests yet"}'
    reasoner = Reasoner([nope] * 4)
    final, rlog, driver, _ = run_plan(tmp_path, reasoner)
    assert [e["attempt"] for e in fields(rlog, "loop.step_incomplete")][:4] == [1, 2, 3, 4]
    assert "living" in reasoner.asked and fields(rlog, "loop.stuck_replan")[0]["before"] == 2 and fields(rlog, "loop.stuck_replan")[0]["after"] == 1
    assert [e["text"] for e in fields(rlog, "loop.item")][-1] == "Write test_report.py" and fields(rlog, "loop.item")[-1]["total"] == 1
    assert "loop.done" in rlog.kinds() and "plan complete" in final
