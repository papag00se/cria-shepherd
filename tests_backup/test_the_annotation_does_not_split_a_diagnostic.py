"""cria's annotation goes after the checker's whole message, never into the middle of it.

The gate's findings list is one entry per LINE, and a compiler's diagnostic spans several: Go prints
`have (int)` / `want (string)` under its error, javac prints `symbol:` and `location:`. The flagged-
line quote was appended right after the first line, so cria's sentence landed between the error and
the rest of its own explanation — 132 times in one run, under a header that reads "each is the
checker's OWN message"."""
import os
import tempfile
import unittest

from cria import probegate


class _Plan:
    def __init__(self, workspace):
        self.workspace = workspace


class TheDiagnosticStaysWholeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "main.go"), "w") as f:
            f.write("package main\n\nfunc main() {\n\tfoo(1)\n}\n")

    def test_the_quote_follows_the_continuation_lines(self):
        findings = ["main.go:4:2: not enough arguments in call to foo",
                    "\thave (number)",
                    "\twant (number, string)"]
        out = probegate._with_delimiter_facts(findings, _Plan(self.dir))
        heads = [i for i, l in enumerate(out) if l.startswith("  the flagged line")]
        self.assertEqual(len(heads), 1, out)
        quote_at = heads[0]
        self.assertEqual(out[:quote_at], findings)      # the checker's message, in one piece
        self.assertEqual(quote_at, len(findings))       # cria's line comes after all of it

    def test_a_continuation_line_is_never_annotated_on_its_own(self):
        findings = ["main.go:4:2: not enough arguments in call to foo", "\thave (number)"]
        out = probegate._with_delimiter_facts(findings, _Plan(self.dir))
        self.assertLessEqual(sum(1 for l in out if l.startswith("  the flagged line")), 1)

    def test_two_separate_diagnostics_each_keep_their_own(self):
        findings = ["main.go:4:2: first", "main.go:5:1: second"]
        out = probegate._with_delimiter_facts(findings, _Plan(self.dir))
        self.assertEqual([l for l in out if not l.startswith("  ")], findings)


if __name__ == "__main__":
    unittest.main()
