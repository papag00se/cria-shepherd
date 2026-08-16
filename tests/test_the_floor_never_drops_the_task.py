"""The context floor may not delete the user's task.

The floor's active span is "the last user message onward", so the task is protected only while
nothing follows it. cria itself injects user-role turns after it — the reasoned steer, and
focus-trim's repeat notes — and the moment one lands the task becomes the OLDEST droppable turn and
is the first thing the floor deletes.

Measured across one day of real sessions: 53 of 1,475 coder prompts shipped with no task in them, in
8 of 22 sessions. 15 traced to cria's own steer, 12 to focus-trim's notes. In one, the model's only
standing instruction left was the steer: it reasoned "use float64 instead of decimal" and edited the
test to undo the decimal work the task had asked for.

`⟦ctx:task⟧` is already a protected marker, but self-compaction only emits it once it fires, and the
floor starts dropping at a far lower budget than self-compaction triggers at — so on the plan-off
path the raw task carries no marker for most of a session. Protecting it structurally needs no
marker and adds nothing to what the model reads.
"""

import unittest

from cria import contextfloor, selfcompact


TASK = "Fix the rounding bug causing totals to be one cent low. Stop using float64 for money."
BANNER = "<environment_context>\n  <cwd>/tmp/ws</cwd>\n</environment_context>"


def u(t):
    return {"role": "user", "content": t}


def a(t):
    return {"role": "assistant", "content": t}


class TheTaskSurvivesTests(unittest.TestCase):
    def mask(self, msgs):
        return contextfloor._protected_mask(msgs)

    def test_the_task_is_protected_once_a_steer_follows_it(self):
        msgs = [{"role": "system", "content": "sys"}, u(TASK), a("ok"),
                u("⟦ctx:steer⟧ read cart.go then fix the rounding")]
        m = self.mask(msgs)
        self.assertTrue(m[1], "the task was droppable with a steer after it")

    def test_the_harness_banner_is_not_mistaken_for_the_task(self):
        msgs = [u(BANNER), u(TASK), a("ok"), u("⟦ctx:steer⟧ go")]
        m = self.mask(msgs)
        self.assertTrue(m[1], "the real task must be the protected one")
        self.assertFalse(m[0], "the env preamble is not the task")

    def test_a_transcript_with_only_a_banner_protects_nothing_extra(self):
        msgs = [u(BANNER), a("ok"), u("⟦ctx:steer⟧ go")]
        self.assertFalse(self.mask(msgs)[0])

    def test_the_active_span_is_still_protected(self):
        msgs = [u(TASK), a("x"), u("latest"), a("y")]
        m = self.mask(msgs)
        self.assertTrue(m[2] and m[3])

    def test_the_task_survives_a_real_drop_to_a_tiny_budget(self):
        """End to end through the dropper, not just the mask."""
        msgs = [{"role": "system", "content": "sys"}, u(TASK)]
        for i in range(40):
            msgs += [a("filler " * 200), u("filler note " + str(i))]
        kept, _ = contextfloor._drop_oldest(msgs, 400)
        self.assertTrue(any(TASK in (m.get("content") or "") for m in kept),
                        "the task was dropped")


class TheEnvPredicateStaysInSyncTests(unittest.TestCase):
    """contextfloor imports nothing by design, so its copy of the tokens is checked against the
    owner rather than shared — the same convention _PROTECT_MARKERS already uses."""

    def test_both_recognise_the_same_preambles(self):
        for t in (BANNER, "<user_instructions>do x</user_instructions>"):
            self.assertTrue(contextfloor._is_env_preamble(u(t)), t)
            self.assertTrue(selfcompact.is_env_context(u(t)), t)

    def test_neither_claims_a_real_task_is_a_preamble(self):
        self.assertFalse(contextfloor._is_env_preamble(u(TASK)))
        self.assertFalse(selfcompact.is_env_context(u(TASK)))


if __name__ == "__main__":
    unittest.main()
