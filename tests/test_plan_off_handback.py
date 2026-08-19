"""Plan-off gets NO plan machinery: one item, the raw task, no step cage, no replans.

Operator contract (2026-08-04): "All that was supposed to happen is a research step, on both
plan-off and plan-on." What shipped on 08-03 (ef0b771) instead drove a 2-item plan-off session
through the FULL multi-step machinery — "Do ONLY this step (k of n), then stop" framing, hidden
later steps, and living replans that split the user's task into more steps. Audited: gemma4 at
temperature 0 went ladder 4/4 -> campaign 0/4 twice, both runs pinned on step 1 for ~86-89 coder
calls with the README structurally unreachable.

**The reading step itself was removed on 2026-08-19**
(`docs/audits/base-vs-cria-footgun-patterns.md`), which is what made a plan-off plan two items in
the first place. So the contract simplifies to what it should always have been, and these tests hold
the line against re-growing it:

- a plan-off session is ALWAYS synthetic — one item, whose text is the user's own task;
- its framing is the raw task, with no "Do ONLY this step (k of n)" cage;
- the living re-derivation NEVER runs on it — the tail is the user's task, not a planner guess.

A two-item plan-off session is constructed by hand below precisely because nothing builds one any
more: if some future path starts to, the driver must still hand back to the raw task rather than
cage it.
"""

import json
import unittest

from cria.loop import Loop, LoopContext, LoopStore, _plan_off_session, _synthetic_plan
from cria.plan import Plan, PlanItem


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


class _Scripted:
    def __init__(self, responses):
        self._r = list(responses)
        self.calls = 0

    def __call__(self, body, rlog):
        self.calls += 1
        r = self._r.pop(0) if len(self._r) > 1 else self._r[0]
        return json.dumps(r).encode()


class _Planner:
    def plan_for(self, messages, rlog, prior_work="", rewrite_summary=""):
        return None


def _toolcall():
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]}}]}


_SHELL = {"type": "function", "function": {"name": "shell", "parameters": {
    "type": "object", "properties": {"command": {"type": "array"}}}}}
TASK = "build an ada handle resolver with tests and a README"


def _body():
    return {"messages": [{"role": "user", "content": TASK}], "tools": [_SHELL], "stream": True}


def _two_item_sess():
    plan = Plan(id="x", task=TASK, created="c",
                items=[PlanItem(text="Read api.handle.me to learn its response shapes"),
                       PlanItem(text=TASK)])
    return _plan_off_session(plan, "")


class PlanOffHandbackTests(unittest.TestCase):
    def test_a_synthesized_plan_off_plan_has_exactly_one_item(self):
        """The removal, asserted at its source: nothing cria synthesizes is more than the task."""
        from cria.loop import _synthetic_plan
        plan = _synthetic_plan(TASK)
        self.assertEqual([it.text for it in plan.items], [TASK])
        self.assertTrue(_plan_off_session(plan, "").synthetic)

    def test_a_plan_off_session_is_synthetic_whatever_it_was_handed(self):
        """Even a hand-built two-item plan drives as the raw task — the cage has no way back in."""
        sess = _two_item_sess()
        self.assertTrue(sess.plan_off)
        self.assertTrue(sess.synthetic)

    def test_the_coder_is_driven_once_through_the_synthetic_path(self):
        store = LoopStore()
        coder = _Scripted([_toolcall()])
        ctx = LoopContext(planner=_Planner(), coder_chat=coder, reasoner_chat=_Scripted([_toolcall()]),
                          runs_dir="")
        loop = Loop(ctx, store)
        sess = _two_item_sess()
        store.put("sid:k", sess)
        loop.drive(_body(), "sid:k", None, _Rlog())
        self.assertTrue(sess.synthetic)
        self.assertEqual(coder.calls, 1)

    def test_handback_framing_is_the_raw_task_not_a_step(self):
        store = LoopStore()
        seen = {}

        def coder(body, rlog):
            seen["msgs"] = body["messages"]
            return json.dumps(_toolcall()).encode()
        ctx = LoopContext(planner=_Planner(), coder_chat=coder, reasoner_chat=_Scripted([_toolcall()]),
                          runs_dir="")
        loop = Loop(ctx, store)
        sess = _two_item_sess()
        store.put("sid:k", sess)
        loop.drive(_body(), "sid:k", None, _Rlog())
        joined = " ".join(str(m.get("content") or "") for m in seen["msgs"])
        self.assertIn(TASK, joined)                                  # the raw task is the ask
        self.assertNotIn("Do ONLY this step", joined)                # no step cage
        self.assertNotIn("(2 of 2)", joined)

    def test_replans_never_run_on_plan_off(self):
        # The living re-derivation must not split the user's task into steps. _advance on a
        # plan-off session skips _replan_tail entirely (reasoner never asked for a new tail).
        reasoner = _Scripted([_toolcall()])
        ctx = LoopContext(planner=_Planner(), coder_chat=_Scripted([_toolcall()]),
                          reasoner_chat=reasoner, runs_dir="")
        loop = Loop(ctx, LoopStore())
        sess = _two_item_sess()
        rlog = _Rlog()
        out = loop._advance(sess, "sid:k", _body(), 1, 2, rlog)
        self.assertNotIn("loop.replan", rlog.kinds())
        self.assertNotIn("loop.replan_noise", rlog.kinds())
        self.assertEqual([it.text for it in sess.plan.items][-1], TASK)  # the task item is intact

    def test_one_item_plan_off_unchanged(self):
        plan = Plan(id="x", task=TASK, created="c", items=[PlanItem(text=TASK)])
        sess = _plan_off_session(plan, "")
        self.assertTrue(sess.synthetic)
        self.assertTrue(sess.plan_off)


class TheReadingCheckIsGoneTests(unittest.TestCase):
    """It cleared the reading step, and there is no reading step. Walked run
    ada-handles_gemma4_codex_poff_1785861503 is why it existed: the reading was ledger-complete by
    call 12 and weak critics refused the step for 247 calls. Removing the step removes the trap the
    check was built to escape, so the check goes with it — and the second-completion-authority
    defect it was scoped against (run 1785812224) loses its last route in."""

    def test_the_driver_no_longer_carries_a_reading_check(self):
        self.assertFalse(hasattr(Loop, "_research_check"))

    def test_nothing_asks_a_model_to_author_a_reading_step(self):
        import cria.research as research
        self.assertFalse(hasattr(research, "authored_research_step"))
        self.assertFalse(hasattr(research, "step_reading_verdict"))

    def test_the_facts_it_gathered_are_still_gathered(self):
        """What survives is the deterministic half — judges and steers still get real sources."""
        import cria.research as research
        self.assertTrue(callable(research.sources_read))
        self.assertEqual(research.grounded_sources({"u": ("200", "/handles/{h}", "holder")}),
                         [("u", "/handles/{h}", "holder")])
        self.assertEqual(research.grounded_sources({"u": ("200", "", "")}), [])


if __name__ == "__main__":
    unittest.main()
