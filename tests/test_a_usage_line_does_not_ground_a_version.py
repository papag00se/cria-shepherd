"""A tool printing the SHAPE of an argument has not told cria a version exists.

Walked on the sub-40 pass: cart-billing-go x nemotron-elastic, scored 27. `go build` answered a
malformed manifest with its own synopsis —

    go: errors parsing go.mod:
    go.mod:4:5: usage: require module/path v1.2.3

— cria's steer at call 0091 quoted that line back at the coder as the format to use, and the coder
wrote `v1.2.3` into go.mod. `_invented_version` is the guard for exactly this class and it passed
the steer, because its grounding test was "the token appears in the evidence" and the token did.

`v1.2.3` stands in for a version the same way `module/path` stands in for a module. The fix keeps
the grounding rule (#5b — the exact token must have been observed) and takes away the one kind of
line where a tool is describing its own syntax rather than reporting a fact about the repo.
"""

import unittest

from cria.loop import _grounds_a_version, _invented_version


USAGE = "go: errors parsing go.mod:\ngo.mod:4:5: usage: require module/path v1.2.3\n"


class TheSynopsisIsNotEvidenceTests(unittest.TestCase):
    def test_the_measured_case(self):
        directive = "Fix go.mod line 4 — the go.mod requires the correct format: `require module/path v1.2.3`."
        self.assertEqual(_invented_version(directive, USAGE), "v1.2.3")

    def test_a_version_something_reported_still_grounds(self):
        ev = "go.sum: github.com/shopspring/decimal v1.4.0 h1:...\n"
        self.assertIsNone(_invented_version("pin decimal at v1.4.0", ev))

    def test_one_real_appearance_is_enough(self):
        """The rule takes away a LINE, not a token. A version named both in a synopsis and in a real
        report is still grounded."""
        self.assertTrue(_grounds_a_version("v1.2.3", USAGE + "found v1.2.3 in the module cache\n"))

    def test_it_is_not_written_for_go(self):
        """Every CLI answers a bad argument with its own synopsis, and they all spell it the same
        way (#20)."""
        for line in ("Usage: pip install package==1.2.3",
                     "usage: npm install <pkg>@1.2.3",
                     "  SYNOPSIS: gem install NAME -v 1.2.3",
                     "error (usage: cargo add crate@1.2.3)"):
            with self.subTest(line=line):
                self.assertFalse(_grounds_a_version("1.2.3", line))

    def test_a_word_containing_usage_is_not_a_synopsis(self):
        for line in ("disk usage 1.2.3 GB high", "MemoryUsage: 1.2.3"):
            with self.subTest(line=line):
                self.assertTrue(_grounds_a_version("1.2.3", line))


if __name__ == "__main__":
    unittest.main()
