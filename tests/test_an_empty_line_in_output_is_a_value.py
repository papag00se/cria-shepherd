"""cria deleted the one byte that named the bug, then a reasoner concluded the opposite.

`shipping-rates-rb x ternary-bonsai` 1787111689 — the single probe in the whole run that answered
the question. The coder ran:

    bundle exec ruby -e "require 'countries'; c = ISO3166::Country.new('FR');
                         puts c.data[:eu_member]; puts c.name"

and the harness returned:

    Chunk ID: 2abf9d
    Wall time: 0.0000 seconds
    Process exited with code 0
    Original token count: 2
    Output:

    France

**The blank line before `France` IS the bug.** `data` is string-keyed, so `[:eu_member]` is `nil` and
`puts nil` prints an empty line. Two `puts`, one visible answer: the first one printed nothing.

The session digest handed to the steer author rendered that entire call as:

    → exit 0: France

`_defanged_line` ran the envelope regex over the whole result and `.strip()`ed what was left, which
deletes a leading blank line. The author then reasoned — in its own words — *"the country lookup
works fine in isolation, but something's wrong when it runs inside the test suite"*, and steered the
coder at `shipping_cost` instead. The run ended 3/5 with the real defect untouched.

The fix anchors on the harness's own `Output:` marker: everything after it is the program speaking,
byte for byte, and only the envelope's final newline is dropped. An empty line in stdout is a value
(#5 — never destroy information the model relies on).
"""

import unittest

from cria import selfcompact


def tool(text):
    return {"role": "tool", "content": text}


MEASURED = ("Chunk ID: 2abf9d\nWall time: 0.0000 seconds\nProcess exited with code 0\n"
            "Original token count: 2\nOutput:\n\nFrance")


class TheMeasuredProbeTests(unittest.TestCase):
    def test_the_blank_line_survives(self):
        line = selfcompact._defanged_line(tool(MEASURED))
        self.assertEqual(line, "→ exit 0: \nFrance")
        self.assertNotEqual(line, "→ exit 0: France", "the nil print was deleted again")

    def test_the_exit_code_is_still_stated(self):
        self.assertTrue(selfcompact._defanged_line(tool(MEASURED)).startswith("→ exit 0:"))

    def test_a_trailing_blank_line_survives_too(self):
        line = selfcompact._defanged_line(tool("Process exited with code 0\nOutput:\nA\n\nB\n"))
        self.assertIn("A\n\nB", line)


class OrdinaryOutputIsUnchangedTests(unittest.TestCase):
    def test_a_one_line_result_reads_the_same_as_before(self):
        self.assertEqual(selfcompact._defanged_line(
            tool("Chunk ID: x\nProcess exited with code 1\nOutput:\nboom\n")), "→ exit 1: boom")

    def test_the_envelope_itself_is_never_quoted_back(self):
        """The envelope is the shape a model copies when it fabricates a result — it stays out."""
        line = selfcompact._defanged_line(tool(MEASURED))
        for leak in ("Chunk ID", "Wall time", "Original token count", "Process exited with code"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, line)

    def test_a_result_with_no_envelope_still_cleans(self):
        self.assertEqual(selfcompact._defanged_line(tool("  plain result  ")), "→ result: plain result")

    def test_an_empty_result_says_only_that_it_is_a_result(self):
        self.assertEqual(selfcompact._defanged_line(tool("Output:\n")), "→ result")


class ItAnchorsOnTheMarkerNotTheRegexTests(unittest.TestCase):
    def test_output_after_the_marker_is_passed_through_untouched(self):
        """Once `Output:` is found the program's own text is never re-processed — a program that
        prints something envelope-shaped keeps it."""
        line = selfcompact._defanged_line(
            tool("Process exited with code 0\nOutput:\nWall time: 3s per the app's own log\n"))
        self.assertIn("Wall time: 3s per the app's own log", line)


if __name__ == "__main__":
    unittest.main()
