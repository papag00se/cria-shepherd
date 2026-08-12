"""A task's declared deliverables must match what its verifier actually scores.

`suite/run.py` paces a run at `15 minutes x len(meta.deliverables)`, so the count is not
bookkeeping — it is how long every run of that task gets. The two drifted unnoticed:
shipping-rates-rb, cart-billing-go and feed-pipeline-java each scored FIVE checks while declaring
FOUR deliverables, so they ran on a 60-minute clock where 75 was right, and handles-cli-node
declared five while scoring four, giving it 75 where 60 was right.

Nothing surfaced it. The count appears in `meta.toml`, the checks appear in `verify.py`, and no
reader compared them. This is that reader.

The prompt itself needs no test of this kind: `suite/tasks/<task>/prompt.txt` is the single copy and
run.py reads it directly, so there is no second source to fall out of step with.
"""

import pathlib
import re
import sys
import tomllib
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "suite"))

from battery_status import SUITE, TASKS  # noqa: E402

# How verify.py records a scored check — read from the verifier rather than listed here, so a
# renamed or added check is picked up without this file being touched.
CHECK = re.compile(r'r\["parts"\]\["(\w+)"\]')
MINUTES_PER_DELIVERABLE = 15


def facts(task: str):
    d = SUITE / "tasks" / task
    meta = tomllib.loads((d / "meta.toml").read_text())
    checks = list(dict.fromkeys(CHECK.findall((d / "verify.py").read_text())))
    return list(meta.get("deliverables") or []), checks


class EveryTaskAgreesWithItsVerifierTests(unittest.TestCase):
    def test_the_deliverable_count_equals_the_scored_check_count(self):
        for task in TASKS:
            with self.subTest(task=task):
                dels, checks = facts(task)
                self.assertEqual(
                    len(dels), len(checks),
                    f"{task}: {len(dels)} deliverables but {len(checks)} checks — the wall would be "
                    f"{MINUTES_PER_DELIVERABLE * len(dels)} min for {len(checks)} things to do")

    def test_every_task_declares_at_least_one_deliverable(self):
        """run.py raises rather than pacing a run at zero minutes; catch it here instead."""
        for task in TASKS:
            with self.subTest(task=task):
                self.assertTrue(facts(task)[0])

    def test_every_task_scores_at_least_one_check(self):
        for task in TASKS:
            with self.subTest(task=task):
                self.assertTrue(facts(task)[1])


class ThePromptIsTheOnlyCopyTests(unittest.TestCase):
    def test_each_task_has_exactly_one_prompt_file(self):
        for task in TASKS:
            with self.subTest(task=task):
                p = SUITE / "tasks" / task / "prompt.txt"
                self.assertTrue(p.is_file())
                self.assertTrue(p.read_text().strip(), "the prompt file is empty")

    def test_the_runner_reads_it_at_run_time(self):
        """Not cached, not copied into meta, not baked into a doc the runner consults."""
        self.assertIn('(task_dir / "prompt.txt").read_text()', (SUITE / "run.py").read_text())


if __name__ == "__main__":
    unittest.main()
