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

from cria import prompts

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
        """RENDERED, not the source. This clause moved out of probegate.py into
        prompts/checks_error_class.txt with the seeded-test rule as one owner — the inline copy was
        the one that shipped (3,254 prompts) and the one an update had missed. (A source-text check
        for the old phrase was dropped from here: it now survives only in this file's own explanatory
        comment about the incident, so `assertNotIn` on the module's source was checking a comment,
        not a code path — and would break the moment that comment gets reworded, for no behavioral
        reason. The rendered assertion below is the actual claim and is strictly stronger: it proves
        the CURRENT wording ships, not merely that one old spelling is absent.)"""
        out = prompts.render("checks_error_class", findings="x.py:1: boom")
        self.assertIn("changing the test so it stops asking is not a fix", out)
        self.assertIn("already in the repository", out)   # …and now it says WHICH tests


class FailedFetchNoteTests(unittest.TestCase):
    def test_it_no_longer_volunteers_a_menu_of_causes(self):
        note = prompts.load_map("fetched_facts_sections")["failed"]
        for cause in ("wants credentials", "429", "5xx", "401/403"):
            with self.subTest(cause=cause):
                self.assertNotIn(cause, note)

    def test_the_label_names_no_cause_at_all(self):
        """It used to name one — "check the VALUE you put in the path" — and on 2026-08-07 that guess
        was wrong in both directions in one day (maple 0014 the route was wrong, mellum 0019 the value
        was). The cause is now decided PER URL against cria's own route list, so the shared label above
        the list must not prejudge it."""
        note = prompts.load_map("fetched_facts_sections")["failed"]
        for cause in ("parameter description", "the VALUE you put", "credential", "rate", "retry"):
            self.assertNotIn(cause, note)

    def test_the_per_url_diagnosis_names_the_half_that_is_actually_wrong(self):
        from cria import loop
        led = {"spec": ("HTTP 200", "/handles/{handle}, /holders/{address}",
                        "GET /holders/{address} (replace in the URL path: {address} = The stake "
                        "address of the Holder) returns:", "")}
        wrong_route = loop._failed_fetch_diagnosis("https://api.handle.me/handle/goose", led)
        wrong_value = loop._failed_fetch_diagnosis("https://api.handle.me/holders/addr1qxsf", led)
        self.assertIn("no such route", wrong_route)
        self.assertIn("/handles/{handle}", wrong_route)          # the near miss, named
        self.assertIn("this route exists", wrong_value)
        self.assertIn("stake address of the Holder", wrong_value)  # the spec's own words

    def test_with_no_route_list_it_says_nothing(self):
        """Silence over a guess — cria has nothing to match the URL against."""
        from cria import loop
        self.assertEqual(loop._failed_fetch_diagnosis("https://x.test/a", {"u": ("HTTP 404", "", "", "")}), "")

    def test_it_no_longer_claims_cria_has_no_content(self):
        # False: cria held the 404's 89-byte body and had replaced it with a key list.
        self.assertNotIn("you have no content from them",
                         prompts.load_map("fetched_facts_sections")["failed"])

    def test_a_404_still_does_not_condemn_the_other_routes(self):
        note = prompts.load_map("fetched_facts_sections")["failed"]
        self.assertTrue("says nothing about the others" in note
                        or "says nothing about any other URL" in note, note)


if __name__ == "__main__":
    unittest.main()
