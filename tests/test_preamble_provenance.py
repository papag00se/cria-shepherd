"""cria may not vouch for instructions it never checked came from this repo.

`reframe_preamble` re-presents a harness's instruction blob as "Project instructions (from the
repo — follow these)". A harness concatenates every instruction file it can see — the operator's
global one and the repo's — so that clause is a claim about provenance cria never verified.

Measured on the six-language battery: it put THIS repo's development doctrine inside an unrelated
/tmp task workspace containing no such file —

    Project instructions (from the repo — follow these):
    # AGENTS
    ## One rule to rule them all:
    Mitigations, fallbacks, and band-aids are strictly prohibited. There is an upstream fix. Find it.

— and nemotron-elastic cited it to justify a destructive rewrite, talking itself past its own
caution to do so: "the instruction says we should not make unnecessary changes; but this is
necessary". A rule written for a long-lived repo is the worst possible instruction for a weak model
that has just formed a wrong theory.

The workspace is the `cwd` the preamble already carries, so the check needs no plumbing.
"""
import tempfile
import unittest
from pathlib import Path

from cria import loop

DOCTRINE = "# AGENTS\n\n## One rule\nMitigations, fallbacks and band-aids are strictly prohibited."
OWN = "# House rules\n\nRun the tests with rake before you claim anything works."


def preamble(cwd, instructions):
    return (f"# AGENTS.md instructions <INSTRUCTIONS>{instructions}</INSTRUCTIONS>"
            f"<environment_context><cwd>{cwd}</cwd><shell>bash</shell></environment_context>")


class ForeignDoctrineIsDroppedTests(unittest.TestCase):
    def test_instructions_from_no_file_in_the_workspace_are_dropped(self):
        with tempfile.TemporaryDirectory() as ws:          # a bare task workspace, as the suite makes
            out = loop._reframe_preamble_text(preamble(ws, DOCTRINE))
        self.assertNotIn("band-aids", out or "", "another repo's doctrine was relayed as this repo's")

    def test_the_environment_fields_survive(self):
        """Dropping the foreign half must not cost the cwd/shell the coder legitimately needs."""
        with tempfile.TemporaryDirectory() as ws:
            out = loop._reframe_preamble_text(preamble(ws, DOCTRINE))
        self.assertIn("bash", out or "")

    def test_the_workspace_own_file_is_relayed(self):
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "AGENTS.md").write_text(OWN)
            out = loop._reframe_preamble_text(preamble(ws, OWN))
        self.assertIn("rake", out)
        self.assertIn("Project instructions", out)

    def test_only_the_workspace_part_of_a_concatenated_blob_survives(self):
        """The observed shape: the harness hands over global doctrine AND the repo's own file."""
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "AGENTS.md").write_text(OWN)
            out = loop._reframe_preamble_text(preamble(ws, DOCTRINE + "\n\n" + OWN))
        self.assertIn("rake", out)
        self.assertNotIn("band-aids", out)

    def test_other_instruction_filenames_count(self):
        for name in ("CLAUDE.md", "CONVENTIONS.md", ".cursorrules"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as ws:
                Path(ws, name).write_text(OWN)
                self.assertIn("rake", loop._reframe_preamble_text(preamble(ws, OWN)) or "")

    def test_a_missing_or_unreadable_cwd_drops_rather_than_vouches(self):
        out = loop._reframe_preamble_text(preamble("/nonexistent/nowhere", DOCTRINE))
        self.assertNotIn("band-aids", out or "")

    def test_no_cwd_at_all_drops_the_instructions(self):
        text = f"<INSTRUCTIONS>{DOCTRINE}</INSTRUCTIONS>"
        self.assertNotIn("band-aids", loop._reframe_preamble_text(text) or "")


if __name__ == "__main__":
    unittest.main()
