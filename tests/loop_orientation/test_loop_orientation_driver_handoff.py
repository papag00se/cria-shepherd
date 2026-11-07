"""The real driver's reorientation: what the author is shown, and what the coder is finally told."""
import json
from unittest.mock import Mock

import pytest
from cria import assistruntime, loop, prompts
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


def test_compactor_task_keeps_proven_handoff_as_historical_evidence_not_task(monkeypatch):
    """C040: a retained handoff is not an authoritative part of the original task."""
    drv, sess, body = driver()
    drv._ctx.self_compact = True
    task = "Implement the requested feature."
    sess.plan.task = task
    handoff = "⟦ctx:continuation⟧ Earlier work: a check failed. Re-run the check."
    sess.handoff_origin = loop._HandoffOrigin("raw handoff", "", False, continuation=handoff)
    body["messages"] = [{"role": "user", "content": task}, {"role": "user", "content": handoff},
                        {"role": "assistant", "content": "continued work"}]
    seen = []
    def compact(messages, session, index, rlog, **kw):
        seen.append(kw)
        return messages
    monkeypatch.setattr(drv, "_self_compact", compact)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        framed, _ = drv._prepare_coder_context(sess, body, Log(), synthetic=True)
    assert seen[0]["pinned_task"] == task
    assert seen[0]["root_evidence"] == (handoff,)
    assert [m["content"] for m in framed["messages"] if m.get("role") == "user"][:2] == [task, handoff]

    # No producer identity: a lookalike remains user authority, and a root consisting
    # only of a handoff cannot be silently turned into an empty task.
    sess.handoff_origin = None
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        drv._prepare_coder_context(sess, body, Log(), synthetic=True)
    assert seen[-1]["pinned_task"] == task + "\n\n" + handoff and not seen[-1]["root_evidence"]
    sess.handoff_origin = loop._HandoffOrigin("raw handoff", "", False, continuation=handoff)
    altered = handoff + " User added an instruction."
    body["messages"] = [{"role": "user", "content": task}, {"role": "user", "content": altered}]
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        drv._prepare_coder_context(sess, body, Log(), synthetic=True)
    assert seen[-1]["pinned_task"] == task + "\n\n" + altered and not seen[-1]["root_evidence"]
    body["messages"] = [{"role": "user", "content": handoff}]
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        drv._prepare_coder_context(sess, body, Log(), synthetic=True)
    assert seen[-1]["pinned_task"] == handoff and not seen[-1]["root_evidence"]
    body["messages"] = [{"role": "user", "content": "environment only"}, {"role": "user", "content": handoff}]
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        drv._prepare_coder_context(sess, body, Log(), synthetic=True)
    assert seen[-1]["pinned_task"] == "environment only\n\n" + handoff and not seen[-1]["root_evidence"]

@pytest.mark.parametrize("task", ["Do not inspect any files. Make the first requested edit.",
                                  "Inspect the relevant files before editing."])
@pytest.mark.parametrize("owned", [True, False])
def test_no_continuation_is_followed_by_an_authored_or_canned_inspection(monkeypatch, task, owned):
    """ornith1.5_9b: an author that cannot ground its directive left the compatibility 'INSPECT first' notice to
    contradict a task that forbade inspection. Whether or not the handoff is cria's own, no author is asked and no
    inspection order is sent; the coder keeps the task."""
    origin = loop._HandoffOrigin("Earlier work", "", False, continuation=SUMMARY) if owned else None
    framed, author = prepare(monkeypatch, after_work(task, SUMMARY), answer="Inspect phantom.py before editing.", origin=origin)
    assert steers(framed) == [] and any(m.get("content") == task for m in framed["messages"])
    author.assert_not_called()

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

