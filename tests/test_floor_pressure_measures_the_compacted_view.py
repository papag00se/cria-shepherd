"""Floor pressure is asked about the view rolling memory would SEND, not the raw history.

Run07 (ornith1.5_9b / Java, session 01a17e45): ``Loop._self_compact`` sized floor pressure on the raw
harness history, which only grows. Once it passed the window the answer stayed "overflow" on every
later turn, although the compacted view the coder received fitted (14.6k-18.5k est. tokens of a
49,152 window, no floor trim between the accepted compactions). An accepted briefing restores the
throttle bypass, so nearly every coder turn bought a writer plus its validation judges for a band of
one to four messages (writer calls 0059, 0063, 0067, 0071, 0075; the 0063 middle was one 152-char
sentence). Run05 (01a17d03) shows the same cadence (0071, 0075, 0081, 0090).

The intent of the bypass (run 1792480002: briefings rejected, the floor dropping 45-85 coder turns
per call for ~20 minutes) is preserved: with no accepted summary the view IS the raw history, and a
view that genuinely overflows still folds through the band throttle.

Driven through the production owner ``Loop._self_compact`` with the real ``_floor_would_drop`` sizing
(coder density, coder reserve, real window) and the real rolling engine and validators; only the
model replies are fake.
"""
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace

from cria import selfcompact, tokenratio, windowcaps
from cria.config import Role
from cria.loop import Loop, LoopContext, PlanSession
from cria.plan import Plan, PlanItem

MODEL = "pressure-test-model"
RESERVE = 2_000
BIG = "w" * 4_000          # 1,000 est. tokens per old turn


class _Log:
    def emit(self, *a, **kw):
        pass


def _reply(text: str) -> bytes:
    return json.dumps({"choices": [{"finish_reason": "stop",
                                    "message": {"role": "assistant", "content": text}}]}).encode()


class _Reasoner:
    """Writer + three validation lenses. ``accept=False`` makes the retrospective lens say PLAN."""

    def __init__(self, accept: bool = True):
        self.accept = accept
        self.writer_calls = 0

    def __call__(self, body, rlog):
        system = body["messages"][0]["content"]
        if "PLAN or RETROSPECTIVE" in system:
            return _reply("RETROSPECTIVE" if self.accept else "PLAN")
        if "NARROWS or PRESERVES" in system:
            return _reply("PRESERVES")
        if "CHANGED or NOT CHANGED" in system:
            return _reply("NONE")      # the change-claim lens: nothing here to list
        if "GREEN or EARLIER or NOT GREEN" in system:
            return _reply("NONE")      # the build-state lens: nothing here to list
        if "UNFAITHFUL or FAITHFUL" in system:
            return _reply("FAITHFUL")
        self.writer_calls += 1
        return _reply("The coder read the importer and recorded its baseline totals.")


def _coder_chat(window: int):
    def chat(body, rlog):
        return _reply("")
    chat.upstream = SimpleNamespace(_resolve_window=lambda rlog: window, _window_guessed=False,
                                    loaded_model=lambda rlog: MODEL)
    return chat


def _loop(reasoner: _Reasoner, window: int | None = None) -> Loop:
    ctx = LoopContext(planner=None, coder_chat=_coder_chat(window or WINDOW), reasoner_chat=reasoner,
                      reasoner_role=Role(name="reasoner", backend="local"), runs_dir="")
    return Loop(replace(ctx, trigger_compaction=100,
                        coder_role=Role(name="coder", backend="local", output_reserve=RESERVE)))


def _history(old_turns: int = 40) -> list[dict]:
    return [{"role": "system", "content": "sys"}] + [
        {"role": "user" if i % 2 else "assistant", "content": f"old {i} " + BIG} for i in range(old_turns)]


def _grow(msgs: list[dict], n: int, tag: str) -> list[dict]:
    """``n`` new turns. Each pushes one old turn out of the 6,000-token verbatim tail, so two of
    them leave a ~2,000-token unfolded band: under RECOMPACT_TOKENS (4,000), a sub-band increment."""
    return msgs + [{"role": "user" if i % 2 else "assistant", "content": f"{tag} {i} " + BIG}
                   for i in range(n)]


def _session() -> PlanSession:
    return PlanSession(plan=Plan(id="20261027T0000-abcd1234", task="fix the importer",
                                 created="2026-10-27T00:00:00+00:00", items=[PlanItem("step 1")]))


# The compaction thresholds are shares of the coder's window (windowcaps), so a fixture that wants a
# particular amount of ROOM must not change the window — that would move the 6,000-token tail and the
# 4,000-token band throttle the turn sizes below are written against. The coder serves the reference
# window and the rest of its request (system frame, task, tool list) is the ``frame_tokens`` the
# production caller already passes: ``_room(n)`` is the frame that leaves exactly ``n`` estimated tokens
# of room for the conversation.
WINDOW = windowcaps.REFERENCE_WINDOW


