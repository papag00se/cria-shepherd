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
RED = "___CTX_GATE_probe-0___\napp.py:3: undefined name 'x'\nEXIT:1\n___CTX_GATE_git___\nabc\n"
GREEN = "___CTX_GATE_probe-0___\nEXIT:0\n___CTX_GATE_git___\nabc\n"
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
        if rlog.phase == "satisfaction-diagnosis":
            question = "\n".join(str(m.get("content", "")) for m in body["messages"])
            if "required_output" in question:
                return say(json.dumps({"required_output": True, "subject": "README.md", "task_quote": QUOTE}))
            return say("SUPPORTED")
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
    run = Run(tmp_path, coder, judge([GAP, SILENT, {**OK, "by_tool": True}, OK], asked), satisfaction_check_start_minutes=0)
    read = {"id": "r0", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": str(tmp_path / "app.py")})}}
    run.body["messages"] += [{"role": "assistant", "content": None, "tool_calls": [read]},
                             {"role": "tool", "tool_call_id": "r0", "content": "x = 1"}]
    probe = run.turn()                                        # claim 1 -> the repo's checks are run, not believed
    assert "running the repo's checks" in probe["content"] and "CTX_GATE_probe-0" in probe["tool_calls"][0]["function"]["arguments"]
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
    failed = {"satisfied": False, "reason": "The app still contains an undefined name.", "diagnosis_kind": "failed_check",
              "task_quote": "Build app.py", "evidence_source": "checks", "evidence_quote": "undefined name 'x'"}
    run = Run(tmp_path, lambda b, r: (bodies.append(b), rewrite(b, r))[1], judge([failed], []) if reasoner else None, tools=(SHELL, WRITE))
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
    assert ("Build app.py" in steer and "undefined name 'x'" in steer) is reasoner
    assert ("you have rewritten `app.py` repeatedly" in steer) is (not reasoner)


@pytest.mark.parametrize("refusal", [False, True], ids=["wheel-spin", "refusal"])
@pytest.mark.parametrize("verdict,delivered", [
    ({**SILENT, "on_track": True}, False),
    ({**SILENT, "on_track": True, "by_tool": True}, False),
    ({**OK}, False),
    ({**SILENT, "reason": "unsupported claim"}, False),
    (GAP, True),
], ids=["productive-incomplete", "productive-tool-verdict", "already-complete", "ungrounded", "missing-output"])
def test_stuck_review_shares_task_evidence_delivery_and_cadence_without_completion_or_s1(tmp_path, verdict, delivered, refusal):
    """A wheel-spin requests one task-aware inspection, not a second timer verdict or a canned rescue.
    The focused result cannot release completion, and next-turn completion claims still need their own review."""
    from cria import completionreview

    class NoS1:
        def __getattr__(self, name):
            pytest.fail("task review must not call System 1")

    bodies, asked, inspected = [], [], []
    base = judge([verdict, SILENT], asked)
    def reasoner(body, log):
        inspected.append((log.phase, body))
        return base(body, log)
    count = [0]
    def coder(body, log):
        bodies.append(body)
        count[0] += 1
        return say(None, tool_calls=[{"id": f"w{count[0]}", "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": "app.py", "content": f"x = {count[0]}"})}}])

    run = Run(tmp_path, coder, reasoner, tools=(SHELL, WRITE), system1=NoS1(), satisfaction_check_start_minutes=0)
    for _ in range(5):
        run.turn()
    run.turn()  # guard asks the harness for current checks
    if refusal:
        from cria import stalledwork
        # Exercise the other detector's returned-probe contract at the same real driver boundary.
        run.sess.stalled_probe = stalledwork.PendingProbe(stalledwork.Trigger.REFUSAL, run.sess.stalled_probe.call)
        run.sess.repeat_count, run.sess.repeat_action = 3, "refused write"
    run.sess.latest_satisfaction, run.sess.latest_satisfaction_evidence = False, "held negative completion verdict"
    run.sess.pending_done, run.sess.pending_done_parts = "held claim", ("held",)
    # Make the timer due on the very turn its guard result returns: the focused inspection must consume the opportunity.
    ctx = run.driver._ctx
    ctx.satisfaction_check_start_minutes = ctx.satisfaction_check_every_minutes = 1
    ctx.satisfaction_check_min_turns = ctx.satisfaction_check_max_turns = 1
    result = run.turn(RED)
    assert result["tool_calls"] and not run.ended()
    assert asked.count("satisfaction") == 1 and "deliverable-observation" not in asked
    review = next(body for phase, body in inspected if phase == "satisfaction")
    packet = "\n".join(str(m.get("content", "")) for m in review["messages"])
    assert TASK in packet and "README.md" in packet and "x = 5" in packet and "undefined name 'x'" in packet
    assert ("refused" if refusal else "rewrit") in packet and "on_track" in packet
    answer_tool = next(t["function"] for t in review["tools"] if t["function"]["name"] == "verdict")
    assert answer_tool["parameters"]["properties"]["on_track"]["type"] == "boolean"
    assert run.sess.latest_satisfaction is False and run.sess.latest_satisfaction_evidence == "held negative completion verdict"
    assert run.sess.pending_done == "held claim" and run.sess.pending_done_parts == ("held",)
    notes = [m["content"] for m in bodies[-1]["messages"] if m["role"] == "user" and m["content"].startswith("⟦ctx:steer⟧")]
    assert bool(notes) is delivered
    if delivered:
        assert len(notes) == 1 and QUOTE in notes[0] and run.sess.completion_remediation_subject == "README.md"
        assert "loop.satisfaction_gap_named" in run.log.names()
    else:
        assert not run.sess.nudge_reason and not run.sess.completion_remediation_subject
    assert [(f["trigger"], f["status"]) for k, f in run.log.events if k == "loop.task_review"] == [
        (completionreview.ReviewTrigger.STUCK.value, "guidance" if delivered else "on-track" if verdict.get("on_track") or verdict.get("satisfied") else "withheld")]


