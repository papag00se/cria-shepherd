"""The measured compaction predicate: the room is computed from real windows/densities and fires before a compaction call stops fitting."""
import copy
from types import SimpleNamespace

import pytest

from cria import bodykeys, contextfloor, handoffdistill, loop as cloop, selfcompact as sc, tokenratio, windowcaps
from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore, PlanSession
from cria.plan import Plan, PlanItem
from compaction_handoff_helpers import asst, chat_reply, history, lens_answer

@pytest.fixture(autouse=True)
def _fresh_density():
    tokenratio.reset()
    yield
    tokenratio.reset()

def test_growth_is_the_largest_of_the_last_five_turns_and_room_abstains_on_an_unmeasured_window():
    """Growth is the largest of the last five turns; the room formula uses each window, reserve and density>=1, and abstains when unmeasured."""
    turns = lambda *sizes: history(0) + [m for n in sizes for m in (asst(n // 2), {"role": "tool", "tool_call_id": "c", "content": "y" * 2 * n})]
    assert sc.expected_growth(turns(100, 100, 700, 100, 100, 100, 100)) == 700      # not the mean, not a setting
    assert sc.expected_growth(turns(900, 100, 100, 100, 100, 100)) == 100           # a 900 read six turns ago has left the window
    assert sc.expected_growth([{"role": "system", "content": "s"}, {"role": "user", "content": "u" * 12000}]) == 3000   # no turn yet: the biggest delivered message
    # coder (49152 - 16384 reserve)/1.2 - 4000 frame; evidence (49152 - 14000 fixed)/1.2; density under 1.0 is not believed
    assert sc.view_room(coder=(49152, 16384, 1.2), frame_tokens=4000, compaction=(49152, 1.2), compaction_fixed=14000) == (23306, 29293)
    assert sc.view_room(coder=None, frame_tokens=0, compaction=None, compaction_fixed=0) == (None, None)
    assert sc.view_room(coder=(10000, 0, 0.5), frame_tokens=0, compaction=None, compaction_fixed=0) == (10000, None)

def _endpoint(window, chat=None):
    def default(body, rlog):
        raise AssertionError("not called")
    chat = chat or default
    chat.upstream = SimpleNamespace(_resolve_window=lambda rlog: window, _window_guessed=window is None, loaded_model=lambda rlog: "m")
    return chat

def _loop(coder_window, compactor_window, reserve=None, chat=None):
    compactor = _endpoint(compactor_window, chat)
    ctx = LoopContext(planner=None, coder_chat=_endpoint(coder_window), reasoner_chat=compactor, compactor_chat=compactor,
                      compactor_role=Role(name="compactor", backend="local"),
                      coder_role=Role(name="coder", backend="local", output_reserve=reserve), planner_enabled=False, runs_dir="")
    return Loop(ctx, LoopStore())

_Rlog = lambda: SimpleNamespace(session=None, phase=None, emit=lambda *a, **k: None)

def test_each_models_own_window_density_and_reserve_bound_its_own_room():
    """The pinned trigger_compaction=28884 ignored learned density (1.13-1.2): 428 of 463 coder requests had turns dropped under it."""
    tokenratio._ratios["m"] = 1.15                         # coder density
    tokenratio._ratios["m#summary"] = 1.33                 # summary requests tokenize denser
    lp = _loop(49152, 49152, reserve=16384)
    room, evidence = lp._compaction_room(_Rlog(), lp._ctx.compactor_chat, 4000, facts_text="")
    assert room == int((49152 - 16384) / 1.15) - 4000 and room < 28884
    fixed = handoffdistill.FRAME_TOKENS + windowcaps.resolve(cloop.ROLLUP_MAX_TOKENS, 49152) + cloop.COMPACTION_VERDICT_RESERVE
    assert evidence == int((49152 - fixed) / 1.33)       # frame, reply cap and verdict reserve come out of the compactor's window at ITS density
    big_coder = _loop(262144, 16384, reserve=4096)
    room, evidence = big_coder._compaction_room(_Rlog(), big_coder._ctx.compactor_chat, 4000, facts_text="")
    assert evidence < 16384 < room                         # a small compactor binds the evidence bound, not the coder's
    unknown = _loop(None, None)
    assert unknown._compaction_room(_Rlog(), unknown._ctx.compactor_chat, 4000, facts_text="") == (None, None)

def test_the_first_view_that_does_not_fit_one_more_turn_is_compacted_and_every_call_reads_it_whole():
    """The writer and every validator read the whole view: at the firing point each compaction body fits its window with its reply."""
    window = 49152
    tokenratio._ratios["m"] = tokenratio._ratios["m#summary"] = 1.0
    seen, verdict = [], {}

    def chat(body, rlog):
        seen.append(copy.deepcopy(body))
        return chat_reply(lens_answer(body["messages"][0]["content"], **verdict) or "Retrospective state of the work.").encode()
    lp = _loop(window, window, reserve=windowcaps.scaled(windowcaps.GEN_RESERVE, window), chat=chat)
    sess = PlanSession(plan=Plan(id="p", task="t", created="2026-10-30T00:00:00+00:00", items=[PlanItem("s")]))
    for turns in range(4, 400):
        seen.clear()
        msgs = history(turns, 250)
        out = lp._self_compact(msgs, sess, None, _Rlog(), pinned_task="t")
        if seen:
            break
    assert turns > 4 and seen, "it did not fire on the first call, and it did fire"
    _, evidence_room = lp._compaction_room(_Rlog(), chat, 0, facts_text="t")
    evidence = sc.evidence_tokens(msgs[1:])
    assert evidence_room - 6 * 250 <= evidence <= evidence_room          # the first view whose NEXT turn would not fit (labels/facts account for the slack)
    assert any(sc.SUMMARY_MARKER in (m.get("content") or "") for m in out)
    for body in seen:
        reserve = body.get(bodykeys.OUTPUT_RESERVE) if body.get(bodykeys.OUTPUT_RESERVE) is not None else windowcaps.resolve(body.get("max_tokens"), window)
        assert contextfloor.est_total(body["messages"], None) + reserve <= window
        assert not any("⟦ctx:compacted⟧" in str(m.get("content")) for m in body["messages"])      # the floor dropped nothing
    verdict["retrospective"], seen[:] = "PLAN", []                         # the same view with the briefing rejected: every turn stays verbatim, nothing latches
    sess = PlanSession(plan=Plan(id="q", task="t", created="2026-10-30T00:00:00+00:00", items=[PlanItem("s")]))
    assert lp._self_compact(msgs, sess, None, _Rlog(), pinned_task="t") == msgs and seen and not sess.compact_state.summary
