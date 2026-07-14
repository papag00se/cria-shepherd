import unittest

from cria import prompts


class PromptLoaderTests(unittest.TestCase):
    def test_load_trims_trailing_newline_only(self):
        text = prompts.load("classify")
        self.assertTrue(text.startswith("You are a REQUEST CLASSIFIER"))
        self.assertFalse(text.endswith("\n"))
        self.assertIn("\n", text)  # internal newlines preserved

    def test_render_fills_double_brace_tokens_case_insensitively(self):
        # nudge.txt content is user-tunable, so assert the MECHANISM (the {{REASON}} token is filled
        # from the case-insensitive kwarg), not the surrounding wording.
        out = prompts.render("nudge", reason="tests are red")
        self.assertIn("tests are red", out)      # the token was substituted
        self.assertNotIn("{{REASON}}", out)      # no placeholder left behind
        self.assertNotIn("{{", out)

    def test_render_leaves_literal_single_braces_untouched(self):
        # the critic must be told to emit `{"done": true}` — a single-brace literal that
        # must survive rendering (only {{TOKEN}} is substituted).
        self.assertIn('{"done": true|false, "reason": "<short>"}', prompts.render("verify"))

    def test_unknown_token_is_left_in_place(self):
        self.assertIn("{{STEP}}", prompts.render("step_framing", idx=1, total=3, completed=""))

    def test_load_map_parses_key_values_and_skips_comments(self):
        m = prompts.load_map("cheatsheet")
        self.assertEqual(set(m) & {"header", "shell", "write_file"}, {"header", "shell", "write_file"})
        self.assertNotIn("#", "".join(m))  # comment lines are skipped, not keys
        self.assertIn("{{SHELL}}", m["shell"])  # token preserved for the caller to fill

    def test_load_map_converts_backslash_n_to_newline(self):
        m = prompts.load_map("verify_user")
        self.assertIn("\n", m["evidence"])       # `\n` in the file → real newline
        self.assertNotIn("\\n", m["evidence"])   # not left as a literal backslash-n


if __name__ == "__main__":
    unittest.main()
