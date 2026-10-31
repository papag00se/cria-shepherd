"""A plan step must not carry its own step number — cria's framing states the position."""
import unittest

from cria.planner import _clean_step


class SelfNumberingTests(unittest.TestCase):
    """Measured on ada-handles_mellum2_codex_pon_1785625253 turn 0023. The plan's step 1 text was
    literally `**Step 1: Resolve a handle to its Cardano address.**`, and cria's framing wrapped it
    as "Do ONLY this step (2 of 6)". What the coder saw:

        Completed so far:
        1. Step 1: Resolve a handle to its Cardano address.
        Do ONLY this step (2 of 6), then stop: GET /holders/{address}...

    In its own words: "This is ambiguous... The 'Do ONLY this step (2 of 6)' is likely a copy-paste
    error in the prompt... Given the ambiguity, I should... ask for clarification." It spent the
    turn adjudicating cria's numbering instead of doing the step.
    """

    def test_the_real_step_from_that_run(self):
        self.assertEqual(_clean_step("**Step 1: Resolve a handle to its Cardano address.**"),
                         "Resolve a handle to its Cardano address.")

    def test_the_shapes_a_planner_writes(self):
        for raw, want in (("Step 2: GET /holders/{address}", "GET /holders/{address}"),
                          ("step 3 - write the tests", "write the tests"),
                          ("Step 10. Add the README", "Add the README"),
                          ("STEP 4) run nothing", "run nothing"),
                          ("**Step 7:** ship it", "ship it")):
            with self.subTest(raw=raw):
                self.assertEqual(_clean_step(raw), want)

    def test_the_existing_ordinal_strip_still_works(self):
        self.assertEqual(_clean_step("1. Write resolve_handle.py"), "Write resolve_handle.py")
        self.assertEqual(_clean_step("2) Add tests"), "Add tests")

    def test_a_step_that_merely_MENTIONS_a_step_is_untouched(self):
        # Only a LEADING self-number is stripped. "Write a counter that prints Step 1: done" is the
        # step's actual content and must survive intact — never block the first fix by eating text.
        for s in ("Write a step counter that prints Step 1: done",
                  "Document Step 2 of the install guide",
                  "Add a test for the step 3 branch"):
            with self.subTest(s=s):
                self.assertEqual(_clean_step(s), s)

    def test_legitimate_bold_is_not_mangled(self):
        self.assertEqual(_clean_step("Write **bold** text and more**"),
                         "Write **bold** text and more**")

    def test_an_ordinary_step_passes_through(self):
        s = "Write resolve_handle.py that accepts one argument: the Ada Handle"
        self.assertEqual(_clean_step(s), s)
