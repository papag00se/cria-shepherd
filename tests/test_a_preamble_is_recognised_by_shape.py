"""Two Codex tags decided which message is the task, on every harness.

`selfcompact.is_env_context` was `"<environment_context>" in c or "<user_instructions>" in c` —
Codex's two spellings and nobody else's. Cline and Roo send `<environment_details>`: the same idea,
a different word. Two consumers get this question wrong in ways that matter.

`contextfloor._protected_mask` picks the first NON-preamble user message as the task and protects it
from the drop-oldest lever. With an unrecognised preamble it protects the BANNER and leaves the real
task droppable — its own docstring records the cost: *"53 of 1,475 coder prompts shipped with no
task in them, in 8 of 22 sessions."*

`loop.session_key` keys on the first non-preamble user message. An unrecognised preamble is stable
across a whole workspace, so every conversation in one repo collides onto ONE `task:` key —
reproduced with a Cline-shaped preamble:

    non-Codex preamble: task:dfe222ec…  task:dfe222ec…   COLLIDE
    Codex preamble    : task:5c8a91b8…  task:22b3f6d2…   distinct

`session_key`'s own docstring describes that collision as a fixed bug: a new task looked like a
compaction-rewrite of the old one, and the old conversation's briefing leaked into it.

The kernel is the tag NAME — a harness names its preamble for what it is — and the CLOSING tag is
what keeps it safe: "Fix the bug in <Context> so it renders" is a React component in prose, and
reading it as a preamble would say this message is NOT the task, which is the same damage from the
other side.
"""

import unittest

from cria import contextfloor, loop, selfcompact

CODEX = "<environment_context><cwd>/ws</cwd></environment_context>"
CODEX_AGENTS = ("# AGENTS.md instructions <INSTRUCTIONS>be careful</INSTRUCTIONS>"
                "<environment_context><cwd>/ws</cwd></environment_context>")
CLINE = "<environment_details>\n# VSCode Visible Files\nlib/app.rb\n</environment_details>"
ROO = "<system_information>os: linux\nshell: bash</system_information>"

PROSE = ("build an ada handle resolver",
         "Fix the bug in <Context> so it renders",
         "Use React context; see <ContextProvider> below")


def _u(text):
    return {"role": "user", "content": text}


class EveryHarnessPreambleIsRecognisedTests(unittest.TestCase):
    def test_the_conventions_cria_has_met(self):
        for name, text in (("codex", CODEX), ("codex+agents", CODEX_AGENTS),
                           ("cline/roo", CLINE), ("system banner", ROO)):
            with self.subTest(harness=name):
                self.assertTrue(selfcompact.is_env_context(_u(text)))
                self.assertTrue(contextfloor._is_env_preamble(_u(text)))

    def test_prose_is_never_mistaken_for_one(self):
        """Including prose that names a component whose name carries the same word."""
        for text in PROSE:
            with self.subTest(text=text):
                self.assertFalse(selfcompact.is_env_context(_u(text)))
                self.assertFalse(contextfloor._is_env_preamble(_u(text)))

    def test_the_two_owners_answer_the_same_way(self):
        """`contextfloor` imports nothing, so the rule is stated twice on purpose — and must agree."""
        for text in (CODEX, CODEX_AGENTS, CLINE, ROO, *PROSE):
            with self.subTest(text=text[:40]):
                self.assertEqual(selfcompact.is_env_context(_u(text)),
                                 contextfloor._is_env_preamble(_u(text)))


class TwoTasksInOneWorkspaceDoNotCollideTests(unittest.TestCase):
    def _key(self, preamble, task):
        return loop.session_key(None, [_u(preamble), _u(task)])

    def test_a_cline_preamble_no_longer_collides_every_conversation(self):
        a = self._key(CLINE, "build the shipping module")
        b = self._key(CLINE, "write a CSV importer")
        self.assertNotEqual(a, b)

    def test_codex_was_already_right_and_stays_right(self):
        self.assertNotEqual(self._key(CODEX, "task one"), self._key(CODEX, "task two"))

    def test_the_same_task_still_correlates_across_requests(self):
        self.assertEqual(self._key(CLINE, "build the shipping module"),
                         self._key(CLINE, "build the shipping module"))


class TheTaskIsWhatGetsProtectedTests(unittest.TestCase):
    def test_the_real_task_is_protected_not_the_banner(self):
        msgs = [_u(CLINE), _u("build the shipping module"),
                {"role": "assistant", "content": "ok"}]
        mask = contextfloor._protected_mask(msgs)
        self.assertFalse(mask[0], "the harness banner was protected as the task")
        self.assertTrue(mask[1], "the real task was left droppable")


if __name__ == "__main__":
    unittest.main()
