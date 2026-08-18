"""The off-ramp for a finished session could not be reached by most runs.

`_periodic_satisfaction` exists for one thing — *"a session that has FINISHED the work but cannot
stop"* — and was gated at `satisfaction_check_start = 100`, then every 25 drives. **The median run in
`results.jsonl` is 70 calls, so 300 of 463 runs could never reach it.** On the cell that exposed it
the gate was arithmetic: 54 calls against a start of 100, while the run sat on a banked 4/4 for
twenty-six minutes.

THE RULE (operator, 2026-08-17): the more parameters a model actually scans per token, the LOWER the
start and interval, because higher-parameter models tend to be done in fewer turns. A model that
converges in fifty drives must be asked before drive fifty.

PINNED TO PARAMETERS, NOT tok/s. Throughput was the first cut and it is hardware-bound — the same
model on a different GPU changes band without changing at all.

ACTIVE, not total, and that is the whole point for this fleet: `nemotron-elastic` and `gemma4` are
both ~11.9B TOTAL and one scans a sixth of itself. `n_params` comes from the server; the expert
counts come from the GGUF header at the `model_path` the server reports — the same source
`docs/model-settings.md` classifies the fleet from, *"never a card or a name"*.

ONE FORMULA, no notches: `start = 60 - 30·log10(active_B)`, clamped. The ceiling is what makes it
work — a start above the 70-call median is a check that never happens, which is exactly what the flat
100 was.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "suite"))
from sampling import (CADENCE_MAX_START, CADENCE_UNKNOWN, apply,  # noqa: E402
                      cadence_for_active, gguf_experts)

SKELETON = ('[context]\ntrigger_compaction = 20000\n\n[roles.coder]\nbackend = "local"\n\n'
            '[roles.reasoner]\nbackend = "local"\n\n[roles.classifier]\nbackend = "local"\n\n'
            '[roles.compactor]\nbackend = "local"\n')


class TheScaleSlidesTests(unittest.TestCase):
    def test_more_scanned_parameters_means_a_lower_start(self):
        """The rule, as an invariant rather than a table of cases."""
        starts = [cadence_for_active(b)[0] for b in (1, 2, 4, 9, 12, 20, 27)]
        self.assertEqual(starts, sorted(starts, reverse=True))

    def test_it_is_continuous_not_notched(self):
        """Neighbouring sizes must not jump a band — that was the four-notch version."""
        for a, b in ((8, 9), (9, 10), (11, 12), (12, 13)):
            with self.subTest(pair=(a, b)):
                self.assertLessEqual(abs(cadence_for_active(a)[0] - cadence_for_active(b)[0]), 3)

    def test_a_decade_of_scale_is_thirty_drives(self):
        self.assertEqual(cadence_for_active(1)[0] - cadence_for_active(10)[0], 30)

    def test_the_interval_tracks_the_start(self):
        for b in (1, 9, 27):
            with self.subTest(active=b):
                start, every = cadence_for_active(b)
                self.assertEqual(every, max(5, round(start / 2)))


class EveryStartIsActuallyReachableTests(unittest.TestCase):
    """The defect being fixed: a start above the median run is a check that never happens."""

    MEDIAN_RUN_CALLS = 70

    def test_nothing_is_stranded_at_any_size(self):
        for b in (0.1, 0.5, 1, 2, 9, 12, 27, 70, 500):
            with self.subTest(active=b):
                self.assertLess(cadence_for_active(b)[0], self.MEDIAN_RUN_CALLS)

    def test_the_ceiling_is_below_the_median_run(self):
        self.assertLess(CADENCE_MAX_START, self.MEDIAN_RUN_CALLS)

    def test_an_unreadable_model_takes_the_low_end(self):
        """Unknown is not "small" — fail toward asking sooner (#13's safe direction)."""
        self.assertEqual(cadence_for_active(None), CADENCE_UNKNOWN)
        self.assertEqual(cadence_for_active(0), CADENCE_UNKNOWN)


class ActiveNotTotalTests(unittest.TestCase):
    def test_a_sixth_scanned_lands_far_from_the_same_total_dense(self):
        """nemotron-elastic and gemma4 are both ~11.9B TOTAL. Scanned, they are nothing alike."""
        dense_12b = cadence_for_active(11.9)[0]
        moe_12b_a2b = cadence_for_active(11.9 * 6 / 128)[0]
        self.assertGreater(moe_12b_a2b, dense_12b + 20)

    def test_a_dense_gguf_reports_no_experts(self):
        """No expert keys in the header is the dense case — ratio 1.0, active == total."""
        import struct
        f = Path(tempfile.mkdtemp()) / "d.gguf"
        f.write_bytes(struct.pack("<4sIQQ", b"GGUF", 3, 0, 0))
        self.assertIsNone(gguf_experts(str(f)))

    def test_a_non_gguf_file_is_not_guessed_at(self):
        f = Path(tempfile.mkdtemp()) / "x.bin"
        f.write_bytes(b"not a gguf at all")
        self.assertIsNone(gguf_experts(str(f)))

    def test_a_missing_file_is_not_guessed_at(self):
        self.assertIsNone(gguf_experts("/nonexistent/model.gguf"))


class ItLandsOnEverySwapTests(unittest.TestCase):
    def test_other_context_keys_are_untouched(self):
        t = Path(tempfile.mkdtemp()) / "cria.toml"
        t.write_text(SKELETON)
        apply("gemma4", t)
        self.assertIn("trigger_compaction = 20000", t.read_text())

    def test_the_roles_still_get_their_sampling(self):
        t = Path(tempfile.mkdtemp()) / "cria.toml"
        t.write_text(SKELETON)
        apply("gemma4", t)
        self.assertIn("temperature", t.read_text())

    def test_the_cadence_is_written(self):
        t = Path(tempfile.mkdtemp()) / "cria.toml"
        t.write_text(SKELETON)
        apply("gemma4", t)
        self.assertIn("satisfaction_check_start", t.read_text())


if __name__ == "__main__":
    unittest.main()
