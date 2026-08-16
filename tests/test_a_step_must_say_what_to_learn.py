"""A reading step that names only a PLACE is refused.

`research_step.txt` asks for "one sentence naming that source **and** what task-specific names,
structures, or behavior must be learned from it". ternary-bonsai/go answered the bare string
`go.mod`, which every existing arm passes: it is not a build verb, not third person, not over-long,
not an echo of the instructions, and the task's own words contain `go.mod`, so the guessed-location
arm exempts it. It became "Do ONLY this step (1 of 2), then stop: go.mod" in 43 of 43 coder prompts.
The coder read that file 17 times, rewrote it 5 times, never once opened `cart_test.go`, and the
cell scored 1 of 5 on a workspace that was three edits from 4 of 5.

WHAT THIS IS NOT. It does not refuse a step for naming a file in the workspace. This module decided
the opposite deliberately: counting web fetches alone made the research check permanently NOT_DONE
for every task whose reading is local, which is the trap it exists to remove. A workspace file is a
legitimate source; a bare noun is not a step.
"""

import unittest

from cria.research import step_defect


GO_TASK = ("Fix the rounding bug. Stop using float64 for money. Add a third-party Go decimal "
           "module to go.mod and use it for cart calculations.")
RB_TASK = "Add `Shipping.zone_for(code)` for two-letter country codes."


class ABareLocationIsRefusedTests(unittest.TestCase):
    def test_the_measured_case(self):
        why = step_defect("go.mod", GO_TASK)
        self.assertIsNotNone(why)
        self.assertIn("nothing to learn", why)

    def test_any_bare_noun_however_spelled(self):
        for bare in ("cart.go", "Cargo.toml", "README", "src/main.rs", "pom.xml"):
            self.assertIsNotNone(step_defect(bare, GO_TASK), bare)

    def test_the_reason_is_plain_words_for_the_retry_to_quote(self):
        why = step_defect("go.mod", GO_TASK)
        self.assertNotIn("_", why)          # no identifiers
        self.assertLess(len(why), 200)


class ARealStepStillPassesTests(unittest.TestCase):
    def test_a_workspace_file_is_a_legitimate_source(self):
        """THE REGRESSION GUARD. Refusing local sources would revert this module's own decision."""
        self.assertIsNone(step_defect(
            "Read go.mod to learn the declared module path before changing imports.", GO_TASK))
        self.assertIsNone(step_defect(
            "Read cart_test.go to learn the exact values the existing tests assert.", GO_TASK))

    def test_an_external_source_still_passes(self):
        self.assertIsNone(step_defect(
            "Read the shopspring/decimal documentation to learn the constructor and rounding "
            "method names before converting the money arithmetic.", GO_TASK))

    def test_a_source_with_no_path_at_all_still_passes(self):
        self.assertIsNone(step_defect(
            "Read the countries gem documentation to learn the method that reports EU membership.",
            RB_TASK))


class TheOtherArmsAreUntouchedTests(unittest.TestCase):
    def test_a_build_verb_is_still_refused(self):
        self.assertIsNotNone(step_defect("Write the zone_for method and add tests for it.", RB_TASK))

    def test_third_person_is_still_refused(self):
        self.assertIsNotNone(step_defect(
            "Read the docs and instruct the coder to identify the rounding method.", GO_TASK))

    def test_a_guessed_location_is_still_refused(self):
        self.assertIsNotNone(step_defect(
            "Learn the API by fetching https://example.invalid/spec.json first.", RB_TASK))


if __name__ == "__main__":
    unittest.main()
