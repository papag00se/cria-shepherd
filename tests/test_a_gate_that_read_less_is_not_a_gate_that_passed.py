"""A gate whose sections were cut in transit recorded GREEN.

`interpret_gate` already knew: when a selected check's section never came back it appends the
command to `outcome.unran`, under a comment saying *"Absence must not BLOCK, but it must not read as
CLEAN either: `results` silently became a subset of `selected`, and nothing downstream said a check
was missing, so a truncated gate looked like a passing one."*

It had exactly one reader — `_verify_after_probe`, the plan-ON per-step gate. `loop.gate` events
carrying `probes_run` (the plan-ON reading) per day across the log window: 2, 5, 4, 6, 3, 1, **0, 0,
0, 0, 0, 0** — zero on every day since the workspace survey started riding the gate result. The three
LIVE readers all read `outcome.report` only, and `proberun.unran_probes` answers a different question
(a probe that launched and returned no exit code), so a section cut in transit is not in `results` at
all.

With no reader, `findings` came back "" and `record_gate_state` wrote GREEN and `gate_fresh = True`.
`ran` cannot carry this — it is True as long as ANY section came back.

Three properties, in the order they have to hold:

  1. a found error is a found error, complete gate or not — RED wins;
  2. a clean PARTIAL gate is neutral: attempted, so it never wedges a real 'done', and it may not
     clear a previous red, because it did not re-read what made that red;
  3. a clean COMPLETE gate is still green.
"""

import unittest

from cria import loop, probegate


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append(kind)


class _Outcome:
    def __init__(self, ran=True, unran=()):
        from cria.proberun import ProbeReport
        self.ran, self.unran = ran, list(unran)
        self.report = ProbeReport(project_type=["x"], selected=[], results=[])


class APartialGateIsNeitherRedNorGreenTests(unittest.TestCase):
    def _state(self, outcome, findings, prior_red=True):
        gs = loop.GuardState()
        gs.last_gate_red = prior_red
        rlog = _Rlog()
        loop.record_gate_state(gs, outcome, findings, rlog)
        return gs, rlog

    def test_a_clean_partial_gate_does_not_clear_a_previous_red(self):
        gs, _ = self._state(_Outcome(unran=["pytest -q"]), "")
        self.assertTrue(gs.last_gate_red)

    def test_it_still_counts_as_attempted_so_a_real_done_is_never_wedged(self):
        gs, _ = self._state(_Outcome(unran=["pytest -q"]), "")
        self.assertTrue(gs.gate_fresh)

    def test_it_is_recorded_where_the_operator_can_see_it(self):
        """It used to be unmeasurable from the outside by construction — no emit anywhere (#12)."""
        _, rlog = self._state(_Outcome(unran=["pytest -q"]), "")
        self.assertIn("loop.gate_partial", rlog.events)

    def test_a_found_error_outranks_the_gap(self):
        """A partial gate that DID find something is red — the finding is real either way."""
        gs, _ = self._state(_Outcome(unran=["pytest -q"]), "x.py:1: SyntaxError", prior_red=False)
        self.assertTrue(gs.last_gate_red)
        self.assertFalse(gs.gate_fresh)

    def test_a_complete_clean_gate_is_still_green(self):
        gs, rlog = self._state(_Outcome(unran=[]), "")
        self.assertFalse(gs.last_gate_red)
        self.assertTrue(gs.gate_fresh)
        self.assertNotIn("loop.gate_partial", rlog.events)


class ThePartialGateGivesNoCleanSignalTests(unittest.TestCase):
    def test_the_ground_truth_block_stays_silent(self):
        """`guard_ground_truth` had two ways to say 'no clean signal' and needed a third."""
        self.assertEqual(loop.guard_ground_truth(_Outcome(unran=["pytest -q"])), "")

    def test_a_complete_clean_gate_still_says_so(self):
        self.assertNotEqual(loop.guard_ground_truth(_Outcome(unran=[])), "")

    def test_the_question_has_one_owner(self):
        self.assertTrue(probegate.gate_is_partial(_Outcome(unran=["x"])))
        self.assertFalse(probegate.gate_is_partial(_Outcome(unran=[])))
        self.assertFalse(probegate.gate_is_partial(_Outcome(ran=False)))


if __name__ == "__main__":
    unittest.main()
