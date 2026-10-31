"""Optional context stages through the real driver (Loop.drive) and the real Upstream wire: an unselected stage never runs its
detector, a disabled step framing keeps the required remediation/nudge, restoration credit follows what survives the final-wire
floor. Only the model server's transport is scripted."""
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from cria import (assistruntime, bodykeys, contextfloor, contextrestoration, focustrim, ledgercopies, loop, prompts,
                  reorientation, steppreparation, wsview)
from cria.classify import Classification
from cria.loop import Loop, LoopContext, LoopStore, PlanSession
from cria.plan import Plan, PlanItem
from cria.upstream import Upstream

from loop_main_helpers import Chat, Rlog, SHELL, acting, body, plan_off_loop, synthetic

CODING = Classification("task", "coding", "fixture")
TASK = "Perform the requested action."
READ_CALL = {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
    {"id": "next", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"next.txt"}'}}]}}]}
READ = {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}


def session(planned):
    if not planned:
        return synthetic(TASK)
    return PlanSession(plan=Plan(id="p", task=TASK, created="c", items=[PlanItem(TASK)]))


def real_wire_driver(planned=False, **ctx):
    """A driver whose coder is the REAL Upstream; `posts` collects every /chat/completions body it would send."""
    up = Upstream("http://fixture", context_window=16384, capture_dir=None, capture_rendered=False)
    posts = []

    def transport(request, **options):
        import io
        if not request.full_url.endswith("/v1/chat/completions"):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(READ_CALL).encode())
    up._receive_open = transport
    store = LoopStore()
    store.put("sid", session(planned))
    driver = Loop(LoopContext(planner=None, coder_chat=up.chat, reasoner_chat=None, runs_dir="", planner_enabled=planned, **ctx), store)
    return driver, store.get("sid") if hasattr(store, "get") else None, posts


@pytest.mark.parametrize("planned", [False, True])
def test_an_unselected_context_stage_never_runs_its_detector_and_the_history_ships_untouched(planned):
    """Rung 0 with the compaction/focus switches on: restoration, ledger-copy elision, focus trimming, reorientation, the
    workspace inventory and the step-artifact detector must not even be entered, and the caller's task is what the coder gets."""
    poison = Mock(side_effect=AssertionError("unselected detector ran"))
    originals = []
    for module, name in [(focustrim, "_collapse_duplicates"), (focustrim, "_squash_failures"), (contextrestoration, "restore"),
                         (ledgercopies, "elide"), (reorientation, "_reason"), (loop, "workspace_inventory"),
                         (loop, "step_artifacts_on_disk")]:
        originals.append((module, name, getattr(module, name)))
        setattr(module, name, poison)
    try:
        driver, _, posts = real_wire_driver(planned, self_compact=True, focus_trim=True,
                                            pilot_runtime=assistruntime.AssistRuntime.select(level=0))
        driver.drive({"model": "m", "messages": [{"role": "user", "content": TASK}], "tools": [SHELL, READ]}, "sid", CODING, Rlog())
    finally:
        for module, name, original in originals:
            setattr(module, name, original)
    poison.assert_not_called()
    assert len(posts) == 1 and posts[0]["messages"][1] == {"role": "user", "content": TASK}
    assert not any(m.get(bodykeys.RESTORED_FILES) for m in posts[0]["messages"])


@pytest.mark.parametrize("planned", [False, True])
def test_a_disabled_step_framing_keeps_the_required_remediation_and_the_raw_task_nudge(planned):
    """Original measured missing-file evidence must still reach the coder as the typed remediation and the nudge, and the
    legacy step prompt is never used as a fallback."""
    reason = "Original measured missing-file evidence."
    store = LoopStore()
    sess = session(planned)
    sess.completion_remediation_subject = "missing.txt"
    sess.completion_remediation_reason = sess.nudge_reason = reason
    store.put("sid", sess)
    chat = Chat(acting())
    runtime = assistruntime.AssistRuntime.select(level=5, disabled=(steppreparation.DEFINITION.policy.id,))
    driver = plan_off_loop(chat, store=store, planner_enabled=planned, pilot_runtime=runtime)
    original = loop._item_prompt
    loop._item_prompt = Mock(side_effect=AssertionError("legacy step fallback"))
    try:
        driver.drive(body(TASK), "sid", CODING, Rlog())
    finally:
        loop._item_prompt = original
    sent = chat.bodies[0]
    messages = sent["messages"]
    assert sent[bodykeys.COMPLETION_REMEDIATION] == "missing.txt"
    assert messages[1]["content"] == TASK and messages[-1]["content"] == prompts.render("nudge", reason=reason)
    assert (prompts.load("completion_remediation") in messages[0]["content"]) is planned     # the plan-off frame carries it as the body key
    assert not any("Prioritize this step (" in str(m.get("content")) for m in messages)


def test_the_context_usage_reported_for_a_session_counts_its_prior_work_without_asking_the_step_detector():
    task = body(TASK)
    plain = plan_off_loop(Chat(acting()), store=LoopStore()).visible_context_tokens(task, "sid:u")
    store = LoopStore()
    store.put("sid:u", PlanSession(plan=Plan(id="u", task=TASK, created="", items=[]), summary="Progress",
                                   prior_work="Earlier complete work. " * 400))
    detector = Mock(side_effect=AssertionError("step detector asked for a usage figure"))
    original, loop.step_artifacts_on_disk = loop.step_artifacts_on_disk, detector
    try:
        used = plan_off_loop(Chat(acting()), store=store).visible_context_tokens(task, "sid:u")
    finally:
        loop.step_artifacts_on_disk = original
    detector.assert_not_called()
    assert used >= plain + 1500                         # the prior-work briefing is part of what the coder is shown


@pytest.mark.parametrize("floor_drops_it", [False, True])
def test_restoration_credit_is_earned_only_for_text_that_survives_the_final_wire_floor(tmp_path, monkeypatch, floor_drops_it):
    """The workspace is re-read onto the wire; a restoration the floor then removes must neither reach the model nor count
    as a delivery (else the file is never offered again)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.txt").write_text("fresh exact bytes\n")
    driver, _, posts = real_wire_driver(self_compact=False, focus_trim=False)
    sess = driver._store.get("sid") if hasattr(driver._store, "get") else None
    sess = sess or next(iter(driver._store._sessions.values()))
    sess.workspace_root = str(tmp_path)
    sess.read_files = {"notes.txt": (17, "1 lines")}
    original_fit = contextfloor.fit

    def fit(messages, tools, **budget):
        if floor_drops_it:
            return [m for m in messages if not m.get(bodykeys.RESTORED_FILES)], tools, contextfloor.FloorReport(applied=True)
        return original_fit(messages, tools, **budget)
    monkeypatch.setattr(contextfloor, "fit", fit)
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        driver.drive({"model": "m", "messages": [{"role": "user", "content": TASK}], "tools": [SHELL, READ]}, "sid", CODING, Rlog())
    finally:
        wsview.unbind(token)
    assert len(posts) == 1
    assert ("fresh exact bytes" in json.dumps(posts[0])) is (not floor_drops_it)
    assert set(sess.restored_current) == (set() if floor_drops_it else {"notes.txt"})
