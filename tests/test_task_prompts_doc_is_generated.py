"""`docs/task-prompts.md` must be what the prompt files actually say, not a copy that drifted.

The prompt a model receives is `suite/tasks/<task>/prompt.txt` — `suite/run.py` reads that file and
nothing else. Reviewing the wording used to mean opening six of them, so the text was pasted into
`docs/task-battery.md`. A pasted copy is a second source of truth, and this project has already paid
for two: `BUILD_ARTIFACT_DIRS` went out of sync with its copy in `execcheck`, and the read ledger's
docstring stated the right rule while its input lied to it.

So the document is generated, and this test is what keeps it honest: edit a prompt without
regenerating and the suite goes red here rather than a reviewer reading last week's wording.
"""

import pathlib
import subprocess
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "task-prompts.md"
GEN = REPO / "suite" / "prompt_digest.py"

sys.path.insert(0, str(REPO / "suite"))


class TheDocumentMatchesTheFilesTests(unittest.TestCase):
    def test_regenerating_it_changes_nothing(self):
        fresh = subprocess.run([sys.executable, str(GEN)], capture_output=True, text=True, cwd=REPO)
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertEqual(fresh.stdout, DOC.read_text(),
                         "docs/task-prompts.md is stale — run: python3 suite/prompt_digest.py --write")

    def test_every_matrix_task_is_in_it(self):
        from battery_status import TASKS
        body = DOC.read_text()
        for task in TASKS:
            with self.subTest(task=task):
                self.assertIn(f"## {task}", body)

    def test_each_prompt_appears_verbatim(self):
        from battery_status import SUITE, TASKS
        body = DOC.read_text()
        for task in TASKS:
            with self.subTest(task=task):
                text = (SUITE / "tasks" / task / "prompt.txt").read_text().rstrip("\n")
                self.assertIn(text, body, f"{task}'s prompt is not in the document as written")


class TheGeneratorReadsRatherThanRestatesTests(unittest.TestCase):
    def test_the_task_list_has_one_owner(self):
        """Imported from battery_status, never re-typed — a task added there appears here."""
        self.assertIn("from battery_status import", GEN.read_text())

    def test_the_checks_are_parsed_from_the_verifier(self):
        import prompt_digest
        from battery_status import SUITE
        facts = prompt_digest.task_facts("shipping-rates-rb")
        self.assertIn("country_zone_mapping", facts["checks"])
        verifier = (SUITE / "tasks" / "shipping-rates-rb" / "verify.py").read_text()
        for check in facts["checks"]:
            self.assertIn(check, verifier)

    def test_a_deliverable_and_check_count_mismatch_is_reported(self):
        """The wall is paced on the deliverable count, so a drift between the two changes how long
        every run of that task gets. Three tasks were on the wrong clock before this was noticed."""
        import prompt_digest
        out = prompt_digest.render([{
            "task": "x", "language": "Ruby", "prompt": "do a thing",
            "deliverables": ["a", "b"], "checks": ["a", "b", "c"], "wall_minutes": 30}])
        self.assertIn("Count mismatch", out)

    def test_no_mismatch_in_the_real_battery(self):
        import prompt_digest
        from battery_status import TASKS
        for task in TASKS:
            with self.subTest(task=task):
                f = prompt_digest.task_facts(task)
                self.assertEqual(len(f["deliverables"]), len(f["checks"]))


if __name__ == "__main__":
    unittest.main()
