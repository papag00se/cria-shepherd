"""cria named a Go module `github.com/arithmetic/decimal;` and told the coder to `go get` it.

`cart-billing-go x nemotron-elastic` 1787152914, scored 0%. Go's message reads

    no required module provides package github.com/arithmetic/decimal; to add it:
            go get github.com/arithmetic/decimal

and the semicolon is Go's sentence separator, not part of the name. The pattern's `\\S+` took it,
so the note cria appended to the checks — carried into six coder turns and echoed by four reasoner
directives — was:

    Note: no module in this project provides `github.com/arithmetic/decimal;`.
    `go get github.com/arithmetic/decimal;` records it in go.mod so the import resolves.

That command cannot work for ANY module, real or invented. cria composed a repair that was broken
before it was sent (#5b).

Trimmed for every ecosystem, not only Go: a package name never legitimately ends in a sentence
separator, and the next runtime to append one should not need its own fix (#20).
"""

import unittest

from cria import probeparse


class TheNameStopsWhereTheRuntimesSentenceDoesTests(unittest.TestCase):
    def test_the_measured_case(self):
        self.assertEqual(
            probeparse.dependency_missing(
                "cart.go:5:2: no required module provides package "
                "github.com/arithmetic/decimal; to add it:\n\tgo get github.com/arithmetic/decimal"),
            ("go", "github.com/arithmetic/decimal"))

    def test_a_message_with_no_separator_is_unchanged(self):
        self.assertEqual(
            probeparse.dependency_missing("no required module provides package example.com/x"),
            ("go", "example.com/x"))

    def test_every_other_ecosystem_still_parses_exactly(self):
        for text, want in (
                ("cannot load such file -- countries (LoadError)", ("ruby", "countries")),
                ("ModuleNotFoundError: No module named 'requests'", ("python", "requests")),
                ("Error: Cannot find module 'commander'", ("node", "commander")),
                ("error[E0463]: can't find crate for `toml`", ("rust", "toml"))):
            with self.subTest(text=text[:40]):
                self.assertEqual(probeparse.dependency_missing(text), want)

    def test_a_separator_from_any_runtime_is_trimmed(self):
        """Not keyed to Go's semicolon — the next runtime to punctuate gets it for free."""
        for tail in (";", ":", ",", ".", "'", '"', ")", "]", "}"):
            with self.subTest(tail=tail):
                got = probeparse.dependency_missing(
                    f"no required module provides package example.com/x{tail} to add it:")
                self.assertEqual(got, ("go", "example.com/x"))

    def test_the_note_built_from_it_names_a_runnable_command(self):
        eco, name = probeparse.dependency_missing(
            "no required module provides package github.com/x/y; to add it:")
        self.assertNotIn(";", name)
        self.assertNotIn(";", f"go get {name}")


if __name__ == "__main__":
    unittest.main()
