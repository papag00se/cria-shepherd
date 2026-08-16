"""The compaction briefing may not invent work, and a model's summary is never labelled ground truth.

cart-billing-go x qwen35 lost two checks to one sentence. The word `main.go` appears nowhere in that
session before call 0062 — not in the task, not in a prompt, not in the model's own thinking. Its
first appearance is the compactor's answer to "what remains to be done", where the observation
("LoadDiscounts is never called") was true and the prescription ("invoke it at startup, e.g. in
`main.go`") was invented. cria pinned that into 36 straight coder prompts and filed it to the
completion judge under a header reading `(ground truth)`. The judge cited it as fact — "Looking at
the summary, it says…" — and the coder, one call after noticing the task never mentions main.go,
wrote "The task requires that LoadDiscounts() be called at startup." A second package in one Go
directory forced a restructure, which renamed the module, which failed both checks. One token back
in go.mod scores 5/5.

Two causes, two fixes. The bullet had no evidence rule while every other bullet in that prompt has
one, so a tool-less model asked what remains answers by inventing. And the evidence header told the
judge that a model's own prose was ground truth, which is the provenance half of #5b: tool output is
ground truth, a summary is a claim, and the two must not arrive under the same label.

The bullet is FENCED, not deleted — tests/test_compaction_contract_stated_once.py pins the literal
and this prompt has had a trim reverted before.
"""

import unittest

from cria import prompts


class TheOutstandingBulletCarriesTheEvidenceRuleTests(unittest.TestCase):
    def setUp(self):
        self.sys = prompts.load("selfcompact_summary")

    def test_the_bullet_still_exists(self):
        """Fenced, never removed — the pin in test_compaction_contract_stated_once.py holds."""
        self.assertIn("What remains to be done", self.sys)

    def test_it_is_bound_to_evidence_like_every_other_bullet(self):
        line = next(l for l in self.sys.splitlines() if "What remains to be done" in l)
        low = line.lower()
        self.assertIn("evidence rule", low)
        self.assertTrue("a check that ran" in low or "check that ran" in low)

    def test_it_forbids_naming_a_thing_the_task_does_not(self):
        line = next(l for l in self.sys.splitlines() if "What remains to be done" in l)
        low = line.lower()
        self.assertIn("the task does not name", low)
        for noun in ("file", "command", "step"):
            self.assertIn(noun, low)

    def test_it_offers_the_empty_answer(self):
        line = next(l for l in self.sys.splitlines() if "What remains to be done" in l)
        self.assertIn("nothing verified outstanding", line.lower())

    def test_the_files_rule_now_runs_both_ways(self):
        """It forbade claiming a file was CREATED and said nothing about claiming one is MISSING —
        which is the half cart-billing-go x nemotron-elastic's briefing got wrong."""
        low = self.sys.lower()
        self.assertIn("never state that a file was created unless it is on that list", low)
        self.assertIn("never state that a file is missing when it is on that list", low)


class AModelsSummaryIsNotGroundTruthTests(unittest.TestCase):
    def setUp(self):
        self.user = prompts.load("satisfaction_user")

    def test_the_header_no_longer_calls_the_evidence_block_ground_truth_outright(self):
        head = self.user.split("{{EVIDENCE}}")[0]
        self.assertNotIn("(ground truth):", head)

    def test_it_names_tool_output_as_the_ground_truth_and_a_summary_as_a_claim(self):
        head = self.user.split("{{EVIDENCE}}")[0].lower()
        self.assertIn("tool output is ground truth", head)
        self.assertIn("claim", head)

    def test_it_tells_the_judge_which_to_trust(self):
        head = self.user.split("{{EVIDENCE}}")[0].lower()
        self.assertIn("trust the tool output", head)

    def test_the_task_still_comes_first(self):
        self.assertTrue(self.user.lstrip().startswith("THE USER'S ORIGINAL TASK"))


if __name__ == "__main__":
    unittest.main()
