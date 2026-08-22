"""cria composed a gate whose output cria then refused, and read the refusal as "no check ran".

Cycle 1 of the 100% campaign, 24 cells. Oversize refusals in SEVEN of them, every one in a narrow
band just over the bound — 8,912 to 10,107 bytes. Not floods: 194 to 248 lines, ordinary test and
compiler output. The bound was written for a 302,983-token flood and what it actually caught was
`mvn -q compile`.

TWO NUMBERS THAT NEVER MET. `proberun.PROBE_OUTPUT_CAP_BYTES` was derived from
`content_reduce.INLINE_RESULT_MAX_BYTES` — which fixed the constant and left the arithmetic wrong,
because a gate joins EVERY probe into ONE shell result and the bound is applied to that one result.
Six probes at 8,500 each cannot fit in 9,000.

WHAT THAT COST, both directions, from docs/audits/cycle-1-walk.md:

  rust-toml-cli x ternary-bonsai   three gates ran, 30,310 bytes of compiler output, all refused
                                   whole. cria then read its OWN refusal as the probe result, set
                                   `ran = False`, and told its judge "PROBES: none ran - the gate
                                   command produced no output" 5.24 seconds after one had. Zero
                                   `ctx:checks` blocks in all 43 prompts. The run scored 0%.

  orders-api-py x nemotron-elastic a fragment survived, so cria reported the fragment: 19x "the
                                   repo's own checks reported no error-class problems" and 8x "The
                                   repo's automated checks pass" -- while pytest was red and the
                                   route returned nothing.

One bound, two opposite falsehoods (#5b), and both are a fail-OPEN on missing ground truth (#13) --
the cross-cutting root of every early exit this project has traced.

THE FIX IS ARITHMETIC, NOT POLICY. The refusal itself is untouched: the operator's 2026-08-12 ruling
(refuse whole, never elide) still governs what happens to output that genuinely does not fit. What
changes is that cria no longer composes a probe set whose own output it is guaranteed to refuse --
the per-section budget is this plan's SHARE of the one result, so the sum fits by construction
instead of by luck. Each section still head+tails with its own disclosed marker; nothing vanishes
silently.
"""

import unittest

import tempfile
from unittest import mock

from cria import content_reduce, probegate, proberun, writeproxy
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind


def candidate(name: str) -> ProbeCandidate:
    return ProbeCandidate(
        kind=ProbeKind.Test, command=["echo", name], working_dir=tempfile.gettempdir(),
        confidence=90, expected_value=80, cost=ProbeCost.Cheap, mutates_code=False,
        may_hang=False, may_need_services=False, reason="test",
    )


def planned(n: int):
    """A gate plan with exactly ``n`` probes, composed against an empty workspace so the test
    measures the arithmetic rather than whatever happens to be on disk."""
    from unittest import mock
    with tempfile.TemporaryDirectory() as ws:
        with mock.patch.object(proberun, "select_completion_probes",
                               return_value=[candidate(f"p{i}") for i in range(n)]):
            return probegate.plan_gate(ws)


class TheBudgetIsSharedNotRepeatedTests(unittest.TestCase):
    def test_one_probe_gets_the_whole_result_budget(self):
        cap, fits = proberun.probe_output_budget(1)
        self.assertTrue(fits)
        self.assertGreater(cap, 6000)

    def test_six_probes_each_get_a_sixth_of_it(self):
        one, _ = proberun.probe_output_budget(1)
        six, fits = proberun.probe_output_budget(6)
        self.assertTrue(fits)
        self.assertLess(six, one // 5)

    def test_the_sum_of_the_sections_fits_the_bound_that_judges_them(self):
        """THE REGRESSION. Six sections at the old constant summed to 51,000 against a 9,000 bound."""
        for n in (1, 2, 3, 4, 6, 8):
            with self.subTest(probes=n):
                cap, fits = proberun.probe_output_budget(n)
                if fits:
                    self.assertLessEqual(n * cap + proberun.PROBE_ENVELOPE_RESERVE_BYTES,
                                         content_reduce.INLINE_RESULT_MAX_BYTES)

    def test_an_impossible_plan_says_so_rather_than_starving_silently(self):
        cap, fits = proberun.probe_output_budget(40)
        self.assertFalse(fits)
        self.assertEqual(cap, proberun.MIN_PROBE_SECTION_BYTES)

    def test_zero_probes_is_not_a_division(self):
        self.assertEqual(proberun.probe_output_budget(0), (proberun.PROBE_OUTPUT_CAP_BYTES, True))


class TheComposedProbeCarriesItsShareTests(unittest.TestCase):
    def test_the_cap_reaches_the_shell(self):
        cmd = proberun.compose_probe_command(candidate("a"), 10.0, cap=1200)
        self.assertIn("-le 1200", cmd)
        self.assertIn("head -c 150", cmd)        # an eighth to the opening context
        self.assertIn("head -c 900", cmd)        # three quarters to the diagnostics themselves
        self.assertIn("tail -c 150", cmd)        # an eighth to the tally line at the end

    def test_the_elision_marker_counts_against_the_same_number(self):
        """The disclosed count must describe the bytes actually dropped, not a different budget."""
        cmd = proberun.compose_probe_command(candidate("a"), 10.0, cap=1200)
        self.assertIn("__cria_n - 1200", cmd)

    def test_a_lone_probe_still_gets_the_whole_budget(self):
        cmd = proberun.compose_probe_command(candidate("a"), 10.0)
        self.assertIn(f"-le {proberun.PROBE_OUTPUT_CAP_BYTES}", cmd)


class TheWholeGateFitsTests(unittest.TestCase):
    def test_every_probe_in_the_script_carries_the_shared_cap(self):
        """END TO END. Before the fix each probe carried 8,500 whatever the plan held, so six of
        them promised 51,000 bytes into a 9,000-byte result."""
        for n in (1, 2, 4, 6):
            with self.subTest(probes=n):
                plan = planned(n)
                cap, _ = proberun.probe_output_budget(n)
                self.assertEqual(plan.script.count(f"-le {cap}"), n)
                self.assertLessEqual(
                    n * cap + proberun.PROBE_ENVELOPE_RESERVE_BYTES + proberun.MARKER_OVERHEAD_BYTES,
                    content_reduce.INLINE_RESULT_MAX_BYTES)

    def test_six_probes_no_longer_promise_fifty_one_thousand_bytes(self):
        """The exact regression, stated as the number it was."""
        plan = planned(6)
        self.assertNotIn(f"-le {proberun.PROBE_OUTPUT_CAP_BYTES}", plan.script)

    def test_the_plan_records_when_it_could_not_fit(self):
        self.assertTrue(any("sharing one result" in n for n in planned(40).notes))

    def test_a_normal_plan_records_nothing(self):
        """#3 — silence on a clean signal."""
        self.assertEqual(planned(2).notes, [])


class TheOutboundCapRemainsTests(unittest.TestCase):
    """The inbound refusal is gone -- it ran on a result the harness had already delivered whole, so
    it could not prevent the harness cut it was named for, and the function that did it has been
    deleted. What this file exists for is the OUTBOUND cap, which is the half of the number that was
    ever coherent: cria still decides how much its own composed probes print."""

    def test_the_gate_still_sizes_its_own_probes(self):
        cap, _ = proberun.probe_output_budget(6)
        self.assertIn(f"-le {cap}", planned(6).script)

    def test_the_inbound_bound_is_gone_for_good(self):
        self.assertFalse(hasattr(writeproxy, "_bounded_exec_result"))


if __name__ == "__main__":
    unittest.main()
