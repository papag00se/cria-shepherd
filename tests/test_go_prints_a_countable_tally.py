"""On Go, cria could not see a deleted test, because the gate never asked the runner to count.

`passing_test_regression` is the one signal that catches a coder DESTROYING working code — the
measured shape is an append written as a replace, where a seeded test goes out with the old text and
`go build`, `go vet` and `go test` all stay green. It reads the runner's own summary through
`runner_tally` (#12), which is what makes it language-agnostic.

`go test` without `-v` prints one line per PACKAGE —

    ok  	cartsvc	0.003s

— and nothing per test. `runner_tally` returns "", `gate_passing_tests` returns -1, and -1 means
"the runner said nothing", so the detector correctly stays silent. Correctly, and forever: on Go it
could not fire at all.

probeparse's own tally table already said so in its comment — "go test -v · one `--- PASS:` /
`--- FAIL:` per test" — so the parser expected the flag and the composer had never sent it.
"""

import unittest

from cria import probegate, probediscovery

QUIET = "ok  \tcartsvc\t0.003s\n"
VERBOSE = ("=== RUN   TestTotal\n--- PASS: TestTotal (0.00s)\n"
           "=== RUN   TestDiscount\n--- PASS: TestDiscount (0.00s)\n"
           "PASS\nok  \tcartsvc\t0.003s\n")


class TheGateAsksForACountTests(unittest.TestCase):
    def test_the_composed_command_carries_v(self):
        import pathlib
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "go.mod").write_text("module x\n")
            cmds = [" ".join(c.command) for c in probediscovery.discover(pathlib.Path(d))]
            self.assertIn("go test -count=1 -v ./...", cmds)

    def test_count_one_is_still_there(self):
        """The cache defeat is not traded away for the count: `go test` replays a cached pass
        without executing anything."""
        import pathlib
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "go.mod").write_text("module x\n")
            cmds = [" ".join(c.command) for c in probediscovery.discover(pathlib.Path(d))]
            self.assertTrue(any("-count=1" in c and c.startswith("go test") for c in cmds))


class TheTallyIsReadableTests(unittest.TestCase):
    def test_quiet_output_yields_nothing(self):
        """The state cria was in: no count, so no signal — and the silence was permanent."""
        self.assertEqual(probegate.runner_tally(QUIET), "")

    def test_verbose_output_yields_a_count(self):
        self.assertEqual(probegate.runner_tally(VERBOSE), "0f/2p")

    def test_a_failure_is_counted_separately(self):
        red = VERBOSE.replace("--- PASS: TestDiscount", "--- FAIL: TestDiscount")
        self.assertEqual(probegate.runner_tally(red), "1f/1p")

    def test_a_deleted_test_shows_up_as_a_smaller_count(self):
        """The whole point: two passing become one, and the number cria compares against moves."""
        one = "=== RUN   TestTotal\n--- PASS: TestTotal (0.00s)\nPASS\nok  \tcartsvc\t0.002s\n"
        self.assertEqual(probegate.runner_tally(VERBOSE), "0f/2p")
        self.assertEqual(probegate.runner_tally(one), "0f/1p")


class TheRegressionSignalNowFiresOnGoTests(unittest.TestCase):
    class _Sess:
        tests_passed_high = 0

    def _report(self, tally):
        """A real ProbeReport shape: `results` correlate to `selected` by joined command, and the
        kind is what tells passing_test_regression this row is a TEST."""
        import tempfile

        from cria import loop, probediscovery as pdisc
        cmd = ["go", "test", "-count=1", "-v", "./..."]
        cand = pdisc.ProbeCandidate(kind=pdisc.ProbeKind.Test, command=cmd,
                                    working_dir=tempfile.gettempdir(), confidence=90,
                                    expected_value=90, cost=pdisc.ProbeCost.Moderate,
                                    mutates_code=False, may_hang=False,
                                    may_need_services=False, reason="t")

        class _R:
            def __init__(self, t):
                from cria import proberun
                self.command = proberun.display_command(cmd)
                self.tally, self.timed_out = t, False

        class _Report:
            def __init__(self, t):
                self.results = [_R(t)]
                self.selected = [cand]
        return loop, _Report(tally)

    def test_a_dropped_count_is_reported(self):
        loop, rep_two = self._report("0f/2p")
        sess = self._Sess()
        self.assertEqual(loop.passing_test_regression(sess, rep_two), "")
        self.assertEqual(sess.tests_passed_high, 2)
        _, rep_one = self._report("0f/1p")
        note = loop.passing_test_regression(sess, rep_one)
        self.assertIn("2", note)
        self.assertIn("1", note)

    def test_no_tally_is_still_silence_not_zero(self):
        loop, rep = self._report("")
        sess = self._Sess()
        sess.tests_passed_high = 5
        self.assertEqual(loop.passing_test_regression(sess, rep), "")


if __name__ == "__main__":
    unittest.main()
