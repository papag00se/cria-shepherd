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

def steers(framed):
    return [m["content"] for m in framed["messages"] if str(m.get("content")).startswith("⟦ctx:steer⟧")]


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

