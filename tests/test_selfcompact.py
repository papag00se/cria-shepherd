import unittest

from cria import selfcompact
from cria.selfcompact import CompactState, compact

# Small token budgets so tiny fixtures exercise the real token paths.
_KW = dict(trigger_tokens=100, keep_tail_tokens=30, recompact_tokens=20)


def _m(role, text):
    return {"role": role, "content": text}


def _msgs(n, anchor_at=None, anchor_text="⟦cria:briefing⟧ prior"):
    out = [_m("system", "sys")]
    for i in range(n):
        if anchor_at is not None and i == anchor_at:
            out.append(_m("user", anchor_text))
        else:
            out.append(_m("assistant", f"turn-{i} " + "x" * 20))   # ~6 tokens each
    return out


class SelfCompactTests(unittest.TestCase):
    def test_noop_below_trigger(self):
        m = _msgs(3)
        calls = []
        out, st, applied = compact(m, lambda mm: (calls.append(1), "S")[1], CompactState(), **_KW)
        self.assertFalse(applied)
        self.assertIs(out, m)
        self.assertEqual(calls, [])

    def test_triggers_on_tokens_not_message_count(self):
        # a FEW big messages (over the token trigger) compact even though the count is small
        big = [_m("system", "sys")] + [_m("assistant", "y" * 800) for _ in range(6)]  # ~1200 tokens
        out, _, applied = compact(big, lambda mm: "ROLLUP", CompactState(), **_KW)
        self.assertTrue(applied)
        self.assertTrue(any(selfcompact.SUMMARY_MARKER in str(x.get("content")) for x in out))

    def test_compacts_old_middle_keeps_recent_tail(self):
        m = _msgs(40)
        calls = []
        out, st, applied = compact(m, lambda mm: (calls.append(mm), "ROLLUP")[1], CompactState(), **_KW)
        self.assertTrue(applied)
        self.assertEqual(len(calls), 1)                 # summarized once
        self.assertLess(len(out), len(m))               # leaner
        self.assertEqual(out[0], m[0])                  # system kept
        self.assertEqual(out[-1], m[-1])               # most recent turn verbatim

    def test_throttled_reuse_then_recompact(self):
        state = CompactState()
        calls = []
        summ = lambda mm: (calls.append(1), f"S{len(calls)}")[1]
        _, state, _ = compact(_msgs(40), summ, state, **_KW)
        self.assertEqual(len(calls), 1)
        _, state, _ = compact(_msgs(42), summ, state, **_KW)     # tiny growth → reuse
        self.assertEqual(len(calls), 1)
        _, state, _ = compact(_msgs(80), summ, state, **_KW)     # band over recompact → re-summarize
        self.assertEqual(len(calls), 2)

    def test_anchor_kept_verbatim_not_summarized(self):
        m = _msgs(40, anchor_at=2, anchor_text="⟦cria:briefing⟧ the earlier plan handoff")
        out, _, _ = compact(m, lambda mm: "ROLLUP", CompactState(), **_KW)
        self.assertTrue(any("the earlier plan handoff" in str(x.get("content")) for x in out))

    def test_anchor_markers_stay_in_sync(self):
        from cria.loop import BRIEFING_OPEN
        from cria.probegate import SECTION_PREFIX
        self.assertIn(BRIEFING_OPEN, selfcompact._ANCHOR_MARKERS)
        self.assertIn(SECTION_PREFIX, selfcompact._ANCHOR_MARKERS)


if __name__ == "__main__":
    unittest.main()
