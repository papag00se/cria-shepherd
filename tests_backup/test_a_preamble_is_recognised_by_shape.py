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

That shape-based repair was unsafe too: a complete closed block can itself be the request.
The same collision and task-loss incidents now guard preserving the entire initial user prelude,
not guessing which packet is a banner. Retaining extra context beats losing a real requirement.
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


class UnprovenUserPreamblesAreRetainedTests(unittest.TestCase):
    def test_known_spellings_do_not_prove_harness_origin(self):
        for name, text in (("codex", CODEX), ("codex+agents", CODEX_AGENTS),
                           ("cline/roo", CLINE), ("system banner", ROO)):
            with self.subTest(harness=name):
                self.assertFalse(selfcompact.is_env_context(_u(text)))
                self.assertFalse(contextfloor._is_env_preamble(_u(text)))
                self.assertEqual(loop._history_root([_u(text), _u("the actual task")])[0],
                                 text + "\n\nthe actual task")

    def test_prose_is_never_mistaken_for_one(self):
        """Including prose that names a component whose name carries the same word."""
        for text in PROSE:
            with self.subTest(text=text):
                self.assertFalse(selfcompact.is_env_context(_u(text)))
                self.assertFalse(contextfloor._is_env_preamble(_u(text)))

    def test_the_two_owners_answer_the_same_way(self):
        """Both compatibility entry points use the same role authority, never tag guesses."""
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
    def test_both_initial_context_and_actual_task_are_protected(self):
        msgs = [_u(CLINE), _u("build the shipping module"),
                {"role": "assistant", "content": "ok"}]
        mask = contextfloor._protected_mask(msgs)
        self.assertTrue(mask[0], "unproven initial user context must not be discarded")
        self.assertTrue(mask[1], "the real task was left droppable")


if __name__ == "__main__":
    unittest.main()
