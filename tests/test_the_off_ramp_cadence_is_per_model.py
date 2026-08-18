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
from sampling import CADENCE_BANDS, MODEL_SAMPLING, apply, cadence, measured_tok_s  # noqa: E402


def cadence_for_tok_s(tok_s):
    for ceiling, band in CADENCE_BANDS:
        if tok_s < ceiling:
            return band
    return CADENCE_BANDS[-1][1]

SKELETON = ('[context]\ntrigger_compaction = 20000\n\n[roles.coder]\nbackend = "local"\n\n'
            '[roles.reasoner]\nbackend = "local"\n\n[roles.classifier]\nbackend = "local"\n\n'
            '[roles.compactor]\nbackend = "local"\n')


def swap(model):
    t = Path(tempfile.mkdtemp()) / "cria.toml"
    t.write_text(SKELETON)
    apply(model, t)
    return t.read_text()


class TheOperatorsRuleTests(unittest.TestCase):
    """Slower tok/s — which tracks the parameters actually scanned per token — gets a LOWER start and
    interval. A slow model gets fewer drives inside any wall clock, so a cadence counted in drives
    has to shrink with it or it never arrives."""

    ANCHORS = (("ternary-bonsai", 41.7, (20, 10)), ("gemma4", 60.3, (24, 12)),
               ("qwen35", 78.2, (30, 15)), ("nemotron-elastic", 131.8, (54, 18)))

    def test_the_four_anchors_land_in_their_bands(self):
        for model, tok_s, want in self.ANCHORS:
            with self.subTest(model=model, tok_s=tok_s):
                self.assertEqual(cadence_for_tok_s(tok_s), want)

    def test_the_bands_are_monotonic(self):
        """Faster never gets a lower start than slower — that is the rule, stated as an invariant."""
        seen = [cadence_for_tok_s(t)[0] for t in (10, 45, 65, 80, 140, 500)]
        self.assertEqual(seen, sorted(seen))

    def test_it_is_keyed_on_the_measurement_not_a_name_list(self):
        """A hand-kept family table got this wrong on its first outing — see
        test_a_slow_MoE_is_filed_by_speed_not_architecture."""
        import inspect
        import sampling
        self.assertIn("avg_tok_s", inspect.getsource(sampling.measured_tok_s))

    def test_a_slow_MoE_is_filed_by_speed_not_architecture(self):
        """THE CORRECTION. `maple-preview` is a 256-expert MoE and was hand-filed with the other MoEs
        at 54/18. It measures ~63 tok/s — next door to gemma4's 60.3 — because tq2_0 on a fork kernel
        is nothing like nemotron-elastic's 131.8. Architecture was the wrong key."""
        self.assertEqual(cadence_for_tok_s(63.2), (24, 12))
        self.assertEqual(cadence_for_tok_s(131.8), (54, 18))

    def test_an_unmeasured_model_takes_the_slowest_band(self):
        """Unmeasured is not "fast". Checking too early costs one reasoner call; checking too late
        costs a finished session that never stops (#13's safe direction)."""
        self.assertEqual(cadence("a-model-that-has-never-run"), (20, 10))

    def test_every_start_is_reachable_by_a_median_run(self):
        """The whole point: the median run is 70 calls, and 100 was out of reach."""
        for _, band in CADENCE_BANDS:
            with self.subTest(band=band):
                self.assertLess(band[0], 70)


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
