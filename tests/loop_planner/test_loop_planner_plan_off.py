"""Plan-off is a degenerate single-item driver; its off-ramps work and persist only on sid: keys."""
import json

import pytest

from cria import assistruntime, loop, wsview
from cria.classify import Classification
from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore, PlanSession, _plan_off_session, _synthetic_plan
from cria.plan import Plan, PlanItem

from loop_planner_helpers import SHELL, Rlog, Scripted, text_reply, tool_call_reply

TASK = "build an ada handle resolver with tests and a README"
CODING = Classification("task", "coding", "fixture")


class ExplodingPlanner:
    def plan_for(self, *a, **k):
        raise AssertionError("the planner was asked to plan without opt-in")


def body():
    return {"messages": [{"role": "user", "content": TASK}], "tools": [SHELL], "stream": True}


def plan_off_loop(coder, store=None, **ctx):
    """Loop built the way production builds plan-off: planner_enabled is NOT passed (default off)."""
    return Loop(LoopContext(planner=ExplodingPlanner(), coder_chat=coder, reasoner_chat=Scripted(tool_call_reply()),
                            runs_dir="", **ctx), store or LoopStore())


@pytest.mark.parametrize("key,persisted", [("sid:conv-1", True), ("task:abc123", False)])
def test_fresh_task_without_opt_in_is_one_raw_item_and_persists_only_on_a_stable_sid_key(key, persisted):
    """A new plan-off task never touches the planner, frames the RAW task (no step cage),
    and is stored only under a content-independent sid: key (a task: key is re-synthesised each turn so
    it cannot leak into an unrelated conversation with the same prompt: the plan-cache-leak class)."""
    seen = []

    def coder(b, rlog):
        seen.append(json.dumps(b["messages"]))
        return json.dumps(tool_call_reply()).encode()
    store = LoopStore()
    out = plan_off_loop(coder, store).drive(body(), key, CODING, Rlog())
    assert out["choices"][0]["message"]["tool_calls"]
    sess = store.get(key)
    assert (sess is not None) is persisted
    if sess:
        assert sess.synthetic and sess.plan_off and [i.text for i in sess.plan.items] == [TASK]
    assert TASK in seen[0] and "Prioritize this step" not in seen[0]


def test_synthetic_session_survives_a_service_restart_on_a_sid_key(tmp_path):
    """The persisted plan-off session is the same one-item raw-task session after reload."""
    path = str(tmp_path / "state.json")
    store = LoopStore(state_path=path)
    plan_off_loop(lambda b, r: json.dumps(tool_call_reply()).encode(), store).drive(body(), "sid:conv-1", CODING, Rlog())
    restored = LoopStore(state_path=path).get("sid:conv-1")
    assert restored.synthetic and restored.plan_off and [i.text for i in restored.plan.items] == [TASK]


def two_item_session():
    plan = Plan(id="x", task=TASK, created="c", items=[PlanItem("Read api.handle.me to learn its shapes"), PlanItem(TASK)])
    return _plan_off_session(plan, "")


@pytest.mark.parametrize("consent", [False, True])
def test_a_hand_built_two_item_plan_off_session_is_still_driven_as_the_raw_task_with_no_replan(consent):
    """2026-08-04 / ef0b771: plan-off was driven through the multi-step machinery (the step cage ('Prioritize this step (2 of 2)'),
    living replans splitting the task); gemma4 went ladder 4/4 -> campaign 0/4, pinned on step 1 for ~88 calls.
    Holds even when planning consent is bound: the session's plan_off/synthetic flags, not config, decide."""
    assert [i.text for i in _synthetic_plan(TASK).items] == [TASK]
    seen = []

    def coder(b, rlog):
        seen.append(json.dumps(b["messages"]))
        return json.dumps(tool_call_reply()).encode()
    reasoner = Scripted(text_reply(json.dumps({"steps": ["split one", "split two"]})))
    runtime = assistruntime.AssistRuntime.select(experimental_planning=consent)
    store, rlog = LoopStore(), Rlog()
    driver = Loop(LoopContext(planner=ExplodingPlanner(), coder_chat=coder, reasoner_chat=reasoner,
                              reasoner_role=Role(name="reasoner", backend="local"), runs_dir="",
                              planner_enabled=consent, pilot_runtime=runtime), store)
    sess = two_item_session()
    assert sess.synthetic and sess.plan_off
    driver._put_session("sid:k", sess)
    driver.drive(body(), "sid:k", None, rlog)
    assert len(seen) == 1 and TASK in seen[0] and "Prioritize this step" not in seen[0] and "(2 of 2)" not in seen[0]
    with assistruntime.bound(runtime):
        driver._advance(sess, "sid:k", body(), 1, 2, rlog)
    assert reasoner.calls == 0 and not {"loop.replan", "loop.replan_noise"} & set(rlog.kinds())
    assert [i.text for i in sess.plan.items][-1] == TASK


