"""The real driver's reorientation: what the author is shown, and what the coder is finally told."""
from unittest.mock import Mock

import pytest
from cria import assistruntime, loop
from cria.config import Role
from loop_orientation_helpers import Log, driver, local_workspace_view  # noqa: F401

TASK = "Use a third-party CSV library; do not write a custom parser. Produce REVIEW.md."
SUMMARY = f"{loop.CONTINUATION_MARKER} Dependency resolution failed. Importer.java is partly written."
LISTING = "FILES ON DISK — WORKSPACE SURVEY (names observed, newest first).\n  src/main/java/pipeline/Importer.java (11796 B)"

def prepare(monkeypatch, messages, *, answer="Inspect Importer.java before continuing.", origin=None, root=""):
    """Run the real _prepare_coder_context at L5 with a scripted author; returns (framed body, author calls)."""
    drv, sess, body = driver()
    drv._ctx.reasoner_role = Role(name="reasoner", backend="local")
    sess.workspace_root = root
    sess.handoff_origin = origin
    body["messages"] = messages
    author = Mock(return_value=answer)
    monkeypatch.setattr(loop, "summarize", author)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        return drv._prepare_coder_context(sess, body, Log(), synthetic=True, rewritten=True)[0], author

def after_work(task, summary):
    """A task, a prior tool turn, then the continuation: the work-role boundary that marks the summary as history."""
    return [{"role": "user", "content": task},
            {"role": "assistant", "tool_calls": [{"id": "ls", "type": "function", "function": {
                "name": "list_dir", "arguments": '{"path":"."}'}}]},
            {"role": "tool", "tool_call_id": "ls", "content": "README.md\npom.xml\n"},
            {"role": "user", "content": summary}]

def steers(framed):
    return [m["content"] for m in framed["messages"] if str(m.get("content")).startswith("⟦ctx:steer⟧")]

def test_author_gets_the_task_apart_from_the_history_and_the_coder_keeps_the_task(monkeypatch):
    """A failed-dependency summary cannot erase the library requirement nor pass for the task itself."""
    framed, author = prepare(monkeypatch, after_work(TASK, SUMMARY))
    system, grounding = author.call_args.args[2:4]
    assert grounding.index(TASK) < grounding.index("HISTORICAL CONTINUATION") < grounding.index(SUMMARY)
    assert "requirements are not evidence of completed work" in system
    assert any(m.get("content") == TASK for m in framed["messages"])
    assert "Importer.java" in steers(framed)[0]

    _, only = prepare(monkeypatch, [{"role": "user", "content": SUMMARY}])
    grounding = only.call_args.args[3]
    assert "Original task not independently available" in grounding and grounding.count(SUMMARY) == 1

@pytest.mark.parametrize("task", ["Do not inspect any files. Make the first requested edit.",
                                  "Inspect the relevant files before editing."])
def test_a_handoff_cria_produced_never_overrides_the_task_with_a_canned_inspection(monkeypatch, task):
    """ornith1.5_9b: an author that cannot ground its directive left the compatibility 'INSPECT first' notice to
    contradict a task that forbade inspection. With a producer-owned handoff the optional steer is simply omitted."""
    origin = loop._HandoffOrigin("Earlier work", "", False, continuation=SUMMARY)
    framed, _ = prepare(monkeypatch, after_work(task, SUMMARY), answer="Inspect phantom.py before editing.", origin=origin)
    assert steers(framed) == [] and any(m.get("content") == task for m in framed["messages"])

@pytest.mark.parametrize("recorded_for,root,shown", [
    ("same", "/w", True),                       # the listing the briefing writer saw reaches the orienter
    ("other-boundary", "/w", False),            # a continuation cria did not produce gets no listing
    ("same", "/elsewhere", False),              # a listing for another workspace root is not this disk
])
def test_orienter_sees_the_disk_the_briefing_was_written_against(monkeypatch, recorded_for, root, shown):
    """ornith1.5_9b / Java run 4 (01a18337): compaction removed every survey, so the orienter's inventory was empty in
    28 of 32 prompts; it read a folded line as the whole tree, and the coder restored the seed over its rewrite (2%)."""
    other = f"{loop.CONTINUATION_MARKER} A handoff cria did not produce."
    origin = loop._HandoffOrigin("Built Importer.java.", "", False,
                                 continuation=SUMMARY if recorded_for == "same" else other)
    origin.inventory, origin.inventory_root = LISTING, "/w"
    _, author = prepare(monkeypatch, after_work(TASK, SUMMARY), origin=origin, root=root)
    assert ("Importer.java (11796 B)" in author.call_args.args[3]) is shown


@pytest.mark.parametrize("plan_off", [True, False])
def test_a_gap_named_by_the_scheduled_review_reaches_the_coder_turn_it_precedes_and_is_consumed(monkeypatch, plan_off):
    """10bc361d: the pending note was resolved BEFORE the scheduled satisfaction review ran, so a grounded negative it produced waited a
    whole extra request (the coder drove one more turn blind to it). The note must be on THIS turn's body, once, then cleared."""
    drv, sess, body = driver()
    drv._ctx.assists = True
    sess.plan_off = plan_off

    def review(self, sess, body, rlog, *, plan_off, blocked):
        sess.nudge_reason = "The measured source still lacks the required content."
        return None
    monkeypatch.setattr(loop.Loop, "_periodic_satisfaction", review)
    for name in ("guard_intervene", "guard_probe_reissue", "guard_periodic_gate"):
        monkeypatch.setattr(loop, name, lambda *a, **k: None)
    monkeypatch.setattr(drv, "_periodic_step_check", lambda *a, **k: None)
    monkeypatch.setattr(drv, "_replan_if_thrashing", lambda *a, **k: None)
    offered, reply = [], loop._completion_toolcalls([{"id": "i", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}])
    monkeypatch.setattr(drv, "_coder_turn", lambda sess, framed, raw, **k: offered.append(framed) or reply)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        run = drv._drive_single_item(sess, body, "sid:k", Log()) if plan_off else drv._work_item(sess, "sid:k", body, Log(), sess.plan.items[0], 1)
    assert run is reply and len(offered) == 1
    assert "still lacks the required content" in "\n".join(str(m.get("content", "")) for m in offered[0]["messages"])
    assert not sess.nudge_reason
