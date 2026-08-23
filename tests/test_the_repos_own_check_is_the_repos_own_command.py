"""cria reported a repo's tests as failing while the repo's own command ran them green.

`shipping-rates-rb x gemma4` 1787268190. The model added `gem "europe"` and installed it with
bundler into `vendor/bundle`, which is what the project's `.bundle/config` asks for. cria's gate
then ran `rake test` — bare, not through bundler — which cannot see a vendored gem, and published
the resulting `cannot load such file -- europe (LoadError)` under the header that tells the coder
this section is the ONLY thing it may base a statement about the build on. Four gate cycles said it.
The run's own compaction reads "Fix the load path or environment configuration so that the europe
gem ... are correctly recognized during test execution"; it spent the rest of the run on a load path
that was not broken, and scored 1/5 against 3/5 for the same model on the same task.

`bundle exec rake test` in that exact archived workspace: 8 runs, 8 assertions, 0 failures.

MEASURED BEFORE IT WAS BUILT. Every archived ruby run whose checks reported a require failure and
whose workspace held a bundler install, n=18: five declare `gem "rake"`, and on two of those the
bundled command is green while the bare one is red. The other thirteen do not declare it, and for
them `bundle exec rake` fails with "rake is not currently included in the bundle" — so the bare
command is genuinely theirs. 14 of 18 report red today; 12 do under this rule, and the two that move
are the two independently confirmed green.
"""

import re
import tempfile
import unittest
from pathlib import Path

from cria import probediscovery as pd
from cria import wsview


def _project(gemfile: str) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "Gemfile").write_text(gemfile)
    (d / "Rakefile").write_text("task :test do\n  puts 1\nend\n")
    (d / "test").mkdir()
    (d / "test" / "test_a.rb").write_text("def test_a; end\n")
    return d


class TheRunnerComesFromTheManifestTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(wsview.unbind, wsview.bind(wsview.DirectView()))

    def _rake_probe(self, gemfile):
        out = []
        d = _project(gemfile)
        pd.build_ruby(pd.ProjectDir(d, {"Gemfile", "Rakefile"}), out)
        return [c.command for c in out if "rake" in c.command]

    def test_a_project_that_bundles_rake_is_run_through_bundler(self):
        self.assertEqual(self._rake_probe('source "x"\ngem "europe"\ngem "rake"\n'),
                         [["bundle", "exec", "rake", "test"]])

    def test_a_project_that_does_not_is_left_exactly_as_it_was(self):
        """The thirteen runs where `bundle exec rake` would fail on rake's own absence."""
        self.assertEqual(self._rake_probe('source "x"\ngem "europe"\n'),
                         [["rake", "test"]])

    def test_the_declaration_is_read_as_a_declaration_not_a_substring(self):
        for gemfile, bundled in (
                ("gem 'rake'\n", True),
                ('gem "rake", "~> 13.0"\n', True),
                ("  gem 'rake'\n", True),
                ("# gem 'rake'\n", False),
                ("gem 'rakelike'\n", False),
                ("gem 'rspec'  # not rake\n", False)):
            with self.subTest(gemfile=gemfile):
                self.assertEqual(bool(pd._BUNDLED_RAKE.search(gemfile)), bundled)


class OnlyTheToolsTheProjectDeclaresTests(unittest.TestCase):
    """`bundle exec rspec` and `bundle exec rubocop` were composed for EVERY ruby project, under
    reason strings that read "if in Gemfile" — while the Gemfile was read into a variable and never
    consulted. On shipping-rates-rb x nemotron-elastic 1787432916 the repo has no rspec anywhere, and
    the failure of a command it does not own was reported to the coder as `LATEST CHECK RESULTS (the
    repo's own checks, most recent run)` for 49 consecutive calls, while its real check — `rake test`
    — was green throughout."""

    def setUp(self):
        self.addCleanup(wsview.unbind, wsview.bind(wsview.DirectView()))

    def _tools(self, gemfile):
        out = []
        pd.build_ruby(pd.ProjectDir(_project(gemfile), {"Gemfile", "Rakefile"}), out)
        return {c.command[2] for c in out if c.command[:2] == ["bundle", "exec"]} - {"rake"}

    def test_a_project_that_declares_neither_gets_neither(self):
        self.assertEqual(self._tools('source "x"\ngem "rake"\n'), set())

    def test_a_project_that_declares_them_still_gets_them(self):
        self.assertEqual(self._tools('source "x"\ngem "rspec"\ngem "rubocop"\n'), {"rspec", "rubocop"})

    def test_each_is_gated_on_its_own_declaration(self):
        self.assertEqual(self._tools('source "x"\ngem "rspec"\n'), {"rspec"})

    def test_a_gemfile_cria_could_not_read_claims_nothing(self):
        """Unknown is not a declaration. A probe cria cannot justify is not the repo's own check."""
        d = Path(tempfile.mkdtemp())
        (d / "Rakefile").write_text("task :test do\nend\n")
        out = []
        pd.build_ruby(pd.ProjectDir(d, {"Rakefile"}), out)
        self.assertEqual([c for c in out if c.command[:2] == ["bundle", "exec"]
                          and c.command[2] != "rake"], [])


if __name__ == "__main__":
    unittest.main()
