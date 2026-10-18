"""cria's own cleanup command rode into the coder's context as the coder's own work.

`orders-api-py x nemotron-elastic` 1787270062: the litter-removal block appeared in 28 coder prompts
as an assistant `exec_command`, and at call 0044 the model emitted cria's `compileall` line back as
its own, exclusion regex and all.

This is a regression from `8f18472`, which moved the removal onto the harness — correctly, since cria
cannot unlink on a filesystem it does not own. The leak was not the removal, it was that every reader
downstream had to RECOGNISE cria's own text to hide it, and this leg was a shape none of the patterns
had ever seen. It was the third such patch in one day, which is what finally moved the answer
upstream: `plan_gate` now states which of its own bytes are showable, so a new internal leg is hidden
the day it is written, by never being on the list (#4).
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from cria import probediscovery, probegate, proberun


class TheCleanupLegIsStrippedTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        pathlib.Path(self.ws, "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
        pathlib.Path(self.ws, "test_orders.py").write_text("def test_a():\n    assert True\n")

    def _shown(self):
        """Only declared checker commands, never the cleanup instrumentation."""
        return probegate._strip_gate_plumbing(probegate.plan_gate(self.ws).script)

    def test_the_model_sees_only_its_own_checks(self):
        self.assertEqual(self._shown().splitlines(), ["python3 -m pytest -q"])

    def test_no_trace_of_cria_survives(self):
        out = self._shown()
        for token in ("__CRIA_LITTER__", "shutil", "os.unlink", "cria", "__pycache__", "orders.db"):
            with self.subTest(token=token):
                self.assertNotIn(token, out.lower() if token == "cria" else out)

    def test_the_gate_is_still_worth_showing(self):
        """Hiding cria's leg must not hide the coder's checks with it."""
        self.assertTrue(self._shown().strip())

    def test_the_harness_receives_cleanup_but_the_coder_does_not(self):
        """The incident was an internal program presented as the coder's work."""
        plan = probegate.plan_gate(self.ws)
        self.assertIn(f'gate launch {plan.transport_id}', plan.script)
        self.assertNotIn(plan.transport_id, self._shown())
        self.assertNotIn('_gate_aux_cleanup', self._shown())

    def test_the_leg_really_is_in_the_script_that_ran(self):
        """Actual private bytes disappear before handoff; a declaration alone is not enough."""
        program = ("import os; from pathlib import Path; "
                   "(Path(os.environ['CTX_PROBE_AUX'])/'proof').write_text('private'); print('NATIVE CHECKER OUTPUT')")
        candidate = probediscovery.ProbeCandidate(probediscovery.ProbeKind.BuildCheck,
            [sys.executable, '-c', program], pathlib.Path(self.ws), 100, 100, probediscovery.ProbeCost.Cheap,
            False, False, False, 'private fixture', composed_by_cria=True)
        with tempfile.TemporaryDirectory() as harness, mock.patch.object(proberun, 'select_completion_probes', return_value=[candidate]):
            plan = probegate.plan_gate(self.ws)
            result = subprocess.run(['sh', '-c', plan.script], cwd=self.ws,
                env={**os.environ, 'TMPDIR': harness}, capture_output=True, text=True, check=True)
            outcome = probegate.interpret_gate(plan, result.stdout)
            self.assertTrue(plan.transport_complete)
            self.assertFalse(probegate.gate_is_partial(outcome))
            self.assertFalse((pathlib.Path(plan.transport_path).parent / 'aux').exists())
            shown = probegate.clean_gate_output(plan.transport_data.decode(), plan)
            self.assertIn('NATIVE CHECKER OUTPUT', shown)
            self.assertNotIn('_gate_aux_cleanup', shown)
            self.assertNotIn('os.unlink', shown)


if __name__ == "__main__":
    unittest.main()
