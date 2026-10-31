"""Whole plan-off sessions through the real Loop (only the coder and reasoner model servers are fake; the harness's
tool results are played by the test): what the coder is shown, what the harness is asked to run, and how each ends.

* done claims: the coder says "done" with no tool call -> cria sends its own check probe -> a RED page steers the coder
  with the checker's own words; a GREEN page still goes to the whole-task judge, whose grounded gap steers it again;
  GREEN and satisfied ends the session.
* wheel-spin: five writes to one path -> cria runs the repo's checks itself and steers the coder with the reading
  (reasoner-authored and vetted when there is a reasoner, the measured floor when there is not).
* scheduled check: a finished task that cannot stop is offered the off-ramp by a timer; its negative verdict reaches the
  coder, its positive one is verified by the repo's checks before the session ends.
"""
import json

import pytest

from cria import bodykeys, denial, wsview
from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore, PlanSession
from cria.plan import Plan, PlanItem
from loop_guards_gatefixture import gate_page
from loop_guards_helpers import Chat, Log, reply

SHELL = {"type": "function", "function": {"name": "shell", "parameters": {
    "type": "object", "properties": {"command": {"type": "array"}}}}}
WRITE = {"type": "function", "function": {"name": "write_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}}
RED = "___CRIA_GATE_probe-0___\napp.py:3: undefined name 'x'\nEXIT:1\n___CRIA_GATE_git___\nabc\n"
GREEN = "___CRIA_GATE_probe-0___\nEXIT:0\n___CRIA_GATE_git___\nabc\n"
TASK = "Build app.py, then write README.md describing it."
QUOTE = "write README.md describing it."
GAP = {"satisfied": False, "reason": "no README", "proposed_fix": "", "diagnosis_kind": "missing_file", "subject": "README.md",
       "task_quote": QUOTE, "evidence_source": "workspace_absence", "evidence_quote": ""}
SILENT = {"satisfied": False, "reason": "", "proposed_fix": ""}
OK = {"satisfied": True, "reason": "all deliverables exist", "proposed_fix": ""}


@pytest.fixture(autouse=True)
def local_view():
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


def say(text=None, **kw):
    return json.dumps(reply(text, **kw)).encode()


def judge(verdicts, asked):
    """A reasoner that answers each of the loop's own questions by phase; verdicts are the whole-task rulings in order."""
    rulings = iter(verdicts)

    def chat(body, rlog):
        asked.append(rlog.phase)
        if rlog.phase == "satisfaction":
            ruling = next(rulings)
            if ruling.get("by_tool"):                                  # the judge declares its verdict as a call, not as text
                return say(None, tool_calls=[{"id": "v", "type": "function", "function": {
                    "name": "verdict", "arguments": json.dumps({k: v for k, v in ruling.items() if k != "by_tool"})}}])
            return say(json.dumps(ruling))
        if rlog.phase == "satisfaction-confirm":                       # the independent look at the files must LOOK first
            if not any(m["role"] == "tool" for m in body["messages"]):
                return say(None, tool_calls=[{"id": "r", "type": "function", "function": {
                    "name": "read_file", "arguments": '{"path": "app.py"}'}}])
            return say("CONSISTENT")
        if rlog.phase == "test-participation-requirement":
            return say("NOT_REQUIRED")
        if rlog.phase == "satisfaction-diagnosis":                     # grounding question about the claimed absence
            return say(json.dumps({"required_output": True, "subject": "README.md", "task_quote": QUOTE}))
        if rlog.phase == "steer-code":                                 # the vetting of an authored steer
            return say("SUPPORTED")
        return say("Run pytest on app.py and read the failure before rewriting it again.")
    return chat


class Run:
    """One plan-off session at 'sid:k'; ``turn`` plays the harness: it answers the previous call, then drives once."""

    def __init__(self, tmp_path, coder, reasoner=None, tools=(SHELL,), **ctx):
        (tmp_path / "app.py").write_text("x = 1\n")
        self.driver = Loop(LoopContext(planner=None, coder_chat=coder, reasoner_chat=reasoner, runs_dir="",
                                       reasoner_role=Role(name="reasoner", backend="local") if reasoner else None,
                                       workspace_root=str(tmp_path), **ctx), LoopStore())
        self.sess = PlanSession(plan=Plan(id="p", task=TASK, created="c", items=[PlanItem(TASK)]), synthetic=True, plan_off=True)
        self.driver._put_session("sid:k", self.sess)
        self.body = {"messages": [{"role": "user", "content": TASK}], "tools": list(tools), "stream": True}
        self.log, self.out = Log(), None

    def turn(self, result=None):
        if self.out is not None:
            call = self.out["choices"][0]["message"]["tool_calls"][0]
            content = result if result is not None else "wrote it"
            if call["function"]["name"] == "shell":             # cria's own check probe: the page the harness would deliver
                content = gate_page(self.sess.gate_plan, result)
            self.body["messages"] += [{"role": "assistant", "content": None, "tool_calls": [call]},
                                      {"role": "tool", "tool_call_id": call["id"], "content": content}]
        self.out = self.driver.drive(json.loads(json.dumps(self.body)), "sid:k", None, self.log)
        return self.out["choices"][0]["message"]

    def ended(self):
        return self.driver._store.get("sid:k") is None


def steer_seen(coder, n):
    return coder.bodies[n]["messages"][-1]["content"]


def test_each_done_claim_is_settled_by_the_repos_checks_then_the_task_judge(tmp_path):
    asked = []
    coder = Chat(reply("All done."), reply("Fixed the name."), reply("Added the README."), reply("Added more."),
                 reply("Now complete."))
    run = Run(tmp_path, coder, judge([GAP, SILENT, {**OK, "by_tool": True}, OK], asked), satisfaction_check_start=0)
    read = {"id": "r0", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": str(tmp_path / "app.py")})}}
    run.body["messages"] += [{"role": "assistant", "content": None, "tool_calls": [read]},
                             {"role": "tool", "tool_call_id": "r0", "content": "x = 1"}]
    probe = run.turn()                                        # claim 1 -> the repo's checks are run, not believed
    assert "running the repo's checks" in probe["content"] and "CRIA_GATE_probe-0" in probe["tool_calls"][0]["function"]["arguments"]
    assert run.sess.done_probe and run.sess.pending_done == "Fixed the name." and len(coder.bodies) == 2   # act-first re-ask, then the probe
    probe = run.turn(RED)                                     # RED: the checker's own message steers the coder
    assert "not done yet" in steer_seen(coder, 2) and "undefined name 'x'" in steer_seen(coder, 2)
    assert not asked and probe["tool_calls"]                  # red never reaches the judge
    probe = run.turn(GREEN)                                   # GREEN, but the judge names a gap -> it reaches the coder
    assert asked.count("satisfaction") == 1 and steer_seen(coder, 3).startswith("⟦ctx:steer⟧") and QUOTE in steer_seen(coder, 3) and probe["tool_calls"]
    probe = run.turn(GREEN)                                   # a judge that names nothing: the coder is told only that it is NOT CONFIRMED
    assert "did not name which deliverable is unfinished" in steer_seen(coder, 4) and "README.md" not in steer_seen(coder, 4)
    final = run.turn(GREEN)                                   # GREEN and satisfied -> done; the session is dropped
    assert final["content"] == "Now complete." and "tool_calls" not in final
    assert asked.count("satisfaction") == 3 and "satisfaction-confirm" in asked and run.ended()
    assert "loop.verdict_by_tool" in run.log.names()                  # the approval that ended it was read off the judge's verdict CALL
    assert [(k, f.get("blocked", f.get("satisfied"))) for k, f in run.log.events if k in ("loop.gate", "loop.done_critic")] == [
        ("loop.gate", True), ("loop.done_critic", False), ("loop.done_critic", False), ("loop.done_critic", True), ("loop.gate", False)]


@pytest.mark.parametrize("reasoner", [True, False])
def test_five_rewrites_of_one_file_run_the_repos_checks_and_steer_with_the_reading(tmp_path, reasoner):
    """Wheel-spin: nothing intervenes on writes 1-5; the sixth drive is cria running the checks; the coder then sees the reading."""
    count = [0]

    def rewrite(body, rlog):
        count[0] += 1
        return say(None, tool_calls=[{"id": f"w{count[0]}", "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": "app.py", "content": f"x = {count[0]}\n"})}}])
    bodies = []
    run = Run(tmp_path, lambda b, r: (bodies.append(b), rewrite(b, r))[1], judge([], []) if reasoner else None, tools=(SHELL, WRITE))
    forwarded = [run.turn() for _ in range(5)]
    assert [json.loads(m["tool_calls"][0]["function"]["arguments"])["content"] for m in forwarded] == [f"x = {i}\n" for i in range(1, 6)]
    probe = run.turn()
    assert "repeated rewrites detected" in probe["content"] and probe["tool_calls"][0]["function"]["name"] == "shell"
    assert run.log.names().count("loop.wheel_spinning") == 1 and len(bodies) == 5   # the probe turn did not spend a coder call
    run.turn(RED)
    shown = "\n".join(m["content"] for m in bodies[5]["messages"][-3:])
    assert "undefined name 'x'" in shown and "⟦ctx:checks⟧" in shown               # the checker's own words reach the coder
    steer = bodies[5]["messages"][-1]["content"]
    assert steer.startswith("⟦ctx:steer⟧")
    assert ("Run pytest on app.py and read the failure" in steer) is reasoner
    assert ("you have rewritten `app.py` repeatedly" in steer) is (not reasoner)


