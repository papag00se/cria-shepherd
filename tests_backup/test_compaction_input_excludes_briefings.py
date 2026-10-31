"""selfcompact states the rule in its own words: cria's prior briefings are "excluded from the
summarizer input, so cria's OWN prior briefings never become a rollup-of-a-rollup (each round
summarizing the last round's summary is how a transient hallucination hardened into authoritative
misdirection)."

That exclusion was enforced in the self-compaction path only. The HARNESS path fed the previous
briefing straight back in, so a false claim was re-signed every cycle and became unfalsifiable.

Walked on ada-handles_fabliq_codex_pon_1785721353: the compactor asserted "handle_resolver.py has a
syntax error - it's missing a closing parenthesis", was handed its own briefing the next round,
emitted the identical sentence back, and that fixed point rode every prompt for the rest of the run
while cria's own compileall exited 0.
"""
import unittest

from cria import selfcompact, server


class HarnessCompactionInputTests(unittest.TestCase):
    BRIEFING = selfcompact.SUMMARY_MARKER + " handle_resolver.py has a syntax error."
    CONTINUATION = "⟦ctx:continuation⟧ the work so far: a missing closing parenthesis."
    REAL = "I ran pytest and got 3 failed, 1 passed."

    def _transcript(self, *contents):
        # `_compaction_messages` now excludes the harness's ask BY POSITION (the latest user turn),
        # not by matching marker text (C37 B1) — so every fixture here appends a trailing ask turn,
        # exactly how a real compaction call is shaped, and asserts against the EVIDENCE turns before
        # it rather than treating the last supplied content as evidence itself.
        return server._compaction_transcript(
            [{"role": "user", "content": c} for c in contents]
            + [{"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize the thread."}])

    def test_a_prior_rollup_is_not_fed_back_to_the_compactor(self):
        # Assert against the rollup's OWN text. A first version of this test checked for a phrase
        # that was only in the CONTINUATION fixture, so it passed without exercising anything —
        # the self-serving shape the code-health lens exists to catch.
        out = self._transcript(self.REAL, self.BRIEFING)
        self.assertIn("3 failed", out)
        self.assertNotIn("has a syntax error", out)

    def test_a_prior_continuation_is_not_either(self):
        # This one was ALREADY excluded before the fix; kept so it cannot regress.
        out = self._transcript(self.REAL, self.CONTINUATION)
        self.assertNotIn("missing a closing parenthesis", out)

    def test_real_work_still_reaches_it(self):
        self.assertIn("3 failed", self._transcript(self.REAL))

    def test_both_paths_use_the_same_rule(self):
        """One owner: `_compaction_transcript` must call `selfcompact.has_anchor` itself, never a
        private copy of the anchor rule (two copies is how they drift apart). Proven by patching
        the SHARED rule to disagree with its everyday answer and watching the filter follow it —
        a private reimplementation would not move, because it never actually calls this function."""
        from unittest import mock
        with mock.patch.object(server.selfcompact, "has_anchor", lambda m: False):
            out = self._transcript(self.REAL, self.BRIEFING)
        self.assertIn("has a syntax error", out)   # the shared rule now says "nothing is an anchor"

        self.assertTrue(selfcompact.has_anchor({"content": self.BRIEFING}))
        self.assertFalse(selfcompact.has_anchor({"content": self.REAL}))
