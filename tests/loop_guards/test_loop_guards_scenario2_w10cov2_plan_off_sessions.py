"""Scenario2 (w10 COV2): a plan-off session persisted with a NEGATIVE scheduled verdict, reloaded by a fresh store and Loop (a cria restart).

Completion-critical state must survive the restart: a green gate and a done claim must not end the session (with a shell: after the repo's
checks; without one: on the claim itself), and the coder is told the persisted evidence."""
import json

from cria.loop import LoopStore, PlanSession
from cria.plan import Plan, PlanItem
from loop_guards_helpers import Chat, reply
from loop_guards_gatefixture import gate_page
from test_loop_guards_scenario_lb_sessions import GREEN, OK, SHELL, TASK, WRITE, Run, judge, local_view, steer_seen  # noqa: F401

EVIDENCE = "README.md is still absent from the workspace"


def restarted(tmp_path, coder, reasoner=None, **kw):
    """A session persisted with a scheduled negative verdict, then picked up by a brand-new store and Loop (a cria restart)."""
    path = str(tmp_path / "loopstate.json")
    store = LoopStore(state_path=path)
    gone = PlanSession(plan=Plan(id="p", task=TASK, created="c", items=[PlanItem(TASK)]), synthetic=True, plan_off=True,
                       latest_satisfaction=False, latest_satisfaction_evidence=EVIDENCE)
    store.put("sid:k", gone)
    store.persist("sid:k")
    run = Run(tmp_path, coder, reasoner, **kw)
    run.driver._store = LoopStore(state_path=path)
    run.sess = run.driver._store.get("sid:k")
    assert run.sess is not gone and run.sess.latest_satisfaction is False and run.sess.latest_satisfaction_evidence == EVIDENCE
    return run


WRITE_README = reply(None, tool_calls=[{"id": "w", "type": "function", "function": {
    "name": "write_file", "arguments": json.dumps({"path": "README.md", "content": "# app\n"})}}])


def test_a_negative_verdict_that_survived_a_restart_still_bars_the_end_after_a_green_check_and_the_coder_hears_its_evidence(tmp_path):
    """No reasoner can re-judge after the restart, so the persisted verdict is the only voice: the repo's checks run, come back GREEN, and the
    session still does not end - the coder is steered with the verdict's own evidence and is not told the work is verified."""
    coder = Chat(reply("All done."), reply("All done."), WRITE_README)
    run = restarted(tmp_path, coder, tools=(SHELL, WRITE))
    probe = run.turn()
    assert "running the repo's checks" in probe["content"] and run.sess.done_probe
    step = run.turn(GREEN)
    heard = steer_seen(coder, 2)
    assert step["tool_calls"][0]["function"]["name"] == "write_file" and not run.sess.done_probe and not run.ended()
    assert heard.startswith("⟦ctx:steer⟧ The repo's automated checks pass, but a completion check could not confirm the task is finished") and EVIDENCE in heard
    assert run.sess.latest_satisfaction is False                       # only a fresh, positive verdict could clear it


def test_without_a_shell_the_persisted_negative_verdict_steers_on_the_claim_itself_and_states_the_checks_could_not_run(tmp_path):
    """No shell means no gate: a done claim from a session holding a negative verdict is answered with the persisted evidence and
    'the repo's checks could not be run' - never forwarded as the end, never read as a pass."""
    coder = Chat(reply("All done."), reply("All done."), WRITE_README)
    run = restarted(tmp_path, coder, tools=(WRITE,))
    step = run.turn()
    assert step["tool_calls"][0]["function"]["name"] == "write_file" and not run.ended()
    heard = steer_seen(coder, 2)
    assert EVIDENCE in heard and "checks could NOT be run here, so nothing has verified the work" in heard



def deliver(run, content):
    """The harness answers cria's last call with ``content`` (one page) and the loop is driven once more."""
    call = run.out["choices"][0]["message"]["tool_calls"][0]
    run.body["messages"] += [{"role": "assistant", "content": None, "tool_calls": [call]},
                             {"role": "tool", "tool_call_id": call["id"], "content": content}]
    run.out = run.driver.drive(json.loads(json.dumps(run.body)), "sid:k", None, run.log)
    return run.out["choices"][0]["message"]


def test_a_done_probe_whose_output_arrives_in_pages_is_pulled_to_the_last_page_before_anything_steers_the_coder(tmp_path):
    """A long checker output comes back from the harness one page at a time: the first page steers nobody (the coder is not called again, the
    session still holds the claim), cria asks for the rest, and only the COMPLETE red output reaches the coder in the checker's own words."""
    coder = Chat(reply("All done."), reply("All done."), WRITE_README)
    run = Run(tmp_path, coder, tools=(SHELL, WRITE))
    run.turn()
    raw = "___CTX_GATE_probe-0___\napp.py:3: undefined name 'x'\n" + "".join(f"noise {i}\n" for i in range(60)) + "EXIT:1\n___CTX_GATE_git___\nabc\n"
    plan = run.sess.gate_plan
    ask = deliver(run, gate_page(plan, raw, 0, 90))
    assert "receiving the repo's complete check output" in ask["content"] and ask["tool_calls"] and run.sess.done_probe and len(coder.bodies) == 2
    step = deliver(run, gate_page(plan, raw, 90))
    assert step["tool_calls"][0]["function"]["name"] == "write_file" and not run.sess.done_probe
    assert "undefined name 'x'" in steer_seen(coder, 2) and "not done yet" in steer_seen(coder, 2)


def test_a_done_claim_on_a_session_whose_original_task_is_unknown_is_never_approved_and_the_judge_is_not_asked_to_guess(tmp_path):
    """Fail closed: with no recoverable original task the whole-task judge cannot be asked a question, so a GREEN check plus a done claim
    does not end the session - the coder is told the completion check could not confirm the task, and no verdict is invented."""
    asked = []
    coder = Chat(reply("All done."), reply("All done."), WRITE_README)
    run = Run(tmp_path, coder, judge([OK, OK], asked), tools=(SHELL, WRITE))
    run.sess.plan.task = ""
    run.turn()
    step = run.turn(GREEN)
    assert step["tool_calls"][0]["function"]["name"] == "write_file" and not run.ended() and "satisfaction" not in asked
    assert "did not name which deliverable is unfinished" in steer_seen(coder, 2) and run.sess.latest_satisfaction is False
    assert ("loop.done_critic", {"plan_off": True, "satisfied": False, "original_task_unknown": True}) in run.log.events
