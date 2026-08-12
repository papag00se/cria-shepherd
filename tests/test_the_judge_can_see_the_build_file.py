"""cria asked a judge which build tool to run, having deleted every file that says which one.

`runnable_listing` strips data extensions from the workspace listing before a judge picks a program
to run. That guard is right and stays: cria once listed its OWN spilled 96 KB spec as the workspace's
only file, and the judge — forbidden from naming anything off the list — answered with the JSON.

But the blocklist covers `.xml`, `.toml`, `.json` and `.mod`, which is every file that identifies the
build tool. The same prompt then says the command may be *"that tool's own run target — `cargo run`,
`go run .`, `mvn exec:java`, `npm start`, `rake`"* and asks the judge to choose. Measured on the
six-language battery, gemma4's Java run showed the judge one line — `Importer.java` — and it answered:

    There is no `pom.xml` or `build.gradle` listed in the provided file list? … if there's only a
    `.java` file and no build system visible…

so no verification run happened. `execcheck.runnable_listing`'s own docstring records the same loss on
rust, where Cargo.toml and Cargo.lock were stripped.

Manifests are now kept in their own labelled section: enough to name the run target, never presented
as a program. `probediscovery.PRIMARY_MANIFESTS` is the one owner of the set, reused rather than
copied, so a new ecosystem is added in one place.
"""

import unittest

from cria import execcheck, probediscovery


def _listing(*entries: str) -> str:
    return "\n".join([
        "WORKSPACE FILES in /tmp/ws (on-disk ground truth at judging time, newest first):",
        *(f"  {e}" for e in entries),
        "This list is complete — a file not listed here does not exist in the workspace.",
    ])


ECOSYSTEMS = [
    ("java", "src/main/java/pipeline/Importer.java (6783 B)", "pom.xml (1204 B)"),
    ("rust", "src/main.rs (900 B)", "Cargo.toml (210 B)"),
    ("go", "main.go (640 B)", "go.mod (88 B)"),
    ("node", "lookup.js (2100 B)", "package.json (410 B)"),
    ("python", "app.py (3300 B)", "pyproject.toml (180 B)"),
    ("ruby", "lib/shipping/rates.rb (986 B)", "Gemfile (60 B)"),
]


class TheBuildFileSurvivesTheFilterTests(unittest.TestCase):
    def test_every_ecosystem_keeps_the_file_that_names_its_run_target(self):
        for lang, program, manifest in ECOSYSTEMS:
            with self.subTest(language=lang):
                out = execcheck.runnable_listing(_listing(program, manifest))
                self.assertIn(manifest, out, f"{lang}: the build file was stripped")
                self.assertIn(program, out, f"{lang}: the program was stripped")

    def test_the_build_file_is_labelled_so_it_is_never_named_as_the_program(self):
        """The blocklist exists because a judge named a data file as the program. Keeping manifests
        must not re-open that: they appear under their own heading, marked as not programs."""
        out = execcheck.runnable_listing(_listing("src/main.rs (900 B)", "Cargo.toml (210 B)"))
        self.assertIn("BUILD FILES", out)
        self.assertIn("not programs", out)
        self.assertLess(out.index("src/main.rs"), out.index("BUILD FILES"),
                        "the real program must come first")

    def test_the_manifest_set_has_one_owner(self):
        """Reused, not copied — a new ecosystem is added in probediscovery and works here."""
        for name in ("pom.xml", "Cargo.toml", "go.mod", "package.json", "pyproject.toml", "Gemfile"):
            self.assertIn(name, probediscovery.PRIMARY_MANIFESTS)


class WhatTheFilterStillRemovesTests(unittest.TestCase):
    def test_crias_own_spilled_document_is_still_gone(self):
        """The incident the blocklist was built for. A 96 KB fetched spec is not the deliverable."""
        out = execcheck.runnable_listing(_listing("app.py (10 B)", "tmp/read-only/spec.json (96221 B)"))
        self.assertNotIn("spec.json", out)

    def test_ordinary_data_and_documents_are_still_gone(self):
        out = execcheck.runnable_listing(
            _listing("app.py (10 B)", "data/feed.csv (900123 B)", "REVIEW.md (2011 B)",
                     "config.ini (40 B)", "notes.txt (12 B)"))
        for gone in ("feed.csv", "REVIEW.md", "config.ini", "notes.txt"):
            self.assertNotIn(gone, out)

    def test_a_workspace_with_only_a_manifest_returns_nothing(self):
        """A build file alone is not a program, so the honest answer is still the empty list — the
        prompt's own "nothing runnable has been written yet" branch, which it calls correct."""
        self.assertEqual(execcheck.runnable_listing(_listing("pom.xml (1204 B)")), "")

    def test_the_completeness_claim_still_does_not_ride_a_filtered_list(self):
        out = execcheck.runnable_listing(_listing("app.py (10 B)", "data/feed.csv (900123 B)"))
        self.assertNotIn("This list is complete", out)


if __name__ == "__main__":
    unittest.main()
