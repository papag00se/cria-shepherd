"""The mid-run gate asks the same question it always asked — and the judge answering is a person.

At 30 minutes: have two deliverables been completed? At 45: three. At 60: four. That schedule is the
operator's and it is unchanged. What changed is who decides "complete".

It used to be `verify.py`'s all-or-nothing count. That count says "not done" for work that IS done
and merely fails a check on something incidental — a complete, correct, working CLI one directory too
deep scored 0 — and it killed all three cells on 2026-08-27 at thirty minutes with real work on disk.

The judge is the person running the campaign, and always has been: every verdict in `results.jsonl`
was written by one reading an evidence packet from `usefulness.emit`. So the gate writes the same
kind of packet — the task's own deliverable list, the diff from the seed, and the verifier's
observations as EVIDENCE rather than as the verdict — and waits for a file holding one integer.

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
        (suite_run.GATE_DIR / "run-2.045min.verdict").write_text("3\n")
        self.assertEqual(suite_run.ask_gate("run-2", 45, 3, ws, TASK, "t"), 3)

    def test_the_packet_names_the_deliverables_and_the_floor(self):
        ws = Path(tempfile.mkdtemp())
        self._ask(ws)
        q = (suite_run.GATE_DIR / "run-1.030min.md").read_text()
        self.assertIn("threshold bug fixed", q)
        self.assertIn("below 2", q)
        self.assertIn("EVIDENCE, not the verdict", q)
        self.assertIn("whether the work is DONE, not whether a check passes", q)


class TheScheduleAndTheKillTests(unittest.TestCase):
    def test_the_floor_is_two_at_the_first_look_then_one_more_each(self):
        """Operator: "At 30 mins - Did it complete two tasks?, at 45 mins - Did it complete three"."""
        import inspect
        src = inspect.getsource(suite_run)
        self.assertIn("next_check = milestone_s * 2 if milestone_s else 0", src)
        self.assertIn("floor = int(round(next_check / milestone_s))", src)
        self.assertIn("next_check += milestone_s", src)

    def test_a_run_is_stopped_only_on_an_answer_below_the_floor(self):
        import inspect
        src = inspect.getsource(suite_run)
        self.assertIn("if done is not None and done < floor:", src)

    def test_no_strict_score_decides_anything(self):
        import inspect
        src = inspect.getsource(suite_run)
        self.assertNotIn("score >= due", src)


if __name__ == "__main__":
    unittest.main()
