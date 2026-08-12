"""The two most expensive things a directive did, both now forbidden at the author.

**It chose the implementation — 15 occurrences, 9 lost checks, the most of any single mechanism in
the assisted-arm walk.** The supervisor restated the job in its own words and the coder built the
restatement. The task said *"don't hand-roll the EU member list; lean on something maintained"*; the
directive said *"Use a simple constant hash for the country-to-zone map"* and the coder hand-rolled
it. Another told the coder to *"Add commander to your dependencies in package.json"* on a task whose
whole point was removing a dependency.

**It stated a cause it had not verified — 24 occurrences, wrong all 24.** In every one the coder had
already seen evidence pointing elsewhere and dropped it, because an injected instruction outranks a
model's own eyes.

Both are constraints on the AUTHOR, not filters on its output. A drop-guard would need cria to judge
prose after the fact and would throw away good directives with the bad; forbidding it up front costs
nothing and cannot misfire. This is the safe direction — removing latitude rather than adding
machinery (#1).

What is deliberately NOT here: a check that the directive orders work already done. That mechanism
was filed with 22 occurrences in the walk, but measured against the real directives — 536 of them —
exactly one says "create X" for a file already written, and reading it, that one is a false positive
about a missing database table. It does not survive measurement (#15).
"""

import re
import unittest

from cria import prompts


class TheAuthorMayNotPickTheApproachTests(unittest.TestCase):
    def setUp(self):
        self.body = prompts.load("steer_diagnose")

    def test_it_is_told_not_to_choose_the_implementation(self):
        self.assertIn("Do not choose the IMPLEMENTATION", self.body)

    def test_it_names_the_choices_that_are_not_its_to_make(self):
        for choice in ("library", "data structure", "flag", "output format", "file to create"):
            with self.subTest(choice=choice):
                self.assertIn(choice, self.body)

    def test_it_says_where_those_choices_do_belong(self):
        self.assertRegex(self.body, r"belong to the TASK or to the coder")

    def test_the_rule_carries_its_evidence(self):
        """A rule with its incident attached survives the next person who thinks it is fussy."""
        self.assertIn("nine checks", self.body)


class TheAuthorMayNotInventACauseTests(unittest.TestCase):
    def setUp(self):
        self.body = prompts.load("steer_diagnose")

    def test_it_is_told_not_to_state_an_unverified_cause(self):
        self.assertIn("Do not state a CAUSE you have not verified", self.body)

    def test_it_is_given_what_to_say_instead(self):
        """A prohibition with no replacement is a prohibition a weak model routes around."""
        self.assertIn("Report what a check printed", self.body)
        self.assertIn("name the next thing to look at", self.body)

    def test_the_identify_rule_now_asks_for_a_quote_not_an_explanation(self):
        self.assertIn("by quoting it, not by explaining it", self.body)

    def test_the_rule_carries_its_evidence(self):
        self.assertIn("twenty-four", self.body)


class WhatTheAuthorMayStillDoTests(unittest.TestCase):
    """The directive has to remain useful, or the assist is deleted rather than narrowed."""

    def setUp(self):
        self.body = prompts.load("steer_diagnose")

    def test_it_still_must_give_one_concrete_next_action(self):
        self.assertIn("Give exactly ONE concrete next action", self.body)

    def test_it_still_may_quote_a_real_error_or_a_line_it_read(self):
        self.assertIn("Quoting a real error or a line you actually read is not writing code", self.body)

    def test_it_still_redirects_to_a_missing_deliverable(self):
        self.assertIn("explicitly redirect it to that deliverable", self.body)

    def test_it_still_has_its_positive_veto(self):
        """ON_TRACK, never the negation of the trigger (#21)."""
        self.assertIn("ON_TRACK", self.body)
        self.assertNotIn("NOT_STUCK", self.body)

    def test_it_still_names_the_read_only_tools_it_really_has(self):
        self.assertIn("`read_file` and `list_dir`", self.body)

    def test_it_never_names_the_program_to_the_model(self):
        for line in self.body.splitlines():
            self.assertIsNone(re.search(r"\bcria\b", line, re.I))


if __name__ == "__main__":
    unittest.main()
