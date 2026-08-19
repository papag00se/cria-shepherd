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

# The live-execution seat this file tested was REMOVED on 2026-08-18 (operator: "drop the
# 'something needs to be ran' assertion altogether — it is more trouble than it is worth").
# The classes that exercised it are gone with it; what remains below tests mechanisms that
# outlived it. See docs/audits/finish-and-remeasure-progress.md for the reasoning.


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


class OneOwnerForWhereTheProjectIsTests(unittest.TestCase):
    def test_it_reads_the_inventory(self):
        """The measured incident itself: a Cargo.toml one directory down from root — `cargo new
        toml-cli` — must still be found. Reading root only (the original bug) finds nothing here."""
        with _Workspace({"toml-cli/Cargo.toml": CARGO, "toml-cli/src/main.rs": "fn main() {}\n"}) as root:
            out = execcheck.manifest_commands(root)
        self.assertIn("cargo run", out)
        self.assertIn("cargo test", out)


if __name__ == "__main__":
    unittest.main()
