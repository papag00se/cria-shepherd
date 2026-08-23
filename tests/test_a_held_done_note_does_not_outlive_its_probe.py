"""A satisfaction reason from 3.5 minutes earlier became the session's closing message.

`pending_done_parts` is set by the periodic satisfaction check when it rules the task satisfied,
and is meant to be recomposed once the completion gate's own answer is in — "All checks were run
and they pass" rather than "the reasoner thought so". It was cleared on ONE of the done-probe
branch's three exits: the RED exit and the critic-rejected exit both left it in place, while
`pending_done` is re-set every time the coder claims done again.

Walked on session `01a00ade-b84b-7850-b9ea-e2d8905b2c02` (2026-08-16, the Go cart task):

    14:15:49.553  loop.satisfaction_check satisfied=True   -> parts set
    14:15:49.802  loop.gate plan_off=True blocked=True     -> the probe came back RED; parts survive
    14:17:09      loop.task_complete + completion_probe    -> pending_done = the coder's summary
    14:17:54      loop.done_critic satisfied=False         -> pending_done cleared; parts survive
    14:18:21      loop.task_complete + completion_probe    -> a third coder summary
    14:19:15      loop.done_critic satisfied=True, gate green -> parts truthy, the summary discarded

What shipped was the 14:15 reason: *"decimal module added to go.mod … All tests pass, build and vet
succeed"* — a claim whose very next gate was red, rendered as the session's last word after roughly
35 more model calls.

Rare (1 of 233 satisfaction checks in the whole corpus) and in the worst possible direction: a stale
claim of success, in cria's own voice, as the final message. The pieces are held FOR a probe, so
they are consumed by that probe — once, on whichever way it exits.
"""

import unittest

from cria import loop


class _Rlog:
    phase = ""

    def emit(self, *a, **kw):
        pass


class _Store:
    def mark_done(self, key):
        pass

    def drop(self, key):
        pass


def _ctx():
    """A REAL LoopContext with no reasoner, so the critic branches never fire and the note logic is
    isolated — the red exit continues into a full coder turn, which a hand-rolled double cannot
    carry."""
    from tests.test_loop import _Recorder, _Scripted, _ctx as build, _plan as plan_of, _write
    return build(_Recorder([_write("cart.go", "package main")]), _Scripted([]), plan_of(1))


def _plan():
    from cria.plan import Plan, PlanItem
    return Plan(id="p", task="build the cart", created="c", items=[PlanItem(text="build the cart")])


def _drive(*, errors, parts=("the reasoner said so",)):
    """One done-probe turn whose gate answers `errors`. Returns (completion, session)."""
    saved = loop.guard_gate_verdict
    loop.guard_gate_verdict = lambda *a, **k: errors
    try:
        lp = loop.Loop.__new__(loop.Loop)
        lp._ctx, lp._store = _ctx(), _Store()
        sess = loop.PlanSession(plan=_plan())
        sess.synthetic = True
        sess.done_probe = True
        sess.probe_call_id = "probe1"
        sess.pending_done = "I finished the cart."
        sess.pending_done_parts = parts
        sess.last_gate_ran = True
        body = {"messages": [{"role": "user", "content": "t"},
                             {"role": "tool", "tool_call_id": "probe1", "content": "gate output"}],
                "tools": []}
        return lp._drive_single_item(sess, body, "k1", _Rlog()), sess
    finally:
        loop.guard_gate_verdict = saved


class TheHeldPiecesAreConsumedByTheirOwnProbeTests(unittest.TestCase):
    def test_a_red_gate_does_not_leave_them_for_a_later_probe(self):
        _out, sess = _drive(errors="rates.go:4: undefined: multiplier")
        self.assertEqual(sess.pending_done_parts, ())

    def test_a_green_gate_still_recomposes_from_them(self):
        """The mechanism itself is unchanged — the pieces exist so the note can say what RAN."""
        out, sess = _drive(errors=None)
        text = str(out["choices"][0]["message"]["content"])
        self.assertIn("the reasoner said so", text)
        self.assertEqual(sess.pending_done_parts, ())

    def test_a_green_gate_with_no_held_pieces_keeps_the_coders_own_words(self):
        out, _sess = _drive(errors=None, parts=())
        self.assertIn("I finished the cart.", str(out["choices"][0]["message"]["content"]))

    def test_a_stale_reason_cannot_reach_a_later_completion(self):
        """The whole incident in one assertion: red first, then a later green, and the reason from
        before the red must not be what the session says at the end."""
        saved = loop.guard_gate_verdict
        try:
            lp = loop.Loop.__new__(loop.Loop)
            lp._ctx, lp._store = _ctx(), _Store()
            sess = loop.PlanSession(plan=_plan())
            sess.synthetic = True
            sess.pending_done_parts = ("All tests pass, build and vet succeed",)

            def turn(errors, claim):
                loop.guard_gate_verdict = lambda *a, **k: errors
                sess.done_probe = True
                sess.probe_call_id = "probe1"
                sess.pending_done = claim
                body = {"messages": [{"role": "user", "content": "t"},
                                     {"role": "tool", "tool_call_id": "probe1", "content": "out"}],
                        "tools": []}
                return lp._drive_single_item(sess, body, "k1", _Rlog())

            turn("cart.go:9: undefined: total", "first claim")     # RED
            out = turn(None, "I fixed the cart and the tests pass now.")   # later GREEN
        finally:
            loop.guard_gate_verdict = saved
        text = str(out["choices"][0]["message"]["content"])
        self.assertNotIn("All tests pass, build and vet succeed", text)
        self.assertIn("I fixed the cart", text)


if __name__ == "__main__":
    unittest.main()
