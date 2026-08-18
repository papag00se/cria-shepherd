"""cria described an install that had never happened, and ruled out the step that had failed.

Walked twice in cycle 4, independently, on the two worst cells of the worst column — cell 13
(`shipping-rates-rb × ternary-bonsai`, 10% useful) and cell 19 (`shipping-rates-rb ×
nemotron-elastic`, 5%). In cell 19, at call 0061, beside the coder's own `LoadError`:

    Note: `countries` is installed nowhere ruby is looking. A gem installed with --install-dir is not
    on the load path by default — set GEM_HOME to that directory when you run, or add its `lib`
    directory to $LOAD_PATH from your code. Fix the loading; the code that uses it is not what failed
    here.

Every `gem install` in that run had been REFUSED and every `bundle install` was `command not found`.
The surviving workspace has no `vendor/`, no `.bundle/` and no `Gemfile.lock`. So *"a gem installed
with --install-dir"* describes a thing that never happened, and *"the code that uses it is not what
failed here"* rules out the one correct next move — the install is precisely what failed. The model
read it and went back to `gem install`, which was the last action of the run.

The line is right AFTER an install; it is a false description of the world before one (#5b). It was
recorded in the cycle-3 ledger as *"MODIFY FIRST — add a condition, never soften the sentence"* and
not landed then. Two more sightings is enough.

ONLY WHERE CRIA CAN SETTLE IT. Ruby, Node and Python put their install evidence inside the workspace
— `Gemfile.lock`/`vendor/`/`.bundle/`, `node_modules/`, a venv or `site-packages`. Rust, Go and Java
resolve from caches outside it, and their notes are about DECLARING a dependency rather than loading
an installed one, so they are untouched. An ecosystem cria cannot settle, or a workspace it cannot
read, keeps the original sentence (#3).
"""

import pathlib
import tempfile
import unittest

from cria import prompts, probeparse
from cria.proberun import dependency_line, report_root as proberun_root


class _Project:
    def __init__(self, files=(), dirs=()):
        self.files, self.dirs = files, dirs

    def __enter__(self):
        self._d = tempfile.TemporaryDirectory()
        root = pathlib.Path(self._d.name)
        for f in self.files:
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            (root / f).write_text("x\n")
        for d in self.dirs:
            (root / d).mkdir(parents=True, exist_ok=True)
        return str(root)

    def __exit__(self, *a):
        self._d.cleanup()
        return False


def line(eco, root, name="countries"):
    return prompts.fill(dependency_line(eco, root), name=name)


