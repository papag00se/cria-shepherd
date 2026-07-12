"""The pure rumination detector (cria/rumination.py) — a port of codex-local's
rumination_detector.rs; these mirror its unit tests."""
import unittest

from cria import rumination


class MarkerCountTests(unittest.TestCase):
    def test_case_insensitive(self):
        self.assertEqual(rumination.count_markers("Actually"), 1)
        self.assertEqual(rumination.count_markers("ACTUALLY"), 1)
        self.assertEqual(rumination.count_markers("actually"), 1)

    def test_word_boundary_prevents_false_positives(self):
        # `waiting` `factually` `reconsideration` must NOT fire `wait` `actually` `reconsider`.
        self.assertEqual(rumination.count_markers("waiting factually reconsideration whatever"), 0)

    def test_multi_word_markers(self):
        self.assertEqual(rumination.count_markers("But wait, let me think again."), 2)
        self.assertEqual(rumination.count_markers("on second thought, scratch that"), 2)

    def test_realistic_drift_passage_flags(self):
        text = ("Let me think. Actually, wait. I should check the file. But hmm, maybe I need to "
                "reconsider. On second thought, let me re-examine. Actually no, the plan was fine.")
        self.assertGreaterEqual(rumination.count_markers(text), 6)


class DetectorTests(unittest.TestCase):
    def test_below_budget_gate_never_flags(self):
        det = rumination.Detector(10_000, 3)
        text = "actually wait hmm let me reconsider actually wait"
        self.assertIsNone(det.check(text, 100))  # packed markers but under the 5000-token gate

    def test_above_gate_with_threshold_hits_flags(self):
        det = rumination.Detector(1000, 3)
        self.assertIsNotNone(det.check("Actually, wait. Hmm, let me reconsider.", 600))

    def test_above_gate_below_threshold_stays_ok(self):
        det = rumination.Detector(1000, 5)
        self.assertIsNone(det.check("I'll check the file. Actually, that's fine. Proceeding.", 600))

    def test_length_backstop_fires_without_markers(self):
        # The real incident: a marker-FREE reasoning runaway that consumes the whole budget must
        # abort on length alone (the marker arm never fires).
        det = rumination.Detector(8192, 6)
        prose = "The handler resolves the handle and returns the address. " * 200
        self.assertEqual(rumination.count_markers(prose), 0)
        self.assertIsNotNone(det.check(prose, 48_882))   # over full budget → flagged on length
        self.assertIsNone(det.check(prose, 5000))        # past the gate, under budget, 0 markers → ok

    def test_zero_budget_falls_back_to_default(self):
        det = rumination.Detector(0, 3)
        self.assertEqual(det.budget_gate(), rumination.DEFAULT_REASONING_BUDGET // 2)

    def test_from_reasoning_budget(self):
        self.assertEqual(rumination.Detector.from_reasoning_budget(None).budget_gate(),
                         rumination.DEFAULT_REASONING_BUDGET // 2)
        self.assertEqual(rumination.Detector.from_reasoning_budget(8192).budget_gate(), 4096)

    def test_verdict_carries_hits_and_tokens(self):
        det = rumination.Detector(1000, 3)
        v = det.check("actually wait hmm nope scratch that hold on", 900)
        self.assertIsNotNone(v)
        self.assertIn("hits", v)
        self.assertEqual(v["reasoning_tokens"], 900)


if __name__ == "__main__":
    unittest.main()
