"""cria must not withhold its correction on the belief that a better one is already visible."""
import unittest

from cria import loop

CHECKS = ("• test_resolve_handle.py:48: AssertionError: Exception not raised\n"
          "• test_resolve_handle.py:42: AssertionError: Exception not raised")


def body(*contents):
    return {"messages": [{"role": "user", "content": c} for c in contents]}


class VisibilityTests(unittest.TestCase):
    def test_sees_the_checks_when_they_are_in_the_prompt(self):
        self.assertTrue(loop._checks_already_visible(
            body("some history", "⟦ctx:steer⟧ [GROUND TRUTH]\n" + CHECKS), CHECKS))

    def test_does_NOT_see_them_when_the_prompt_carries_only_the_task(self):
        # The measured case: 129 of 176 coder prompts in one run looked like this.
        self.assertFalse(loop._checks_already_visible(
            body("Write unit tests in `test_resolve_handle.py` that mock the API responses."),
            CHECKS))

    def test_matches_through_different_framing(self):
        # The same finding is re-rendered with different wrappers in different places; anchoring on
        # the checker's own first line is what survives that.
        reframed = "The repo checks report:\n  test_resolve_handle.py:48: AssertionError: Exception not raised"
        self.assertTrue(loop._checks_already_visible(body(reframed), CHECKS))

    def test_empty_checks_are_treated_as_visible(self):
        self.assertTrue(loop._checks_already_visible(body("anything"), ""))
        self.assertTrue(loop._checks_already_visible(body("anything"), "   \n  "))

    def test_no_messages_means_not_visible(self):
        self.assertFalse(loop._checks_already_visible({"messages": []}, CHECKS))

    def test_non_string_content_does_not_crash(self):
        b = {"messages": [{"role": "user", "content": [{"type": "text", "text": CHECKS}]}]}
        self.assertFalse(loop._checks_already_visible(b, CHECKS))


class RepeatPromptTests(unittest.TestCase):
    def test_it_repeats_the_checkers_own_words_verbatim(self):
        from cria import loop, prompts
        out = prompts.render("steer_checks_repeat", findings=CHECKS,
                             since=loop._checks_ran_before([]))
        self.assertIn("test_resolve_handle.py:48", out)
        self.assertIn("test_resolve_handle.py:42", out)

    def test_it_claims_no_currency_it_cannot_verify(self):
        """It used to open "unchanged since you were last shown them — you have not cleared them
        yet". cria knows when the checks RAN and that nothing re-ran them; it does not know whether
        the findings still hold, because the coder edits between gates. 25 wrong turns across the
        six-language battery, every model (#5b)."""
        from cria import loop, prompts
        out = prompts.render("steer_checks_repeat", findings=CHECKS,
                             since=loop._checks_ran_before([]))
        self.assertNotIn("unchanged", out)
        self.assertNotIn("you have not cleared them", out)
        self.assertIn("nothing has run them again since", out)
        self.assertIn("not as proof of the state right now", out)

    def test_it_names_the_coders_own_edit_not_a_call_number(self):
        from cria import loop, prompts
        out = prompts.render("steer_checks_repeat", findings=CHECKS,
                             since=loop._checks_ran_before(["lib/shipping/rates.rb"]))
        self.assertIn("before your change to lib/shipping/rates.rb", out)
        self.assertNotRegex(out, r"\b(?:call|turn)\s+\d+")

    def test_no_placeholder_ever_reaches_the_model(self):
        from cria import loop, prompts
        for paths in ([], ["a.rb"], ["a.rb", "b.rb"]):
            out = prompts.render("steer_checks_repeat", findings=CHECKS,
                                 since=loop._checks_ran_before(paths))
            self.assertNotIn("{{", out)

    def test_it_never_speaks_for_the_checker(self):
        # principle: cria may SELECT a checker's real lines, never SUBSTITUTE its own words.
        from cria import prompts
        out = prompts.render("steer_checks_repeat", findings=CHECKS)
        for line in CHECKS.splitlines():
            self.assertIn(line.strip(), out)

    def test_marker_is_the_ctx_namespace_never_the_proper_noun(self):
        from cria import prompts
        out = prompts.render("steer_checks_repeat", findings=CHECKS)
        self.assertIn("⟦ctx:", out)
        self.assertNotIn("cria", out.lower())