def test_the_scheduled_check_steers_on_a_grounded_gap_and_ends_only_after_the_repos_checks_pass(tmp_path):
    """A coder that finished but cannot stop: drive 1's timer verdict names README.md (grounded on disk) and the coder hears it
    on that same turn; drive 2's verdict is satisfied, so the checks are run ("task looks done") and only a GREEN page ends it."""
    asked = []
    notes = iter(range(100))
    coder = lambda b, r: say(None, tool_calls=[{"id": f"n{next(notes)}", "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({"path": f"notes{next(notes)}.txt", "content": "x"})}}])
    bodies = []
    run = Run(tmp_path, lambda b, r: (bodies.append(b), coder(b, r))[1], judge([GAP, OK, OK], asked),
              tools=(SHELL, WRITE), satisfaction_check_start=1, satisfaction_check_every=1)
    step = run.turn()
    assert step["tool_calls"][0]["function"]["name"] == "write_file"       # the coder still acts; the verdict rode along
    heard = bodies[0]["messages"][-1]["content"]
    assert heard.startswith("⟦ctx:steer⟧ A completion check confirmed that a task-named file is currently absent") and QUOTE in heard and run.log.names().count("loop.satisfaction_check") == 1
    probe = run.turn()
    assert "task looks done" in probe["content"] and run.sess.done_probe and run.sess.pending_done_parts
    final = run.turn(GREEN)
    assert "verified by the completion check and the repo's own checks" in final["content"] and run.ended()


def writer_to_new_files(bodies):
    """A coder that keeps acting on a different file every turn (so no wheel-spin) and records what it was shown."""
    def chat(body, rlog):
        bodies.append(body)
        n = len(bodies)
        return say(None, tool_calls=[{"id": f"n{n}", "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": f"notes{n}.txt", "content": "x"})}}])
    return chat


