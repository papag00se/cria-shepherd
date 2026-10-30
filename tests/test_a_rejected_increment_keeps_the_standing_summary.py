"""A rejected rolling increment sends the standing summary's view, not the raw history behind it.

ornith1.5_9b / Java run07 (session 01a17e45): coder call 0074 carried an accepted ``⟦ctx:rollup⟧`` (29
messages). The next increment's writer (0075) was rejected by the scope lens (0076: NARROWS), and coder
call 0077 got 47 raw messages and no rollup; 0079, with no new attempt, carried the same rollup again
(33 messages). The empty-summary guard (9fd3f691) exists so an EMPTY summary is never adopted ("fold
nothing, keep every turn verbatim"); it returned the raw history even when an accepted, validated summary
already stood in for the older turns, so the coder's view flipped for one turn, and under floor pressure
(a0c711d1) the turns the summary covered went back to the floor to be dropped.

Now a rejection folds nothing NEW: the standing rollup covers what it already covered, the rejected band
and the tail stay verbatim. With no summary, or a summary whose indices no longer describe the history,
the raw history is still the view.

Driven through ``Loop._self_compact`` with the real rolling engine, sizing and validators; only the
model replies are fake.
"""
import unittest

from cria import selfcompact, tokenratio
from tests.test_floor_pressure_measures_the_compacted_view import (
    BIG, _Log, _Reasoner, _grow, _history, _loop, _room, _session)

TASK = "fix the importer"


class ARejectedIncrementKeepsTheStandingSummary(unittest.TestCase):
    def setUp(self):
        tokenratio.reset()
        self.addCleanup(tokenratio.reset)

    def _accepted(self, room):
        # ``room``: estimated tokens the window leaves the conversation (see _room: the window itself is
        # fixed, because the compaction thresholds are shares of it).
        self.frame = _room(room)
        reasoner = _Reasoner()
        loop, sess, rlog = _loop(reasoner), _session(), _Log()
        msgs = _history()
        first = loop._self_compact(msgs, sess, None, rlog, pinned_task=TASK, frame_tokens=self.frame)
        self.assertEqual(reasoner.writer_calls, 1)
        self.assertTrue(sess.compact_state.summary, "fixture: the first briefing was accepted")
        return reasoner, loop, sess, rlog, msgs, first

    def _assert_standing_view(self, out, grown, covered, summary):
        sent = [m.get("content") for m in out]
        rollups = [c for c in sent if selfcompact.SUMMARY_MARKER in (c or "")]
        self.assertEqual(len(rollups), 1, "the standing rollup is sent")
        self.assertIn(summary, rollups[0])
        for m in grown[1:covered]:
            self.assertNotIn(m["content"], sent, "a turn the accepted summary covers is not resent raw")
        self.assertEqual(out[-len(grown[covered:]):], grown[covered:],
                         "the rejected band and the tail reach the coder verbatim")

    def _run(self, room, grow):
        reasoner, loop, sess, rlog, msgs, first = self._accepted(room)
        summary, covered = sess.compact_state.summary, sess.compact_state.covered
        reasoner.accept = False                       # the next increment's briefing is rejected
        grown = grow(msgs)
        out = loop._self_compact(grown, sess, None, rlog, pinned_task=TASK,
                                    frame_tokens=self.frame)
        self.assertEqual(reasoner.writer_calls, 2, "fixture: a new increment was attempted")
        self.assertEqual((sess.compact_state.summary, sess.compact_state.covered), (summary, covered))
        self._assert_standing_view(out, grown, covered, summary)
        # The next turn makes no attempt; its view starts exactly as the rejected turn's did.
        after = loop._self_compact(grown, sess, None, rlog, pinned_task=TASK,
                                    frame_tokens=self.frame)
        self.assertEqual(reasoner.writer_calls, 2)
        self.assertEqual(after, out, "the coder's view does not flip across a rejected increment")

    def test_a_rejected_band_increment_keeps_the_rollup(self):
        # A full new band (over RECOMPACT_TOKENS) is due; the window holds the compacted view.
        self._run(30_000, lambda msgs: _grow(msgs, 10, "band"))

    def test_a_rejected_floor_pressure_increment_keeps_the_rollup(self):
        # A sub-band increment bought only by floor pressure: the compacted view overflows (run07 shape).
        self._run(5_000, lambda msgs: _grow(msgs, 2, "new"))

    def test_without_a_standing_summary_a_rejection_still_sends_every_turn_verbatim(self):
        reasoner = _Reasoner(accept=False)
        loop, sess, rlog = _loop(reasoner), _session(), _Log()
        msgs = _history()
        self.assertIs(loop._self_compact(msgs, sess, None, rlog, pinned_task=TASK,
                                         frame_tokens=_room(12_000)), msgs)
        self.assertEqual(reasoner.writer_calls, 1)

    def test_a_summary_whose_indices_no_longer_fit_the_history_is_not_reused_on_rejection(self):
        # The harness replaced the history (it shrank below ``covered``): the standing summary's indices
        # describe turns that are not these, so a rejected re-summary keeps the raw history.
        reasoner, loop, sess, rlog, msgs, _first = self._accepted(30_000)
        reasoner.accept = False
        shrunk = [msgs[0]] + [{"role": "user" if i % 2 else "assistant", "content": f"other {i} " + BIG}
                              for i in range(12)]
        self.assertGreater(sess.compact_state.covered, len(shrunk), "fixture: state no longer fits")
        out = loop._self_compact(shrunk, sess, None, rlog, pinned_task=TASK,
                                    frame_tokens=self.frame)
        self.assertEqual(reasoner.writer_calls, 2)
        self.assertIs(out, shrunk)


if __name__ == "__main__":
    unittest.main()
