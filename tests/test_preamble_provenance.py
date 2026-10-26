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

A matching workspace file establishes only that text's provenance, never the enclosing
user packet's origin. Keep the original incident and positive workspace-reader controls,
but assert that public framing abstains and preserves all literal user bytes.
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
    def assert_literal_user_packet(self, text):
        packet = {"role": "user", "content": text}
        before = dict(packet)
        self.assertEqual(loop.reframe_preamble(packet), before)
        self.assertEqual(packet, before)
        self.assertIsNone(loop._reframe_preamble_text(text))  # no claimed reframe/provenance

    def test_instructions_from_no_file_in_the_workspace_are_dropped(self):
        with tempfile.TemporaryDirectory() as ws:          # a bare task workspace, as the suite makes
            self.assert_literal_user_packet(preamble(ws, DOCTRINE))
            self.assertIsNone(loop._workspace_instructions(ws, DOCTRINE))

    def test_the_environment_fields_survive(self):
        """Abstention must retain the whole environment, not just extracted cwd/shell fields."""
        with tempfile.TemporaryDirectory() as ws:
            self.assert_literal_user_packet(preamble(ws, DOCTRINE))

    def test_the_workspace_own_file_is_relayed(self):
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "AGENTS.md").write_text(OWN)
            self.assert_literal_user_packet(preamble(ws, OWN))
            self.assertEqual(loop._workspace_instructions(ws, OWN), OWN.strip())

    def test_only_the_workspace_part_of_a_concatenated_blob_survives(self):
        """The observed shape: the harness hands over global doctrine AND the repo's own file."""
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "AGENTS.md").write_text(OWN)
            combined = DOCTRINE + "\n\n" + OWN
            self.assert_literal_user_packet(preamble(ws, combined))
            self.assertEqual(loop._workspace_instructions(ws, combined), OWN.strip())

    def test_other_instruction_filenames_count(self):
        for name in ("CLAUDE.md", "CONVENTIONS.md", ".cursorrules"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as ws:
                Path(ws, name).write_text(OWN)
                self.assert_literal_user_packet(preamble(ws, OWN))
                self.assertEqual(loop._workspace_instructions(ws, OWN), OWN.strip())

    def test_a_missing_or_unreadable_cwd_drops_rather_than_vouches(self):
        self.assert_literal_user_packet(preamble("/nonexistent/nowhere", DOCTRINE))
        self.assertIsNone(loop._workspace_instructions("/nonexistent/nowhere", DOCTRINE))

    def test_no_cwd_at_all_drops_the_instructions(self):
        text = f"<INSTRUCTIONS>{DOCTRINE}</INSTRUCTIONS>"
        self.assert_literal_user_packet(text)
        self.assertIsNone(loop._workspace_instructions("", DOCTRINE))


if __name__ == "__main__":
    unittest.main()
