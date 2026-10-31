""""Your dependency is not loadable" and "your code is wrong" look identical to a weak model.

Measured on the six-language battery: 39 of 73 dependency-shaped checks failed, and 8 of those had
the dependency DECLARED correctly and simply not reachable. The cost is not a wasted call, it is the
rest of the run — gemma4's ruby run installed two gems, `require` failed, three checks that had been
passing went red, and it spent the remaining twenty minutes on the package manager.

cria's gate has probe rows for test, lint, syntax, typecheck and build, and nothing that says "this
one is a dependency". So an unresolved import arrives as a stack trace or a compile error and reads
as broken code.

Every ecosystem states it plainly in its own words, so this CLASSIFIES the tool's own error class
(#12) rather than guessing at prose, and only where the message can mean nothing else. "package X
does not exist" is deliberately absent — it is equally a typo in the project's own code, and
mislabelling a real bug is the expensive direction (#3).

The checker's line is untouched and still shown above the note. cria may select a checker's real
lines and add its own fact beside them, never substitute its own words for them.
"""

import pathlib
import tempfile
import unittest

from cria import probeparse, proberun, prompts
from cria.probeparse import Finding, ProbeResult


def report(*summaries: str) -> proberun.ProbeReport:
    return proberun.ProbeReport(
        project_type=[], selected=[],
        results=[ProbeResult(command="check", exit_code=1, summary=s) for s in summaries])


# What each tool actually prints, verbatim in shape.
REAL_OUTPUT = {
    "ruby": ("cannot load such file -- countries (LoadError)", "countries"),
    "python": ("ModuleNotFoundError: No module named 'requests'", "requests"),
    "node": ("Error: Cannot find module 'commander'", "commander"),
    "rust": ("error[E0463]: can't find crate for `toml`", "toml"),
    "go": ("no required module provides package github.com/shopspring/decimal",
           "github.com/shopspring/decimal"),
    "java": ("Could not resolve dependencies for project x: org.apache.commons:commons-csv:jar:1.10.0",
             "org.apache.commons:commons-csv:jar:1.10.0"),
}


class EveryEcosystemIsRecognisedTests(unittest.TestCase):
    def test_the_tool_output_is_classified_and_the_name_extracted(self):
        for eco, (line, name) in REAL_OUTPUT.items():
            with self.subTest(ecosystem=eco):
                self.assertEqual(probeparse.dependency_missing(line), (eco, name))

    def test_each_one_produces_a_note_naming_it(self):
        for eco, (line, name) in REAL_OUTPUT.items():
            with self.subTest(ecosystem=eco):
                note = proberun.dependency_note(report(f"exited 1: {line}"))
                self.assertIn(name, note)
                # It must still steer away from the call site — but only where that is true. The
                # note now names BOTH branches, because cria cannot tell an undeclared real
                # dependency from an invented name, and asserting the first cost a whole go cell.
                # BOTH BRANCHES, whatever the ecosystem calls the first one ("the dependency",
                # "the loading"). cria cannot tell an undeclared real dependency from an invented
                # name, and asserting the first as fact cost a whole go cell.
                self.assertIn("not the code that uses it", note)
                self.assertIn("the fix is the name", note)

    def test_every_ecosystem_has_a_note_and_none_is_a_hole(self):
        notes = prompts.load_map("dependency_note")
        for eco, _ in probeparse._DEPENDENCY_MISSING:
            with self.subTest(ecosystem=eco):
                self.assertTrue(notes.get(eco, "").strip())

    def test_the_note_says_where_that_ecosystem_looks(self):
        """"Install it" was never the missing step — every one of these had it installed."""
        notes = prompts.load_map("dependency_note")
        for eco, marker in (("ruby", "load path"), ("python", "interpreter"),
                            ("node", "node_modules"), ("rust", "Cargo.toml"),
                            ("go", "go.mod"), ("java", "pom.xml")):
            with self.subTest(ecosystem=eco):
                self.assertIn(marker, notes[eco])


class ItStaysSilentWhenItCannotBeSureTests(unittest.TestCase):
    def test_an_ordinary_compile_error_gets_nothing(self):
        self.assertEqual(proberun.dependency_note(report("exited 1: cart.go:12:2: undefined: foo")), "")

    def test_a_failing_assertion_gets_nothing(self):
        self.assertEqual(
            proberun.dependency_note(report("test_rates.rb:15: Expected: 0.0 Actual: 7.24")), "")

    def test_a_clean_report_gets_nothing(self):
        self.assertEqual(proberun.dependency_note(report()), "")

    def test_the_ambiguous_java_message_is_deliberately_not_matched(self):
        """"package X does not exist" is equally a typo in the project's own code."""
        self.assertIsNone(probeparse.dependency_missing(
            "Importer.java:[3,26] package org.apache.commons.csv does not exist"))

    def test_the_projects_own_module_is_not_called_a_dependency(self):
        """A false "your own module is missing" would send the coder after a package that should
        not exist. The workspace settles it, so cria asks the disk rather than guessing (#8)."""
        with tempfile.TemporaryDirectory() as ws:
            pathlib.Path(ws, "shipping").mkdir()
            self.assertTrue(probeparse.names_a_workspace_file("shipping.rates", ws))
            self.assertFalse(probeparse.names_a_workspace_file("commons.csv", ws))
            note = proberun.dependency_note(
                report("exited 1: ModuleNotFoundError: No module named 'shipping'"), ws)
            self.assertEqual(note, "", "called the project's own package a missing dependency")

    def test_a_file_not_a_directory_counts_too(self):
        with tempfile.TemporaryDirectory() as ws:
            pathlib.Path(ws, "rates.rb").write_text("x")
            self.assertTrue(probeparse.names_a_workspace_file("rates", ws))


class TheCheckersOwnWordsSurviveTests(unittest.TestCase):
    def test_the_note_is_appended_never_substituted(self):
        rep = report("exited 1: cannot load such file -- countries (LoadError)")
        rep.results[0].findings = [Finding(file="lib/rates.rb", line=3,
                                           message="cannot load such file -- countries (LoadError)")]
        nudge = proberun.completion_block_nudge(rep) or ""
        self.assertIn("cannot load such file -- countries (LoadError)", nudge)
        self.assertIn("Note:", nudge)
        self.assertLess(nudge.index("cannot load such file"), nudge.index("Note:"),
                        "the checker's line must come first; the note rides beside it")


if __name__ == "__main__":
    unittest.main()