class TheWorldIsAskedBeforeItIsDescribedTests(unittest.TestCase):
    def test_the_measured_cell(self):
        """A Gemfile, and nothing installed — cell 19's workspace exactly."""
        with _Project(files=["Gemfile"]) as root:
            said = line("ruby", root)
            self.assertIn("not installed anywhere", said)
            self.assertNotIn("installed with --install-dir", said)
            self.assertNotIn("the code that uses it is not what failed here", said)

    def test_it_names_what_it_looked_for(self):
        with _Project(files=["Gemfile"]) as root:
            for token in ("Gemfile.lock", "vendor/", ".bundle/"):
                with self.subTest(token=token):
                    self.assertIn(token, line("ruby", root))

    def test_after_a_real_install_the_load_path_advice_returns(self):
        """It is the right advice then, and this is the case it was written for. Note what stands for
        an install: a lock FILE, or a vendor tree with a file actually in it — see
        test_an_empty_tree_is_not_an_install.

        WHICH load-path advice depends on WHICH install, and cria reads that off the disk too since
        2026-08-18 (probeparse.install_flavour). A `Gemfile.lock` is bundler's; a bare
        `vendor/bundle/gems/` tree with no lock is `gem install --install-dir`'s. Both get a
        load-path sentence; they get different ones, because the two mechanisms are reached
        differently and naming the wrong one sent a coder after GEM_HOME — see
        test_the_bundler_case_does_not_prescribe_GEM_HOME below."""
        with _Project(files=["Gemfile", "Gemfile.lock"]) as root:
            self.assertIn("only on the load path under bundler", line("ruby", root))
        with _Project(files=["Gemfile", "vendor/bundle/gems/countries-1.0/lib/countries.rb"]) as root:
            self.assertIn("installed with --install-dir", line("ruby", root))

    def test_the_bundler_case_does_not_prescribe_GEM_HOME(self):
        """THE MEASURED COST. `shipping-rates-rb x ternary-bonsai`: the --install-dir sentence was
        appended to a BUNDLER project's failing `bundle exec rake test` — no --install-dir install
        had happened in that run — and its remedy, "set GEM_HOME to that directory", is where the
        coder's `Dir[ENV["GEM_HOME"], Dir.pwd]` came from. That raises TypeError with GEM_HOME unset
        and aborted `rake test` until the coder backed it out. Its own reasoning had the right answer
        first — "bundler isolates gems and doesn't include system-installed gems like minitest" — and
        it deferred to cria's note anyway."""
        with _Project(files=["Gemfile", "Gemfile.lock"]) as root:
            said = line("ruby", root, name="minitest/autorun")
            self.assertNotIn("GEM_HOME", said)
            self.assertNotIn("--install-dir", said)
            # …and it says the thing the model actually needed, which cria had withheld
            self.assertIn("not in the `Gemfile`", said)

    def test_the_opener_no_longer_claims_ruby_cannot_see_it(self):
        """"is installed nowhere ruby is looking" was a claim cria never checked, and in the walked
        run it was false: `ruby -e 'require "minitest"'` printed 5.16.3. The gem was exactly where
        plain ruby looks and missing only from the bundle. What survives is what the checker's output
        established — the require failed."""
        for files in (["Gemfile", "Gemfile.lock"],
                      ["Gemfile", "vendor/bundle/gems/countries-1.0/lib/countries.rb"]):
            with self.subTest(files=files[-1]):
                with _Project(files=files) as root:
                    said = line("ruby", root)
                    self.assertNotIn("installed nowhere ruby is looking", said)
                    self.assertIn("did not load", said)

    def test_a_flavour_cria_cannot_read_keeps_the_general_line(self):
        """#3: no evidence, no claim. A ruby project with an install cria can see but no marker
        saying HOW keeps the sentence that was there before."""
        from cria import probeparse
        with _Project(files=["Gemfile", "vendor/bundle/gems/countries-1.0/lib/countries.rb"]) as root:
            self.assertEqual(probeparse.install_flavour("ruby", root), "install_dir")
        with _Project(files=["Cargo.toml"]) as root:
            self.assertEqual(probeparse.install_flavour("rust", root), "")
        self.assertEqual(probeparse.install_flavour("ruby", ""), "")

    def test_an_empty_tree_is_not_an_install(self):
        """THE REPLAY. Cell 13's real workspace holds `vendor/bundle/gems/eu_countries/` — ten
        directories and ZERO files, built by the model's own `mkdir -p` while every real install was
        refused. Reading the directory NAME answered True, so cria would have looked at a workspace
        where nothing landed, seen the folder the failed attempts left behind, and gone back to the
        false sentence this whole file exists to kill. An install writes files; `mkdir -p` writes
        none. The fixture above had encoded the same mistake."""
        with _Project(files=["Gemfile"],
                      dirs=["vendor/bundle/gems/eu_countries", "vendor/bundler/gems"]) as root:
            self.assertFalse(probeparse.install_landed("ruby", root))
            self.assertIn("not installed anywhere", line("ruby", root))

    def test_node_and_python_too(self):
        with _Project(files=["package.json"]) as root:
            self.assertIn("no node_modules/", line("node", root, name="axios"))
        with _Project(files=["node_modules/axios/index.js"]) as root:
            self.assertIn("Node loads from this project's own node_modules", line("node", root, "axios"))
        with _Project(files=["app.py"]) as root:
            self.assertIn("no virtualenv or site-packages", line("python", root, "requests"))
        with _Project(files=[".venv/lib/python3.12/site-packages/requests/__init__.py"]) as root:
            self.assertIn("cannot be imported", line("python", root, "requests"))


class WhatIsLeftAloneTests(unittest.TestCase):
    def test_an_ecosystem_that_resolves_outside_the_workspace(self):
        """rust/go/java fetch from caches cria cannot see, and their notes are about DECLARING a
        dependency — a different sentence with a different truth condition."""
        with _Project(files=["Cargo.toml"]) as root:
            for eco, phrase in (("rust", "has to be in Cargo.toml's [dependencies]"),
                                ("go", "records it in go.mod"),
                                ("java", "against what the repository actually publishes")):
                with self.subTest(ecosystem=eco):
                    self.assertIn(phrase, line(eco, root, name="x"))

    def test_no_workspace_keeps_the_original(self):
        self.assertIn("installed with --install-dir", line("ruby", ""))

    def test_an_unreadable_workspace_keeps_the_original(self):
        self.assertIn("installed with --install-dir",
                      line("ruby", "/nonexistent-path-for-this-test"))

    def test_install_landed_says_it_cannot_tell_rather_than_guessing(self):
        with _Project(files=["Cargo.toml"]) as root:
            self.assertIsNone(probeparse.install_landed("rust", root))
        self.assertIsNone(probeparse.install_landed("ruby", ""))


