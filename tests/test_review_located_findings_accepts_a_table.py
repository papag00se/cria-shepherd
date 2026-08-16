"""A located finding is a file and a line near each other, however the reviewer laid it out.

The incident (cycle 2, feed-pipeline-java x ternary-bonsai): 729 words of findings in a proper
`| File | Line(s) | Before | After |` table scored **0 located findings** and lost the check. Between
`.java` and the number sit a backtick, a space, a pipe, a space and a tilde — five non-word
characters against a window of four. The model wrote the location down in the most natural way a
markdown document offers and the matcher missed it by one character.

The verifier's own comment two lines above the pattern names this failure class: "a correctly located
finding scored as unlocated because of how the reviewer punctuated it... assert the property the task
names, nothing adjacent." The task asks for a file name and a line number. It does not say how to
punctuate one.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1] / "suite"
VERIFY = SUITE / "tasks" / "feed-pipeline-java" / "verify.py"


def located(text: str) -> list[str]:
    """The verifier's own pattern, lifted from its source so this test cannot drift from it."""
    src = VERIFY.read_text()
    start = src.index("located = re.findall(")
    body = src[start:src.index("rtext, re.I)", start)]
    parts = re.findall(r'r"((?:[^"\\]|\\.)*)"', body)
    return re.findall("".join(parts), text, re.I)


class ALocationIsALocationHoweverItIsWritten(unittest.TestCase):
    TABLE = (
        "| File | Line(s) | Before | After |\n"
        "|---|---|---|---|\n"
        "| `src/main/java/pipeline/Importer.java` | ~45–50 | ArrayList.contains | HashSet |\n"
        "| `src/main/java/pipeline/Importer.java` | ~30–45 | shared mutable state | ConcurrentHashMap |\n"
    )

    def test_a_markdown_table_counts(self):
        """FAILS BEFORE: the window was four non-word characters and a table cell needs five."""
        self.assertGreaterEqual(len(located(self.TABLE)), 2)

    def test_the_shapes_that_already_worked_still_do(self):
        for text in ("Importer.java:31 leaks a handle",
                     "`Importer.java` (31) is O(n^2)",
                     "Importer.java, on line 31",
                     "Lines 31-33 of Importer.java are racy",
                     "See line 96 for the typo"):
            with self.subTest(text=text):
                self.assertTrue(located(text), f"regressed on: {text}")

    def test_prose_with_no_location_still_scores_nothing(self):
        """The check must still be able to fail. nemotron-elastic's 419-word review has no located
        finding under the old window or the new one, and stays correctly at zero."""
        self.assertEqual([], located(
            "The importer is slow and the threading is unsafe. The CSV parsing should use a library. "
            "There are risks around malformed input handling and the summary API."))

    def test_the_window_cannot_reach_across_a_table_row(self):
        """A wider window must not pair a filename with some OTHER row's number. A cell's own text
        sits between them, so 24 non-word characters cannot span it."""
        two_rows = ("| `Alpha.java` | some prose describing the issue at length here |\n"
                    "| `Beta.java`  | 77 |\n")
        hits = located(two_rows)
        self.assertTrue(all("Alpha" not in h for h in hits), f"reached across a row: {hits}")


if __name__ == "__main__":
    unittest.main()
