"""Learned per-model token-density ratio (real÷chars/4), asymmetric EWMA."""
import unittest

from cria import tokenratio


class TokenRatioTests(unittest.TestCase):
    def setUp(self):
        tokenratio.reset()

    def test_default_until_measured(self):
        self.assertEqual(tokenratio.observed("m"), tokenratio.DEFAULT_RATIO)

    def test_rises_fast_toward_a_denser_turn(self):
        # observed ratio 2.4 (real 24k vs est 10k) should pull the learned ratio UP hard.
        tokenratio.record("m", 24000, 10000)
        r = tokenratio.observed("m")
        self.assertGreater(r, 2.0)  # rose fast from 1.8 toward 2.4
        self.assertLessEqual(r, 2.4)

    def test_falls_slow_after_a_light_turn(self):
        tokenratio.record("m", 30000, 10000)   # 3.0 → ratio climbs high
        high = tokenratio.observed("m")
        tokenratio.record("m", 18000, 10000)   # 1.8 → one light turn
        low = tokenratio.observed("m")
        self.assertLess(low, high)             # it fell...
        self.assertGreater(low, 2.2)           # ...but only slowly (guard mostly held)

    def test_clamped_to_max(self):
        for _ in range(10):
            tokenratio.record("m", 100000, 10000)  # 10x → clamps at MAX
        self.assertLessEqual(tokenratio.observed("m"), tokenratio.MAX_RATIO)

    def test_never_below_default(self):
        for _ in range(10):
            tokenratio.record("m", 5000, 10000)  # 0.5x → clamped up to DEFAULT
        self.assertGreaterEqual(tokenratio.observed("m"), tokenratio.DEFAULT_RATIO)

    def test_per_model(self):
        tokenratio.record("dense", 30000, 10000)
        self.assertGreater(tokenratio.observed("dense"), tokenratio.observed("other"))

    def test_ignores_missing_or_zero(self):
        self.assertIsNone(tokenratio.record("m", None, 10000))
        self.assertIsNone(tokenratio.record("m", 0, 10000))
        self.assertIsNone(tokenratio.record("m", 24000, 0))
        self.assertEqual(tokenratio.observed("m"), tokenratio.DEFAULT_RATIO)

    def test_reports_shift_then_settles_once_converged(self):
        self.assertIsNotNone(tokenratio.record("m", 30000, 10000))  # first big jump → reported
        # feeding the same density, the EWMA converges and stops reporting (no per-turn spam)
        results = [tokenratio.record("m", 30000, 10000) for _ in range(8)]
        self.assertIn(None, results, "settles (stops reporting a shift) once converged")


if __name__ == "__main__":
    unittest.main()