def test_every_fifteenth_acting_turn_runs_the_checks_and_a_persisting_red_gets_a_reasoned_unstick(tmp_path):
    """The check-in: 15 acting turns -> cria runs the repo's checks itself -> the coder sees the reading as ground truth;
    when the same error is still there 15 turns later the raw reading is replaced by the reasoner's one concrete next step."""
    bodies, asked = [], []
    run = Run(tmp_path, writer_to_new_files(bodies), judge([], asked), tools=(SHELL, WRITE))
    drives = []
    for cycle in range(2):
        acting = 0
        while (step := run.turn(RED))["tool_calls"][0]["function"]["name"] == "write_file":
            acting += 1
        drives.append(acting)
        assert "periodic check-in" in step["content"]
        run.turn(RED)
        shown = bodies[-1]["messages"][-1]["content"]
        if cycle == 0:                                        # first reading: the checker's own words, no reasoner spent
            assert shown.startswith("⟦ctx:steer⟧ I am giving you the CURRENT state") and "undefined name 'x'" in shown and not asked
    assert drives[0] == 15 and drives[1] <= 15                # nothing intervened before the 15th acting turn
    assert shown == "⟦ctx:steer⟧ Run pytest on app.py and read the failure before rewriting it again." and asked == ["reasoner", "steer-code"]


@pytest.mark.parametrize("key,flag,told", [
    (bodykeys.LOST_CALL, {"tried": ["str_replace_editor"], "menu": ["shell", "write_file"]},
     ["`str_replace_editor`, which is not one of your tools", "shell, write_file"]),
    (bodykeys.FENCED_REFUSED, {"reason": "off_menu", "tool": "patch_file", "path": "app.py"},
     ["call to `patch_file` for `app.py`", "`patch_file` is not one of this turn's tools"])])
