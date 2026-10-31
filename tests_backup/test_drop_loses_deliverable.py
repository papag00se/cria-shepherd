"""The noise judge deleted a README the task asked for, and the coverage check passed it.

Walked on ada-handles_fabliq_codex_pon_1785801960 (00:14:24). The re-derivation's noise judge
dropped two steps:

    'Set up a Python environment with the `requests` library installed…'
    'Add a README.md file explaining how to install dependencies (`pip install requests pytest`),
     run the script with an Ada Handle, and execute unit tests.'

The first is a correct removal. The second is a deliverable the task names in its own words — "add a
README that explains how to install and run the script and the tests" — deleted because a README
that explains how to install necessarily contains `pip install`, which reads as environment setup.
The plan went 8 steps to 6 and nothing produced a README again.

cria's enforced coverage check RAN over the survivors and returned nothing missing, so the deletion
was never refused. That check asks an OPEN question over the whole plan; these tests pin the narrow
one that replaces it as the first gate — "would deleting THIS step lose something the request asked
for?" — and pin that it fails CLOSED, because its action is a deletion and deletion is the dangerous
direction (#2).

Not a one-off: cria's own logs record this judge firing 156 times across every recorded day and
dropping at least one step 75 times, and it deleted deliverables twice in this ladder alone — once
ending a run at 1/4 with "unit tests" and "live test" gone from the plan.
"""
import unittest

from cria import planner

TASK = ("I would like you to write a Python script that accepts an Ada Handle as input and resolves "
        "it to the Cardano address using the Ada Handles API. Unit tests are required. Separately, "
        "create a live test that resolves the handle goose or papagoose. When you're done, add a "
        "README that explains how to install and run the script and the tests.")

README_STEP = ("Add a README.md file explaining how to install dependencies (`pip install requests "
               "pytest`), run the script with an Ada Handle, and execute unit tests.")
VENV_STEP = "Set up a Python environment with the `requests` library installed for HTTP communication."
REMAINING = ["Write a Python function that resolves a handle via the endpoint the spec names",
             "Create unit tests using pytest that mock the API response",
             "Develop a live test that resolves the handles goose and papagoose"]


class TheQuestionItAsksTests(unittest.TestCase):
    def test_it_asks_about_the_one_step_and_shows_what_remains(self):
        seen = {}

        def ask(sysp, usr):
            seen["system"], seen["user"] = sysp, usr
            return '{"lost": ""}'

        planner.deliverable_lost_by_drop(ask, TASK, README_STEP, REMAINING)
        self.assertIn(README_STEP, seen["user"])
        for s in REMAINING:
            self.assertIn(s, seen["user"])
        self.assertIn(TASK[:40], seen["user"])
        # The trap by name — a step can DESCRIBE installing while its action is producing a doc.
        self.assertIn("README", seen["system"])

    def test_a_named_loss_is_returned(self):
        lost = planner.deliverable_lost_by_drop(
            lambda s, u: '{"lost": "a README explaining how to install and run it"}',
            TASK, README_STEP, REMAINING)
        self.assertEqual(lost, "a README explaining how to install and run it")

    def test_a_clean_verdict_lets_the_deletion_stand(self):
        self.assertEqual(
            planner.deliverable_lost_by_drop(lambda s, u: '{"lost": ""}', TASK, VENV_STEP, REMAINING),
            "")


class ItFailsClosedTests(unittest.TestCase):
    """Every other judge in planner.py takes the safe null by doing nothing. This one's action is a
    DELETION, so its safe null is the other way: an answer it cannot read KEEPS the step."""

    def test_unparseable_keeps_the_step(self):
        for answer in ("", "I think it is fine", "{}", '{"lost": null}', "NONE", None):
            with self.subTest(answer=answer):
                self.assertTrue(planner.deliverable_lost_by_drop(
                    lambda s, u: answer, TASK, README_STEP, REMAINING))

    def test_a_reasoner_that_raises_is_not_swallowed_into_a_deletion(self):
        def boom(sysp, usr):
            raise RuntimeError("upstream died")
        with self.assertRaises(RuntimeError):
            planner.deliverable_lost_by_drop(boom, TASK, README_STEP, REMAINING)


class TheWalkedVerdictTests(unittest.TestCase):
    """The exact two-step drop of run 1785801960: the venv step goes, the README step stays, and the
    correct half of the verdict is not thrown away with the wrong half."""

    STEPS = [VENV_STEP, README_STEP] + REMAINING

    def test_only_the_deliverable_drop_is_refused(self):
        answers = iter(['{"lost": ""}',                       # step 0, the venv step
                        '{"lost": "a README explaining how to install and run it"}'])  # step 1

        kept_drop, refused = planner.surviving_noise_drops(
            lambda s, u: next(answers), TASK, self.STEPS, {0, 1})

        self.assertEqual(kept_drop, {0})                      # the venv deletion still lands
        self.assertEqual(list(refused), [1])
        self.assertIn("README", refused[1])

    def test_each_step_is_judged_against_the_others_that_survive(self):
        """A step is not judged against a plan that still contains the other doomed steps — else two
        steps producing the same thing each look redundant and both get deleted."""
        asked = []

        def ask(sysp, usr):
            asked.append(usr)
            return '{"lost": ""}'

        planner.surviving_noise_drops(ask, TASK, self.STEPS, {0, 1})
        self.assertEqual(len(asked), 2)
        self.assertNotIn(README_STEP, asked[0])   # judging the venv step: the README is also going
        self.assertNotIn(VENV_STEP, asked[1])

    def test_nothing_is_asked_when_nothing_is_being_dropped(self):
        def ask(sysp, usr):
            raise AssertionError("no drop → no question")
        kept_drop, refused = planner.surviving_noise_drops(ask, TASK, self.STEPS, set())
        self.assertEqual((kept_drop, refused), (set(), {}))


if __name__ == "__main__":
    unittest.main()
