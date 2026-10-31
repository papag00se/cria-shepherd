"""The briefing writer states the task as a description, not as orders to the reader.

Replayed on real ornith1.5_9b servers (window 16,384 and 32,768; session 01a162ad's history, production
validators, system1 classifier OFF so the reasoner's retrospective lens answers): the lens called the
briefing PLAN in 4 of 8 writer replies at 16K and 5 of 8 at 32K, and judged by single sentence the ones it
flagged were the task's own requirements restated as commands ("Fix the threading bug and re-enable parallel
workers", "Make the importer at least 4x faster", "Decide and implement how each bad-row type is handled").
The scope lens demands that the full task survive the briefing; the retrospective lens refuses any sentence that
tells the agent what to do; a writer that quotes the task in its own imperative satisfies one and fails the
other. With one VOICE rule in the writer prompt the same input was accepted 6 of 8 at 16K (3 of 8 before) and
4 of 8 at 32K (1 of 8 before).

Pinned here as the writer's contract; the measurement above is the evidence it works. A model-free test cannot
show the verdict moves.
"""

import unittest

from cria import prompts


class TheWriterIsToldToDescribeTheTaskTests(unittest.TestCase):
    def setUp(self):
        self.sys = prompts.load("selfcompact_summary")

    def test_the_voice_rule_names_both_what_to_do_and_what_not_to(self):
        line = next(l for l in self.sys.splitlines() if l.startswith("- VOICE."))
        low = line.lower()
        self.assertIn("what was asked", low)
        self.assertIn("never as a command", low)
        self.assertIn("no run has shown it done", low)

    def test_the_rule_sits_with_the_rules_not_inside_the_state_bullets(self):
        lines = self.sys.splitlines()
        rules_at = next(i for i, l in enumerate(lines) if l.startswith("Rules:"))
        voice_at = next(i for i, l in enumerate(lines) if l.startswith("- VOICE."))
        self.assertGreater(voice_at, rules_at)

    def test_the_remaining_work_bullet_is_unchanged(self):
        """Fenced elsewhere (test_a_briefing_may_not_invent_a_requirement): this rule adds, never trims."""
        self.assertIn("do not prescribe a repair, file edit, command, implementation, or next action", self.sys)


if __name__ == "__main__":
    unittest.main()
