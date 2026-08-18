'''cria refused a file write with the message `:36: s`.

`shipping-rates-rb x ternary-bonsai`, 2026-08-17, call 0026. The coder had just written a complete
implementation — the threshold fix, the `express` zone, the rate table, `zone_for`, country-code
dispatch, all five changes, 2,025 characters. cria's validate-before-write ran `ruby -c` on it,
correctly found it did not parse, and reported:

    write_file REFUSED (not written): this would replace a currently-valid rates.rb with content
    that does not parse - /tmp/suite-.../lib/shipping/rates.rb: /tmp/suite-.../lib/shipping/rates.rb:36: s

The real error was `syntax error, unexpected '(', expecting 'end'` at `ISO3166::Country[]("#{code}")`.

REPRODUCED BYTE-EXACT. The validator wrote the content to a temp file, ran the checker on it,
substituted the REAL workspace path back in, and only then cut: `_msg.splitlines()[0][:200]`.
`ruby -c` prints the path TWICE on line one, and a suite workspace path is 96 characters:

    before substitution   44 chars of path   156 left for the message
    after  substitution  198 chars of path     2 left for the message

So the cap was never the size the message needed. The substitution inflated the string four and a
half times and the cap then cut the half carrying the diagnosis. Two truncations were stacked: the
`splitlines()[0]` also threw away the offending source line and the caret, which are two thirds of
what makes a syntax error actionable, before the character budget even ran (#5 names both shapes —
"per-line caps, character budgets").

The coder cannot re-read its own rejected payload; cria elides it as `[2025 characters - this edit
was REJECTED]`. So a coordinate with no message pointed at nothing. Its next write dropped `express`,
the rate table and the dispatch, and they were never recovered in the run's remaining 17 calls.

THE PATH IS THE ONE PART THAT CARRIES NO INFORMATION — the coder knows which file it just tried to
write. Stripping it rather than substituting it leaves the whole diagnostic inside any budget.

ALSO FIXED HERE: `_at`, the helper that quotes the offending source line back, matched
`line\\s+(\\d+)` only. Python's `compile()` and an XML parser say "line 34, column 1" — the run this
helper was written for. Ruby says `rates.rb:36:`, and so do `node --check`, `php -l` and `gofmt -e`.
It abstained SILENTLY on four of the six languages the validator beside it covers, which is worse
than absent: it looks present (#20).
'''

import unittest

from cria import writeproxy

RB_BAD = ('module Shipping\n'
          '  def self.zone_for(code)\n'
          '    country = ISO3166::Country[]("#{code}")\n'
          '  end\n'
          'end\n')
# The real workspace path from the walked run — 96 characters, which is the whole point.
WS = "/tmp/suite-shipping-rates-rb_ternary-bonsai_codex_poff_1787012069-kk9cedw4/lib/shipping/rates.rb"


def _validator():
    """`_v` and `_at` as they really ship — the whole validator source executed as the harness
    executes it, imports, `_EXT_CMD` and all. Testing a copy of this logic would test the copy."""
    ns = {}
    exec(writeproxy._VALIDATE_FN, ns)
    return ns


class TheDiagnosticSurvivesTheRefusalTests(unittest.TestCase):
    def setUp(self):
        self.ns = _validator()
        if not __import__("shutil").which("ruby"):
            self.skipTest("ruby is not installed on this machine")

    def test_the_measured_refusal_now_says_what_is_wrong(self):
        msg = self.ns["_v"](WS, RB_BAD)
        self.assertIn("syntax error", msg)
        self.assertIn("unexpected", msg)

    def test_the_caret_line_survives(self):
        """`splitlines()[0]` threw away the two lines that locate the fault in the text."""
        self.assertIn("^", self.ns["_v"](WS, RB_BAD))

    def test_the_workspace_path_is_not_reprinted_at_all(self):
        """It is what ate the budget, and the coder already knows which file it wrote."""
        msg = self.ns["_v"](WS, RB_BAD)
        self.assertNotIn("/tmp/suite-", msg)
        self.assertIn("rates.rb:", msg)          # the coordinate is still there

    def test_a_long_workspace_path_cannot_crowd_the_message_out(self):
        """The regression in one assertion: the same content under a 300-character path."""
        deep = "/tmp/" + "d" * 240 + "/lib/shipping/rates.rb"
        self.assertIn("syntax error", self.ns["_v"](deep, RB_BAD))

    def test_valid_content_is_still_accepted(self):
        self.assertIsNone(self.ns["_v"](WS, "module Shipping\nend\n"))


class TheQuotedLineReachesEveryCheckerTests(unittest.TestCase):
    def setUp(self):
        self.ns = _validator()

    def test_the_colon_shape_is_matched_now(self):
        """`rates.rb:3:` — ruby, node, php, gofmt. Silently unmatched before."""
        said = self.ns["_at"](RB_BAD, "rates.rb:3: syntax error, unexpected '('")
        self.assertIn("Line 3", said)
        self.assertIn("ISO3166::Country", said)

    def test_the_word_shape_still_matches(self):
        """Python and XML. The case this helper was written for must not regress."""
        said = self.ns["_at"](RB_BAD, "not well-formed (invalid token): line 2, column 1")
        self.assertIn("Line 2", said)
        self.assertIn("def self.zone_for", said)

    def test_the_quoted_line_is_not_clipped(self):
        """A cap here cuts the long line most likely to BE the fault."""
        long_line = "x = " + "a" * 500 + "\n"
        said = self.ns["_at"](long_line, "f.rb:1: syntax error")
        self.assertIn("a" * 500, said)

    def test_a_message_with_no_coordinate_adds_nothing(self):
        self.assertEqual(self.ns["_at"](RB_BAD, "something went wrong"), "")

    def test_a_coordinate_past_the_end_adds_nothing(self):
        """#5b: a message that cannot name a line must not print one."""
        self.assertEqual(self.ns["_at"](RB_BAD, "f.rb:99: syntax error"), "")

    def test_every_checker_the_validator_runs_can_be_quoted(self):
        """The gap this closes: the validator covers six extensions and the quoter covered two."""
        for shape in ("f.rb:3: syntax error", "f.js:3", "in f.php on line 3",
                      "f.go:3:5: expected ';'", "line 3, column 1"):
            with self.subTest(shape=shape):
                self.assertIn("Line 3", self.ns["_at"](RB_BAD, shape))


if __name__ == "__main__":
    unittest.main()
