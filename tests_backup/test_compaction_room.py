"""WHEN a view is compacted is a predicate over MEASURED room, not a configured trigger.

The incident this replaces: the live config pinned ``[context] trigger_compaction = 28884`` — at 49,152
tokens that is ``window - the coder's 16,384 reply reserve - ~3.9K frame`` at density 1.0, a hand derivation
of exactly this room that ignores the learned density (1.13-1.2 in the 463 coder requests the floor trimmed
under that pin: 428 of them DROPPED coder turns). At any other window the same number is wrong; at 16K the
share it was tuned as never fires before the floor drops turns, and a view past the room cannot be read WHOLE
by the compaction calls (the writer and every validator read the whole view plus their own frame and reply
room), so the validators judge a floor-reduced digest.

The room is the largest view both consumers hold whole; a view is compacted iff ONE MORE TURN of measured
growth (the largest of the last turns this session's view actually grew by) would no longer fit it.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from cria import bodykeys, config, contextfloor, handoffdistill, loop as cloop, selfcompact, tokenratio, windowcaps
from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore, PlanSession
from cria.plan import Plan, PlanItem
from cria.selfcompact import CompactState, compact, expected_growth, turn_sizes, view_room
from tests.test_selfcompact_wiring import _validation_reply
from tests.window_fakes import with_room


def _a(n):      # an assistant message of ~n estimated tokens
    return {"role": "assistant", "content": "x" * (4 * n)}


def _t(n):
    return {"role": "tool", "tool_call_id": "c", "content": "y" * (4 * n)}


# ------------------------------------------------------------------ measured growth

def test_growth_is_the_largest_of_the_last_turns_not_the_mean_and_not_a_setting():
    msgs = [{"role": "system", "content": "s" * 4000}] + [m for n in (100, 100, 700, 100, 100, 100, 100)
                                                        for m in (_a(n // 2), _t(n // 2))]
    assert turn_sizes(msgs) == [100, 100, 700, 100, 100, 100, 100]    # the system prompt is not growth
    assert expected_growth(msgs) == 700                               # the 700 turn is inside the last 5? no: 7 turns
    older = msgs[:1] + [m for n in (900, 100, 100, 100, 100, 100) for m in (_a(n // 2), _t(n // 2))]
    assert expected_growth(older) == 100                              # a 900 read six turns ago has left the window


def test_growth_with_no_turn_yet_is_the_largest_message_already_delivered():
    msgs = [{"role": "system", "content": "s" * 400}, {"role": "user", "content": "u" * 12000}]
    assert expected_growth(msgs) == 3000
    assert expected_growth([]) == 0


# ------------------------------------------------------------------ the room, from measured numbers

def test_room_is_a_coder_bound_and_an_evidence_bound_each_from_its_own_window():
    # coder: (49152 - 16384) / 1.2 - 4000 = 23,306 raw tokens; evidence: (49152 - 14000) / 1.2 = 29,293
    assert view_room(coder=(49152, 16384, 1.2), frame_tokens=4000,
                     compaction=(49152, 1.2), compaction_fixed=14000) == (int(32768 / 1.2) - 4000, int(35152 / 1.2))


def test_room_abstains_without_a_measured_window_and_never_reads_unknown_as_large_or_small():
    assert view_room(coder=None, frame_tokens=4000, compaction=None, compaction_fixed=14000) == (None, None)
    assert view_room(coder=(16384, 2048, 1.0), frame_tokens=0, compaction=None, compaction_fixed=0) == (14336, None)
    assert view_room(coder=None, frame_tokens=0, compaction=(16384, 1.0), compaction_fixed=6000) == (None, 10384)


def test_density_below_one_is_not_believed():
    assert (view_room(coder=(10000, 0, 0.5), frame_tokens=0, compaction=(10000, 0.5), compaction_fixed=0)
            == view_room(coder=(10000, 0, 1.0), frame_tokens=0, compaction=(10000, 1.0), compaction_fixed=0))


def test_evidence_is_the_rendered_blocks_not_the_raw_message_size():
    msgs = [m for _ in range(40) for m in (_a(25), _t(25))]                  # 80 small messages
    raw = sum(selfcompact._msg_tokens(m) for m in msgs)
    assert selfcompact.evidence_tokens(msgs) > raw + 80 * 10, "each turn carries its role/label framing"
    assert selfcompact.evidence_tokens(msgs, 40) > selfcompact.evidence_tokens(msgs), "a retained-tail label is longer"


# ------------------------------------------------------------------ the engine's predicate

def _history(n_turns, per_turn):
    return [{"role": "system", "content": "sys"}] + [m for _ in range(n_turns) for m in (_a(per_turn // 2), _t(per_turn // 2))]


def _fold(msgs, room, **kw):
    return compact(msgs, lambda mm, **k: "BRIEFING", CompactState(), room_tokens=room, keep_tail_tokens=300,
                   recompact_tokens=100, **kw)


def test_it_compacts_iff_one_more_turn_would_not_fit():
    msgs = _history(20, 100)                      # 2,000 est tokens, grows 100 a turn
    view = sum(selfcompact._msg_tokens(m) for m in msgs)
    assert expected_growth(msgs) == 100
    _out, _st, applied = _fold(msgs, view + 100)          # exactly fits one more turn
    assert not applied
    _out, _st, applied = _fold(msgs, view + 99)           # one token short of fitting it
    assert applied


def test_a_bigger_recent_turn_compacts_the_same_size_view_earlier():
    quiet, bursty = _history(20, 100), _history(19, 100)
    bursty += [_a(500), _t(500)]                  # the last turn read a big file
    room = sum(selfcompact._msg_tokens(m) for m in quiet) + 150
    assert not _fold(quiet, room)[2]
    assert sum(selfcompact._msg_tokens(m) for m in bursty) < room + 1000
    assert _fold(bursty, room + 800)[2] is True


def test_with_no_measured_window_only_floor_pressure_compacts():
    huge = _history(200, 400)                     # 80K est tokens, far past any window
    assert not _fold(huge, None)[2], "no window, no prediction: nothing compacts on size alone"
    out, _st, applied = _fold(huge, None, floor_pressure=lambda view: True) if False else (None, None, None)
    result = selfcompact.rolling(selfcompact.RollingInput(
        huge, lambda mm, **k: "BRIEFING", room_tokens=None, keep_tail_tokens=300, recompact_tokens=100,
        floor_pressure=lambda view: True), CompactState())
    assert result.applied, "the floor already having to drop turns is the one signal that needs no prediction"
    quiet = selfcompact.rolling(selfcompact.RollingInput(
        huge, lambda mm, **k: "BRIEFING", room_tokens=None, keep_tail_tokens=300, recompact_tokens=100,
        floor_pressure=lambda view: False), CompactState())
    assert not quiet.applied


def test_a_standing_summary_keeps_the_compacted_view_even_if_the_growth_measure_dips():
    msgs = _history(30, 100)
    view = sum(selfcompact._msg_tokens(m) for m in msgs)
    first = selfcompact.rolling(selfcompact.RollingInput(msgs, lambda mm, **k: "B", room_tokens=view,
                                keep_tail_tokens=300, recompact_tokens=100), CompactState())
    assert first.applied
    # the same raw history, now with room to spare: the rollup that already stands is not abandoned for the raw view
    again = selfcompact.rolling(selfcompact.RollingInput(msgs, lambda mm, **k: "B", room_tokens=10 * view,
                                keep_tail_tokens=300, recompact_tokens=10 ** 6), first.state)
    assert any(selfcompact.SUMMARY_MARKER in selfcompact._text(m) for m in again.messages)


# ------------------------------------------------------------------ the loop computes the room from what it measures

def _endpoint(window, model="m"):
    def chat(body, rlog):
        raise AssertionError("not called")
    chat.upstream = SimpleNamespace(_resolve_window=lambda rlog: window, _window_guessed=window is None,
                                    loaded_model=lambda rlog: model)
    return chat


def _loop(*, coder_window, compactor_window, reserve=None, chat=None):
    coder = _endpoint(coder_window)
    compactor = chat or _endpoint(compactor_window)
    if chat is not None:
        chat.upstream = SimpleNamespace(_resolve_window=lambda rlog: compactor_window, _window_guessed=compactor_window is None,
                                        loaded_model=lambda rlog: "m")
    ctx = LoopContext(planner=None, coder_chat=coder, reasoner_chat=compactor, compactor_chat=compactor,
                      compactor_role=Role(name="compactor", backend="local"),
                      coder_role=Role(name="coder", backend="local", output_reserve=reserve),
                      planner_enabled=False, runs_dir="")
    return Loop(ctx, LoopStore())


class _Rlog:
    session = None
    phase = None

    def emit(self, *a, **k):
        pass


def test_the_loop_room_at_49152_with_the_live_coder_reserve_is_the_coder_bound():
    tokenratio.reset()
    tokenratio.record("m", 1150, 1000)                                  # learned: 1.15 real per estimated
    d = tokenratio.observed("m")
    lp = _loop(coder_window=49152, compactor_window=49152, reserve=16384)
    room, evidence_room = lp._compaction_room(_Rlog(), lp._ctx.compactor_chat, 4000, facts_text="")
    assert room == int((49152 - 16384) / d) - 4000
    # ... and the pinned 28,884 sits ABOVE it: the floor already drops turns there
    assert room < 28884


def test_each_bound_uses_its_own_model_density_reserve_and_frame():
    tokenratio.reset()
    tokenratio.record("m", 1150, 1000)
    tokenratio._ratios["m#summary"] = 1.33        # summary requests tokenize denser than the coder's traffic
    d = tokenratio.observed_kind("summary")
    lp = _loop(coder_window=49152, compactor_window=49152, reserve=2048)
    room, evidence_room = lp._compaction_room(_Rlog(), lp._ctx.compactor_chat, 4000, facts_text="")
    reply = windowcaps.resolve(cloop.ROLLUP_MAX_TOKENS, 49152)
    fixed = handoffdistill.FRAME_TOKENS + reply + cloop.COMPACTION_VERDICT_RESERVE
    assert evidence_room == int((49152 - fixed) / d)
    assert room == int((49152 - 2048) / tokenratio.observed("m")) - 4000        # the coder bound, its own density


def test_each_model_is_sized_by_its_own_window():
    tokenratio.reset()
    tokenratio.record("m", 1000, 1000)
    big_coder_small_compactor = _loop(coder_window=262144, compactor_window=16384, reserve=4096)
    room, evidence_room = big_coder_small_compactor._compaction_room(
        _Rlog(), big_coder_small_compactor._ctx.compactor_chat, 4000, facts_text="")
    assert evidence_room < 16384 < room                                 # each model's own window binds its own bound


def test_an_unmeasured_summary_density_is_the_floors_conservative_default_not_the_coders():
    """Measured: with the coder's 1.2 standing in for the unmeasured summary kind (1.8 at the floor), the first
    compaction call at a 32K window was floor-reduced (35 turns dropped) although the room said it fit."""
    tokenratio.reset()
    tokenratio._ratios["m"] = 1.2
    lp = _loop(coder_window=32768, compactor_window=32768, reserve=8192)
    _room, evidence_room = lp._compaction_room(_Rlog(), lp._ctx.compactor_chat, 0, facts_text="")
    fixed = (handoffdistill.FRAME_TOKENS + windowcaps.resolve(cloop.ROLLUP_MAX_TOKENS, 32768)
             + cloop.COMPACTION_VERDICT_RESERVE)
    assert evidence_room == int((32768 - fixed) / tokenratio.DEFAULT_RATIO)


def test_an_unknown_window_gives_no_room():
    lp = _loop(coder_window=None, compactor_window=None)
    assert lp._compaction_room(_Rlog(), lp._ctx.compactor_chat, 4000, facts_text="") == (None, None)


# ------------------------------------------------------------------ the guarantee, through the real loop

def _bodies_fit_whole(window, density, bodies):
    for body in bodies:
        reserve = (body.get(bodykeys.OUTPUT_RESERVE) if body.get(bodykeys.OUTPUT_RESERVE) is not None
                   else windowcaps.resolve(body.get("max_tokens"), window))
        est = contextfloor.est_total(body["messages"], None)
        assert est * density + reserve <= window, (est, density, reserve, window)
        assert not any("⟦ctx:compacted⟧" in str(m.get("content")) for m in body["messages"])


@pytest.mark.parametrize("window", [16384, 32768, 49152])
def test_the_first_view_that_does_not_fit_one_more_turn_is_compacted_and_every_call_reads_it_whole(window):
    tokenratio.reset()
    tokenratio._ratios["m"] = 1.0                                       # the coder's measured density
    tokenratio._ratios["m#summary"] = 1.0                               # ... and the summary requests'
    density = 1.0
    seen = []

    def chat(body, rlog):
        seen.append(copy.deepcopy(body))   # a Cap in the body survives the copy, as on the wire
        text = _validation_reply(body["messages"][0]["content"]) or "Retrospective state of the work."
        return json.dumps({"choices": [{"message": {"content": text}}]}).encode()

    lp = _loop(coder_window=window, compactor_window=window, reserve=windowcaps.scaled(windowcaps.GEN_RESERVE, window),
               chat=chat)
    per_turn = 250
    fired = None
    for turns in range(4, 400):
        seen.clear()
        msgs = _history(turns, per_turn)
        sess = PlanSession(plan=Plan(id="p", task="t", created="2026-10-30T00:00:00+00:00", items=[PlanItem("s")]))
        out = lp._self_compact(msgs, sess, None, _Rlog(), pinned_task="t")
        if seen:
            fired = turns
            break
    assert fired is not None
    room, evidence_room = lp._compaction_room(_Rlog(), chat, 0, facts_text="t")
    evidence = selfcompact.evidence_tokens(_history(fired, per_turn)[1:])
    assert evidence_room - 6 * per_turn <= evidence <= evidence_room, \
        "it fired on the first view whose next turn would not fit (tail labels and the facts account for the slack)"
    assert any(selfcompact.SUMMARY_MARKER in selfcompact._text(m) for m in out)
    _bodies_fit_whole(window, density, [b for b in seen])


# ------------------------------------------------------------------ the knob is gone, loudly

def test_a_config_still_carrying_the_removed_key_fails_at_startup_naming_it(tmp_path):
    p = tmp_path / "cria.toml"
    p.write_text("[context]\nself_compact = true\ntrigger_compaction = 28884\n")
    with pytest.raises(ValueError) as err:
        config.Config.load(str(p))
    assert "trigger_compaction" in str(err.value) and "removed" in str(err.value)


def test_the_example_config_and_loop_context_have_no_such_field():
    assert not hasattr(config.ContextConfig(), "trigger_compaction")
    assert "trigger_compaction" not in LoopContext.__dataclass_fields__
    p = config.Path(__file__).resolve().parent.parent / "cria.example.toml" if hasattr(config, "Path") else None
    import pathlib
    assert "trigger_compaction" not in (pathlib.Path(__file__).resolve().parent.parent / "cria.example.toml").read_text()