def test_plan_on_focused_review_reaches_the_same_coder_turn_without_a_second_scheduled_review(tmp_path):
    """The step driver settles a guard before incrementing its work-drive clock; coalescing must use that next drive."""
    from cria import assistruntime, stalledwork
    from cria.loop import _StalledWorkView
    bodies, asked = [], []
    run = Run(tmp_path, writer_to_new_files(bodies), judge([GAP], asked), tools=(SHELL, WRITE),
              satisfaction_check_start_minutes=1, satisfaction_check_every_minutes=1,
              satisfaction_check_min_turns=1, satisfaction_check_max_turns=1)
    run.sess.synthetic = run.sess.plan_off = False
    run.sess.workspace_root = str(tmp_path)
    run.driver._ctx.planner_enabled = True  # explicit test-only planner opt-in
    run.sess.drive_count, run.sess.spin_path = 4, "app.py"
    ticket = stalledwork.PendingProbe(stalledwork.Trigger.WHEEL_SPIN, {"id": "guard"})
    run.sess.stalled_probe = ticket
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        service = run.driver._probe_author("wheel_spin", run.sess, None, run.body, run.log)
        settled = stalledwork.DEFINITION.settle(stalledwork.ReturnedProbeInput(
            ticket, lambda: None, lambda: "current checker output", service, run.log),
            _StalledWorkView(run.sess))
        assert settled.steer is not None
        out = run.driver._work_item(run.sess, "sid:k", run.body, run.log, run.sess.plan.items[0], 1)
    assert out["choices"][0]["message"]["tool_calls"] and not run.ended()
    assert run.sess.drive_count == run.sess.task_review_last_drive == 5
    assert asked.count("satisfaction") == 1 and "deliverable-observation" not in asked
    notes = [m["content"] for m in bodies[0]["messages"] if str(m.get("content", "")).startswith("⟦ctx:steer⟧")]
    assert len(notes) == 1 and QUOTE in notes[0]
    assert run.sess.latest_satisfaction is None and run.sess.completion_remediation_subject == "README.md"


