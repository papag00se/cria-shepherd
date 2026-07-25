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
