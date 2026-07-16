import unittest

from cria import selfcompact
from cria.selfcompact import CompactState, compact


def _msgs(n, anchor_at=None, anchor_text="⟦cria:briefing⟧ prior"):
    out = [{"role": "system", "content": "sys"}]
    for i in range(n):
        if anchor_at is not None and i == anchor_at:
            out.append({"role": "user", "content": anchor_text})
        else:
            out.append({"role": "assistant", "content": f"turn-{i}"})
    return out


class SelfCompactTests(unittest.TestCase):
    def test_noop_below_trigger(self):
        m = _msgs(50)
        calls = []
        out, st, applied = compact(m, lambda mm: (calls.append(1), "S")[1], CompactState())
        self.assertFalse(applied)
        self.assertIs(out, m)          # same list, untouched
        self.assertEqual(calls, [])    # no reasoner call

    def test_compacts_old_middle_keeps_tail(self):
        m = _msgs(120)                 # 121 messages
        calls = []
        out, st, applied = compact(m, lambda mm: (calls.append(mm), "ROLLUP")[1], CompactState())
        self.assertTrue(applied)
        self.assertEqual(len(calls), 1)                        # summarized ONCE
        self.assertLess(len(out), len(m))                      # much leaner
        self.assertEqual(out[0], m[0])                         # system kept
        self.assertTrue(any(selfcompact.SUMMARY_MARKER in str(x.get("content")) for x in out))  # rollup present
        self.assertEqual(out[-selfcompact.KEEP_TAIL:], m[-selfcompact.KEEP_TAIL:])  # tail verbatim

    def test_throttled_reuse_then_recompact(self):
        state = CompactState()
        calls = []
        summ = lambda mm: (calls.append(1), f"S{len(calls)}")[1]
        _, state, _ = compact(_msgs(120), summ, state)          # first summary
        self.assertEqual(len(calls), 1)
        # a few more turns → band under the throttle → REUSE (no new reasoner call)
        _, state, _ = compact(_msgs(125), summ, state)
        self.assertEqual(len(calls), 1)
        # far past the throttle → RE-summarize
        _, state, _ = compact(_msgs(160), summ, state)
        self.assertEqual(len(calls), 2)

    def test_anchor_kept_verbatim_not_summarized(self):
        m = _msgs(120, anchor_at=5, anchor_text="⟦cria:briefing⟧ the earlier plan handoff")
        out, _, _ = compact(m, lambda mm: "ROLLUP", CompactState())
        # the anchor is in the output verbatim, and was NOT handed to the summarizer
        self.assertTrue(any("the earlier plan handoff" in str(x.get("content")) for x in out))

    def test_anchor_markers_stay_in_sync(self):
        from cria.loop import BRIEFING_OPEN
        from cria.probegate import SECTION_PREFIX
        self.assertIn(BRIEFING_OPEN, selfcompact._ANCHOR_MARKERS)
        self.assertIn(SECTION_PREFIX, selfcompact._ANCHOR_MARKERS)


if __name__ == "__main__":
    unittest.main()
