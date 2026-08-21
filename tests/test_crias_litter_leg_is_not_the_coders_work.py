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

import pathlib
import tempfile
import unittest

from cria import probegate


class TheCleanupLegIsStrippedTests(unittest.TestCase):
    def setUp(self):
        probegate._LITTER_QUEUE.clear()
        self.ws = tempfile.mkdtemp()
        pathlib.Path(self.ws, "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
        pathlib.Path(self.ws, "test_orders.py").write_text("def test_a():\n    assert True\n")

    def _shown(self):
        """What the coder reads back of a gate that had litter to clear first."""
        probegate._queue_litter(self.ws, ["tests/__pycache__/test_db.cpython-312.pyc", "orders.db"])
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

    def test_the_removal_itself_still_names_the_paths(self):
        """Stripping is for the model's view only — the harness must still get the command."""
        probegate._queue_litter(self.ws, ["orders.db"])
        self.assertIn("orders.db", probegate.litter_removal_command(self.ws))

    def test_the_leg_really_is_in_the_script_that_ran(self):
        """Otherwise every assertion above passes for the wrong reason."""
        probegate._queue_litter(self.ws, ["orders.db"])
        self.assertIn("orders.db", probegate.plan_gate(self.ws).script)


if __name__ == "__main__":
    unittest.main()
