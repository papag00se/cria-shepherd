"""LoopStore: the session registry, the conversation-shape memory behind rewrite detection, and what survives a restart."""

import pytest

from cria.loop import _MAX_SHAPES, LoopStore, PlanSession
from cria.plan import Plan, PlanItem


def test_a_changed_root_under_a_stable_key_is_a_sticky_rewrite_until_the_loop_clears_it():
    """Structural harness-compaction detection, no phrase matching: appended turns never flag; a REPLACED root or a SHRUNK
    history (Codex keeps the user turns and drops the work: 139 compactions, 0 detected) flags and stays flagged (a failed
    plan attempt must not consume the signal) until the loop acts and clears it."""
    store = LoopStore()
    seen = [store.observe_shape("k", "fp1", 3), store.observe_shape("k", "fp1", 9),
            store.observe_shape("k", "fp2", 2), store.observe_shape("k", "fp2", 5)]
    store.clear_rewrite("k")
    seen += [store.observe_shape("k", "fp2", 7), store.observe_shape("k2", "", 1),
             store.observe_shape("h", "fp", 9), store.observe_shape("h", "fp", 3)]      # same root, history SHRANK
    assert seen == [False, False, True, True, False, False, False, True]


def test_the_done_bit_survives_reobservation_and_an_active_shape_is_not_the_one_evicted():
    """The only server-side completion memory is a one-bit marker on the shape; recency refreshes on re-observe, so
    the oldest ABANDONED shape is evicted rather than the session in use."""
    store = LoopStore()
    store.mark_done("sid:unknown")                                       # no shape: a no-op, not a crash
    store.observe_shape("sid:active", "fp", 2)
    store.mark_done("sid:active")
    for i in range(_MAX_SHAPES - 1):
        store.observe_shape(f"sid:e{i}", "x", 1)
    store.observe_shape("sid:active", "fp", 9)
    store.observe_shape("sid:new", "y", 1)
    assert store.shape_done("sid:active") and not store.shape_done("sid:unknown")


def test_a_restart_resumes_a_live_plan_where_it_stopped_and_keeps_the_done_bit_and_rewrite_detection(tmp_path):
    """The restart-amnesia fix: finished steps stay finished, the summary survives, the transient turn state resets."""
    path = str(tmp_path / "loopstate.json")
    first = LoopStore(state_path=path)
    first.observe_shape("sid:x", "rootfp", 4)
    first.mark_done("sid:x")
    plan = Plan(id="p", task="t", created="c", items=[PlanItem("step 1", done=True), PlanItem("step 2")])
    live = PlanSession(plan=plan, summary="1. did the thing")
    live.awaiting_probe = True
    first.put("sid:x", live)
    again = LoopStore(state_path=path)
    resumed = again.get("sid:x")
    assert again.shape_done("sid:x") and again.observe_shape("sid:x", "NEWROOT", 2)
    assert resumed.plan.items[0].done and resumed.plan.current().text == "step 2"
    assert resumed.summary == "1. did the thing" and not resumed.awaiting_probe


@pytest.mark.parametrize("garbage", ["null", "[]", '"a string"', '{"completed": [1,2], "shapes": "nope"}',
                                     '{"completed": {"k": 5}, "shapes": {"k": {"fp": 7}}}'])
def test_a_garbage_state_file_loads_as_an_empty_store_instead_of_crashing_the_service(garbage, tmp_path):
    """A corrupt loopstate.json at startup must not take cria down."""
    path = tmp_path / "loopstate.json"
    path.write_text(garbage)
    store = LoopStore(state_path=str(path))
    assert not store.shape_done("k") and not store.knows("k")
