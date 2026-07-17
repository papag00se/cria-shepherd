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
        from cria.loop import BRIEFING_OPEN, CONTINUATION_MARKER
        from cria.probegate import SECTION_PREFIX
        self.assertIn(BRIEFING_OPEN, selfcompact._ANCHOR_MARKERS)
        self.assertIn(SECTION_PREFIX, selfcompact._ANCHOR_MARKERS)
        # cria's harness-compaction reframe is a cria-authored summary — it must be an anchor so the
        # next self-compaction never summarizes it (the rollup-of-rollup task-inversion footgun).
        self.assertIn(CONTINUATION_MARKER, selfcompact._ANCHOR_MARKERS)

    def test_continuation_reframe_is_not_fed_to_the_summarizer(self):
        # A ⟦cria:continuation⟧ message in the middle must be kept verbatim, never summarized — so
        # cria's own reframed prior-summary can't compound into a rollup-of-a-rollup.
        from cria.loop import CONTINUATION_MARKER
        m = _msgs(40, anchor_at=2, anchor_text=f"{CONTINUATION_MARKER} your earlier work: built X")
        captured = []
        out, _, _ = compact(m, lambda mm: captured.append(mm) or "ROLLUP", CompactState(), **_KW)
        # kept verbatim in the compacted view
        self.assertTrue(any("your earlier work: built X" in str(x.get("content")) for x in out))
        # and NOT among the messages handed to the summarizer
        fed = captured[0] if captured else []
        self.assertFalse(any(CONTINUATION_MARKER in selfcompact._text(x) for x in fed))


if __name__ == "__main__":
    unittest.main()


class PinnedTaskTests(unittest.TestCase):
    """The conversation-root task is re-emitted verbatim as a ⟦cria:task⟧ north-star header on every
    compacted view — so it can't erode into the summary across rounds. Without it a plan-off session
    lost its goal (only an impoverished one-line rollup survived) and drifted onto tangential work."""

    def test_task_header_pinned_after_system_before_rollup(self):
        m = _msgs(40)
        out, _, applied = compact(m, lambda mm: "ROLLUP", CompactState(),
                                  pinned_task="Build the Handle resolver", **_KW)
        self.assertTrue(applied)
        self.assertEqual(out[0], m[0])                                    # system still first
        self.assertIn(selfcompact.TASK_MARKER, str(out[1]["content"]))    # task header right after system
        self.assertIn("Build the Handle resolver", str(out[1]["content"]))
        contents = [str(x.get("content")) for x in out]
        ti = next(i for i, c in enumerate(contents) if selfcompact.TASK_MARKER in c)
        si = next(i for i, c in enumerate(contents) if selfcompact.SUMMARY_MARKER in c)
        self.assertLess(ti, si)                                          # task leads, rollup follows

    def test_task_survives_rounds_despite_impoverished_summary(self):
        task = "Resolve an Ada Handle to a Cardano address via api.handle.me"
        state = CompactState()
        for n in (40, 60, 90):   # summarizer returns a stale, task-less one-liner every round
            out, state, applied = compact(_msgs(n), lambda mm: "mocked requests.get in tests", state,
                                          pinned_task=task, **_KW)
            self.assertTrue(applied)
            self.assertTrue(any(task in str(x.get("content")) for x in out))   # never lost

    def test_no_pinned_task_no_header(self):
        out, _, applied = compact(_msgs(40), lambda mm: "ROLLUP", CompactState(), **_KW)
        self.assertTrue(applied)
        self.assertFalse(any(selfcompact.TASK_MARKER in str(x.get("content")) for x in out))

    def test_huge_task_is_clipped(self):
        out, _, _ = compact(_msgs(40), lambda mm: "R", CompactState(), pinned_task="Z" * 5000, **_KW)
        header = next(str(x["content"]) for x in out if selfcompact.TASK_MARKER in str(x.get("content")))
        self.assertEqual(header.count("Z"), selfcompact._TASK_CLIP)   # task body clipped to the cap
