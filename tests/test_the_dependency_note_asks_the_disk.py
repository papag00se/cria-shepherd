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
from cria.proberun import dependency_line


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
        """It is the right advice then, and this is the case it was written for."""
        for ev in ("Gemfile.lock",), ():
            with self.subTest(evidence=ev or "vendor/bundle"):
                with _Project(files=["Gemfile", *ev],
                              dirs=[] if ev else ["vendor/bundle"]) as root:
                    self.assertIn("installed with --install-dir", line("ruby", root))

    def test_node_and_python_too(self):
        with _Project(files=["package.json"]) as root:
            self.assertIn("no node_modules/", line("node", root, name="axios"))
        with _Project(dirs=["node_modules/axios"]) as root:
            self.assertIn("Node loads from this project's own node_modules", line("node", root, "axios"))
        with _Project(files=["app.py"]) as root:
            self.assertIn("no virtualenv or site-packages", line("python", root, "requests"))
        with _Project(dirs=[".venv/lib"]) as root:
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
        with _Project(dirs=["node_modules"]) as root:
            self.assertTrue(probeparse.install_landed("node", root))

    def test_it_does_not_walk_the_whole_tree(self):
        """An install tree lives at the top of a project, not eight levels down — and walking a big
        workspace on every failing check is not free."""
        with _Project(dirs=["a/b/c/d/e/node_modules"]) as root:
            self.assertFalse(probeparse.install_landed("node", root))


if __name__ == "__main__":
    unittest.main()
