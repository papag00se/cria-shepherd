"""cria's harness-compaction detector had never fired. Not rarely — zero times, ever.

MEASURED, before anything was changed:

    loop.history_rewritten          0 events, across every log cria has kept
    route.compaction              139 events, same window
    persisted shapes              256, all sid:-keyed, all with a stored fingerprint
    of those, pending=True          0
    loop.probe_reissued             0 events

Four mechanisms are gated on that one boolean — the post-compaction continuation plan and three
probe re-issues — so a gate result destroyed by a compaction was simply gone, and cria carried on
as though the check had declined to answer.

WHY. The detector's premise: "compaction REPLACES the conversation root — the first real user
message becomes the harness's summary". That is one way to rewrite a history. It is not Codex's.
Codex keeps EVERY user message, the original task among them, and drops the assistant and tool items
behind them. The root fingerprint is therefore identical before and after, and the test could not
fire no matter how many times the harness compacted.

WHAT IT DOES DO is get shorter, and `observe_shape` was already being handed `n_messages` and
storing it without ever comparing it. Measured across 141 real sessions: inbound length dropped 108
times, and every single one of the 108 followed a `route.compaction` — no false positives at any
threshold. 56 of the 60 compacting sessions show a drop (the other 4 ended on the compaction). The
drops are not subtle: 144 → 4, 172 → 4, 169 → 4.

Both signals are kept. A harness that replaces the root is still detected by the root; a harness that
keeps it is now detected by the length. Turns that merely append can only grow a history, so neither
test can misread ordinary work. #18: the fix is a second structural signal, not a Codex special case.
#11b: the detector could not observe the thing it was asked about and answered "no" for months.

The continuation planner is corrected to match. It was handed `root_text` as "the harness's summary",
which is true only under the replaced-root shape; under Codex's, the root is the original task, and
telling the planner to continue from the task means re-planning the whole job — the one thing a
continuation exists to prevent. `_rewrite_summary_text` picks the re-anchored continuation turn when
there is one and falls back to the root, which is the old behaviour exactly.
"""

import json
from pathlib import Path
import unittest

from cria.loop import CONTINUATION_MARKER, LoopStore, _history_root, _rewrite_summary_text


class TheCodexShapeIsDetectedTests(unittest.TestCase):
    """THE REGRESSION. Same root, shorter history — the shape 139 real compactions produced."""

    def test_a_shorter_history_under_the_same_root_is_a_rewrite(self):
        s = LoopStore()
        self.assertFalse(s.observe_shape("sid:k", "fp1", 3))
        self.assertFalse(s.observe_shape("sid:k", "fp1", 144))   # ordinary work, appending
        self.assertTrue(s.observe_shape("sid:k", "fp1", 4))      # 144 → 4, root unchanged

    def test_the_real_measured_lengths(self):
        """The three largest real drops, replayed as they arrived."""
        for before, after in ((144, 4), (172, 4), (169, 4)):
            with self.subTest(drop=f"{before}->{after}"):
                s = LoopStore()
                s.observe_shape("sid:k", "root", 3)
                s.observe_shape("sid:k", "root", before)
                self.assertTrue(s.observe_shape("sid:k", "root", after))

    def test_it_is_sticky_like_the_root_signal(self):
        s = LoopStore()
        s.observe_shape("sid:k", "fp1", 90)
        self.assertTrue(s.observe_shape("sid:k", "fp1", 4))
        self.assertTrue(s.observe_shape("sid:k", "fp1", 6))   # not consumed by a turn that didn't act
        s.clear_rewrite("sid:k")
        self.assertFalse(s.observe_shape("sid:k", "fp1", 8))


class WhatMustNotBecomeARewriteTests(unittest.TestCase):
    """A false positive here re-issues a probe and re-anchors the coder's turn for no reason."""

    def test_growing_is_never_a_rewrite(self):
        s = LoopStore()
        s.observe_shape("sid:k", "fp1", 3)
        for n in (5, 9, 30, 144, 145):
            with self.subTest(n=n):
                self.assertFalse(s.observe_shape("sid:k", "fp1", n))

    def test_the_same_length_twice_is_not_a_rewrite(self):
        s = LoopStore()
        s.observe_shape("sid:k", "fp1", 12)
        self.assertFalse(s.observe_shape("sid:k", "fp1", 12))

    def test_first_sight_is_not_a_rewrite_however_short(self):
        self.assertFalse(LoopStore().observe_shape("sid:k", "fp1", 1))

    def test_no_root_at_all_still_never_flags(self):
        self.assertFalse(LoopStore().observe_shape("sid:k", "", 1))

    def test_the_root_signal_is_untouched(self):
        """The original test, restated: a replaced root is still a rewrite on its own."""
        s = LoopStore()
        s.observe_shape("sid:k", "fp1", 3)
        self.assertTrue(s.observe_shape("sid:k", "fp2", 500))   # root replaced, history GREW


