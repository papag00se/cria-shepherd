"""A step that names a FILE TO WRITE is not strategy noise.

The noise judge exists to delete steps like "Error handling strategy." and "Run the tests". It has
deleted DELIVERABLES three times in this ladder:

  * run 1785625253 — unit tests, live test and README removed together;
  * run 1785659842 — "Write unit tests" and "Write a live test script live_test_goose.py" removed;
    the session then ENDED at 1/4 in 181 seconds because the plan it had left was finished;
  * run 1785660278 — logged verbatim, one run after the dropped-text logging landed:
        dropped 2 kept 1
          "Write live_test.py: call GET /handles/goose, print resolved_address, holder_address, ..."
          "Write README.md: install requirements (requests, pytest); run script; run tests; ..."
    That run scored 0/4 with no live test and no README on disk — exactly the two deleted steps.

missing_deliverables is the reasoned brake for this and it does fire (34 times across every log day)
— but it is a judge, and it missed all three. A step naming a file is definitionally not noise, so it
is settled deterministically before any judgment.

KNOWN LIMIT, stated rather than papered over: "Write unit tests for resolve_handle with 3-4 test
cases" names no file and is NOT protected by this rule. Two of the three measured cases are covered
in full; that one is not.
"""
import inspect
import unittest

from cria import loop


class ArtifactNamingTests(unittest.TestCase):
    def test_a_shell_command_that_merely_names_a_path_is_still_droppable(self):
        # `grep -n 'x' spec.json` names a file and IS the bare-command noise this judge should
        # delete. Authoring intent is the discriminator, not the presence of a filename.
        self.assertEqual(loop.step_authors_artifact(
            "grep -n 'resolve' ./tmp/read-only/api.handle.me_openapi.json"), [])
        self.assertEqual(loop.step_authors_artifact("Run pytest on test_x.py"), [])

    def test_the_two_logged_deletions_are_recognised_as_deliverables(self):
        for step in ("Write live_test.py: call GET /handles/goose, print resolved_address, "
                     "holder_address, total_handles",
                     "Write README.md: install requirements (requests, pytest); run script; "
                     "run tests; explain two-step resolution"):
            with self.subTest(step=step[:40]):
                self.assertTrue(loop.step_authors_artifact(step))

    def test_real_noise_steps_are_still_droppable(self):
        for step in ("Error handling strategy.", "Code style strategy.", "Testing strategy.",
                     "Run the unit tests", "Set up the development environment",
                     "Verify the tests pass"):
            with self.subTest(step=step):
                self.assertEqual(loop.step_authors_artifact(step), [])

    def test_the_KNOWN_LIMIT_is_real_and_documented(self):
        # Not protected — stated in the module docstring rather than hidden.
        self.assertEqual(
            loop.step_authors_artifact("Write unit tests for resolve_handle with 3-4 test cases"), [])

    def test_each_artifact_once(self):
        self.assertEqual(
            loop.step_authors_artifact("Add README.md, then check README.md again"), ["README.md"])


class RefusalWiringTests(unittest.TestCase):
    def test_the_drop_set_excludes_protected_steps(self):
        src = inspect.getsource(loop.reassess_remaining)
        self.assertIn("protected = {i for i, text in enumerate(cleaned) if step_authors_artifact(text)}", src)
        self.assertIn("drop = drop - protected", src)

    def test_the_refusal_is_announced_not_silent(self):
        src = inspect.getsource(loop.reassess_remaining)
        self.assertIn("loop.replan_noise_refused", src)
        i = src.index("loop.replan_noise_refused")
        self.assertIn("cleaned[i]", src[i:i + 220], "say WHICH steps were protected")

    def test_it_happens_BEFORE_kept_is_built(self):
        src = inspect.getsource(loop.reassess_remaining)
        self.assertLess(src.index("drop = drop - protected"),
                        src.index("kept = [s for i, s in enumerate(cleaned)"))

    def test_the_reasoned_brake_still_runs_after(self):
        # This is additive: missing_deliverables remains the backstop it always was.
        src = inspect.getsource(loop.reassess_remaining)
        self.assertIn("missing_deliverables(", src)
