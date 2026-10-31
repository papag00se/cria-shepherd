"""Scenario2 (LA2): the session registry across a service lifetime - rewrite tickets that outlive appends and restarts, an oversized or
unwritable state file, guard-only owners that age out, the per-session lock table, and a legacy refusal set meeting a structured ledger."""
import json

from cria import refusalledger
from cria.loop import _MAX_SESSIONS, _MAX_SHAPES, Loop, LoopContext, LoopStore, PlanSession, SurveyBootstrap, _session_to_dict
from cria.plan import Plan, PlanItem


def session(task="t"):
    return PlanSession(plan=Plan(id="p", task=task, created="c", items=[PlanItem("s")]))


def test_a_rewrite_ticket_keeps_one_identity_through_appends_and_a_restart_and_only_its_own_ack_clears_it(tmp_path):
    path = str(tmp_path / "state.json")
    store = LoopStore(state_path=path)
    assert store.observe_shape_with_ticket("sid:a", "root", 6) is None
    ticket = store.observe_shape_with_ticket("sid:a", "root", 2)              # history shrank: the harness compacted
    assert ticket is not None and ticket.key == "sid:a"
    assert store.observe_shape_with_ticket("sid:a", "root", 9).event_id == ticket.event_id    # appends keep the same event
    again = LoopStore(state_path=path)                                         # restart mid-compaction
    assert again.observe_shape_with_ticket("sid:a", "root", 10).event_id == ticket.event_id
    newer = again.observe_shape_with_ticket("sid:a", "OTHER", 12)
    assert newer.event_id != ticket.event_id
    assert not again.ack_rewrite(ticket) and not again.ack_rewrite(None) and not again.ack_rewrite("sid:a")
    assert again.ack_rewrite(newer) and not again.ack_rewrite(newer)           # a stale or repeated ack consumes nothing
    assert again.observe_shape_with_ticket("sid:a", "OTHER", 13) is None
    assert again.observe_shape_with_ticket("sid:a", "", 1) is None             # no fingerprint: nothing to compare


def test_an_oversized_state_file_loads_only_its_newest_entries_and_an_unwritable_one_never_breaks_a_turn(tmp_path):
    path = tmp_path / "state.json"
    sessions = {f"sid:{i}": _session_to_dict(session(f"task {i}")) for i in range(_MAX_SESSIONS + 5)}
    shapes = {f"sid:{i}": {"fp": "f", "n": 1, "pending": False, "done": False} for i in range(_MAX_SHAPES + 5)}
    path.write_text(json.dumps({"sessions": sessions, "shapes": shapes}))
    store = LoopStore(state_path=str(path))
    assert store.get("sid:0") is None and store.get("sid:4") is None and store.get("sid:5").plan.task == "task 5"
    assert store.get(f"sid:{_MAX_SESSIONS + 4}") is not None and not store.knows("sid:4") and store.knows("sid:5")
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    broken = LoopStore(state_path=str(blocked / "state.json"))
    broken.put("sid:x", session())
    broken.persist("sid:x")
    broken.persist("sid:never-put")
    assert broken.get("sid:x") is not None and not blocked.is_dir() and blocked.read_text() == "not a directory"


def test_guard_only_owners_age_out_of_the_bound_and_knows_sees_a_survey_in_flight():
    store = LoopStore()
    first = store.get_guard("sid:g0", create=True)
    assert store.get_guard("sid:g0", create=True) is first and store.get("sid:g0") is None
    assert store.get_guard("sid:missing") is None and not store.knows("sid:b")
    store.put_bootstrap("sid:b", SurveyBootstrap())
    assert store.knows("sid:b")
    for i in range(1, _MAX_SESSIONS + 1):
        store.get_guard(f"sid:g{i}", create=True)
    assert store.get_guard("sid:g0") is None and store.get_guard(f"sid:g{_MAX_SESSIONS}") is not None


def test_a_legacy_refusal_set_on_the_old_session_merges_into_the_new_sessions_structured_ledger():
    store, old, new = LoopStore(), session(), session()
    old.refused_names = {"left-pad"}
    new.refusal_events = refusalledger.RefusalLedger.from_legacy({"is-odd"})
    store.put("sid:r", old)
    store.put("sid:r", new)
    assert new.refused_names == {"left-pad", "is-odd"} == new.refusal_events.active_names()


def test_the_session_lock_table_is_bounded_and_stable_for_a_key_in_use():
    loop = Loop(LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir=""), LoopStore())
    lock = loop._session_lock("sid:keep")
    assert loop._session_lock("sid:keep") is lock
    for i in range(_MAX_SHAPES + 1):
        loop._session_lock(f"sid:{i}")
    assert loop._session_lock("sid:keep") is not lock and len(loop._session_locks) <= _MAX_SHAPES + 1
    assert loop.knows_session("sid:none") is False and loop.has_session("sid:none") is False
