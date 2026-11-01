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
