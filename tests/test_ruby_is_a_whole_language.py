"""Ruby's test story was keyed to rspec alone, and that is a hole with a voice.

`TEST_CONVENTIONS` holds one row per language, and Ruby's named only rspec: `*_spec.rb`,
`RSpec.describe`. Minitest — `test/test_*.rb` driven by a Rakefile, the standard layout and the shape
the battery's Ruby task ships — matched nothing. Two consequences, both measured across the
six-language battery:

  * cria told the coder "No rspec tests were found ... that is not done yet" 49 times in EACH of two
    models' runs, over a suite the coder was running green at 24 runs / 0 failures. nemotron-elastic
    believed it verbatim.
  * `detect_ecosystems` keyed Ruby on a Gemfile, so a Rakefile-only tree had NO ecosystem at all: no
    lint probe, no test probe, and a completion gate that was `ruby -c` and nothing else.

The rule this follows: per-language tables are correct and expected — every language gets its
equivalent check. The defect is a HOLE in one, or one framework's convention standing in for a
language that has two.
"""
import tempfile
import unittest
from pathlib import Path

from cria import probediscovery as pd
from cria import proberun


def _minitest_tree():
    ws = Path(tempfile.mkdtemp())
    (ws / "lib").mkdir()
    (ws / "test").mkdir()
    (ws / "Rakefile").write_text('require "rake/testtask"\n\nRake::TestTask.new(:test) do |t|\n'
                                 '  t.libs << "lib"\nend\n\ntask default: :test\n')
    (ws / "lib" / "rates.rb").write_text("module Shipping\nend\n")
    (ws / "test" / "test_rates.rb").write_text(
        'require "minitest/autorun"\nclass TestRates < Minitest::Test\n'
        "  def test_a\n    assert true\n  end\nend\n")
    return ws


def _rspec_tree():
    ws = Path(tempfile.mkdtemp())
    (ws / "spec").mkdir()
    (ws / "lib.rb").write_text("module X\nend\n")
    (ws / "spec" / "thing_spec.rb").write_text("RSpec.describe X do\nend\n")
    return ws


class MinitestIsRubyTooTests(unittest.TestCase):
    def test_a_green_minitest_suite_draws_no_complaint(self):
        self.assertEqual(pd.undiscoverable_tests(_minitest_tree()), [],
                         "cria told a project with working tests that it had none")

    def test_rspec_still_draws_no_complaint(self):
        self.assertEqual(pd.undiscoverable_tests(_rspec_tree()), [])

    def test_a_ruby_project_with_no_tests_is_still_told_so(self):
        """The check must stay useful — widening it must not silence it."""
        ws = Path(tempfile.mkdtemp())
        (ws / "lib.rb").write_text("module X\nend\n")
        said = pd.undiscoverable_tests(ws)
        self.assertTrue(said)
        self.assertIn("minitest", said[0])
        self.assertIn("rspec", said[0])

    def test_stranded_ruby_test_code_is_still_caught(self):
        ws = Path(tempfile.mkdtemp())
        (ws / "lib.rb").write_text("module X\nend\n")
        (ws / "checks.rb").write_text("class TestX < Minitest::Test\n  def test_a\n    assert true\n  end\nend\n")
        said = pd.undiscoverable_tests(ws)
        self.assertTrue(said and "checks.rb" in said[0])


class ARakefileIsAProjectTests(unittest.TestCase):
    def test_a_rakefile_tree_is_a_ruby_ecosystem(self):
        probes = proberun.select_completion_probes(_minitest_tree())
        kinds = {tuple(c.command[:2]) for c in probes}
        self.assertIn(("rake", "test"), kinds,
                      "a Rakefile declaring a test task supplied no test probe")

    def test_the_rake_probe_is_read_from_the_declaration_not_invented(self):
        """FLAG-3 forbids inventing make/just/task probes and is right to. A target the project
        DECLARES is not an invention — but a Rakefile without one must still produce nothing."""
        ws = Path(tempfile.mkdtemp())
        (ws / "Rakefile").write_text('task :build do\n  puts "no tests here"\nend\n')
        (ws / "lib.rb").write_text("module X\nend\n")
        cmds = {tuple(c.command[:2]) for c in proberun.select_completion_probes(ws)}
        self.assertNotIn(("rake", "test"), cmds)

    def test_the_syntax_floor_still_runs(self):
        probes = proberun.select_completion_probes(_minitest_tree())
        self.assertTrue(any(c.command[:2] == ["ruby", "-c"] for c in probes))


class ABareRubyProjectStillRunsItsTestsTests(unittest.TestCase):
    """The TEST FLOOR existed for exactly one language.

    Its premise, stated in the code, is that every other language arrives with a manifest that
    triggers ranked discovery. That holds for Go, Rust, JS and the JVM — they cannot build without
    one. It did NOT hold for Ruby: `rates.rb` plus `test/test_rates.rb` is a complete, testable
    project with no Gemfile and no Rakefile, and discovery saw nothing in it. Without a floor the
    gate ran `ruby -c` and reported "no error-class problems" over tests it never executed —
    the vacuous green the floor exists to prevent.
    """

    def _bare(self):
        ws = Path(tempfile.mkdtemp())
        (ws / "lib").mkdir()
        (ws / "test").mkdir()
        (ws / "lib" / "rates.rb").write_text("module Shipping\nend\n")
        (ws / "test" / "test_rates.rb").write_text(
            'require "minitest/autorun"\nclass TestRates < Minitest::Test\n'
            "  def test_a\n    assert true\n  end\nend\n")
        return ws

    def test_a_manifestless_ruby_project_gets_a_test_probe(self):
        cmds = [" ".join(c.command) for c in proberun.select_completion_probes(self._bare())]
        self.assertTrue(any(c.startswith("ruby -Ilib -Itest -e") for c in cmds),
                        "a testable project ran no tests and the gate would have read clean")

    def test_the_floor_actually_runs_the_suite(self):
        import subprocess
        ws = self._bare()
        probe = next(c for c in proberun.select_completion_probes(ws)
                     if " ".join(c.command).startswith("ruby -Ilib"))
        done = subprocess.run(probe.command, cwd=ws, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0)
        self.assertIn("1 runs", done.stdout)

    def test_a_ruby_project_with_no_tests_gets_no_test_probe(self):
        ws = Path(tempfile.mkdtemp())
        (ws / "lib.rb").write_text("module X\nend\n")
        cmds = [" ".join(c.command) for c in proberun.select_completion_probes(ws)]
        self.assertFalse([c for c in cmds if c.startswith("ruby -Ilib")])


if __name__ == "__main__":
    unittest.main()