class TheSearchIsBoundedTests(unittest.TestCase):
    def test_evidence_at_the_top_of_the_project_is_found(self):
        with _Project(files=["node_modules/left-pad/index.js"]) as root:
            self.assertTrue(probeparse.install_landed("node", root))

    def test_it_does_not_walk_the_whole_tree(self):
        """An install tree lives at the top of a project, not eight levels down — and walking a big
        workspace on every failing check is not free."""
        with _Project(files=["a/b/c/d/e/node_modules/x/index.js"]) as root:
            self.assertFalse(probeparse.install_landed("node", root))


class TheGatePathReachesTheDiskTests(unittest.TestCase):
    """THE GAP THE ORIGINAL TESTS STEPPED OVER. Every test above calls `dependency_line` with a root
    handed to it, so all of them passed while the path that actually ships — `completion_block_nudge`
    on a gate outcome — called `dependency_note` with no root at all. `install_landed` then returned
    None on every gate, the "not installed anywhere" branch was unreachable, and the coder kept
    getting the false sentence for the entire life of the fix.

    A test written to the FUNCTION cannot catch that. These are written to the PATH."""

    def _report(self, root, message):
        """A gate report shaped exactly as the real one: a Test probe that ran in `root` and came
        back with a LoadError finding."""
        import pathlib as _pl

        from cria import probediscovery, probeparse, proberun
        cand = probediscovery.ProbeCandidate(
            kind=probediscovery.ProbeKind.Test, command=["rake", "test"],
            working_dir=_pl.Path(root), confidence=100, expected_value=100,
            cost=probediscovery.ProbeCost.Cheap, mutates_code=False, may_hang=False,
            may_need_services=False, reason="test")
        res = proberun.ProbeResult(command="rake test", exit_code=1, summary=message,
                                   findings=[probeparse.Finding(file="lib/shipping/rates.rb",
                                                                line=1, message=message)])
        return proberun.ProbeReport(project_type=["ruby"], selected=[cand], results=[res])

    def test_the_root_comes_from_the_report_not_a_parameter(self):
        with _Project(files=["Gemfile"]) as root:
            self.assertEqual(proberun_root(self._report(root, "x")), root)

    def test_an_empty_report_names_no_workspace(self):
        from cria import proberun
        self.assertEqual(proberun_root(proberun.ProbeReport()), "")

    def test_the_gate_note_reads_the_disk(self):
        """The whole point: no caller passes a root, and the note is still the true one."""
        from cria import proberun
        with _Project(files=["Gemfile"]) as root:
            said = proberun.completion_block_nudge(
                self._report(root, "cannot load such file -- countries (LoadError)")) or ""
            self.assertIn("not installed anywhere", said)
            self.assertNotIn("installed with --install-dir", said)

    def test_after_a_real_install_the_gate_note_flips(self):
        from cria import proberun
        with _Project(files=["Gemfile", "Gemfile.lock"]) as root:
            said = proberun.completion_block_nudge(
                self._report(root, "cannot load such file -- countries (LoadError)")) or ""
            self.assertIn("only on the load path under bundler", said)
            self.assertNotIn("not installed anywhere", said)

    def test_the_gate_note_reads_the_INSTALL_MECHANISM_off_the_disk_too(self):
        """The same gap, one level down: the root reaches `dependency_line`, and `dependency_line`
        then has to ask which install put the gems there rather than assume `--install-dir`."""
        from cria import proberun
        # NOTE the gem name: `countries` would be suppressed here, because the fixture's tree
        # contains `countries.rb` and cria leaves a name that resolves to a workspace file alone.
        with _Project(files=["Gemfile", "vendor/bundle/gems/countries-1.0/lib/countries.rb"]) as root:
            said = proberun.completion_block_nudge(
                self._report(root, "cannot load such file -- unaccent (LoadError)")) or ""
            self.assertIn("installed with --install-dir", said)

    def test_no_caller_passes_a_workspace_root(self):
        """If a root ever becomes a parameter again, the gap comes back with it."""
        import inspect
        from cria import proberun
        sig = inspect.signature(proberun.completion_block_nudge)
        self.assertNotIn("workspace_root", sig.parameters)


if __name__ == "__main__":
    unittest.main()
