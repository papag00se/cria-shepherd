"""Two things a model must never be shown: what cria is called, and cria's private line numbers.

RULE 17 — the model never sees the literal token "cria". A distinctive proper noun makes a weak
model meta-reason about the mechanism instead of coding. The rule was already tested, but only
against a six-name list from the day it was written, so 138 of the 144 prompt files were never
checked. Two had drifted into naming it: `confirm_auth_claim` ("The facts cria gathered…") and
`periodic_step_claim` ("cria is asking on a cadence…"). This test covers every prompt, so the next
one fails here.

PRIVATE NUMBERING — cria renders the session for the steer author as a numbered list. Whatever the
author writes is injected into the CODER's context, and the coder has no such numbering: it is
cria's own view of the transcript, built for that one call. Measured on the six-language battery,
15 distinct coder-facing steers cited an index the coder could not resolve — "turn 46", "[65]",
"(turn 117)". The worst ordered:

    Restore the content of test/test_rates.rb to its previous working state from turn [15]

which the coder cannot do, because turn 15 exists nowhere it can see. Nothing consumed the numbers:
one call site, and no prompt mentions them. So they are gone.
"""

import pathlib
import re
import unittest

from cria import prompts, selfcompact


# prompts is a package; its own directory holds the .txt files.
PROMPT_DIR = pathlib.Path(prompts.__file__).parent


def _shipped(path: pathlib.Path) -> str:
    """A prompt file's body as a model receives it — `#` lines are cria's notes and never ship."""
    return "\n".join(l for l in path.read_text().splitlines() if not l.lstrip().startswith("#"))


class TheModelNeverSeesTheNameTests(unittest.TestCase):
    def test_every_prompt_file_not_just_a_snapshot_of_them(self):
        files = sorted(PROMPT_DIR.glob("*.txt"))
        self.assertGreater(len(files), 100, "the prompt directory should not have shrunk")
        for p in files:
            with self.subTest(prompt=p.name):
                for n, line in enumerate(_shipped(p).splitlines(), 1):
                    if "⟦cria⟧" in line:      # the human-facing marker, stripped before the model
                        continue
                    self.assertIsNone(re.search(r"\bcria\b", line, re.I),
                                      f"{p.name}:{n} names it to the model: {line.strip()[:120]}")

    def test_the_two_that_had_drifted_are_still_clean(self):
        for name in ("confirm_auth_claim", "periodic_step_claim"):
            with self.subTest(prompt=name):
                self.assertNotIn("cria", prompts.load(name).lower())

    def test_the_marker_itself_is_untouched(self):
        """⟦ctx:…⟧ anchors are the parsing contract and must survive — the rule is about prose."""
        self.assertIn("⟦ctx:", prompts.load("steer_checks_repeat"))


class TheAuthorsTranscriptCarriesNoPrivateIndexTests(unittest.TestCase):
    MESSAGES = [
        {"role": "assistant", "content": "Let me read the test file."},
        {"role": "assistant", "tool_calls": [{"function": {"name": "read_file",
                                                           "arguments": '{"path":"test/test_rates.rb"}'}}]},
        {"role": "tool", "content": "Process exited with code 1\nOutput:\n1 failure"},
        {"role": "assistant", "tool_calls": [{"function": {"name": "write_file",
                                                           "arguments": '{"path":"lib/rates.rb","content":"x"}'}}]},
    ]

    def test_no_bracketed_line_numbers(self):
        out = selfcompact.serialize(self.MESSAGES, defang=True)
        self.assertTrue(out.strip(), "the transcript should not be empty")
        self.assertIsNone(re.search(r"^\s*\[\d+\]", out, re.M),
                          f"a private index survived:\n{out}")

    def test_the_facts_the_author_needs_all_survive(self):
        """Removing the index must not remove what the author reasons from."""
        out = selfcompact.serialize(self.MESSAGES, defang=True)
        for fact in ("test/test_rates.rb", "lib/rates.rb", "read_file", "write_file"):
            self.assertIn(fact, out)

    def test_order_is_preserved_so_recency_is_still_readable(self):
        out = selfcompact.serialize(self.MESSAGES, defang=True)
        self.assertLess(out.index("test/test_rates.rb"), out.index("lib/rates.rb"))

    def test_the_undefanged_rendering_is_unchanged(self):
        """Only the author's view loses the numbering; nothing else used it."""
        out = selfcompact.serialize(self.MESSAGES, defang=False)
        self.assertIsNone(re.search(r"^\s*\[\d+\]", out, re.M))
        self.assertIn("assistant:", out)


if __name__ == "__main__":
    unittest.main()
