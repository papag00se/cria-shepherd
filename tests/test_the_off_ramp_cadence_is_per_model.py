"""The off-ramp for a finished session could not be reached by most runs.

`_periodic_satisfaction` exists for exactly one thing — *"a session that has FINISHED the work but
cannot stop"* — and it was gated at `satisfaction_check_start = 100`, then every 25 drives. That is a
cadence for long sessions. **The median run in `results.jsonl` is 70 calls**, so 300 of 463 runs
could never reach it, and on the cell that exposed this it was arithmetically unreachable: 54 calls
against a start of 100. The run banked 4/4 at the fifteen-minute milestone and went on for another
twenty-six minutes with the off-ramp structurally out of play.

Operator-set per model (2026-08-17), because how many drives a session takes to converge is a
property of the model, not of cria:

    ternary            start 20, every 10
    gemma              start 24, every 12
    qwen derivatives   start 30, every 15
    MoEs               start 54, every 18

FAMILIES, NOT NAMES (#19/#20). The buckets are the operator's; the assignment is read from the repo's
own GGUF-header classification in `docs/model-settings.md` — *"`general.architecture` plus
`<arch>.expert_count` / `expert_used_count`, never a card or a name"* — so a model joins a bucket by
what it IS rather than by what it is called.

And it is applied the way per-model SAMPLING already is, for the reason that module records in its
own docstring: a per-model number that must be set by hand before a run is a number that will be left
at the previous model's value. That mistake has already been made at scale here — 26 consecutive
gemma4 runs were sent ternary-bonsai's sampling.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "suite"))
from sampling import MODEL_SAMPLING, SATISFACTION_CADENCE, apply, cadence  # noqa: E402

SKELETON = ('[context]\ntrigger_compaction = 20000\n\n[roles.coder]\nbackend = "local"\n\n'
            '[roles.reasoner]\nbackend = "local"\n\n[roles.classifier]\nbackend = "local"\n\n'
            '[roles.compactor]\nbackend = "local"\n')


def swap(model):
    t = Path(tempfile.mkdtemp()) / "cria.toml"
    t.write_text(SKELETON)
    apply(model, t)
    return t.read_text()


class TheOperatorsBucketsTests(unittest.TestCase):
    def test_the_four_buckets(self):
        for model, want in (("ternary-bonsai", (20, 10)), ("gemma4", (24, 12)),
                            ("qwen35", (30, 15)), ("nemotron-elastic", (54, 18))):
            with self.subTest(model=model):
                self.assertEqual(cadence(model), want)

    def test_every_qwen_derivative_shares_the_qwen_bucket(self):
        """qwythos, qwopus and ornith are finetunes of the 9B base — same arch in the headers."""
        for m in ("qwen35", "qwythos", "qwopus", "ornith"):
            with self.subTest(model=m):
                self.assertEqual(cadence(m), (30, 15))

    def test_every_moe_shares_the_moe_bucket(self):
        for m in ("mellum2", "nemotron-elastic", "maple-preview"):
            with self.subTest(model=m):
                self.assertEqual(cadence(m), (54, 18))

    def test_no_model_is_left_unmapped(self):
        """An unmapped model silently keeps the previous model's cadence — the exact failure the
        sampling table was written to stop."""
        self.assertEqual(sorted(SATISFACTION_CADENCE), sorted(MODEL_SAMPLING))

    def test_every_start_is_reachable_by_a_median_run(self):
        """The whole point: the median run is 70 calls, and 100 was out of reach."""
        for m, (start, _) in SATISFACTION_CADENCE.items():
            with self.subTest(model=m):
                self.assertLess(start, 70)


class ItLandsOnEverySwapTests(unittest.TestCase):
    def test_the_cadence_is_written_into_the_config(self):
        text = swap("ternary-bonsai")
        self.assertIn("satisfaction_check_start = 20", text)
        self.assertIn("satisfaction_check_every = 10", text)

    def test_a_swap_replaces_the_previous_models_numbers(self):
        t = Path(tempfile.mkdtemp()) / "cria.toml"
        t.write_text(SKELETON)
        apply("ternary-bonsai", t)
        apply("nemotron-elastic", t)
        text = t.read_text()
        self.assertIn("satisfaction_check_start = 54", text)
        self.assertNotIn("= 20\n", text)

    def test_other_context_keys_are_untouched(self):
        self.assertIn("trigger_compaction = 20000", swap("gemma4"))

    def test_the_roles_still_get_their_sampling(self):
        self.assertIn("temperature", swap("gemma4"))


if __name__ == "__main__":
    unittest.main()
