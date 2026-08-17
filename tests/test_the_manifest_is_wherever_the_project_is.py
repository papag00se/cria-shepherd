"""`no manifest in this workspace declares cargo run`, said over a workspace holding a Cargo.toml.

`manifest_commands` read `root` and nothing below it. A model that starts a Rust project the normal
way — `cargo new toml-cli` — puts its manifest in `toml-cli/`, and cria then answered "this project
declares nothing" and refused to believe the program had run.

Measured on cycle 4 cell 6, `rust-toml-cli x gemma4`: a complete, correct, working CLI — judged 95%
useful — built one directory down. cria held the fact the whole time (the gate composed five probes
with `working_dir=toml-cli`) and its live-execution marker still published

    Live execution inconclusive — no manifest in this workspace declares cargo run

which is false (#5b) and reaches the CODER. The previous member of this class cost a run outright:
the coder answered "The context says cargo run is not an entry point. Let me check the actual state
of the workspace" after having run it successfully.

`probediscovery.inventory` already owns "where are this workspace's projects" — bounded depth, vendor
directories skipped — and the gate composes its probes from it. Reading the same answer here is what
stops the two halves of cria from disagreeing about where the project is (#23). The nesting is not a
special case for Rust: Maven, Gradle, Go with a `cmd/` dir and any monorepo put the manifest below
the workspace as a matter of course.

WHAT IS NOT WIDENED: this only decides whether the PROJECT declares a command. Whether cria will
execute one is still `_runnable` plus `_SHELL_META`, and neither moved.
"""

import os
import pathlib
import tempfile
import unittest

from cria import execcheck


class _Workspace:
    def __init__(self, files):
        self.files = files

    def __enter__(self):
        self._d = tempfile.TemporaryDirectory()
        root = pathlib.Path(self._d.name)
        for name, body in self.files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        return str(root)

    def __exit__(self, *a):
        self._d.cleanup()
        return False


CARGO = '[package]\nname = "toml-cli"\nversion = "0.1.0"\n'
POM = "<project><artifactId>feed</artifactId></project>\n"


class TheNestedManifestIsFoundTests(unittest.TestCase):
    def test_cargo_new_subdir(self):
        """THE CELL. `cargo new toml-cli` is the ordinary way to start, and it was invisible."""
        with _Workspace({"toml-cli/Cargo.toml": CARGO,
                         "toml-cli/src/main.rs": "fn main() {}\n"}) as root:
            self.assertIn("cargo run", execcheck.manifest_commands(root))

    def test_the_false_sentence_is_gone(self):
        with _Workspace({"toml-cli/Cargo.toml": CARGO,
                         "toml-cli/src/main.rs": "fn main() {}\n"}) as root:
            ok, why = execcheck.corroborate("cargo run -- config.toml server.port", [],
                                            ["toml-cli/src/main.rs"], root)
            self.assertTrue(ok, why)
            self.assertNotIn("no manifest in this workspace declares", why)

    def test_other_languages_nest_the_same_way(self):
        for files, want in (({"service/pom.xml": POM}, "mvn test"),
                            ({"cmd/app/go.mod": "module x\n"}, "go run"),
                            ({"web/package.json": '{"scripts": {"start": "node ."}}'}, "npm start")):
            with self.subTest(layout=sorted(files)):
                with _Workspace(files) as root:
                    self.assertIn(want, execcheck.manifest_commands(root))

    def test_a_root_manifest_still_works(self):
        with _Workspace({"Cargo.toml": CARGO, "src/main.rs": "fn main() {}\n"}) as root:
            self.assertIn("cargo run", execcheck.manifest_commands(root))

    def test_a_manifest_at_both_levels_is_listed_once(self):
        with _Workspace({"Cargo.toml": CARGO, "sub/Cargo.toml": CARGO}) as root:
            cmds = execcheck.manifest_commands(root)
            self.assertEqual(cmds.count("cargo run"), 1)


class NothingIsInventedTests(unittest.TestCase):
    def test_an_empty_workspace_declares_nothing(self):
        with _Workspace({"notes.txt": "hello\n"}) as root:
            self.assertEqual(execcheck.manifest_commands(root), [])

    def test_a_missing_root(self):
        self.assertEqual(execcheck.manifest_commands(""), [])
        self.assertEqual(execcheck.manifest_commands(os.path.join(tempfile.gettempdir(), "nope-x")),
                         [])

    def test_a_vendor_copy_is_not_the_project(self):
        """The walk skips vendored trees, which is why reusing it matters: a manifest inside
        node_modules/ or vendor/ is a dependency's, not this project's."""
        with _Workspace({"node_modules/dep/package.json": '{"scripts": {"start": "x"}}'}) as root:
            self.assertEqual(execcheck.manifest_commands(root), [])

    def test_what_cria_will_run_is_unchanged(self):
        for cmd in ("curl http://example.com", "bash -c x"):
            with self.subTest(command=cmd):
                self.assertFalse(execcheck._runnable(cmd)[0])
        self.assertFalse(execcheck._runnable("cargo run | tee /tmp/x")[0])


class OneOwnerForWhereTheProjectIsTests(unittest.TestCase):
    def test_it_reads_the_inventory(self):
        import inspect
        self.assertIn("probediscovery.inventory",
                      inspect.getsource(execcheck.manifest_commands))


if __name__ == "__main__":
    unittest.main()
