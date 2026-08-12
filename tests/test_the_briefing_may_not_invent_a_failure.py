"""The rolling briefing could not invent a passing test, but it could invent a broken build.

When the context grows too long cria asks the same weak model to compress it into a briefing. That
model has no files on screen and no check output — and its instructions require it to fill in "what
still fails and why (quote the concrete error and file:line)". So it fills the slot from memory.

qwen35's Java run, carried forward into more than 200 later prompts:

    **Fix Compilation:** Move the declaration of `List<Future<Map<String, Double>>> futures` outside
    the `if (WORKERS_ENABLED …)` block so it is accessible in the merge logic.

The build error had already been fixed. cria then pinned the note above every later prompt as the
model's own prior work, where it outranks the file on disk, and the run spent its remaining calls on
a problem that was not there. 28 verified wrong turns across the six-language battery — the most
expensive class the walk found.

THE RULE WAS ALREADY THERE, POINTING ONE WAY. The prompt has always forbidden inventing a pass:
*"Only state that tests PASS or the build WORKS if the transcript shows the check ACTUALLY RAN"*.
Nothing said the same about a failure. A summariser that cannot see the workspace is equally unable
to know either one, so the rule is now symmetric — and where the last observation predates an edit,
it must say so rather than assert a present state.

Fixed in the prompt rather than by correcting the output afterwards: this stops the claim being
written. The two existing correctors (`_briefing_disk_truth`, `_briefing_gate_ground_truth`) append
cria's own facts and never delete, precisely because a matcher cannot tell a claim about a file from
a claim about something inside it — so they could not have caught this one.
"""

import re
import unittest

from cria import prompts


class TheEvidenceRuleAppliesBothWaysTests(unittest.TestCase):
    def setUp(self):
        self.body = prompts.load("selfcompact_summary")

    def test_it_still_forbids_inventing_a_pass(self):
        self.assertIn("Only state that tests PASS or the build WORKS", self.body)
        self.assertIn("A confident claim is not a passing test.", self.body)

    def test_it_now_forbids_inventing_a_failure(self):
        self.assertIn("THE SAME RULE FOR FAILURES", self.body)
        for phrase in ("broken, blocked, missing or still to do",
                       "Never carry a problem forward from memory"):
            self.assertIn(phrase, self.body)

    def test_it_says_what_to_write_when_the_observation_predates_an_edit(self):
        """The replacement has to be usable, or the model will just drop the section."""
        self.assertIn("not re-run since", self.body)

    def test_the_current_state_bullet_points_at_the_rule(self):
        """The bullet that ASKS for 'what still fails' is where the invention happens, so the
        constraint has to be visible from there, not only in a list further down."""
        i = self.body.index("what still fails and why")
        j = self.body.index("evidence rule below")
        self.assertLess(j - i, 200)

    def test_the_reason_given_is_the_summarisers_own_blindness(self):
        """Not an appeal to a rule — a reason a weak model can apply to a case nobody wrote down."""
        self.assertIn("You cannot see the files or run anything from here", self.body)


class TheSurroundingContractIsUnchangedTests(unittest.TestCase):
    def setUp(self):
        self.body = prompts.load("selfcompact_summary")

    def test_it_is_still_toolless_and_still_only_writes_the_briefing(self):
        self.assertIn("You have NO tools", self.body)
        self.assertIn("Your ONLY output is the briefing text", self.body)

    def test_it_still_refuses_to_freeze_identifiers(self):
        self.assertIn('"done — don\'t change it."', self.body)

    def test_it_still_names_files_and_errors_precisely(self):
        self.assertIn("Name FILES and concrete ERRORS precisely", self.body)

    def test_it_names_no_call_or_turn_number(self):
        """cria's private numbering means nothing to any model reading this."""
        self.assertIsNone(re.search(r"\b(?:call|turn)\s+\d+", self.body))


if __name__ == "__main__":
    unittest.main()
