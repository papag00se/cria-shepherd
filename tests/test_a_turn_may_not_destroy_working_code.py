"""cria notices when the suite stops running tests it used to pass.

Two of cycle 3's twenty-four lost checks are the same shape, in two languages and two models: the
coder meant to APPEND a test, wrote the edit as a replace, and a seeded test went out with the old
text. shipping-rates-rb x gemma4 lost `test_negative_weight_rejected`; cart-billing-go x gemma4 lost
`TestUnknownCode`. Both were otherwise one check from full marks, and restoring the deleted method
scores 4/5 and 5/5 respectively.

Nothing in the loop asked the question. The gate runs vet, build and test, and all three are green
with a test deleted. In the Go cell the satisfaction judge's evidence held, in order, the test
present, the test passing, the full untruncated edit that overwrote it, and the next run with it
gone — and it answered `satisfied: true`. A second judge read the shortened file and answered
`consistent: true`.

The signal is the runner's own passing count (#12), not a diff and not a test-file name — which is
what keeps it language-agnostic (#20). It is regression-only (#2): it needs a green tally that was
higher earlier, so it cannot fire on a first run, a new suite, or a broken one. And it states the
fact rather than accusing (#5b), because merging two tests into one legitimately lowers the count.
"""

import unittest

from cria import loop, prompts
from cria import probeparse
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
from cria.proberun import ProbeReport


def report(raw, command="python3 -m pytest -q", family="pytest"):
    """A report built through the REAL parser, not by hand.

    THE TEST THAT SHIPPED WITH THIS CHECK BUILT `summary=` DIRECTLY, and that is why the check was
    dead on arrival: `parse_output` replaces a GREEN run's output with the fixed string "no problems
    reported" and keeps no raw text, so every value the old test fed in was one the parser can never
    produce. The tally is taken at parse time now, and every fixture here goes through it.
    """
    cand = ProbeCandidate(kind=ProbeKind.Test, command=command.split(), working_dir="/tmp",
                          confidence=90, expected_value=80, cost=ProbeCost.Cheap, mutates_code=False,
                          may_hang=False, may_need_services=False, reason="t")
    return ProbeReport(project_type=[family], selected=[cand],
                       results=[probeparse.parse_output(command, family, 0, raw, "")])


class Sess:
    tests_passed_high = 0


class ItFiresOnlyOnARegressionTests(unittest.TestCase):
    def test_a_drop_after_a_higher_green_speaks(self):
        s = Sess()
        self.assertEqual(loop.passing_test_regression(s, report("8 passed in 0.04s")), "")
        note = loop.passing_test_regression(s, report("7 passed in 0.04s"))
        self.assertIn("8", note)
        self.assertIn("7", note)

    def test_a_first_run_is_silent_however_small(self):
        self.assertEqual(loop.passing_test_regression(Sess(), report("1 passed in 0.01s")), "")

    def test_a_rising_count_is_silent(self):
        s = Sess()
        for n in (3, 5, 9):
            self.assertEqual(loop.passing_test_regression(s, report(f"{n} passed in 0.1s")), "")
        self.assertEqual(s.tests_passed_high, 9)

    def test_an_unchanged_count_is_silent(self):
        s = Sess()
        loop.passing_test_regression(s, report("4 passed in 0.1s"))
        self.assertEqual(loop.passing_test_regression(s, report("4 passed in 0.1s")), "")

    def test_no_recognised_tally_is_silence_not_zero(self):
        """THE FAIL-SAFE. A runner cria cannot read must not look like a suite that lost every test."""
        s = Sess()
        loop.passing_test_regression(s, report("9 passed in 0.1s"))
        self.assertEqual(loop.passing_test_regression(s, report("all good, chief")), "")
        self.assertEqual(loop.passing_test_regression(s, None), "")


class ItSpeaksForTheRUNNERS_THAT_PRINT_A_TALLY_Tests(unittest.TestCase):
    """Coverage is exactly the runners whose own summary line cria can read — no more.

    THE HONEST BOUND, and the first version of this class got it wrong. It asserted a Go arm by
    feeding `go test -v` output, which the gate never produces: `probediscovery` composes
    `go test -count=1 ./...` deliberately (see the `-count=1` note there), plain `go test` prints one
    `ok <pkg>` line per PACKAGE rather than per test, and `runner_tally` returns "" for it by design.
    So this detector does not cover Go today — which is worth knowing, because the incident that
    motivated it (cart-billing-go losing TestUnknownCode) is a Go one. Recorded as a gap rather than
    papered over with a fixture the gate cannot generate."""

    def test_pytest(self):
        s = Sess()
        self.assertEqual(loop.passing_test_regression(s, report("8 passed in 0.04s")), "")
        self.assertTrue(loop.passing_test_regression(s, report("7 passed in 0.04s")))

    def test_minitest(self):
        s = Sess()
        before = "8 runs, 8 assertions, 0 failures, 0 errors"
        after = "7 runs, 7 assertions, 0 failures, 0 errors"
        self.assertEqual(loop.passing_test_regression(s, report(before, "rake test", "ruby")), "")
        self.assertTrue(loop.passing_test_regression(s, report(after, "rake test", "ruby")))

    def test_plain_go_test_is_NOT_covered_and_stays_silent(self):
        """It must be silent rather than wrong: no tally is silence, never zero."""
        s = Sess()
        for raw in ("ok  \tcartsvc\t0.001s\n", "ok  \tcartsvc\t0.001s\n"):
            self.assertEqual(loop.passing_test_regression(s, report(raw, "go test -count=1 ./...", "go")), "")
        self.assertEqual(s.tests_passed_high, 0)


class TheNoteStatesTheFactTests(unittest.TestCase):
    def test_it_reports_the_runner_and_does_not_accuse(self):
        note = prompts.render("tests_regressed", was="8", now="7")
        low = note.lower()
        self.assertIn("test runner reported", low)
        self.assertIn("deliberate", low)        # merging two tests is legitimate
        self.assertNotIn("you deleted", low)
        self.assertNotIn("cria", low)           # #17

    def test_it_names_the_actual_mistake_without_asserting_it_happened(self):
        note = prompts.render("tests_regressed", was="8", now="7").lower()
        self.assertIn("append", note)
        self.assertIn("restore", note)


if __name__ == "__main__":
    unittest.main()
