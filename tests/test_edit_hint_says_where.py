"""The divergence hint quoted a snippet and never said WHERE it was.

`edit_file` refuses when `old_string` does not match, and cria hands back the file's real text around
the first differing line. The window was right; the address was missing. A snippet that appears twice
in a file cannot tell the model which copy it mistyped, and it cannot tell it that a line it
remembers is absent — so a coder that believes its own copy reads the hint as agreement.

Measured on the six-language battery: a coder resubmitted a byte-identical old_string three times
against a hint showing it text it believed it already had.

The divergence index is computed where the mismatch is found; it only had to be carried out.
"""
import unittest

from cria import prompts


class TheHintCarriesTheLineNumberTests(unittest.TestCase):
    def _rendered(self, line=22):
        return prompts.fill(prompts.load_map("editfail_reports")["anchor"],
                            anchor="  x := 1\n  y := 2", line=line)

    def test_it_names_the_line_that_differs(self):
        self.assertIn("LINE 22", self._rendered())

    def test_it_says_what_a_missing_line_means(self):
        """The other half: a line the model remembers that is NOT in the window is not in the file.
        Without that, an omission reads as an abbreviation."""
        self.assertIn("not shown here is not in the file", self._rendered())

    def test_it_still_hands_over_the_text_to_copy(self):
        r = self._rendered()
        self.assertIn("x := 1", r)
        self.assertIn("verbatim in old_string", r)

    def test_the_template_has_no_stray_tokens(self):
        self.assertNotIn("{{", self._rendered())


if __name__ == "__main__":
    unittest.main()
