"""Two things `_invented_code_spans` counted as invented code, and neither is code.

Walked on the sub-40 pass: feed-pipeline-java x nemotron-elastic, scored 16. cria's reasoner wrote
the one correct directive of the run —

    "Delete the five lines in Importer.load() that call builder.setIgnoreQuotes(false),
     builder.setEscapeCharacter('\\'), builder.setTrimLeadingWhiteSpace(true), … "

— the count came back 2, the restater's rewrite was refused with it, and the coder never got the
fix. Applied by hand to a copy of the shipped tree, all five `cannot find symbol` errors disappear.

The 2 were:

* `Importer.load()` — empty parens. It hands the coder nothing to paste; it says WHERE, the way a
  file path does. A directive is entitled to name the method it is talking about.
* `builder.setEscapeCharacter('\\')` — the same call that is on disk with one character of escaping
  different. Re-typing a line it read is not inventing one.

Both are about the CONTRACT of the count, not about Java: it exists to catch a steer handing over
code the author never saw, and neither of these is that.
"""

import unittest

from cria.loop import _invented_code_spans


ON_DISK = ("CSVReaderBuilder builder = new CSVReaderBuilder(reader);\n"
           "builder.setEscapeCharacter('\\\\');\n"
           "public void load(Path p) throws IOException { }\n")


class ANameIsNotCodeTests(unittest.TestCase):
    def test_an_empty_call_is_a_location(self):
        self.assertEqual(_invented_code_spans("Start from Importer.load() and read down.", ON_DISK), 0)

    def test_a_call_with_arguments_is_still_checked(self):
        """The arguments are the part that can be invented, so the check keeps them."""
        self.assertEqual(
            _invented_code_spans('Call pytest.register_pytest_mark("live") first.', ON_DISK), 1)


class EscapingIsNotContentTests(unittest.TestCase):
    def test_one_character_of_escaping_is_not_an_invention(self):
        d = "Delete the line that calls builder.setEscapeCharacter('\\')."
        self.assertEqual(_invented_code_spans(d, ON_DISK), 0)

    def test_a_different_argument_is_still_an_invention(self):
        """Only quote characters and backslashes are taken out — what is INSIDE them still counts."""
        d = "Add builder.setEscapeCharacter('#') to the builder."
        self.assertEqual(_invented_code_spans(d, ON_DISK), 1)


class TheWalkedDirectiveShipsTests(unittest.TestCase):
    def test_the_measured_directive_counts_only_what_it_invented(self):
        d = ("Delete the five lines in Importer.load() that call builder.setIgnoreQuotes(false), "
             "builder.setEscapeCharacter('\\'), builder.setTrimLeadingWhiteSpace(true), "
             "builder.setTrimTrailingWhiteSpace(true), and builder.setSkipHeader(false).")
        # The four `set…` calls that are NOT on disk are exactly what the directive says to delete,
        # and they are quoted from the compiler's own rejection — the count over THIS fixture sees
        # only what the fixture withholds.
        self.assertEqual(_invented_code_spans(d, ON_DISK + "\n".join(
            ["builder.setIgnoreQuotes(false);", "builder.setTrimLeadingWhiteSpace(true);",
             "builder.setTrimTrailingWhiteSpace(true);", "builder.setSkipHeader(false);"])), 0)


if __name__ == "__main__":
    unittest.main()
