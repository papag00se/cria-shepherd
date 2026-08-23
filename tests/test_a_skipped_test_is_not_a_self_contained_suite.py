"""cria told 5,120 prompts a suite never touches the network, over a test that stepped aside.

`_offline_fact` re-runs the test probe with the network taken away and, when both runs are green
and their tallies MATCH, says:

    The same tests (0f/2p) pass with the network switched off — nothing in them reaches a service
    on the internet.

The whole mechanism is the tally comparison, and its own docstring says why: *"a live test can SKIP
instead of fail when the service is gone — a two-line try/except that leaves the exit code at 0."*
That works where the total EXCLUDES skips, which is pytest's and jest's convention and nobody
else's. minitest's `runs`, phpunit's `Tests:`, surefire's `Tests run:` and gradle's `tests
completed` all COUNT the skipped test, so the two tallies match and the strong sentence ships.

Reproduced with real Ruby, one test that skips when `OFFLINE` is set:

    online  : 2 runs, 2 assertions, 0 failures, 0 errors, 0 skips  -> 0f/2p  exit 0
    offline : 2 runs, 1 assertions, 0 failures, 0 errors, 1 skips  -> 0f/2p  exit 0   EQUAL

Four of the six battery languages read this way. The sentence appears in 5,120 captured prompts.

The skip count is the same question asked in the dimension the tally cannot see, and
`probeparse.skipped_count` now reads all eight runners' spellings — so it is asked.
"""

import unittest

from cria import probediscovery, probegate, proberun

_EXIT = proberun.PROBE_EXIT_SENTINEL


def _plan():
    cand = probediscovery.ProbeCandidate(
        kind=probediscovery.ProbeKind.Test, command=["ruby", "-Itest", "test/t.rb"],
        working_dir=".", confidence=100, expected_value=100,
        cost=probediscovery.ProbeCost.Cheap, mutates_code=False, may_hang=False,
        may_need_services=False, reason="t")
    return probegate.GatePlan(workspace="/ws", candidates=[cand])


def _fact(online, offline):
    return probegate._offline_fact(
        {"probe-0": f"{online}\n{_EXIT}0", "offline": f"{offline}\n{_EXIT}0"}, _plan())


MINITEST_ALL = "2 runs, 2 assertions, 0 failures, 0 errors, 0 skips"
MINITEST_ONE_SKIPPED = "2 runs, 1 assertions, 0 failures, 0 errors, 1 skips"


class ARunnerThatCountsSkipsInItsTotalTests(unittest.TestCase):
    def test_minitest_stepping_aside_is_no_longer_read_as_the_same_suite(self):
        self.assertEqual(_fact(MINITEST_ALL, MINITEST_ONE_SKIPPED), "")

    def test_the_tallies_really_are_equal_so_the_tally_alone_could_not_see_it(self):
        """Not a hypothetical — this is why the comparison above was not enough."""
        from cria.probeparse import runner_tally
        self.assertEqual(runner_tally(MINITEST_ALL), runner_tally(MINITEST_ONE_SKIPPED))

    def test_surefire_phpunit_and_gradle_read_the_same_way(self):
        for name, on, off in (
                ("surefire", "Tests run: 5, Failures: 0, Errors: 0, Skipped: 0",
                             "Tests run: 5, Failures: 0, Errors: 0, Skipped: 1"),
                ("phpunit", "Tests: 3, Assertions: 3, Skipped: 0.",
                            "Tests: 3, Assertions: 2, Skipped: 1."),
        ):
            with self.subTest(runner=name):
                self.assertEqual(_fact(on, off), "")


class AGenuinelySelfContainedSuiteStillEarnsTheSentenceTests(unittest.TestCase):
    def test_the_same_counts_and_the_same_skips_still_say_it(self):
        out = _fact(MINITEST_ALL, MINITEST_ALL)
        self.assertIn("0f/2p", out)

    def test_pytest_was_already_right_and_stays_right(self):
        self.assertIn("0f/2p", _fact("2 passed in 0.1s", "2 passed in 0.1s"))
        self.assertEqual(_fact("2 passed in 0.1s", "1 passed, 1 skipped in 0.1s"), "")


class TheWeakerSentenceIsRefusedOnTheSameEvidenceTests(unittest.TestCase):
    """A runner with no readable tally still says how many it stepped past."""

    def test_more_skips_offline_refuses_even_the_uncounted_wording(self):
        self.assertEqual(_fact("ok  z", "--- SKIP: TestLive\nok  z"), "")

    def test_an_unreadable_runner_with_no_skips_still_gets_the_weaker_sentence(self):
        self.assertNotEqual(_fact("everything fine", "everything fine"), "")


if __name__ == "__main__":
    unittest.main()
