"""The vendored-.gitignore matcher: language-agnostic pruning of installed/vendored trees, driven by
github/gitignore templates, applied per-language so one language's rules never touch another's source."""
import os
import tempfile
import unittest

from cria import ignore, linterprobe


class MatcherTests(unittest.TestCase):
    def test_named_venv_pruned_via_python_lib_rule(self):
        # The crash: a venv the model named `handle_resolver/` — caught by Python's `lib/` rule
        # matching its inner tree, NOT by the directory's name.
        py = ignore.for_exts(("py",))
        self.assertTrue(py.ignored("handle_resolver/lib", True))
        self.assertTrue(py.ignored("handle_resolver/lib/python3.12/site-packages/pip", True))

    def test_no_cross_language_contamination(self):
        # Python's `lib/` (a build/venv artifact) must NOT prune a Ruby project's source `lib/`.
        self.assertTrue(ignore.for_exts(("py",)).ignored("lib", True))
        self.assertFalse(ignore.for_exts(("rb",)).ignored("lib/foo.rb", False))

    def test_common_vendored_dirs_across_ecosystems(self):
        self.assertTrue(ignore.for_exts(("js", "mjs")).ignored("node_modules", True))
        self.assertTrue(ignore.for_exts(("js",)).ignored("a/b/node_modules", True))  # any depth
        self.assertTrue(ignore.for_exts(("rs",)).ignored("target", True))

    def test_real_source_survives(self):
        py = ignore.for_exts(("py",))
        self.assertFalse(py.ignored("resolver.py", False))
        self.assertFalse(py.ignored("src/app/handlers.py", False))

    def test_unknown_ext_is_permissive(self):
        self.assertFalse(ignore.for_exts(("toml",)).ignored("anything/here", True))

    def test_default_matcher_unions_ecosystems(self):
        m = ignore.default_matcher()
        self.assertTrue(m.ignored("node_modules", True))
        self.assertTrue(m.ignored("handle_resolver/lib", True))
        self.assertTrue(m.ignored("target", True))


class CollectFilesIntegrationTests(unittest.TestCase):
    def test_collect_files_skips_an_arbitrarily_named_venv(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "myenv", "lib", "python3.12", "site-packages", "pip"))
            with open(os.path.join(d, "myenv", "lib", "python3.12", "site-packages", "pip", "x.py"), "w") as f:
                f.write("import os\n")
            with open(os.path.join(d, "resolver.py"), "w") as f:  # the model's own source
                f.write("print(1)\n")
            got = [os.path.relpath(p, d) for p in linterprobe.collect_files(d, ["py"])]
            self.assertEqual(got, ["resolver.py"])  # venv's site-packages pruned; real source kept


if __name__ == "__main__":
    unittest.main()
