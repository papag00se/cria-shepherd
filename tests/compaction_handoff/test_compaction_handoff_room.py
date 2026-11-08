"""The measured compaction predicate: the room is computed from real windows/densities and fires before a compaction call stops fitting."""
import copy
import json
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

def test_rolling_action_preserves_original_history_and_is_not_replayed_afterward():
    calls = []
    def chat(body, rlog):
        calls.append(body)
        return chat_reply("Implement the command-line tool functionality including argument parsing and error handling in Node.js.").encode()
    lp = _loop(49152, 49152, chat=chat)
    lp._ctx.system1 = SimpleNamespace(judge_compaction_topic=lambda task, response, **kw: "ON_TASK")
    sess = PlanSession(plan=Plan(id="p", task="Build the CLI", created="2026-10-30T00:00:00+00:00", items=[PlanItem("s")]))
    msgs = history(12, 250)
    msgs[-1]["content"] = "Wrote package.json\npackage.json now has 12 lines; your replacement is at lines 2-2."
    out = lp._self_compact(msgs, sess, None, _Rlog(), force=True, pinned_task="Build the CLI")
    assert out[:len(msgs)] == msgs
    assert len(out) == len(msgs) + 1 and "Implement the command-line tool functionality" in out[-1]["content"]
    assert calls and "Build the CLI" in calls[0]["messages"][-1]["content"]
    # Sanitized phi4/Node 0012 boundary: rolling suggestion followed by the fresh survey and read ledger.
    from cria.upstream import Upstream
    survey = {"role": "user", "content": "⟦ctx:files⟧ package.json (225 B)",
              bodykeys.ANNOTATION_SOURCE: bodykeys.AnnotationSource.WORKSPACE_LISTING}
    ledger = sc.internal_evidence_message("⟦ctx:facts⟧ package.json was read")
    wire_log = SimpleNamespace(session="real-session", phase="coder-s1", emit=lambda *a, **k: None)
    wire, _, _ = Upstream("http://unused", context_window=49152)._prep(
        {"messages": [*out, survey, ledger]}, False, wire_log)
    sent = json.loads(wire)
    text = "\n".join(str(m.get("content") or "") for m in sent["messages"])
    assert text.index("package.json was read") < text.index("MODEL-SUGGESTED NEXT ACTION")
    assert lp._self_compact(msgs, sess, None, _Rlog(), pinned_task="Build the CLI") == msgs


def test_the_first_view_that_does_not_fit_one_more_turn_is_compacted_and_every_call_reads_it_whole():
    """The writer and every validator read the whole view: at the firing point each compaction body fits its window with its reply."""
    window = 49152
    tokenratio._ratios["m"] = tokenratio._ratios["m#summary"] = 1.0
    seen, verdict = [], {}

    def chat(body, rlog):
        seen.append(copy.deepcopy(body))
        return chat_reply(lens_answer(body["messages"][0]["content"], **verdict) or "Retrospective state of the work.").encode()
    lp = _loop(window, window, reserve=windowcaps.scaled(windowcaps.GEN_RESERVE, window), chat=chat)
    lp._ctx.system1 = SimpleNamespace(judge_compaction_topic=lambda task, response, **kw: verdict.get("topic", "ON_TASK"))
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
    assert out[:len(msgs)] == msgs and len(out) == len(msgs) + 1
    for body in seen:
        fitted, _, report = contextfloor.fit(body["messages"], None, window=window, reserve=contextfloor.reserve_for(body))
        assert not report.over_budget
        if report.turns_dropped or report.protected_dropped:
            assert "compacted to fit the context window" in str(fitted)
    verdict["topic"], seen[:] = "OFF_TOPIC", []  # both attempts off-topic: every real turn remains unchanged
    sess = PlanSession(plan=Plan(id="q", task="t", created="2026-10-30T00:00:00+00:00", items=[PlanItem("s")]))
    assert lp._self_compact(msgs, sess, None, _Rlog(), pinned_task="t") == msgs and seen and not sess.compact_state.summary

