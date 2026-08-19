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
not. What is held across the turn is the pieces (the live-execution marker that used to ride with
them was removed on 2026-08-18) and
must not be recomputed.

Both wordings live in prompts/satisfaction_done.txt (#22). The unchecked one says what is true and
claims nothing else: the completion check is satisfied, and the repo's own checks could not be run.
"""

import unittest

from cria import loop, prompts
from cria.plan import Plan, PlanItem

WORDS = prompts.load_map("satisfaction_done")


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class _Ctx:
    """A minimal LoopContext double — only the attributes `_periodic_satisfaction` and
    `_drive_single_item` actually read."""
    reasoner_chat = object()
    reasoner_role = None   # no reasoner → the critic branches never fire, isolating the note logic
    satisfaction_check_start = 1   # due at drive_count == 1, the drive every test below uses
    satisfaction_check_every = 1
    workspace_root = None


def _plan():
    return Plan(id="x", task="build it", created="c", items=[PlanItem("step 1")])


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
        """That path composes no gate at all, so the claim was false there every time. Drive the
        real off-ramp with a harness that advertises NO shell tool (`guard_gate_op`'s only source
        of "no gate") and read the note it actually sends — a source-text grep for the `checks_ran=`
        spelling cannot tell a kwarg that is wired correctly from one that is wired to the wrong
        value."""
        saved = (loop.judge_satisfaction, loop._satisfaction_evidence, loop._gate_notes)
        loop.judge_satisfaction = lambda *a, **k: (True, "the CLI resolves handles", "")
        loop._satisfaction_evidence = lambda *a, **k: "evidence"
        loop._gate_notes = lambda *a, **k: ""
        try:
            lp = loop.Loop.__new__(loop.Loop)
            lp._ctx = _Ctx()
            sess = loop.PlanSession(plan=_plan())
            sess.drive_count = 1
            body = {"messages": [{"role": "user", "content": "t"}], "tools": []}   # no shell tool
            out = lp._periodic_satisfaction(sess, body, _Rlog(), plan_off=True, blocked=False)
        finally:
            loop.judge_satisfaction, loop._satisfaction_evidence, loop._gate_notes = saved
        self.assertIn("could not be run", loop._completion_text(out))


class TheHeldNoteIsRecomposedAtReleaseTests(unittest.TestCase):
    def test_the_pieces_are_what_is_held(self):
        """Composed a turn early, the note would have to guess an answer that does not exist yet."""
        self.assertIn("pending_done_parts", loop.PlanSession.__dataclass_fields__)
        self.assertEqual(loop.GuardState().pending_done_parts, ())

    def _drive_with_gate(self, *, pending_done, pending_done_parts, last_gate_ran):
        """Drives `_drive_single_item` up to and through a green completion-gate verdict — the
        release point where the held pieces (or the coder's own prose) become the final note."""
        saved = loop.guard_gate_verdict
        loop.guard_gate_verdict = lambda *a, **k: None   # green: no findings
        try:
            lp = loop.Loop.__new__(loop.Loop)
            lp._ctx = _Ctx()
            sess = loop.PlanSession(plan=_plan())
            sess.done_probe = True
            sess.probe_call_id = "probe1"
            sess.pending_done = pending_done
            sess.pending_done_parts = pending_done_parts
            sess.last_gate_ran = last_gate_ran
            body = {"messages": [{"role": "user", "content": "t"},
                                 {"role": "tool", "tool_call_id": "probe1", "content": "gate ran clean"}],
                    "tools": []}
            return lp._drive_single_item(sess, body, "k1", _Rlog())
        finally:
            loop.guard_gate_verdict = saved

    def test_release_recomposes_from_last_gate_ran(self):
        """Same held pieces, only `last_gate_ran` differs — the note's claim must track it, not the
        stale guess that was true when the pieces were parked a turn earlier."""
        ran = self._drive_with_gate(pending_done="stale", pending_done_parts=("the CLI resolves handles",),
                                    last_gate_ran=True)
        not_ran = self._drive_with_gate(pending_done="stale", pending_done_parts=("the CLI resolves handles",),
                                        last_gate_ran=False)
        self.assertIn("the repo's own checks", loop._completion_text(ran))
        self.assertNotIn("could not be run", loop._completion_text(ran))
        self.assertIn("could not be run", loop._completion_text(not_ran))

    def test_the_exec_marker_is_not_recomputed(self):
        """It costs a reasoner call; holding the pieces is what keeps it to one. `_periodic_satisfaction`
        parks the reason as `pending_done_parts` rather than re-deriving it at release."""
        saved = (loop.judge_satisfaction, loop._satisfaction_evidence, loop._gate_notes)
        loop.judge_satisfaction = lambda *a, **k: (True, "the resolver handles the live spec", "")
        loop._satisfaction_evidence = lambda *a, **k: "evidence"
        loop._gate_notes = lambda *a, **k: ""
        try:
            lp = loop.Loop.__new__(loop.Loop)
            lp._ctx = _Ctx()
            sess = loop.PlanSession(plan=_plan())
            sess.drive_count = 1
            _SHELL = {"type": "function", "function": {"name": "shell",
                     "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}
            body = {"messages": [{"role": "user", "content": "t"}], "tools": [_SHELL]}
            lp._periodic_satisfaction(sess, body, _Rlog(), plan_off=True, blocked=False)
        finally:
            loop.judge_satisfaction, loop._satisfaction_evidence, loop._gate_notes = saved
        self.assertEqual(sess.pending_done_parts, ("the resolver handles the live spec",))

    def test_a_coder_authored_done_is_untouched(self):
        """`pending_done` also carries the coder's OWN done text on another path (no pieces parked
        for it, `pending_done_parts` stays empty); that is prose cria did not write and must not
        rewrite at release."""
        out = self._drive_with_gate(pending_done="I already wrote hello.py and it works.",
                                    pending_done_parts=(), last_gate_ran=True)
        self.assertEqual(loop._completion_text(out), "I already wrote hello.py and it works.")


if __name__ == "__main__":
    unittest.main()