def test_a_call_cria_could_not_forward_is_said_to_the_coder_not_read_as_done(tmp_path, key, flag, told):
    """cashier 0025 (nemotron-elastic / shipping-rates-rb): a call emitted off-menu was read as a completion claim and spent a
    gate and a judge. The turn is re-asked ONCE with what happened; the retry's real call is forwarded, and no probe ran."""
    bodies = []
    replies = [{**reply(None), key: flag}, reply(None, tool_calls=[{"id": "w", "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({"path": "app.py", "content": "x = 2\n"})}}])]
    run = Run(tmp_path, lambda b, r: (bodies.append(b), json.dumps(replies[len(bodies) - 1]).encode())[1], tools=(SHELL, WRITE))
    step = run.turn()
    assert len(bodies) == 2 and step["tool_calls"][0]["function"]["name"] == "write_file" and not run.sess.done_probe
    assert all(t in bodies[1]["messages"][-1]["content"] for t in told)
    assert key not in step and key not in json.dumps(run.out)


def test_a_done_probe_survives_a_compaction_and_a_corrupt_page_is_never_read_as_green(tmp_path):
    """The harness compacts the history between cria's probe and its result: the result is asked for again (never assumed). The page
    that finally comes back fails its own checksum: the evidence is UNKNOWN, the coder is told so, and the session does not end."""
    coder = Chat(reply("All done."), reply("done again"), reply("still working"))
    run = Run(tmp_path, coder)
    run.turn()
    probe_call = run.out["choices"][0]["message"]["tool_calls"][0]
    run.body["messages"] = [{"role": "user", "content": TASK}, {"role": "user", "content": "[CONTEXT COMPACTION] Summary: all done."}]
    def drive():
        return run.driver.drive(json.loads(json.dumps(run.body)), "sid:k", None, run.log)["choices"][0]["message"]
    poll = drive()                                             # no result survives the fold -> the page is polled for, not guessed
    assert "history was compacted" in poll["content"] and "gate.transport_poll_after_rewrite" in run.log.names() and run.sess.done_probe
    good = gate_page(run.sess.gate_plan, GREEN)
    corrupt = good.replace("sha256\t", "sha256\t0")
    call = poll["tool_calls"][0]
    run.body["messages"] += [{"role": "assistant", "content": None, "tool_calls": [call]},
                             {"role": "tool", "tool_call_id": call["id"], "content": corrupt}]
    step = drive()
    heard = coder.bodies[-1]["messages"][-1]["content"]
    assert heard.startswith("⟦ctx:steer⟧") and "check result is UNKNOWN. This is not a clean or passing result" in heard
    assert "gate.transport_unknown" in run.log.names() and not run.ended()
    assert step["tool_calls"][0]["id"] not in (probe_call["id"], call["id"])      # its next claim is probed afresh, not waved through


def test_repeated_refusals_run_the_repos_checks_and_the_steer_states_only_the_count_cria_measured(tmp_path):
    """Four refused writes (the harness never ran them) are in the history: the coder is not told it is wrong, it is told how many of its
    calls were refused and none ran, beside the repo's own check reading."""
    count = [0]
    bodies = []

    def coder(body, rlog):
        bodies.append(body)
        count[0] += 1
        return say(None, tool_calls=[{"id": f"w{count[0]}", "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": f"f{count[0]}.py", "content": "x"})}}])
    run = Run(tmp_path, coder, tools=(SHELL, WRITE))
    for i in range(4):
        run.body["messages"] += [{"role": "assistant", "content": None, "tool_calls": [{"id": f"x{i}", "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": "/etc/passwd", "content": "x"})}}]},
            {"role": "tool", "tool_call_id": f"x{i}", "content": denial.mark("write_file REFUSED (not written)"),
             bodykeys.RESULT_OUTCOME: denial.REFUSED}]
    run.turn()
    probe = run.turn()
    assert "repeated action detected" in probe["content"] and probe["tool_calls"][0]["function"]["name"] == "shell"
    run.turn(RED)
    steer = bodies[-1]["messages"][-1]["content"]
    assert steer.startswith("⟦ctx:steer⟧") and "4 of your recent calls were refused, so none of them ran" in steer
    assert "undefined name 'x'" in steer                                           # and the checker's own words ride with it


def test_reasoning_that_leaked_into_the_coders_content_never_reaches_the_harness_when_reasoning_is_off(tmp_path):
    leaky = reply("private musings about the task</think>Writing the file now.", tool_calls=[{
        "id": "w", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "n.py", "content": "x"})}}])
    run = Run(tmp_path, Chat(leaky), tools=(SHELL, WRITE), coder_role=Role(name="coder", backend="local", reasoning="off"))
    assert run.turn()["content"] == "Writing the file now."
