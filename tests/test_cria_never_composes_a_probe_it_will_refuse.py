"""The completion gate transports all evidence instead of choosing a printable subset.

Previously a per-probe cap and a separate harness-result bound disagreed. Ordinary compiler output
was clipped before the gate parser saw it. The gate now writes its aggregate to a harness-side
temporary file and returns checked pages; no output-size policy appears in probe composition.
"""

import tempfile
import unittest
from unittest import mock

from cria import probegate, proberun, writeproxy
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind


def candidate() -> ProbeCandidate:
    return ProbeCandidate(
        kind=ProbeKind.Test,
        command=["python3", "-c", "print('x' * 50000)"],
        working_dir=tempfile.gettempdir(),
        confidence=90,
        expected_value=80,
        cost=ProbeCost.Cheap,
        mutates_code=False,
        may_hang=False,
        may_need_services=False,
        reason="test",
    )


class ProbeCompositionHasNoEvidenceBudgetTests(unittest.TestCase):
    def test_the_old_budget_api_is_gone(self):
        self.assertFalse(hasattr(proberun, "PROBE_OUTPUT_CAP_BYTES"))
        self.assertFalse(hasattr(proberun, "probe_output_budget"))

    def test_the_composed_probe_has_no_head_tail_or_elision(self):
        command = proberun.compose_probe_command(candidate(), 120)
        self.assertNotIn("head -c", command)
        self.assertNotIn("tail -c", command)
        self.assertNotIn("elided", command)
        self.assertIn(proberun.PROBE_EXIT_SENTINEL, command)

    def test_the_gate_spools_before_returning_a_page(self):
        with tempfile.TemporaryDirectory() as workspace:
            with mock.patch.object(proberun, "select_completion_probes", return_value=[candidate()]):
                plan = probegate.plan_gate(workspace)
        self.assertTrue(plan.transport_required)
        self.assertIn("mktemp", plan.script)
        self.assertIn(probegate.TRANSPORT_PREFIX, plan.script)

    def test_the_inbound_bound_remains_gone(self):
        self.assertFalse(hasattr(writeproxy, "_bounded_exec_result"))


if __name__ == "__main__":
    unittest.main()