# --- satisfaction off-ramp ------------------------------------------------------------------------------

@pytest.mark.parametrize("drive,last,start,every,due", [
    (79, -1, 80, 20, False), (80, -1, 80, 20, True),     # first one keys to start
    (101, 80, 80, 20, True), (119, 80, 80, 20, True),    # a blocked opportunity retries on the NEXT drive
    (99, 80, 80, 20, False), (81, 80, 80, 20, False),    # but never faster than `every` after it RAN
    (500, -1, 80, 0, False), (500, -1, 0, 20, False)])   # zero disables
def test_periodic_check_is_measured_from_when_it_last_ran(drive, last, start, every, due):
    """rust-toml-cli x ternary-bonsai 2026-08-17: with an absolute modulo, 4 of 5 opportunities fell on a
    blocked drive and the off-ramp ran once in 86 calls."""
    assert loop.periodic_check_due(drive, start, every, last) is due


@pytest.mark.parametrize("kw,why", [
    (dict(steer="x"), "steer"), (dict(rewritten=True), "history-rewritten"),
    (dict(done_probe=True), "done-probe-in-flight"), (dict(gate_red=True), "gate-red"),
    (dict(gate_red=True, gate_stall=loop.RED_HOLDS_SATISFACTION_FOR), ""),   # a red that stopped moving stops blocking
    ({}, "")])
def test_satisfaction_blocker_names_its_reason(kw, why):
    """shipping-rates-rb x nemotron-elastic 1787344941: 68 skips all 'gate-red', check never ran in 31 minutes."""
    args = dict(steer=None, rewritten=False, done_probe=False, gate_red=False) | kw
    assert loop._satisfaction_blocker(**args) == why


def test_both_drivers_offer_the_periodic_satisfaction_off_ramp_with_their_own_flag(monkeypatch):
    """nemotron-elastic planner-ON run 1785629694: 145 turns, deliverables done, ZERO satisfaction checks
    because only the plan-off driver called it."""
    calls = []
    monkeypatch.setattr(Loop, "_periodic_satisfaction", lambda self, sess, b, r, *, plan_off, blocked: calls.append(plan_off))
    coder = Scripted(tool_call_reply())
    plan = Plan(id="p", task="t", created="c", items=[PlanItem("one"), PlanItem("two")])
    sess = PlanSession(plan=plan)
    Loop(LoopContext(planner=None, coder_chat=coder, reasoner_chat=coder, runs_dir=""))._work_item(
        sess, "k", body(), Rlog(), sess.plan.items[0], 1)
    solo = PlanSession(plan=Plan(id="p", task="t", created="c", items=[PlanItem("t")]), synthetic=True)
    Loop(LoopContext(planner=None, coder_chat=coder, reasoner_chat=coder, runs_dir="", planner_enabled=False)
         )._drive_single_item(solo, body(), "sid:x", Rlog())
    assert calls == [False, True]


class Sess:
    drive_count, satisfaction_last_drive = 80, -1
    nudge_reason = last_gap_named = steer_source = last_gate_flag = workspace_root = ""
    done_probe = last_gate_red = False
    gate_plan = plan = None


def run_satisfaction(monkeypatch, sess, verdict, *, blocked=False):
    ctx = type("Ctx", (), dict(reasoner_chat=object(), reasoner_role=None,
                               satisfaction_check_start=80, satisfaction_check_every=20))()
    driver, rlog = Loop.__new__(Loop), Rlog()
    driver._ctx = ctx
    monkeypatch.setattr(loop, "judge_satisfaction", lambda *a, **k: verdict)
    monkeypatch.setattr(loop, "_satisfaction_evidence", lambda *a, **k: "evidence")
    monkeypatch.setattr(loop, "_gate_notes", lambda *a, **k: "")
    out = driver._periodic_satisfaction(sess, {"messages": [{"role": "user", "content": "t"}]}, rlog,
                                        plan_off=True, blocked=blocked)
    return out, rlog


def test_a_blocked_check_returns_before_any_model_call(monkeypatch):
    sess = Sess()
    out, rlog = run_satisfaction(monkeypatch, sess, (False, "zone_for missing", ""), blocked="gate-red")
    assert out is None and sess.nudge_reason == "" and sess.satisfaction_last_drive == -1
    assert rlog.events[0][0] == "loop.satisfaction_blocked" and rlog.events[0][1]["why"] == "gate-red"


