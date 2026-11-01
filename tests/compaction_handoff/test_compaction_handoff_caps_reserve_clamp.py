"""The compaction predicate sizes the coder request with the reply reserve the floor will HOLD, not the role's asked-for number.

Measured 2026-11-01 (wave 10 CAPS, real 16K/24K servers, live config `output_reserve = 16384`): at a window the reserve
swallows, `Loop._coder_sizing` returned the raw 16,384, so the room was negative while `contextfloor.fit` reported the clamped
reserve for the same request (12,469 in the capture, 5,656 once history grew)."""
import pytest

from cria import contextfloor, selfcompact as sc, tokenratio
from test_compaction_handoff_room import _Rlog, _fresh_density, _loop  # noqa: F401  (autouse fixture)

FRAME = [{"role": "system", "content": "s" * 8000}, {"role": "user", "content": "task " * 400}]
TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "d" * 3000, "parameters": {"type": "object", "properties": {}}}}]


@pytest.mark.parametrize("window,reserve,density,held", [(16384, 16384, 1.2, 8192), (24576, 16384, 1.37, 12288), (16384, 12000, 1.0, 8192), (32768, 16384, 1.5, 16384)])
def test_the_sizing_reserve_is_the_one_fit_reports_for_the_same_frame(window, reserve, density, held):
    """Same request, same window, same density: fit's effective reserve IS the sizing's reserve, and the room cannot be negative."""
    tokenratio._ratios["m"] = density
    frame_tokens = contextfloor.est_total(FRAME, TOOLS)
    _, _, rep = contextfloor.fit(FRAME, TOOLS, window=window, reserve=reserve, safety=density)
    lp = _loop(window, window, reserve=reserve)
    got_window, got_reserve, got_density = lp._coder_sizing(_Rlog(), frame_tokens)
    assert (got_window, got_density) == (window, density)
    assert got_reserve == rep.reserve == held   # the reply holds at most half the window
    room, _ = lp._compaction_room(_Rlog(), lp._ctx.compactor_chat, frame_tokens, facts_text="")
    assert room >= 0


def test_a_reserve_that_leaves_the_frame_its_place_is_not_touched():
    """Where the role's reserve already leaves the frame room (the live 49,152 window), sizing, room and the floor's drop test are unchanged."""
    tokenratio._ratios["m"] = 1.15
    lp = _loop(49152, 49152, reserve=16384)
    assert lp._coder_sizing(_Rlog(), 4000) == (49152, 16384, 1.15)
    assert lp._compaction_room(_Rlog(), lp._ctx.compactor_chat, 4000, facts_text="")[0] == int((49152 - 16384) / 1.15) - 4000


@pytest.mark.parametrize("window,frame_tokens,room", [(16384, 1500, 5326), (24576, 1500, 8740), (32768, 1500, 12153), (49152, 1500, 25806)])
def test_an_operator_reserve_above_half_a_small_window_leaves_the_history_its_room(window, frame_tokens, room):
    """wave 12 CLAMP: with the live 16,384 reserve a 16K window had room <= 0 (24K only 5,326 of the 8,740 it now has) (a compaction replaced ONE message of a 9-message view); the reply holds half a small window, the history the rest. 32K and 49K are as before."""
    tokenratio._ratios["m"] = 1.2
    lp = _loop(window, window, reserve=16384)
    assert lp._compaction_room(_Rlog(), lp._ctx.compactor_chat, frame_tokens, facts_text="")[0] == room
    nine = [{"role": "user", "content": "task"}] + [{"role": "assistant" if i % 2 else "tool", "content": "x" * 400} for i in range(8)]
    assert sc.expected_growth(nine) + len("x" * 400 * 8) // 4 < room   # the small view fits: nothing is due


def _turns(n, size):
    return [m for i in range(n) for m in (
        {"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}}]},
        {"role": "tool", "tool_call_id": f"c{i}", "content": "y" * size})]


@pytest.mark.parametrize("result_chars,writer_asked", [(1200, False), (2400, True)])
def test_floor_pressure_is_measured_with_the_persona_the_floor_would_already_have_reduced(result_chars, writer_asked):
    """Real Codex at 16K: its ~17 KB persona (~4.2k tokens) counted in full, so any rejected briefing's view "would drop" and every
    later coder request paid a writer call for a sliver (8 of 11 compactions left the view the same size). The floor reduces the persona
    BEFORE it drops a turn (lever 2b); the question is whether it would still drop. A view that overflows even so is still folded."""
    from cria import assistruntime, bodykeys, wsview
    from cria.loop import PlanSession
    from cria.plan import Plan, PlanItem
    tokenratio._ratios["m"] = 1.0
    asked = []
    def writer(body, rlog):
        asked.append(body)
        return b'{"choices":[{"message":{"content":"BRIEF"}}]}'                       # no lens accepts it: the briefing is rejected, the attempt stands
    persona = "P" * 17000
    lp = _loop(16384, 16384, reserve=16384, chat=writer)
    body = {"model": "m", "tools": [], "messages": [
        {"role": "system", "content": persona + "\nTAIL", bodykeys.CALLER_INSTRUCTIONS: True, bodykeys.CALLER_PERSONA: persona},
        {"role": "user", "content": "do task"}] + _turns(20, result_chars)}
    sess = PlanSession(plan=Plan(id="p", task="do task", created="c", items=[PlanItem("do task")]), synthetic=True, plan_off=True)
    token = wsview.bind(wsview.DirectView())
    try:
        with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
            lp._prepare_coder_context(sess, body, _Rlog(), synthetic=True)
            assert asked and sess.compact_state.attempted > 0 and not sess.compact_state.summary    # the first briefing was offered and rejected
            before = len(asked)
            body["messages"] += _turns(1, result_chars)                                              # less than a new band: only pressure can ask again
            lp._prepare_coder_context(sess, body, _Rlog(), synthetic=True)
    finally:
        wsview.unbind(token)
    assert (len(asked) > before) is writer_asked
