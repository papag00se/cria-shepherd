import unittest

from cria.turnstats import StatsStore, TurnStats


class TurnStatsTests(unittest.TestCase):
    def test_tallies_calls_tps_and_guards(self):
        st = TurnStats()
        st.observe({"choices": [{"message": {"tool_calls": [{"id": "a"}]}}],
                    "cria_notes": ["reasoning loop detected — refocused (1×)"]}, 40.0)
        st.observe({"choices": [{"message": {
            "content": "⟦cria⟧ running the repo's checks (repeated rewrites detected)"}}]}, 36.0)
        s = st.summary()
        self.assertTrue(s.startswith("⟦cria⟧ turn done"))
        self.assertIn("🧮 2 calls", s)
        self.assertIn("38.0 tok/s", s)          # (40 + 36) / 2
        self.assertIn("rumination×1", s)
        self.assertIn("wheel-spin×1", s)

    def test_no_guards_no_shield_section(self):
        st = TurnStats()
        st.observe({"choices": [{"message": {"content": "hi"}}]}, 50.0)
        self.assertNotIn("🛡", st.summary())

    def test_store_reset(self):
        store = StatsStore()
        store.get("k").calls = 5
        store.reset("k")
        self.assertEqual(store.get("k").calls, 0)  # fresh instance after reset
