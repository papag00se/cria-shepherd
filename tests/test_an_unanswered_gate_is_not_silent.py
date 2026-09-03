"""A gate nobody answers is an UNGATED run, and it may not pass quietly.

On 2026-08-27 six gates fired across two cells. None were answered. Each waited fifteen minutes,
failed open, and let the run continue — which is the right direction, because a judge who is asleep
must never end a run (#13). But nothing said so. Both cells ran their full 75-minute budget with no
gate deciding anything, the batch went on to spend a third cell the same way, and the only trace was
`usefulness: null` on a row nobody reads until the batch is over.

Failing open is correct. Failing open SILENTLY is the defect. Three things changed:

* the wait dropped from 900s to 120s — failing open makes a long wait pure cost, and three of them
  added 45 minutes to a run nobody was gating;
* a timed-out gate appends to `gates/UNANSWERED`, and the batch script refuses to start the next
  cell while that file has anything in it;
* `suite/gates.py` makes the worklist one command, so answering is part of a turn rather than
  something to remember.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))
import gates  # noqa: E402
import run as suite_run  # noqa: E402

TASK = Path(__file__).resolve().parents[1] / "suite" / "tasks" / "shipping-rates-rb"


class ATimedOutGateLeavesATraceTests(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        suite_run.GATE_DIR = gates.GATE_DIR = d
        self._w = suite_run.GATE_WAIT_S
        suite_run.GATE_WAIT_S = 1
        self.addCleanup(setattr, suite_run, "GATE_WAIT_S", self._w)

    def test_the_marker_names_the_question(self):
        suite_run.ask_gate("run-1", 30, 2, Path(tempfile.mkdtemp()), TASK, "t")
        self.assertEqual(gates.unanswered(), ["run-1.030min.md"])

    def test_a_second_timeout_appends_rather_than_replaces(self):
        for m in (30, 45):
            suite_run.ask_gate("run-1", m, 2, Path(tempfile.mkdtemp()), TASK, "t")
        self.assertEqual(len(gates.unanswered()), 2)

    def test_an_answered_gate_leaves_no_marker(self):
        (gates.GATE_DIR).mkdir(parents=True, exist_ok=True)
        (gates.GATE_DIR / "run-9.030min.verdict").write_text(
            '{"usefulness":40,"reason":"x. y.","deliverables":[]}')
        suite_run.ask_gate("run-9", 30, 2, Path(tempfile.mkdtemp()), TASK, "t")
        self.assertEqual(gates.unanswered(), [])


class TheWorklistIsOneCommandTests(unittest.TestCase):
    def setUp(self):
        gates.GATE_DIR = Path(tempfile.mkdtemp())

    def test_a_question_with_no_verdict_is_open(self):
        (gates.GATE_DIR / "r.030min.md").write_text("q")
        self.assertEqual([p.name for p in gates.open_questions()], ["r.030min.md"])

    def test_answering_closes_it(self):
        (gates.GATE_DIR / "r.030min.md").write_text("q")
        verdict = '{"usefulness":60,"reason":"x. y.","deliverables":[]}'
        self.assertEqual(gates.main(["--answer", "r.030min", verdict]), 0)
        self.assertEqual(gates.open_questions(), [])
        self.assertEqual((gates.GATE_DIR / "r.030min.verdict").read_text().strip(), verdict)

    def test_a_non_json_verdict_is_refused(self):
        (gates.GATE_DIR / "r.030min.md").write_text("q")
        self.assertEqual(gates.main(["--answer", "r.030min", "most of them"]), 2)
        self.assertEqual(len(gates.open_questions()), 1)


class TheBatchStopsOnAnUngatedRunTests(unittest.TestCase):
    def test_the_runner_checks_the_marker_before_each_cell(self):
        """A halted batch is recoverable; three ungated cells are not."""
        sh = Path("/tmp/claude-1000/-home-jesse-src-cria-shepherd/"
                  "d46635db-f27f-478e-8109-2e5794f35446/scratchpad/red3b.sh")
        if not sh.is_file():
            self.skipTest("batch script is scratch, not part of the repo")
        body = sh.read_text()
        self.assertIn("gates/UNANSWERED", body)
        self.assertIn("exit 1", body)


if __name__ == "__main__":
    unittest.main()
