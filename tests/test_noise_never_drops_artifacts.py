"""The noise judge must never delete a step that produces something the task asked for.

Measured across this ladder, it did exactly that four times:

  * run 1785625253 — unit tests, live test and README removed together;
  * run 1785659842 — "Write unit tests" and "Write a live test script live_test_goose.py"; the
    session then ENDED at 1/4 in 181 seconds because the plan it had left was finished;
  * run 1785660278 — "Write live_test.py ..." and "Write README.md ...", logged verbatim;
  * run 1785682267 — "Write unit tests for resolve_handle covering (a) success ...".

WHAT WAS TRIED FIRST, AND WHY IT IS GONE. A deterministic guard protected any step whose text
matched an authoring verb near a filename. It went through FOUR revisions in four runs and produced
THREE distinct false positives:

    verb anywhere + file anywhere -> protected "Commit the three files (...), add a .gitignore ..."
    verb adjacent to file         -> MISSED "Write a live test file (e.g., test_live_resolve.py)"
    40-character window           -> protected "Add a requirements.txt entry for requests"

The last one was not even a false positive in the way it looked: plan_noise_steps.txt explicitly
lists "adding a requirements entry" as removable, so the judge was RIGHT and the guard was blocking a
correct deletion.

The tell was in the diagnosis from the first walk: the difference between authoring a deliverable and
authoring plumbing is not in the sentence — it is in whether the TASK asked for it. No window over
the sentence can recover information the sentence does not contain, and reasoned_noise_indices'
own docstring already says "ONE reasoner question replaces the whole pile of keyword/shape regexes
that used to read intent out of prose and drive deletions". A regex was bolted onto the function that
had already replaced regexes.

The fix is the question, not a fifth pattern: the judge is now told the invariant it was breaking.
See docs/principles.md #9, corollary.
"""
import inspect
import unittest

from cria import loop, prompts


class TheInvariantIsStatedToTheJudge(unittest.TestCase):
    TEXT = prompts.load("plan_noise_steps")

    def test_the_judge_is_told_deliverables_must_survive(self):
        low = self.TEXT.lower()
        self.assertIn("if removing a step would leave something the task asked for", low)
        self.assertIn("that step stays", low)

    def test_it_is_stated_FIRST_not_buried(self):
        self.assertLess(self.TEXT.index("BEFORE ANYTHING ELSE"),
                        self.TEXT.index("Mark a step for REMOVAL"))

    def test_the_judge_is_told_to_check_its_removals_against_the_list(self):
        self.assertIn("check your removals against that list", self.TEXT)

    def test_it_says_WHY_so_the_rule_survives_paraphrase(self):
        self.assertIn("the work simply never happens", self.TEXT)


class NoRegexGuardRemains(unittest.TestCase):
    def test_the_deterministic_protection_is_GONE(self):
        self.assertFalse(hasattr(loop, "_AUTHORS_FILE"))
        self.assertFalse(hasattr(loop, "step_authors_artifact"))

    def test_reassess_does_not_second_guess_the_judge_with_a_pattern(self):
        src = inspect.getsource(loop.reassess_remaining)
        self.assertNotIn("step_authors_artifact", src)
        self.assertNotIn("protected", src)

    def test_the_reasoned_deliverables_brake_still_backs_it_up(self):
        self.assertIn("missing_deliverables(", inspect.getsource(loop.reassess_remaining))

    def test_the_dropped_step_logging_stays(self):
        # It is what made every one of these findings measurable within a single run.
        self.assertIn("dropped_steps=", inspect.getsource(loop))
