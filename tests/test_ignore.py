"""Which directories a walk may skip, and the proof that let it.

The templates this module used to read answered a VCS's question ("do not track this"), not the
walk's ("the author did not write this"). Python's unanchored `lib/`, `build/`, `dist/` and `env/`
matched at any depth, in every project, so a package the model had just written was pruned from the
lint floor and the gate called the workspace clean without opening it."""
import os
import tempfile
import unittest

from cria import ignore, linterprobe


class ProofTests(unittest.TestCase):
    def test_a_tool_owned_name_needs_no_listing(self):
        called = []

        def children():
            called.append(1)
            return []

        self.assertIsNotNone(ignore.generated("node_modules", children))
        self.assertEqual(called, [])  # the name alone decided it

    def test_a_venv_under_any_name_is_caught_by_its_marker(self):
        # THE CASE THE TEMPLATES EXISTED FOR: a venv the model called `handle_resolver/`.
        proof = ignore.generated("handle_resolver", lambda: ["pyvenv.cfg", "bin", "lib"])
        self.assertIsNotNone(proof)
        self.assertIn("pyvenv.cfg", proof)

    def test_an_ambiguous_name_with_no_marker_is_walked(self):
        for name in ("lib", "build", "dist", "out", "target", "env", "vendor", "bin"):
            self.assertIsNone(ignore.generated(name, lambda: ["shipping.rb", "rates.rb"]),
                              f"{name} was pruned on its name alone")

    def test_a_cargo_target_is_caught_by_its_cache_tag(self):
        self.assertIsNotNone(ignore.generated("target", lambda: ["CACHEDIR.TAG", "debug"]))

    def test_an_unlistable_directory_is_not_proof(self):
        # None means "could not look", which is not "yes" (#23c). The walk proceeds.
        self.assertIsNone(ignore.generated("build", lambda: None))

    def test_the_proof_names_the_directory_and_the_evidence(self):
        # The caller prints this in the sentence about what it did not read.
        self.assertIn("node_modules", ignore.generated("node_modules", lambda: []))
        self.assertIn("site-packages", ignore.generated("deps", lambda: ["site-packages"]))


class CollectFilesIntegrationTests(unittest.TestCase):
    def test_collect_files_skips_an_arbitrarily_named_venv(self):
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "myenv", "lib", "python3.12", "site-packages", "pip")
            os.makedirs(sp)
            open(os.path.join(d, "myenv", "pyvenv.cfg"), "w").write("home = /usr\n")
            open(os.path.join(sp, "x.py"), "w").write("import os\n")
            open(os.path.join(d, "resolver.py"), "w").write("print(1)\n")
            got = [os.path.relpath(p, d) for p in linterprobe.collect_files(d, ["py"])]
            self.assertEqual(got, ["resolver.py"])

    def test_source_the_model_wrote_into_lib_reaches_the_floor(self):
        # The regression the templates caused: `lib/` pruned for every Python walk, at any depth.
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "lib", "handlers"))
            open(os.path.join(d, "lib", "handlers", "zones.py"), "w").write("x = (\n")
            got = [os.path.relpath(p, d) for p in linterprobe.collect_files(d, ["py"])]
            self.assertEqual(got, [os.path.join("lib", "handlers", "zones.py")])

    def test_the_walk_can_name_what_it_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "node_modules", "left-pad"))
            open(os.path.join(d, "node_modules", "left-pad", "i.js"), "w").write("x\n")
            open(os.path.join(d, "app.js"), "w").write("x\n")
            files, skipped = linterprobe.collect_files_with_skips(d, ["js"])
            self.assertEqual([os.path.relpath(p, d) for p in files], ["app.js"])
            self.assertEqual(skipped, ["node_modules"])


class CleanVerdictTests(unittest.TestCase):
    def test_a_clean_verdict_names_what_it_did_not_read(self):
        from cria.linterprobe import LinterFinding, LinterReport
        r = LinterReport(findings=[LinterFinding("python", "py_compile", True)],
                         skipped_dirs=["node_modules", "myenv"])
        text = r.probe_digest()
        self.assertIn("node_modules", text)
        self.assertIn("myenv", text)

    def test_a_clean_verdict_with_nothing_skipped_says_nothing_extra(self):
        from cria.linterprobe import LinterFinding, LinterReport
        r = LinterReport(findings=[LinterFinding("python", "py_compile", True)])
        self.assertNotIn("Not checked", r.probe_digest())


if __name__ == "__main__":
    unittest.main()