class ThePlannerGetsTheSummaryNotTheTaskTests(unittest.TestCase):
    def root(self):
        return "Make these four changes to the orders service: 1. Add …"

    def messages(self, with_continuation: bool):
        msgs = [{"role": "user", "content": self.root()},
                {"role": "assistant", "content": "ok"}]
        if with_continuation:
            msgs.append({"role": "user",
                         "content": f"{CONTINUATION_MARKER} Earlier in THIS session you added the "
                                    "GET /orders/{id} route in orders/api.py; the DELETE route is "
                                    "still missing."})
        return msgs

    def test_the_reanchored_turn_is_the_summary(self):
        out = _rewrite_summary_text(self.messages(True), self.root())
        self.assertIn("DELETE route is still missing", out)
        self.assertNotIn("Make these four changes", out)

    def test_the_replaced_root_shape_still_gets_the_root(self):
        """A harness that puts the summary AT the root: nothing carries the marker, and the root is
        the summary. Falls back to exactly what the caller used to pass unconditionally."""
        self.assertEqual(_rewrite_summary_text(self.messages(False), self.root()), self.root())

    def test_the_newest_one_wins(self):
        msgs = self.messages(True)
        msgs.append({"role": "user", "content": f"{CONTINUATION_MARKER} second compaction, later"})
        self.assertIn("second compaction", _rewrite_summary_text(msgs, self.root()))

    def test_an_assistant_turn_carrying_the_marker_is_not_the_summary(self):
        """cria's own notes are echoed back in assistant turns; only a USER turn is the harness
        handing the conversation over."""
        msgs = [{"role": "user", "content": self.root()},
                {"role": "assistant", "content": f"{CONTINUATION_MARKER} not the harness"}]
        self.assertEqual(_rewrite_summary_text(msgs, self.root()), self.root())


class ItIsWiredIntoTheDriverTests(unittest.TestCase):
    """Drive the real continuation branch of ``_drive_locked``: a Codex-shaped compaction (same
    root, shorter history) on a session ``_drive_locked`` has never seen before (no live
    PlanSession — the shape is primed directly on the store, which is what a completed/evicted
    session plus a resumed harness conversation looks like)."""

    def _drive_continuation(self):
        from cria.loop import CONTINUATION_MARKER, Loop, _history_root
        from tests.test_loop import _ctx, _Rlog, _SHELL

        class _Class:
            def __init__(self, task_type="coding", engagement="task"):
                self.task_type = task_type
                self.engagement = engagement

        root = "Make these four changes to the orders service: 1. Add …"
        _root_text, root_fp = _history_root([{"role": "user", "content": root}])
        coder = lambda b, r: b"{}"

        l = Loop(_ctx(coder, None))
        sk = "sid:x1"
        l._store.observe_shape(sk, root_fp, 40)  # prime a longer prior history under this root

        messages = [
            {"role": "user", "content": root},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": f"{CONTINUATION_MARKER} Earlier in THIS session you added "
                                        "the GET /orders/{id} route in orders/api.py; the DELETE "
                                        "route is still missing."},
        ]
        body = {"messages": messages, "tools": [_SHELL]}
        l._drive_locked(body, sk, _Class(), _Rlog())
        return l

    def test_exact_call_0124_toolless_checkpoint_records_the_rewrite_before_deferral(self):
        """CALL0096's pending work was followed by CALL0124: two messages, no tools.

        The exact checkpoint prose is fixture data; the production decision is solely the
        prior 40-message shape becoming this two-message shape under the same stable key.
        """
        from cria.loop import Loop
        from tests.test_loop import _ctx, _Rlog

        class _Class:
            task_type = "reasoning"
            engagement = "question"

        loop, rlog, key = Loop(_ctx(lambda _body, _rlog: b"{}", None)), _Rlog(), "sid:call0096"
        root = "Make these five changes to the shipping module"
        loop._store.observe_shape(key, _history_root([{"role": "user", "content": root}])[1], 40)
        capture = json.loads((Path(__file__).parent / "fixtures" /
                              "call0096-0124-classifier.body.json").read_text())
        self.assertEqual(len(capture["messages"]), 2)
        self.assertNotIn("tools", capture)
        out = loop._drive_locked(capture, key, _Class(), rlog)

        self.assertIsNone(out)  # still deferred: no tool may be invented for a harness checkpoint
        self.assertIn("loop.history_rewritten", rlog.kinds())
        self.assertTrue(loop._store._shapes[key]["pending"])

    def test_toolless_turn_that_did_not_rewrite_history_stays_deferred_and_unmarked(self):
        from cria.loop import Loop
        from tests.test_loop import _ctx, _Rlog

        class _Class:
            task_type = "reasoning"
            engagement = "question"

        loop, rlog, key = Loop(_ctx(lambda _body, _rlog: b"{}", None)), _Rlog(), "sid:ordinary"
        messages = [
            {"role": "system", "content": "You are a coding agent."},
            {"role": "user", "content": "Summarize this implementation."},
        ]
        loop._store.observe_shape(key, _history_root(messages)[1], len(messages))
        self.assertIsNone(loop._drive_locked({"messages": messages, "tools": []}, key, _Class(), rlog))
        self.assertNotIn("loop.history_rewritten", rlog.kinds())
        self.assertFalse(loop._store._shapes[key]["pending"])

    def test_the_planner_call_uses_the_picker(self):
        """The planner must be told the RE-ANCHORED continuation, not the raw root task — handing
        it the root asks it to re-plan the whole job, the one thing a continuation exists to avoid."""
        l = self._drive_continuation()
        self.assertIn("DELETE route is still missing", l._ctx.planner.rewrite_summary_seen)
        self.assertNotIn("Make these four changes", l._ctx.planner.rewrite_summary_seen)

    def test_the_prior_work_uses_it_too(self):
        """The coder's protected context and the planner's frame must be the same text — handing
        the planner the summary and the coder the task is how the two disagree."""
        l = self._drive_continuation()
        sess = l._store.get("sid:x1")
        self.assertIn("DELETE route is still missing", sess.prior_work)
        self.assertNotIn("Make these four changes", sess.prior_work)


if __name__ == "__main__":
    unittest.main()
