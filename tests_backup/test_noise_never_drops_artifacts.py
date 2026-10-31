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
import json
import unittest

from cria import loop, prompts
from cria.config import Role
from tests.test_loop import _Rlog, _Scripted, _replan, _text


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

    def _role(self):
        return Role(name="reasoner", backend="local")

    def test_reassess_does_not_second_guess_the_judge_with_a_pattern(self):
        """The retired guard vetoed the judge's decision by SHAPE — an authoring verb near a
        filename — on step text just like this one, the SECOND of its own three measured false
        positives (see this file's own docstring: "MISSED 'Write a live test file (e.g.,
        test_live_resolve.py)'" is the mirror image — the shape triggered wrongly both ways
        because it was never the right signal). Drive the real function: when the reasoner marks a
        step noise, it must actually go — no deterministic keyword override survives to keep it."""
        steps = loop.reassess_remaining(
            _Scripted([_replan(["Write a live test file (e.g., test_live_resolve.py)",
                                "Write unit tests"]),
                       _text("1"), _text('{"lost": ""}')]),
            self._role(), "resolve an Ada Handle", "- researched", "- old", "ev", _Rlog())
        self.assertFalse(any("live test file" in s for s in steps),
                         "an authoring-verb-near-filename step must be droppable by the judge alone")
        self.assertTrue(any("unit tests" in s for s in steps))

    def test_the_reasoned_deliverables_brake_still_backs_it_up(self):
        """The regex guard is gone; THIS backs the invariant up now — a tail whose drop would lose
        a deliverable the task asked for is REFUSED (the plan stays untouched), never silently
        shipped. Same shape as two of the measured incidents: unit tests + live test dropped
        together in one re-derivation."""
        out = loop.reassess_remaining(
            _Scripted([_replan(["Write resolve_handle.py"]), _text("NONE"),
                       _text(json.dumps({"missing": ["unit tests", "live test"]}))]),
            self._role(), "script + unit tests + live test", "",
            "- write script\n- write tests\n- write live test", "ev", _Rlog())
        self.assertIsNone(out, "a tail that drops deliverables must be refused, not shipped")

    def test_the_dropped_step_logging_stays(self):
        # It is what made every one of these findings measurable within a single run — the FIELD,
        # not just the count. Drive a real noise-drop and read it off the event.
        rlog = _Rlog()
        loop.reassess_remaining(
            _Scripted([_replan(["grep -n 'resolve' ./tmp/reference/api.handle.me_openapi.json",
                                "Write the resolver using the endpoint the spec names"]),
                       _text("1"), _text('{"lost": ""}')]),
            self._role(), "resolve via api.handle.me", "- researched", "- old", "ev", rlog)
        events = [kw for k, kw in rlog.events if k == "loop.replan_noise"]
        self.assertTrue(events, "the noise-drop event never fired")
        self.assertIn("grep", events[0].get("dropped_steps", ""))
