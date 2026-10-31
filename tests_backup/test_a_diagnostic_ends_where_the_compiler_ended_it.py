"""A checker's message reaches the coder whole — the structure ends it, not a count.

Three cuts sat between a checker and the coder, each one removing the half that says WHAT is wrong:

  * `_CONTINUATION_MAX = 6` cut a compiler diagnostic's indented detail after six lines. javac puts
    `symbol:` and `location:` AFTER a candidate list; rustc's `note:` runs go past six. The loop
    already ends on three structural boundaries — a blank line, a dedent to the header's level, and
    any line that is itself a diagnostic — and the third is what stops a stack trace, because its
    first frame carries a `file:line`. The count could only ever cut a diagnostic the structure said
    was still running.
  * `clip(msg, 200)` cut a test runner's assertion message, whose TAIL is where expected-vs-got
    lives. It was a bare slice, then a marked one.
  * `clip(text, 200)` cut the flagged source line quoted back to the coder — a quote that exists so
    the model does not GUESS the line.

Rule 5 as tightened on 2026-08-16 names per-line caps and disclosed elisions, and says a marked cut
is still a cut.
"""
import unittest

from cria import probeparse

JAVAC = """Importer.java:4: error: cannot find symbol
  symbol:   class CSVRecord
  location: package com.opencsv
  note: candidate one
  note: candidate two
  note: candidate three
  note: candidate four
  note: the seventh line, which the count used to remove
Importer.java:9: error: a second, separate problem
"""


class ADiagnosticEndsWhereTheCompilerEndedIt(unittest.TestCase):

    def test_the_detail_below_a_header_survives_past_six_lines(self):
        found = probeparse.parse_generic(JAVAC)
        self.assertEqual(2, len(found), "two headers, two findings")
        first = found[0].message
        self.assertIn("symbol:   class CSVRecord", first, "the line that names the class")
        self.assertIn("location: package com.opencsv", first, "the line that names the package")
        self.assertIn("the seventh line", first, "past the old count cap")

    def test_a_new_diagnostic_still_ends_the_previous_one(self):
        found = probeparse.parse_generic(JAVAC)
        self.assertNotIn("a second, separate problem", found[0].message,
                         "the next header ends the run — that is the structural boundary")
        self.assertEqual(9, found[1].line)

    def test_a_stack_trace_does_not_run_on_forever(self):
        """Every frame carries a file:line, so `split_diag` ends the continuation at the first."""
        trace = ("app.py:10: error: boom\n"
                 "  detail that belongs to it\n"
                 "  frame.py:22: in inner\n"
                 "  more.py:33: in outer\n")
        msg = probeparse.parse_generic(trace)[0].message
        self.assertIn("detail that belongs to it", msg)
        self.assertNotIn("more.py:33", msg)

    def test_no_count_cap_remains(self):
        self.assertFalse(hasattr(probeparse, "_CONTINUATION_MAX"),
                         "the structural boundary is the terminator; a count on top of it cut real detail")


if __name__ == "__main__":
    unittest.main()