def test_the_scheduled_check_steers_on_a_grounded_gap_and_ends_only_after_the_repos_checks_pass(tmp_path):
    """A coder that finished but cannot stop: drive 1's timer verdict names README.md (grounded on disk) and the coder hears it
    on that same turn; drive 2's verdict is satisfied, so the checks are run ("task looks done") and only a GREEN page ends it."""
    asked = []
    notes = iter(range(100))
    coder = lambda b, r: say(None, tool_calls=[{"id": f"n{next(notes)}", "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({"path": "README.md", "content": "docs"})}}])
    bodies = []
    run = Run(tmp_path, lambda b, r: (bodies.append(b), coder(b, r))[1], judge([GAP, OK, OK], asked),
              tools=(SHELL, WRITE), satisfaction_check_start_minutes=1, satisfaction_check_every_minutes=1,
              satisfaction_check_min_turns=1, satisfaction_check_max_turns=1)
    step = run.turn()
    assert step["tool_calls"][0]["function"]["name"] == "write_file"       # the coder still acts; the verdict rode along
    heard = bodies[0]["messages"][-1]["content"]
    assert heard.startswith("⟦ctx:steer⟧ A completion check confirmed that a task-named file is currently absent") and QUOTE in heard and run.log.names().count("loop.satisfaction_check") == 1
    (tmp_path / "README.md").write_text("docs\n")
    probe = run.turn("Wrote README.md")
    assert "task looks done" in probe["content"] and run.sess.done_probe and run.sess.pending_done_parts
    final = run.turn(GREEN)
    assert "verified by the completion check and the repo's own checks" in final["content"] and run.ended()


@pytest.mark.parametrize("blocked", ["red", "steer", "both"])
@pytest.mark.parametrize("plan_off", [True, False])
def test_one_task_review_finds_a_missing_deliverable_without_waiting_for_checks_or_ordinary_steering(tmp_path, blocked, plan_off):
    """A failing check or parked steer cannot starve task coverage; no second observer competes with it."""
    bodies, asked = [], []
    run = Run(tmp_path, writer_to_new_files(bodies), judge([GAP], asked), tools=(SHELL, WRITE),
              satisfaction_check_start_minutes=1, satisfaction_check_every_minutes=1,
              satisfaction_check_min_turns=1, satisfaction_check_max_turns=1)
    run.sess.last_gate_red = blocked in ("red", "both")
    if blocked in ("steer", "both"):
        run.sess.nudge_reason = "ordinary check steer"
    if plan_off:
        run.turn()
    else:
        from cria import assistruntime
        run.sess.synthetic = run.sess.plan_off = False
        run.sess.workspace_root = str(tmp_path)
        run.driver._ctx.planner_enabled = True  # explicit test-only planner opt-in
        with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
            run.driver._work_item(run.sess, "sid:k", run.body, run.log, run.sess.plan.items[0], 1)
    assert asked.count("satisfaction") == 1
    assert "deliverable-observation" not in asked
    notes = [m["content"] for m in bodies[0]["messages"] if m["role"] == "user" and m["content"].startswith("⟦ctx:steer⟧")]
    assert len(notes) == 1 and QUOTE in notes[0] and "ordinary check steer" not in notes[0]
    assert run.sess.last_gate_red is (blocked in ("red", "both"))
    assert run.sess.completion_remediation_subject == "README.md" and not run.ended()


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
    failed = {"satisfied": False, "reason": "The app still contains an undefined name.", "diagnosis_kind": "failed_check",
              "task_quote": "Build app.py", "evidence_source": "checks", "evidence_quote": "undefined name 'x'"}
    run = Run(tmp_path, writer_to_new_files(bodies), judge([failed], asked), tools=(SHELL, WRITE))
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
    assert shown.startswith("⟦ctx:steer⟧") and "Build app.py" in shown and "undefined name 'x'" in shown
    assert asked == ["satisfaction", "satisfaction-diagnosis"]
    assert any(k == "loop.task_review" and f["trigger"] == "stuck" for k, f in run.log.events)


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


READ = {"type": "function", "function": {"name": "read_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}


def test_shared_task_review_delivers_acknowledges_and_settles_a_missing_deliverable_over_a_red_gate_and_a_parked_steer(tmp_path):
    """Retains the scheduled observer's incident coverage after its consolidation into task review: even under a RED gate
    (the review neither waits for nor clears it), a task-named absent file reaches the coder REPLACING a parked ordinary steer,
    rides every later body (once, never duplicated), is acknowledged by the reply's inspection, draws one non-write follow-up
    after that result, and is released only by the harness's own write result for the exact file."""
    asked, bodies = [], []
    script = iter([("read_file", {"path": "app.py"}), ("read_file", {"path": "app.py"}),
                   ("write_file", {"path": "README.md", "content": "x"}), ("write_file", {"path": "notes.txt", "content": "x"})])

    def coder(body, rlog):
        bodies.append(body)
        name, args = next(script)
        return say(None, tool_calls=[{"id": f"c{len(bodies)}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}])

    run = Run(tmp_path, coder, judge([GAP, GAP], asked), tools=(SHELL, WRITE, READ), satisfaction_check_start_minutes=1,
              satisfaction_check_every_minutes=1, satisfaction_check_min_turns=1, satisfaction_check_max_turns=1)
    run.sess.last_gate_red, run.sess.nudge_reason, run.sess.steer_source = True, "GATE-RED-STEER", "completion gate (repo checks failed)"

    def users(n):
        return [m["content"] for m in bodies[n]["messages"] if m["role"] == "user" and m["content"].startswith("⟦ctx:steer⟧")]

    first = run.turn()                                                  # shared review fires on the first due drive, gate still red
    assert asked.count("satisfaction") == 1 and "deliverable-observation" not in asked
    assert run.sess.completion_remediation_subject == "README.md" and run.sess.task_review_last_drive == 1
    assert len(users(0)) == 1 and "README.md" in users(0)[0] and "GATE-RED-STEER" not in users(0)[0]   # replaced, delivered once
    assert first["tool_calls"] and run.sess.completion_remediation_nonwrite_ids == ("c1",)  # acknowledged by its inspection
    run.turn("x = 1")                                                   # the inspection's result: one follow-up, remediation still carried
    assert asked.count("satisfaction") == 1                            # armed: the review stays out
    assert any("remediation remains open" in u for u in users(1)) and sum("README.md" in u for u in users(1)) == 1
    run.turn("x = 1")                                                   # remediation survives the follow-up, not duplicated
    assert run.sess.completion_remediation_subject == "README.md" and sum("README.md" in u for u in users(2)) == 1
    (tmp_path / "README.md").write_text("docs\n")
    run.turn("Wrote README.md")                                         # the harness's write result releases it
    assert run.sess.completion_remediation_subject == "" and not any("README.md" in u for u in users(3))
    assert "loop.completion_remediation_written" in run.log.names()
