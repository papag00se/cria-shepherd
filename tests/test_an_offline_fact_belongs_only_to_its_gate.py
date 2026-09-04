"""A fact measured by one gate may not survive interpretation of a later gate.

The Go L5 completion confirmer was shown that tests had passed with the network removed even though
the current gate was red after later edits.  GatePlan is the right owner, but its mutable field must
represent the gate result currently being interpreted rather than the last clean result it saw.
"""
import unittest

from cria import probegate, proberun


class OfflineFactLifetimeTests(unittest.TestCase):
    def test_a_later_red_gate_clears_the_old_clean_fact(self):
        plan = probegate.GatePlan(workspace="")
        plan.offline_fact = "The tests passed with the network taken away."
        raw = (
            f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
            "go.mod:5: usage: require module/path v1.2.3\n"
            f"{proberun.PROBE_EXIT_SENTINEL}1\n"
        )

        out = probegate.clean_gate_output(raw, plan)

        self.assertIn("go.mod:5", out or "")
        self.assertEqual(plan.offline_fact, "")

    def test_a_non_gate_message_does_not_mutate_the_current_gate(self):
        plan = probegate.GatePlan(workspace="")
        plan.offline_fact = "current fact"
        self.assertIsNone(probegate.clean_gate_output("ordinary tool output", plan))
        self.assertEqual(plan.offline_fact, "current fact")


if __name__ == "__main__":
    unittest.main()
