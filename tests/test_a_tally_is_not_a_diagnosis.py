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


MINITEST_ERROR = """Run options: --seed 58361

# Running:

..EEE..

Finished in 0.011s, 636.0 runs/s, 363.4 assertions/s.

  1) Error:
TestRates#test_free_shipping_at_the_threshold:
NameError: undefined local variable or method `surcharge' for Shipping:Module
    /w/lib/shipping/rates.rb:19:in `shipping_cost'
    /w/test/test_rates.rb:15:in `test_free_shipping_at_the_threshold'

7 runs, 4 assertions, 0 failures, 3 errors, 0 skips
"""


class AnErrorIsNotAFailureAndBothMustLandTests(unittest.TestCase):
    """minitest prints a FAILURE as `TestX#test_y [file:line]` and an ERROR with bare indented frames.
    The Ruby frame pattern required the literal `from`, which only a plain traceback uses — so every
    minitest Error parsed as nothing, and `summarize` fell back to the bottom-up keyword scan, which
    took `7 runs, 4 assertions, 0 failures, 3 errors, 0 skips` because a tally contains "errors".

    33 of 81 prompts on shipping-rates-rb x nemotron-elastic 1787475117 read "a specific line could
    not be parsed from the output" and then quoted the count."""

    def test_the_error_frame_locates_without_the_word_from(self):
        [*found] = probeparse.parse_runner_locations(MINITEST_ERROR)
        self.assertTrue(any(f.file.endswith("rates.rb") and f.line == 19 for f in found), found)

    def test_the_message_is_the_exception_not_the_index_header(self):
        summary = probeparse.parse_output(
            "rake test", probeparse.family_of(["rake", "test"]), 1, MINITEST_ERROR, "").summary
        self.assertIn("NameError: undefined local variable or method", summary)
        self.assertNotIn("1) Error:", summary)

    def test_an_index_header_is_recognised_as_carrying_nothing(self):
        for line in ("  1) Error:", "2) Failure:", "10) Errors"):
            self.assertFalse(probeparse._says_what_went_wrong(line), line)

    def test_the_fallback_prefers_a_real_line_over_the_tally(self):
        out = ("Run options: --seed 1\n\n..EEE..\n\n"
               "NoMethodError: undefined method `zone_for' for Shipping:Module\n\n"
               "7 runs, 4 assertions, 0 failures, 3 errors, 0 skips\n")
        summary = probeparse.parse_output("rake test", "", 1, out, "").summary
        self.assertIn("NoMethodError", summary)
        self.assertNotIn("7 runs", summary)


if __name__ == "__main__":
    unittest.main()
