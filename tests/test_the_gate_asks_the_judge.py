"""The mid-run gate uses the campaign's own score: inferred usefulness.

At 30 minutes the run owes two of five deliverables' worth of work (40%); at 45 it owes three (60%).
That is not a binary completed-item count. Each fixed deliverable gets 0–100 under the same rubric as
the final judgment, and the average measures how much requested work was actually delivered.

The judge is the person running the campaign, and always has been: every verdict in `results.jsonl`
was written by one reading an evidence packet from `usefulness.emit`. So the gate writes the same
kind of packet — the task's own deliverable list, the diff from the seed, verifier observations, and
the authoritative usefulness rubric — and waits for that rubric's JSON verdict.

Two properties matter more than the rest:

* it fails OPEN. A gate nobody answers, or an answer that does not parse, lets the run continue. A
  judge who is asleep may not end a run (#13).
* it does not pause the coder. The packet describes the workspace at the mark and the run carries on
  while the question is open, so a slow answer costs the run nothing.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))
import run as suite_run  # noqa: E402


TASK = Path(__file__).resolve().parents[1] / "suite" / "tasks" / "shipping-rates-rb"


class TheQuestionIsTheTasksOwnListTests(unittest.TestCase):
    def test_the_deliverables_come_from_meta_toml(self):
        """The list a run is paced against and the list it is finally judged against are one list,
        written by whoever wrote the task."""
        names = suite_run.deliverable_names(TASK)
        self.assertIn("threshold bug fixed", names)
        self.assertEqual(len(names), suite_run.deliverable_count(TASK))

    def test_a_task_with_no_deliverables_is_refused_not_guessed(self):
        d = Path(tempfile.mkdtemp())
        (d / "meta.toml").write_text('name = "x"\n')
        with self.assertRaises(RuntimeError):
            suite_run.deliverable_names(d)


class ItFailsOpenTests(unittest.TestCase):
    def setUp(self):
        suite_run.GATE_DIR = Path(tempfile.mkdtemp())
        self._wait = suite_run.GATE_WAIT_S
        suite_run.GATE_WAIT_S = 2
        self.addCleanup(setattr, suite_run, "GATE_WAIT_S", self._wait)

    def _ask(self, ws=None):
        ws = ws or Path(tempfile.mkdtemp())
        return suite_run.ask_gate("run-1", 30, 2, ws, TASK, "the task text")

    def test_no_answer_means_continue(self):
        self.assertIsNone(self._ask())

    def test_an_unparseable_answer_means_continue(self):
        ws = Path(tempfile.mkdtemp())
        (suite_run.GATE_DIR).mkdir(parents=True, exist_ok=True)
        (suite_run.GATE_DIR / "run-1.030min.verdict").write_text("no idea, sorry")
        self.assertIsNone(suite_run.ask_gate("run-1", 30, 2, ws, TASK, "t"))

    def test_an_answer_is_read(self):
        """Pre-written rather than raced: the packet build runs the task's verifier, so a thread
        sleeping a fixed time is a coin flip, and a flaky test about a gate is worse than none."""
        ws = Path(tempfile.mkdtemp())
        suite_run.GATE_DIR.mkdir(parents=True, exist_ok=True)
        verdict = '{"usefulness":61,"reason":"x. y.","deliverables":[]}'
        (suite_run.GATE_DIR / "run-2.045min.verdict").write_text(verdict)
        self.assertEqual(suite_run.ask_gate("run-2", 45, 3, ws, TASK, "t"), 61)

    def test_the_packet_names_the_deliverables_and_the_floor(self):
        ws = Path(tempfile.mkdtemp())
        self._ask(ws)
        q = (suite_run.GATE_DIR / "run-1.030min.md").read_text()
        self.assertIn("threshold bug fixed", q)
        self.assertIn("40%", q)
        self.assertIn("EVIDENCE, not the verdict", q)
        self.assertIn("Score each deliverable independently", q)
        self.assertIn("A failure affects only deliverables that depend on it", q)
        self.assertNotIn("written but cannot run is not", q)


class TheScheduleAndTheKillTests(unittest.TestCase):
    def test_the_floor_is_two_at_the_first_look_then_one_more_each(self):
        """Operator: "At 30 mins - Did it complete two tasks?, at 45 mins - Did it complete three"."""
        import inspect
        src = inspect.getsource(suite_run)
        self.assertIn("next_check = milestone_s * 2 if milestone_s else 0", src)
        self.assertIn("floor = int(round(next_check / milestone_s))", src)
        self.assertIn("next_check += milestone_s", src)

    def test_a_run_is_stopped_only_when_inferred_usefulness_is_below_the_due_share(self):
        import inspect
        src = inspect.getsource(suite_run)
        self.assertIn("threshold = 100.0 * floor / deliverable_count(task_dir)", src)
        self.assertIn("if inferred is not None and inferred < threshold:", src)

    def test_no_strict_score_decides_anything(self):
        import inspect
        src = inspect.getsource(suite_run)
        self.assertNotIn("score >= due", src)


if __name__ == "__main__":
    unittest.main()
