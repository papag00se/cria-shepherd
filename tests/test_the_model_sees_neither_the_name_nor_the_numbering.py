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


def _consumed_by_load_map() -> set[str]:
    """Prompt names read through `load_map`, which is the ONLY reader that strips `#` lines."""
    src = "\n".join(p.read_text() for p in pathlib.Path("cria").rglob("*.py"))
    return set(re.findall(r'load_map\(\s*["\']([\w-]+)["\']', src))


MAPPED = _consumed_by_load_map()


def _shipped(path: pathlib.Path) -> str:
    """A prompt file's body AS THE MODEL RECEIVES IT.

    `#` lines are stripped only for prompts read through `load_map`. `prompts.load` and `render`
    return the file verbatim, so in those a `#` line is either a markdown heading the model is meant
    to read (coder_system's "# Rules") or a rationale note that ships by accident. An earlier version
    of this helper stripped `#` everywhere and would have passed a comment block naming the program
    straight through to the model — which is exactly the leak these tests exist to catch."""
    body = path.read_text()
    if path.stem in MAPPED:
        return "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    return body


class TheNameMustNotRIDEINACOMMANDEitherTests(unittest.TestCase):
    """Prompt files were covered; COMPOSED COMMANDS were not, and that is where it actually leaked.

    `_COMPILEALL_SKIP_RE` carried `\\.cria` in its skip list, and the coder reads the gate's command
    line: 2,050 captured coder prompts contained it. It was also dead — cria writes only inside its
    own directory and never into the workspace (#7), so no tree this floor walks can hold one.

    #17's own words: internal tokens can be copied into executable commands, so the rule has to hold
    anywhere cria composes content the model may read OR RUN, not only in the prompt files."""

    NAME = re.compile(r"\bcria\b", re.I)

    def _project(self, tmp):
        (tmp / "app.py").write_text("print(1)\n")
        (tmp / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp / "index.js").write_text("console.log(1)\n")
        (tmp / "package.json").write_text('{"name": "x"}\n')
        return tmp

    def test_no_floor_command_names_it(self):
        import pathlib as _pl
        import tempfile

        from cria import probediscovery
        with tempfile.TemporaryDirectory() as d:
            root = self._project(_pl.Path(d))
            cands = probediscovery.syntax_floor_candidates(root)
            self.assertTrue(cands, "the fixture should produce at least one floor probe")
            for c in cands:
                for arg in c.command:
                    with self.subTest(arg=arg[:60]):
                        self.assertIsNone(self.NAME.search(str(arg)))

    def test_no_discovered_command_names_it(self):
        import pathlib as _pl
        import tempfile

        from cria import probediscovery
        with tempfile.TemporaryDirectory() as d:
            root = self._project(_pl.Path(d))
            for c in probediscovery.discover(root):
                for arg in c.command:
                    with self.subTest(arg=str(arg)[:60]):
                        self.assertIsNone(self.NAME.search(str(arg)))

    def test_the_named_gap_steer_does_not_name_it(self):
        """It appends cria's own unresolved findings to a steer that would otherwise name nothing.
        It said "What cria's own checks currently report" — inline, in code, both rules broken at
        once (#17 and #22: model-facing strings live in prompt files)."""
        from cria import loop
        out = loop._named_gap("app.py:3: undefined name 'foo'")
        self.assertIn("undefined name", out)
        self.assertIsNone(self.NAME.search(out))

    def test_an_empty_finding_stays_silent(self):
        from cria import loop
        self.assertEqual(loop._named_gap(""), "")
        self.assertEqual(loop._named_gap("   "), "")


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

    def test_a_rationale_comment_in_a_load_prompt_would_be_caught(self):
        """The trap: `load`/`render` do not strip `#`, so a note left in one of those files is sent
        to the model. Proven against a temporary file rather than by assertion."""
        tmp = PROMPT_DIR / "_ruleseventeen_probe.txt"
        tmp.write_text("# cria uses this to nudge the coder\nDo the thing.\n")
        try:
            self.assertNotIn(tmp.stem, MAPPED, "the probe must exercise the load/render path")
            body = _shipped(tmp)
            self.assertIn("cria", body.lower(), "the comment must survive — that is the hazard")
        finally:
            tmp.unlink()

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