def _room(tokens: int) -> int:
    """``frame_tokens`` that leave ``tokens`` estimated tokens of room in the reference window."""
    return int((WINDOW - RESERVE) / tokenratio.observed(MODEL)) - tokens


class FloorPressureMeasuresTheCompactedView(unittest.TestCase):
    def setUp(self):
        tokenratio.reset()
        self.addCleanup(tokenratio.reset)

    def _assert_sub_band(self, msgs, base):
        """Fixture validity: a real new band exists, smaller than the band throttle."""
        tail_start = selfcompact._tail_start(msgs, 1, selfcompact.KEEP_TAIL_TOKENS)
        band = sum(selfcompact._msg_tokens(m) for m in msgs[base:tail_start])
        self.assertGreater(band, 0)
        self.assertLess(band, selfcompact.RECOMPACT_TOKENS)

    def _first_compaction(self, reasoner, room):
        loop, sess, rlog = _loop(reasoner), _session(), _Log()
        self.frame = _room(room)
        msgs = _history()
        view = loop._self_compact(msgs, sess, None, rlog, pinned_task="fix the importer",
                                  frame_tokens=self.frame)
        return loop, sess, rlog, msgs, view

    def test_a_sub_band_turn_is_not_resummarized_when_the_compacted_view_fits(self):
        # Raw history ~40k est. tokens; the compacted view ~6.5k. The window holds the view only.
        room = 12_000
        reasoner = _Reasoner()
        loop, sess, rlog, msgs, view = self._first_compaction(reasoner, room)
        self.assertEqual(reasoner.writer_calls, 1)
        self.assertTrue(sess.compact_state.summary)
        self.assertTrue(loop._floor_would_drop(msgs, rlog, self.frame), "fixture: the RAW history overflows")
        self.assertFalse(loop._floor_would_drop(view, rlog, self.frame), "fixture: the compacted view fits")

        grown = _grow(msgs, 2, "new")
        covered = sess.compact_state.covered
        self._assert_sub_band(grown, covered)
        out = loop._self_compact(grown, sess, None, rlog, pinned_task="fix the importer",
                            frame_tokens=self.frame)

        self.assertEqual(reasoner.writer_calls, 1,
                         "a sub-band increment must not buy another writer while the view fits")
        # Nothing is lost: every turn past the summarized span reaches the coder verbatim.
        self.assertEqual(sess.compact_state.covered, covered)
        sent = [m.get("content") for m in out]
        for m in grown[covered:]:
            self.assertIn(m["content"], sent)
        self.assertTrue(any(selfcompact.SUMMARY_MARKER in (c or "") for c in sent))

    def test_a_compacted_view_that_genuinely_overflows_still_folds_under_pressure(self):
        # The window holds neither the raw history nor the compacted view (summary + band + tail).
        room = 5_000
        reasoner = _Reasoner()
        loop, sess, rlog, msgs, view = self._first_compaction(reasoner, room)
        self.assertEqual(reasoner.writer_calls, 1)
        self.assertTrue(loop._floor_would_drop(view, rlog, self.frame), "fixture: the compacted view overflows")

        grown = _grow(msgs, 2, "new")
        self._assert_sub_band(grown, sess.compact_state.covered)
        loop._self_compact(grown, sess, None, rlog, pinned_task="fix the importer",
                            frame_tokens=self.frame)
        self.assertEqual(reasoner.writer_calls, 2,
                         "an overflowing view folds before the floor drops turns")

    def test_rejected_briefings_still_bypass_the_throttle_once_per_rejection_run(self):
        # 1792480002 shape: every briefing rejected, so no summary exists and the view IS the raw
        # history, which overflows. Pressure must buy one throttle-bypassing attempt per run.
        room = 12_000
        reasoner = _Reasoner(accept=False)
        loop, sess, rlog, msgs, view = self._first_compaction(reasoner, room)
        self.assertEqual(reasoner.writer_calls, 1)
        self.assertFalse(sess.compact_state.summary)
        self.assertIs(view, msgs, "a rejected briefing keeps every turn verbatim")

        grown = _grow(msgs, 2, "a")
        self._assert_sub_band(grown, sess.compact_state.attempted)
        loop._self_compact(grown, sess, None, rlog, pinned_task="fix the importer",
                            frame_tokens=self.frame)
        self.assertEqual(reasoner.writer_calls, 2, "pressure on the uncompacted view retries once")

        grown = _grow(grown, 2, "b")
        loop._self_compact(grown, sess, None, rlog, pinned_task="fix the importer",
                            frame_tokens=self.frame)
        self.assertEqual(reasoner.writer_calls, 2, "the bypass is spent until a band accumulates")

        reasoner.accept = True
        grown = grown + [{"role": "assistant", "content": f"band {i} " + BIG} for i in range(5)]
        loop._self_compact(grown, sess, None, rlog, pinned_task="fix the importer",
                            frame_tokens=self.frame)
        self.assertEqual(reasoner.writer_calls, 3, "a full new band is still summarized")
        self.assertTrue(sess.compact_state.summary)


if __name__ == "__main__":
    unittest.main()
