import unittest

from cria.turnstats import StatsStore, TurnStats


class TurnStatsTests(unittest.TestCase):
    def test_tallies_calls_tps_and_guards(self):
        st = TurnStats()
        st.observe({"choices": [{"message": {"tool_calls": [{"id": "a"}]}}],
                    "cria_notes": ["reasoning loop detected — refocused (1×)"]}, 40.0, model_calls=1)
        st.observe({"choices": [{"message": {
            "content": "⟦cria⟧ running the repo's checks (repeated rewrites detected)"}}]}, 36.0, model_calls=1)
        s = st.summary()
        self.assertTrue(s.startswith("⟦cria⟧ turn done"))
        self.assertIn("🧮 2 calls", s)
        self.assertIn("38.0 tok/s", s)          # (40 + 36) / 2
        self.assertIn("rumination×1", s)
        self.assertIn("wheel-spin×1", s)

    def test_calls_counts_model_calls_not_finalized_responses(self):
        # THREE finalized responses, but the model-call reality: 1 (a normal request), 0 (a synthetic
        # held-'done' answered with NO model call), 3 (a request that drove coder + self-compact + a
        # retry). "🧮 N calls" must show 4 real model calls — matching the ~/.cria/calls folder — and
        # must NOT be the 3 finalized responses.
        st = TurnStats()
        st.observe({"choices": [{"message": {"tool_calls": [{"id": "a"}]}}]}, 60.0, model_calls=1)
        st.observe({"choices": [{"message": {"tool_calls": [{"id": "b"}]}}]}, None, model_calls=0)
        st.observe({"choices": [{"message": {"content": "done"}}]}, 58.0, model_calls=3)
        self.assertIn("🧮 4 calls", st.summary())   # 1 + 0 + 3 model calls, NOT the 3 finalized responses
        self.assertEqual(st.calls, 3)               # the reset gate still counts finalized responses

    def test_no_guards_no_shield_section(self):
        st = TurnStats()
        st.observe({"choices": [{"message": {"content": "hi"}}]}, 50.0)
        self.assertNotIn("🛡", st.summary())

    def test_generated_tokens_summed_and_shown(self):
        st = TurnStats()
        st.observe({"choices": [{"message": {"tool_calls": [{"id": "a"}]}}]}, 40.0, 1800)
        st.observe({"choices": [{"message": {"content": "done"}}]}, 36.0, 1500)
        s = st.summary()
        self.assertIn("🔢 3.3k tok", s)             # 1800 + 1500 = 3300 → 3.3k

    def test_small_token_count_not_abbreviated(self):
        st = TurnStats()
        st.observe({"choices": [{"message": {"content": "hi"}}]}, 50.0, 850)
        self.assertIn("🔢 850 tok", st.summary())

    def test_no_tokens_no_count_section(self):
        st = TurnStats()
        st.observe({"choices": [{"message": {"content": "hi"}}]}, 50.0)   # gen_tokens defaults to 0
        self.assertNotIn("🔢", st.summary())

    def test_store_reset(self):
        store = StatsStore()
        store.get("k").calls = 5
        store.reset("k")
        self.assertEqual(store.get("k").calls, 0)  # fresh instance after reset
