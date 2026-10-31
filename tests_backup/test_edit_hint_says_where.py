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

    def test_it_says_what_the_divergence_index_actually_proves(self):
        """This used to end "a line you remember that is not shown here is not in the file" — a claim
        about the WHOLE file inferred from a six-line window, and false whenever old_string is longer
        than the window. Walked on cycle 4 cell 4 (`feed-pipeline-java x gemma4`): the model's
        old_string was ~110 lines, its first forty matched the file exactly — that is what "first
        differs at LINE 41" means — and its opening line sat at line 21 of the file, remembered, not
        shown, and present. Told the opposite, it re-sent the byte-identical edit and the run ended.

        What the divergence index really proves is a prefix match, and saying that is both true and
        more useful: it tells the coder which part of its copy to keep."""
        r = self._rendered()
        self.assertIn("BEFORE line 22 matched the file exactly", r)
        self.assertNotIn("not shown here is not in the file", r)

    def test_it_still_hands_over_the_text_to_copy(self):
        r = self._rendered()
        self.assertIn("x := 1", r)
        self.assertIn("verbatim in old_string", r)

    def test_the_template_has_no_stray_tokens(self):
        self.assertNotIn("{{", self._rendered())


if __name__ == "__main__":
    unittest.main()
