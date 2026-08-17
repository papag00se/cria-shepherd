"""cria told a coder, four times, to paste a version number it had made up.

Cycle 4 cell 20, `cart-billing-go × nemotron-elastic`, 1/5 strict and 15% useful. The repo's own
checks said, verbatim:

    cart.go:8: missing go.sum entry for module providing package
    github.com/shopspring/decimal (imported by cartsvc); to add:
            go get cartsvc

The steer author answered with a Go pseudo-version it invented — `v0.0.0-20240817123456-001`, whose
timestamp is the day the run happened — and made it the instruction:

    "Edit the line in go.mod that currently reads `require github.com/shopspring/decimal …` and
     replace it with the exact line `require github.com/shopspring/decimal v0.0.0-20240817123456-001`.
     After saving, run `go mod tidy`. Do this now with the edit_file tool."

Then it diagnosed its own defect and committed it again in the same directive: *"Stop editing go.mod
with invalid version strings … run `go get github.com/shopspring/decimal@v0.0.0-20240817123456`"*.
The coder obeyed, wrote pseudo-version after pseudo-version, and hit the wall with nothing that
compiles. The fix was one grounded word — `go get github.com/shopspring/decimal` — sitting in the
error message cria had already read.

A VERSION IS NOT A JUDGEMENT THE AUTHOR IS ENTITLED TO MAKE. It is a fact about a registry the author
cannot see, so #5b applies at full strength, and the grounding family already enforces exactly this
for URLs, paths, fields, symbols and line citations. This is the missing member.

Matched by SHAPE, not by ecosystem: a rule keyed to Go pseudo-versions is inert on npm, Maven and
RubyGems. Three-or-more dotted numbers, a `v`-prefixed number, or a version after `@`.

Blast radius, measured: of the **71 distinct steers cria delivered across cycle 4's 24 runs, 2
contain a version-shaped token at all**.
"""

import unittest

from cria import loop


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, name, **k):
        self.events.append((name, k))


GO_SUM_EVIDENCE = (
    "$ go vet ./... — cart.go:8: missing go.sum entry for module providing package "
    "github.com/shopspring/decimal (imported by cartsvc); to add:\n\tgo get cartsvc\n"
    "  the flagged line on disk — line 8: `\"github.com/shopspring/decimal\"`\n")


def steer(directive, evidence=GO_SUM_EVIDENCE):
    return loop._grounded_steer_or_none(directive, evidence, _Rlog(), sess=None, messages=[],
                                        workspace_root="")


class TheInventedVersionIsRefusedTests(unittest.TestCase):
    def test_the_directive_that_cost_the_cell(self):
        self.assertIsNone(steer(
            "Edit the line in go.mod that currently reads require github.com/shopspring/decimal "
            "and replace it with the exact line require github.com/shopspring/decimal "
            "v0.0.0-20240817123456-001 . After saving, run go mod tidy to make the go.sum entry "
            "appear. Do this now with the edit_file tool."))

    def test_the_one_that_diagnosed_itself_and_did_it_anyway(self):
        self.assertIsNone(steer(
            "Stop editing go.mod with invalid version strings. Resolve it by running "
            "go get github.com/shopspring/decimal@v0.0.0-20240817123456 and then update go.mod."))

    def test_the_hedged_example_form(self):
        """`(e.g., v0.0.0-…)` is the same fabrication wearing a hedge; the coder pasted it verbatim."""
        self.assertIsNone(steer(
            "Edit go.mod to add the required require github.com/shopspring/decimal line with a "
            "version that matches the format shown in the error (e.g., v0.0.0-20240817123456-001 ), "
            "then run go mod tidy."))

    def test_it_is_reported_by_name(self):
        rlog = _Rlog()
        loop._grounded_steer_or_none("Pin it to v2.7.1 in package.json.", GO_SUM_EVIDENCE, rlog,
                                     sess=None, messages=[], workspace_root="")
        self.assertIn("loop.steer_invented_version", [n for n, _ in rlog.events])


class TheGroundedAnswerSurvivesTests(unittest.TestCase):
    def test_the_real_fix_is_delivered(self):
        """One grounded word. If the guard refused this too it would be worse than the defect."""
        self.assertIsNotNone(steer(
            "Run go get github.com/shopspring/decimal, then go mod tidy, then go test."))

    def test_a_version_the_evidence_reported_may_be_quoted(self):
        """Quoting what the checks, the disk or the transcript said is the only way an author should
        ever have a version — and it must keep working."""
        ev = GO_SUM_EVIDENCE + "\n$ go list -m all — github.com/shopspring/decimal v1.4.0\n"
        self.assertIsNotNone(steer(
            "go.mod must require github.com/shopspring/decimal v1.4.0 — add that line.", ev))

    def test_ordinary_numbers_are_not_versions(self):
        for d in ("The cart total is 48.58 but your code prints 44.98 — fix the tax rounding.",
                  "cart.go:90 declares axed; line 91 uses taxed. Fix the name.",
                  "The suite ran 7 tests in 0.42 seconds with 3 failures."):
            with self.subTest(directive=d[:40]):
                self.assertIsNotNone(steer(d), d)

    def test_a_two_part_number_is_not_a_version(self):
        """`3.11` is a language line and `48.58` is money; neither is pasted into a manifest."""
        self.assertIsNone(loop._invented_version("Use Python 3.11 for this.", ""))


class TheShapeIsNotOneEcosystemTests(unittest.TestCase):
    def test_every_registry_writes_the_same_shape(self):
        for tok, d in (("v0.0.0-20240817123456-001", "require x v0.0.0-20240817123456-001"),
                       ("1.4.0", 'gem "countries", "1.4.0"'),
                       ("v2.7.1", "npm install left-pad@v2.7.1"),
                       ("4.10.0", "<version>4.10.0</version>"),
                       ("3.1.4", "cargo add toml@3.1.4")):
            with self.subTest(token=tok):
                self.assertEqual(loop._invented_version(d, "no versions here"), tok)

    def test_nothing_fires_on_an_empty_directive(self):
        self.assertIsNone(loop._invented_version("", "x"))
        self.assertIsNone(loop._invented_version(None, "x"))


class ItIsPartOfTheGroundingFamilyTests(unittest.TestCase):
    def test_it_runs_inside_the_one_grounding_gate(self):
        """Every steer path funnels through `_grounded_steer_or_none`; adding the check anywhere else
        would give one door a rule the others lack (#23)."""
        import inspect
        self.assertIn("_invented_version(directive, evidence)",
                      inspect.getsource(loop._grounded_steer_or_none))

    def test_it_returns_a_safe_null_not_a_reworded_steer(self):
        """#4: no fallback. The version IS the instruction, so a directive with it stripped out says
        nothing useful."""
        self.assertIsNone(steer("Set it to v9.9.9 and rebuild."))


if __name__ == "__main__":
    unittest.main()
