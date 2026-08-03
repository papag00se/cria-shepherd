"""Two phrases cria repeats, each of which taught a model the wrong lesson.

1. "make the smallest change that clears it" — when the failure is a REAL defect, the smallest
   change that clears it is to stop the check asking. Walked on
   ada-handles_mellum2_codex_poff_1785714194: at 0029 pytest reported `AssertionError: 0 not greater
   than 0`, a true signal that the deliverable was wrong, and the coder rewrote its own assertion to
   `assertEqual(result["total_handles"], 0)`. The test then certified the bug and the run shipped
   green. The phrase landed twice in that run.

2. "401/403 means it exists and wants credentials, 429 and 5xx mean try later" — a menu of causes is
   a menu a stuck model orders from. At 0023 the model's very next reasoning proposed rate-limiting
   and authentication, cria's own two examples read straight back, for a 404 whose real cause was a
   wrong value in the path.
"""
import unittest

from cria import probegate, prompts

CHECK_TEXTS = ("block_nudge_preamble", "steer_checks_repeat")


class SmallestChangeTests(unittest.TestCase):
    def test_no_check_prompt_asks_only_to_CLEAR_the_finding(self):
        for name in CHECK_TEXTS:
            with self.subTest(prompt=name):
                self.assertNotIn("smallest change that clears it", prompts.load(name))

    def test_each_says_a_doctored_test_is_not_a_fix(self):
        for name in CHECK_TEXTS:
            with self.subTest(prompt=name):
                self.assertIn("is not a fix", prompts.load(name))

    def test_the_findings_block_emitted_from_CODE_says_it_too(self):
        import inspect
        src = inspect.getsource(probegate)
        self.assertNotIn("smallest change that clears it:", src)
        self.assertIn("changing the test so it stops asking is not a fix", src)


class FailedFetchNoteTests(unittest.TestCase):
    def test_it_no_longer_volunteers_a_menu_of_causes(self):
        note = prompts.load_map("fetched_facts_sections")["failed"]
        for cause in ("wants credentials", "429", "5xx", "401/403"):
            with self.subTest(cause=cause):
                self.assertNotIn(cause, note)

    def test_it_points_at_the_one_checkable_thing(self):
        note = prompts.load_map("fetched_facts_sections")["failed"]
        self.assertIn("parameter description", note)

    def test_it_no_longer_claims_cria_has_no_content(self):
        # False: cria held the 404's 89-byte body and had replaced it with a key list.
        self.assertNotIn("you have no content from them",
                         prompts.load_map("fetched_facts_sections")["failed"])

    def test_a_404_still_does_not_condemn_the_other_routes(self):
        self.assertIn("says nothing about the others",
                      prompts.load_map("fetched_facts_sections")["failed"])


if __name__ == "__main__":
    unittest.main()