def test_a_not_satisfied_verdict_names_the_gap_once_and_never_ends_the_session(monkeypatch):
    """shipping-rates-rb x nemotron-elastic: four NOT-satisfied verdicts naming Shipping.zone_for went unheard
    (cell 2/4). feed-pipeline-java x qwen35: TWELVE identical verdicts on a 5/5 workspace. So: reach the coder,
    never twice running, a changed verdict reaches it again, the judge's proposed fix is never carried."""
    sess = Sess()
    out, rlog = run_satisfaction(monkeypatch, sess, (False, "Shipping.zone_for(code) is not implemented.",
                                                     "Add ISO3166::Country and map GB to domestic"))
    assert out is None and "zone_for" in sess.nudge_reason and "ISO3166" not in sess.nudge_reason
    assert "loop.satisfaction_gap_named" in rlog.kinds()
    sess.nudge_reason = ""
    sess.drive_count += 20
    run_satisfaction(monkeypatch, sess, (False, "Shipping.zone_for(code) is not implemented.", ""))
    assert sess.nudge_reason == "", "the same gap was named twice"
    sess.drive_count += 20
    run_satisfaction(monkeypatch, sess, (False, "REVIEW.md has not been written.", ""))
    assert "REVIEW.md" in sess.nudge_reason


@pytest.mark.parametrize("parked,reason", [("", ""), ("an earlier guard's steer", "zone_for is missing")])
def test_silence_over_noise_for_an_empty_reason_or_an_already_parked_steer(monkeypatch, parked, reason):
    sess = Sess()
    sess.nudge_reason = parked
    run_satisfaction(monkeypatch, sess, (False, reason, ""))
    assert sess.nudge_reason == parked


def test_a_missing_file_gap_rearms_only_after_a_new_complete_workspace_observation(monkeypatch):
    """feed-pipeline-java: the same REVIEW.md gap stays quiet until a complete survey of the harness shows the
    workspace changed; an unknown (a mutator ran) or partial survey cannot re-arm it."""
    def survey(content_line, complete=True):
        return ("\n".join(["___CRIA_SV_meta___", "root\t/h", "___CRIA_SV_tree___", content_line,
                           "___CRIA_SV_done___", "entries\t1", f"complete\t{int(complete)}"]))
    view = wsview.View("/h", "feed")
    token = wsview.bind(view)
    try:
        gap = loop.VerdictNudge("REVIEW.md is absent.", diagnosis_kind="missing_file", subject="REVIEW.md")
        sess = Sess()
        sess.workspace_root = "/h"
        assert wsview.apply_survey(view, f"{wsview.SURVEY_OPEN}\n{survey('F\t1\t100\tImporter.java')}\n{wsview.SURVEY_CLOSE}\n")
        run_satisfaction(monkeypatch, sess, (False, gap, ""))
        assert "REVIEW.md" in sess.nudge_reason
        sess.nudge_reason = ""
        sess.drive_count += 20
        run_satisfaction(monkeypatch, sess, (False, gap, ""))
        assert sess.nudge_reason == ""                          # same generation: silent
        assert wsview.apply_survey(view, f"{wsview.SURVEY_OPEN}\n{survey('F\t2\t200\tImporter.java')}\n{wsview.SURVEY_CLOSE}\n")
        sess.drive_count += 20
        _, rlog = run_satisfaction(monkeypatch, sess, (False, gap, ""))
        assert "REVIEW.md" in sess.nudge_reason and any(kw.get("rearmed") for k, kw in rlog.events)
        sess.nudge_reason = ""
        view.note_a_mutator_ran()                               # no current absence fact
        sess.drive_count += 20
        run_satisfaction(monkeypatch, sess, (False, gap, ""))
        assert sess.nudge_reason == ""
    finally:
        wsview.unbind(token)


# --- done-critic off-ramp -------------------------------------------------------------------------------

def test_a_no_shell_done_claim_is_checked_by_the_task_critic_and_not_forwarded_when_unsatisfied(monkeypatch):
    """With no shell the repo gate cannot run; rather than exit BLIND the plan-off driver asks the task critic
    (fail-closed) and re-drives the coder on the RAW task, not a step cage."""
    write = {"type": "function", "function": {"name": "write_file", "parameters": {
        "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}
    frames = []
    replies = [text_reply("done"), {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "tool_calls": [
        {"id": "w", "type": "function", "function": {"name": "write_file", "arguments": '{"path":"a.txt"}'}}]}}]}]

    def coder(b, rlog):
        frames.append(json.dumps(b["messages"]))
        return json.dumps(replies.pop(0)).encode()
    monkeypatch.setattr(loop, "judge_satisfaction", lambda *a, **k: (False, "README.md still needed", ""))
    store = LoopStore()
    sess = _plan_off_session(_synthetic_plan(TASK), "")
    sess.action_seq = 1
    store.put("sid:r", sess)
    driver = Loop(LoopContext(planner=None, coder_chat=coder, reasoner_chat=lambda *a: b"{}",
                              reasoner_role=Role(name="reasoner", backend="local"), runs_dir="", self_compact=False,
                              focus_trim=False, satisfaction_check_start=0), store)
    out = driver.drive({"messages": [{"role": "user", "content": TASK}], "tools": [write]}, "sid:r", None, Rlog())
    assert out["choices"][0]["message"].get("tool_calls") and len(frames) == 2
    assert "README.md still needed" in frames[1] and "Prioritize this step" not in frames[1]
