"""Scenario2 (w10 COV2): a plan-off session persisted with a NEGATIVE scheduled verdict, reloaded by a fresh store and Loop (a cria restart).

Completion-critical state must survive the restart: a green gate and a done claim must not end the session (with a shell: after the repo's
checks; without one: on the claim itself), and the coder is told the persisted evidence."""
import json

from cria.loop import LoopStore, PlanSession
from cria.plan import Plan, PlanItem
from loop_guards_helpers import Chat, reply
from test_loop_guards_scenario_lb_sessions import GREEN, SHELL, TASK, WRITE, Run, local_view, steer_seen  # noqa: F401

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

