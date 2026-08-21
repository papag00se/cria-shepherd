"""cria's own cleanup command rode into the coder's context as the coder's own work.

`orders-api-py x nemotron-elastic` 1787270062: the litter-removal block appeared in 28 coder prompts
as an assistant `exec_command`, and at call 0044 the model emitted cria's `compileall` line back as
its own, exclusion regex and all.

This is a regression from `8f18472`, which moved the removal onto the harness — correctly, since cria
cannot unlink on a filesystem it does not own. But the block is a standalone
`{ python3 - <<'__CRIA_LITTER__' … }` leg, not a wrapped probe, so `_kept_probe` (which drops the
multi-line inner command of a capture wrapper) never sees it, and the line filter below has no
pattern for it.
"""

import unittest

from cria import probegate


class TheCleanupLegIsStrippedTests(unittest.TestCase):
    def setUp(self):
        probegate._LITTER_QUEUE.clear()

    def _script(self, ws="/ws"):
        probegate._queue_litter(ws, ["tests/__pycache__/test_db.cpython-312.pyc", "orders.db"])
        return probegate.litter_removal_command(ws) + "\npython3 -m pytest -q"

    def test_the_model_sees_only_its_own_check(self):
        self.assertEqual(probegate._strip_gate_plumbing(self._script()), "python3 -m pytest -q")

    def test_no_trace_of_cria_survives(self):
        out = probegate._strip_gate_plumbing(self._script())
        for token in ("__CRIA_LITTER__", "shutil", "os.unlink", "cria", "__pycache__"):
            with self.subTest(token=token):
                self.assertNotIn(token, out.lower() if token == "cria" else out)

    def test_a_gate_with_no_litter_is_unaffected(self):
        self.assertEqual(probegate._strip_gate_plumbing("python3 -m pytest -q"),
                         "python3 -m pytest -q")

    def test_the_removal_itself_still_names_the_paths(self):
        """Stripping is for the model's view only — the harness must still get the command."""
        probegate._queue_litter("/ws", ["orders.db"])
        self.assertIn("orders.db", probegate.litter_removal_command("/ws"))


if __name__ == "__main__":
    unittest.main()
