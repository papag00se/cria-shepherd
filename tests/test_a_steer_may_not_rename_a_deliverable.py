"""cria's steer told the coder to create `data/review.md`. The check wants `REVIEW.md`.

`feed-pipeline-java x qwen35`, cycle 1 of the 100% campaign, authored at call 0109:

    …the threading section of the code to understand what needs to be fixed. After that,
    create data/review.md

The task says `REVIEW.md`. `verify.py:190` finds it with `rglob("REVIEW.md")` — case-sensitive, so
`data/review.md` matches nothing at any depth. One of five checks, lost to a filename.

The steer author is ALREADY forbidden from doing this. Its own prompt reads: *"Do not choose the
IMPLEMENTATION. Which library to use, which data structure, which flag, which output format, which
file to create — those belong to the TASK or to the coder, never to you."* It did it anyway, which
is what a prompt is: a request, not an enforcement.

So this joins the family that enforces the other half of that prompt — `_phantom_system_path`,
`_symbol_not_in_the_file`, `_false_line_citation`, `_field_the_ledger_denies`. Every one of them is
the same shape: cria holds both strings, so the check is exact rather than judged, and a steer that
contradicts what cria holds is REFUSED rather than reworded. Rewording would be cria picking the
filename, which is the thing being prevented.

Deliberately narrow. Only a basename the TASK ITSELF wrote is checkable — cria compares two strings
it was given and never guesses what a deliverable should be called. A file the task never mentions
passes silently (#3), because the coder may legitimately create scratch files of its own.
"""

import unittest

from cria import loop


def task(text: str) -> list:
    return [{"role": "user", "content": text}]


JAVA = task("Add REVIEW.md describing remaining problems or risks in the code you changed. "
            "For every issue, include the file name and line number.")


class TheMeasuredCaseTests(unittest.TestCase):
    def test_the_directive_that_cost_the_check_is_caught(self):
        self.assertEqual(
            loop._task_named_it_differently(
                "Read the threading section to understand what needs to be fixed. "
                "After that, create data/review.md", JAVA),
            "data/review.md vs REVIEW.md")

    def test_a_bare_case_change_is_caught_too(self):
        self.assertTrue(loop._task_named_it_differently("Create readme.md at the root", 
                                                        task("Add a README.md rate table")))


class WhatMustPassSilentlyTests(unittest.TestCase):
    def test_the_right_filename_is_not_flagged(self):
        self.assertEqual(loop._task_named_it_differently("Create REVIEW.md with the findings", JAVA), "")

    def test_a_file_the_task_never_named_is_the_coders_business(self):
        self.assertEqual(loop._task_named_it_differently("Write a scratch file notes.txt first", JAVA), "")

    def test_merely_mentioning_the_file_is_not_creating_it(self):
        """"Check REVIEW.md" is a reference, not a rename."""
        self.assertEqual(loop._task_named_it_differently("Check whether docs/review.md is stale", JAVA), "")

    def test_no_task_text_checks_nothing(self):
        self.assertEqual(loop._task_named_it_differently("create data/review.md", []), "")

    def test_an_empty_directive_checks_nothing(self):
        self.assertEqual(loop._task_named_it_differently("", JAVA), "")


class ItRefusesRatherThanRewordsTests(unittest.TestCase):
    """Correcting the path would be cria choosing the filename — the exact act being prevented."""

    def test_the_steer_is_dropped_whole(self):
        seen = []

        class Rlog:
            def emit(self, kind, **kw):
                seen.append((kind, kw))

        out = loop._grounded_steer_or_none(
            "Fix the threading bug. After that, create data/review.md", "", Rlog(), messages=JAVA)
        self.assertIsNone(out)
        self.assertIn("loop.steer_renamed_deliverable", [k for k, _ in seen])

    def test_a_clean_steer_still_ships(self):
        class Rlog:
            def emit(self, kind, **kw):
                pass

        out = loop._grounded_steer_or_none(
            "The importer drops rows with a quoted comma. Make those rows parse.", "", Rlog(),
            messages=JAVA)
        self.assertIn("quoted comma", out or "")


if __name__ == "__main__":
    unittest.main()
