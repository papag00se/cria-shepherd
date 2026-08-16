"""The session's last message asserted the repo's checks had verified the work when none ran.

`guard_gate_verdict` returns None twice over: for a gate that ran and was GREEN, and for a gate that
could not run at all — the fail-open every seat in cria honours, so that cria's own inability never
wedges a real 'done'. The completion note read that None one way:

    Task complete — verified by the completion check and the repo's own checks.

and shipped it in both cases. In the second there was nothing to verify against. The same sentence
also went out on the no-shell path, where no gate is composed at all, so the claim was false there
every single time.

#5b: every factual statement cria makes must be true now and backed by a live check. The answer is
`last_gate_ran`, which every gate reader writes since `record_gate_state` became the one mirror —
and the note is composed at RELEASE, when that answer exists, instead of a turn earlier when it does
not. What is held across the turn is the pieces, because the exec_marker costs a reasoner call and
must not be recomputed.

Both wordings live in prompts/satisfaction_done.txt (#22). The unchecked one says what is true and
claims nothing else: the completion check is satisfied, and the repo's own checks could not be run.
"""

import unittest

from cria import loop, prompts

WORDS = prompts.load_map("satisfaction_done")


class TheClaimMatchesWhatHappenedTests(unittest.TestCase):
    def test_a_gate_that_ran_may_claim_it(self):
        note = loop.satisfaction_done_note("The CLI resolves handles.", checks_ran=True)
        self.assertIn("the repo's own checks", note)
        self.assertNotIn("could not be run", note)

    def test_a_gate_that_did_not_run_says_so(self):
        note = loop.satisfaction_done_note("The CLI resolves handles.", checks_ran=False)
        self.assertIn("could not be run", note)
        self.assertNotIn("verified by the completion check and the repo's own checks", note)

    def test_the_reason_survives_both_ways(self):
        for ran in (True, False):
            with self.subTest(checks_ran=ran):
                self.assertIn("The CLI resolves handles.",
                              loop.satisfaction_done_note("The CLI resolves handles.",
                                                          checks_ran=ran))

    def test_the_exec_marker_is_appended_both_ways(self):
        for ran in (True, False):
            with self.subTest(checks_ran=ran):
                note = loop.satisfaction_done_note("done.", "⟦ctx:live-execution⟧ ran ok",
                                                   checks_ran=ran)
                self.assertTrue(note.endswith("⟦ctx:live-execution⟧ ran ok"))

    def test_both_wordings_are_in_a_prompt_file(self):
        self.assertEqual(set(WORDS), {"checked", "unchecked"})
        for body in WORDS.values():
            with self.subTest(body=body[:30]):
                self.assertIn("Task complete", body)

    def test_neither_wording_names_the_shim(self):
        import re
        for body in WORDS.values():
            with self.subTest(body=body[:30]):
                self.assertIsNone(re.search(r"\bcria\b", body, re.I))


class TheNoShellPathStopsClaimingItTests(unittest.TestCase):
    def test_it_passes_checks_ran_false(self):
        """That path composes no gate at all, so the claim was false there every time."""
        import inspect
        src = inspect.getsource(loop.Loop._periodic_satisfaction)
        self.assertIn("satisfaction_done_note(reason, checks_ran=False)", src)


class TheHeldNoteIsRecomposedAtReleaseTests(unittest.TestCase):
    def test_the_pieces_are_what_is_held(self):
        """Composed a turn early, the note would have to guess an answer that does not exist yet."""
        self.assertIn("pending_done_parts", loop.PlanSession.__dataclass_fields__)
        self.assertEqual(loop.GuardState().pending_done_parts, ())

    def test_release_recomposes_from_last_gate_ran(self):
        import inspect
        src = inspect.getsource(loop.Loop._drive_single_item)
        self.assertIn("satisfaction_done_note(*parts, checks_ran=bool(sess.last_gate_ran))", src)

    def test_the_exec_marker_is_not_recomputed(self):
        """It costs a reasoner call; holding the pieces is what keeps it to one."""
        import inspect
        src = inspect.getsource(loop.Loop._periodic_satisfaction)
        self.assertIn("sess.pending_done_parts = (reason, exec_marker)", src)

    def test_a_coder_authored_done_is_untouched(self):
        """`pending_done` also carries the coder's OWN done text on another path; that is prose cria
        did not write and must not rewrite."""
        import inspect
        src = inspect.getsource(loop.Loop._drive_single_item)
        self.assertIn("if parts:", src)


if __name__ == "__main__":
    unittest.main()
