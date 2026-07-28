import unittest
from collections import Counter

from cria.turnstats import StatsStore, TurnStats


class TurnStatsTests(unittest.TestCase):
    def test_tallies_calls_tps_and_steers_from_events(self):
        st = TurnStats()
        # steer fires arrive as event counters (one entry per distinct fire), not note text
        st.observe(40.0, model_calls=1, events=Counter({"rumination.abort": 1}))
        st.observe(36.0, model_calls=1, events=Counter({"loop.wheel_spinning": 1}))
        s = st.summary()
        self.assertTrue(s.startswith("⟦cria⟧ turn done"))
        self.assertIn("🧮 2 calls", s)
        self.assertIn("38.0 tok/s", s)          # (40 + 36) / 2
        self.assertIn("🛡 ", s)
        self.assertIn("rumination×1", s)
        self.assertIn("wheel-spin×1", s)

    def test_steers_and_reshapes_are_separate_buckets(self):
        st = TurnStats()
        # a heavy turn: model-facing steers AND silent context reshaping, from authoritative events
        st.observe(60.0, model_calls=1, events=Counter({
            "loop.periodic_gate": 3, "loop.gate.blocked": 1, "loop.wheel_spinning": 1,
            "context.self_compact": 22, "context.focus_trim": 21,
            "massage.leaked_recovered": 4, "massage.text_from_reasoning": 2,
            "loop.gate": 1,                       # a clean gate pass → NOT counted (only .blocked is)
        }))
        s = st.summary()
        self.assertIn("🛡 ", s)
        self.assertIn("periodic-gate×3", s)       # was invisible under the old text-match
        self.assertIn("gate×1", s)                # from loop.gate.blocked, not the clean loop.gate
        self.assertIn("wheel-spin×1", s)          # distinct fire count, not note echoes
        self.assertIn("🧰 ", s)
        self.assertIn("compact×22", s)
        self.assertIn("focus-trim×21", s)
        self.assertIn("massage×6", s)             # 4 + 2 across the two massage kinds → one label
        self.assertNotIn("gate×2", s)             # the clean pass was not miscounted as a steer

    def test_calls_counts_model_calls_not_finalized_responses(self):
        # THREE finalized responses, but the model-call reality: 1 (a normal request), 0 (a synthetic
        # held-'done' answered with NO model call), 3 (a request that drove coder + self-compact + a
        # retry). "🧮 N calls" must show 4 real model calls — matching the ~/.cria/calls folder — and
        # must NOT be the 3 finalized responses.
        st = TurnStats()
        st.observe(60.0, model_calls=1)
        st.observe(None, model_calls=0)
        st.observe(58.0, model_calls=3)
        self.assertIn("🧮 4 calls", st.summary())   # 1 + 0 + 3 model calls, NOT the 3 finalized responses
        self.assertEqual(st.calls, 3)               # the reset gate still counts finalized responses

    def test_no_interventions_no_shield_or_toolbox_section(self):
        st = TurnStats()
        st.observe(50.0, model_calls=1)   # a clean turn, no intervention events
        s = st.summary()
        self.assertNotIn("🛡", s)
        self.assertNotIn("🧰", s)

    def test_non_intervention_events_are_ignored(self):
        st = TurnStats()
        st.observe(50.0, model_calls=1,
                   events=Counter({"upstream.request": 5, "ctx.estimate": 5, "route.classify": 5}))
        s = st.summary()
        self.assertNotIn("🛡", s)   # plumbing events never appear in the ledger
        self.assertNotIn("🧰", s)

    def test_generated_tokens_summed_and_shown(self):
        st = TurnStats()
        st.observe(40.0, 1800)
        st.observe(36.0, 1500)
        s = st.summary()
        self.assertIn("🔢 3.3k tok", s)             # 1800 + 1500 = 3300 → 3.3k

    def test_small_token_count_not_abbreviated(self):
        st = TurnStats()
        st.observe(50.0, 850)
        self.assertIn("🔢 850 tok", st.summary())

    def test_no_tokens_no_count_section(self):
        st = TurnStats()
        st.observe(50.0)   # gen_tokens defaults to 0
        self.assertNotIn("🔢", st.summary())

    def test_store_reset(self):
        store = StatsStore()
        store.get("k").calls = 5
        store.reset("k")
        self.assertEqual(store.get("k").calls, 0)  # fresh instance after reset


class FinalizeKeepsUnreportedCallsTests(unittest.TestCase):
    """A TALLY THAT WAS NEVER SHOWN MUST NOT BE THROWN AWAY.

    `_finalize` ends a turn on "a text answer after real work" (no tool calls, >=2 calls). The reset
    was unconditional while the SUMMARY was gated on `_has_visible_output` — so an EMPTY answer (no
    tool calls, no content), which this path sees routinely, discarded the counts with nothing shown.

    Measured on run 0728-m2: 1711 real `upstream.done` calls, TWO summaries emitted totalling 86
    calls. ~1625 calls were attributed nowhere, and "🧮 43 calls" reads as the cost of a run that
    actually made 1711. Reset now happens only after the summary is emitted, so the next report
    covers everything since the last one."""

    def _finalize(self, completion, stats_calls=5):
        import types as _t
        from cria.server import CriaHandler
        from cria.turnstats import StatsStore
        store = StatsStore()
        st = store.get("k")
        st.calls = stats_calls
        st.model_calls = 43
        st.observe(50.0, 100, 0)                      # t0 set; calls -> stats_calls+1
        fake = _t.SimpleNamespace(
            server=_t.SimpleNamespace(
                cfg=_t.SimpleNamespace(indicators=_t.SimpleNamespace(enabled=True, stats=True)),
                stats_store=store),
            _decorate=lambda c: c)
        rlog = _t.SimpleNamespace(last_tok_per_s=None, gen_tokens=0, model_calls=0, events=None)
        CriaHandler._finalize(fake, completion, "k", rlog)
        return store.get("k")

    def _empty_answer(self):
        return {"choices": [{"message": {"role": "assistant", "content": ""}}]}

    def _text_answer(self):
        return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}

    def test_an_empty_answer_does_not_discard_the_tally(self):
        st = self._finalize(self._empty_answer())
        self.assertGreater(st.model_calls, 0,
                           "counts were dropped for a turn whose summary was never shown")

    def test_a_visible_answer_reports_then_resets(self):
        comp = self._text_answer()
        st = self._finalize(comp)
        shown = (comp["choices"][0]["message"]["content"])
        self.assertIn("calls", shown)                 # the summary WAS surfaced
        self.assertEqual(st.model_calls, 0)           # and only then is the tally cleared
