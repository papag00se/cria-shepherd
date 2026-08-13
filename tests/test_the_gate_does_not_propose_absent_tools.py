"""cria composed `bundle exec rubocop` for every ruby workspace on a box with no bundler.

Two of five ruby gate probes could never launch — every gate, burning a probe slot and a 240-second
timeout each, and reporting "could not run" about a check that was never available. `shutil.which`
appeared nowhere in discovery or selection; nothing asked whether the program existed.

A launch failure already abstains rather than misreporting, so this was never a correctness bug. It
cost the gate its budget and the operator a confusing non-signal, and cria could answer it for free.

UNSURE MEANS KEEP. A project-local tool (`./gradlew`, `node_modules/.bin/jest`) is checked as a file
rather than on PATH, and anything unresolvable is kept: dropping a real probe is much worse than
running one that abstains, so this only ever removes a certainty.

THE ORACLE MOVED, THE RULE DID NOT. The certainty is now read off the CODER's path rather than
cria's own service path (`cria.toolpath`) — cria could not see cargo, node or pytest and dropped
every probe using them. These cases are unchanged in intent; they mock the new oracle because the
old one answered for the wrong process. See
tests/test_cria_asks_the_coders_path_not_its_own.py.
"""

import os
import pathlib
import tempfile
import unittest
from unittest import mock

from cria import proberun, toolpath


class C:
    """A stand-in candidate — only `command` and `working_dir` are read."""

    def __init__(self, command, working_dir=""):
        self.command = command
        self.working_dir = working_dir


class OnlyACertainAbsenceIsDroppedTests(unittest.TestCase):
    def test_a_tool_on_path_is_kept(self):
        self.assertTrue(proberun.program_is_installed(C(["python3", "-c", "pass"])))

    def test_a_tool_that_is_certainly_absent_is_dropped(self):
        self.assertFalse(proberun.program_is_installed(C(["definitely-not-a-real-tool-xyz", "run"])))

    def test_the_measured_case(self):
        """`bundle exec rubocop` on a box without bundler."""
        with mock.patch.object(toolpath, "which", lambda p: None if p == "bundle" else "/usr/bin/" + p):
            self.assertFalse(proberun.program_is_installed(C(["bundle", "exec", "rubocop"])))
            self.assertTrue(proberun.program_is_installed(C(["ruby", "-c", "x.rb"])))

    def test_an_env_prefix_is_not_mistaken_for_the_program(self):
        with mock.patch.object(toolpath, "which", lambda p: "/usr/bin/ruby" if p == "ruby" else None):
            self.assertTrue(proberun.program_is_installed(C(["GEM_HOME=vendor", "ruby", "-c", "x"])))

    def test_an_empty_command_is_kept(self):
        self.assertTrue(proberun.program_is_installed(C([])))


class AProjectLocalToolIsCheckedAsAFileTests(unittest.TestCase):
    def test_a_wrapper_in_the_workspace_is_kept(self):
        with tempfile.TemporaryDirectory() as ws:
            g = pathlib.Path(ws, "gradlew")
            g.write_text("#!/bin/sh\n")
            g.chmod(0o755)
            self.assertTrue(proberun.program_is_installed(C(["./gradlew", "test"], ws)))

    def test_a_wrapper_that_is_not_there_is_dropped(self):
        with tempfile.TemporaryDirectory() as ws:
            self.assertFalse(proberun.program_is_installed(C(["./gradlew", "test"], ws)))

    def test_a_node_modules_binary_is_found_relative_to_the_workspace(self):
        with tempfile.TemporaryDirectory() as ws:
            b = pathlib.Path(ws, "node_modules", ".bin")
            b.mkdir(parents=True)
            (b / "jest").write_text("#!/bin/sh\n")
            (b / "jest").chmod(0o755)
            self.assertTrue(
                proberun.program_is_installed(C(["node_modules/.bin/jest", "--ci"], ws)))


class TheRealSelectionDropsThemTests(unittest.TestCase):
    def _ruby_ws(self, d):
        pathlib.Path(d, "lib").mkdir()
        pathlib.Path(d, "lib", "x.rb").write_text("module X; end\n")
        pathlib.Path(d, "test").mkdir()
        pathlib.Path(d, "test", "test_x.rb").write_text('require "minitest/autorun"\n')
        pathlib.Path(d, "Gemfile").write_text('source "https://rubygems.org"\n')
        return d

    def test_no_selected_probe_names_a_program_that_is_absent(self):
        with tempfile.TemporaryDirectory() as ws:
            for c in proberun.select_completion_probes(self._ruby_ws(ws)):
                with self.subTest(command=str(c.command)[:50]):
                    self.assertTrue(proberun.program_is_installed(c))

    def test_the_ruby_checks_that_CAN_run_still_do(self):
        """Narrowing must not empty the gate — ruby still gets its syntax floor and its test probe."""
        with tempfile.TemporaryDirectory() as ws:
            cmds = [" ".join(str(x) for x in (c.command if isinstance(c.command, (list, tuple))
                                              else [c.command]))
                    for c in proberun.select_completion_probes(self._ruby_ws(ws))]
            self.assertTrue(any(c.startswith("ruby -c") for c in cmds), cmds)
            self.assertTrue(any("test/**/test_*.rb" in c for c in cmds), cmds)

    def test_a_python_workspace_still_selects_its_probes(self):
        with tempfile.TemporaryDirectory() as ws:
            pathlib.Path(ws, "app.py").write_text("x = 1\n")
            pathlib.Path(ws, "test_app.py").write_text("def test_x():\n    assert True\n")
            self.assertTrue(proberun.select_completion_probes(ws))


if __name__ == "__main__":
    unittest.main()
