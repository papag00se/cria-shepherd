"""A search that matched nothing is a FACT about the world, not a command that failed.

`grep` exits 1 and prints nothing when the string is not there, and the harness envelope renders that
as `Process exited with code 1 / Output:` with a blank beneath it — indistinguishable, to a reader,
from a command that could not run.

Walked on cart-billing-go x nemotron-elastic 1787434778. The coder grepped the decimal library for
`Quantize` six times, got the blank each time, and read it as "the command did not work" rather than
"the method does not exist" — which was the entire question of the run. Its own reasoning at 0072:
"Yes, they have a Quantize method … But in our fetch we didn't see that snippet; maybe it's later in
the file." The answer (`func (d Decimal) Round`) was in a file in its own workspace all run."""
import unittest

from cria import writeproxy

ENV = "Chunk ID: 7f3\nWall time: 0.01 seconds\nProcess exited with code 1\nOutput:\n\n"


class AnEmptyResultSpeaksTests(unittest.TestCase):
    def test_a_grep_with_no_match_is_recognised(self):
        self.assertTrue(writeproxy._found_nothing('grep -n "Quantize" decimal.go', ENV))

    def test_a_grep_that_could_not_read_the_path_is_not(self):
        """Exit 2 is a real error and carries its own message; only 1 means 'no match'."""
        self.assertFalse(writeproxy._found_nothing('grep -n "x" nope.go', ENV.replace("code 1", "code 2")))

    def test_a_grep_that_matched_is_not(self):
        self.assertFalse(writeproxy._found_nothing('grep -n "x" a.go', ENV + "12: x here\n"))

    def test_the_models_own_filter_pipe_belongs_to_the_other_guard(self):
        self.assertFalse(writeproxy._found_nothing('pytest -q | grep -E "passed|failed"', ENV))

    def test_an_ordinary_command_is_untouched(self):
        self.assertFalse(writeproxy._found_nothing("go build ./...", ENV))

    def test_the_note_says_it_is_evidence_of_absence(self):
        from cria import prompts
        note = prompts.load("search_found_nothing")
        self.assertIn("matched nothing", note)
        self.assertIn("not a failed command", note)
        self.assertNotIn("cria", note.lower())


if __name__ == "__main__":
    unittest.main()
