"""The message beside a runner's failure location must say WHAT went wrong, not how many did.

`parse_runner_locations` picked the nearest line containing "assert" — and minitest's banner,
`Finished in 0.011386s, 614.8036 runs/s, 614.8036 assertions/s.`, contains "assert" inside
"assertions". It sits ABOVE the failure header, so it beat `Expected: 12.0` sitting below. cria then
shipped its own stopwatch reading to the coder under "each is the checker's OWN message and the line
it flagged", and `Expected: 12.0 / Actual: 0.0` — the only part anyone can act on — was dropped.

Live for every minitest cell in the battery; both ruby cells of the 2026-08-22 batch scored 20%."""
import unittest

from cria import probeparse

MINITEST = """Run options: --seed 18692

# Running:

....F..

Finished in 0.011386s, 614.8036 runs/s, 614.8036 assertions/s.

  1) Failure:
TestRates#test_oversize_surcharge [/w/test/test_rates.rb:23]:
Expected: 12.0
  Actual: 0.0

7 runs, 7 assertions, 1 failures, 0 errors, 0 skips
"""


class TheCheckersOwnMessageTests(unittest.TestCase):
    def test_the_timing_banner_is_never_the_failure(self):
        [f] = probeparse.parse_runner_locations(MINITEST)
        self.assertNotIn("runs/s", f.message)
        self.assertNotIn("Finished in", f.message)

    def test_the_comparison_survives_whole(self):
        [f] = probeparse.parse_runner_locations(MINITEST)
        self.assertIn("Expected: 12.0", f.message)
        self.assertIn("Actual: 0.0", f.message)

    def test_the_summary_the_coder_reads(self):
        summary = probeparse.parse_output(
            "rake test", probeparse.family_of(["rake", "test"]), 1, MINITEST, "").summary
        self.assertEqual(summary, "/w/test/test_rates.rb:23: Expected: 12.0 / Actual: 0.0")

    def test_a_tally_line_is_recognised_by_shape_not_by_one_runner_s_words(self):
        for line in ("7 runs, 7 assertions, 1 failures, 0 errors, 0 skips",
                     "12 examples, 1 failure, 2 pending",
                     "Tests run: 12, Failures: 1, Errors: 0, Skipped: 2",
                     "Finished in 0.014s, 480.3 runs/s, 480.3 assertions/s.",
                     "2 failed, 7 passed in 0.05s"):
            self.assertFalse(probeparse._says_what_went_wrong(line), line)

    def test_a_real_diagnostic_still_reads_as_one(self):
        for line in ("Expected: 12.0", "AssertionError: 0 not greater than 0",
                     "undefined method `zone_for'", "panicked at src/lib.rs:7",
                     "expected:<3> but was:<4>"):
            self.assertTrue(probeparse._says_what_went_wrong(line), line)

    def test_a_word_inside_another_word_does_not_count(self):
        self.assertFalse(probeparse._says_what_went_wrong("614.8036 assertions/s"))


if __name__ == "__main__":
    unittest.main()
