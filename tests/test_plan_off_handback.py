"""Plan-off gets a READING STEP and nothing else of the plan machinery.

Operator contract (2026-08-04): "All that was supposed to happen is a research step, on both
plan-off and plan-on." What shipped on 08-03 (ef0b771) instead drove a 2-item plan-off session
through the FULL multi-step machinery — "Do ONLY this step (k of n), then stop" framing, hidden
later steps, and living replans that split the user's task into more steps. Audited: gemma4 at
temperature 0 went ladder 4/4 → campaign 0/4 twice, both runs pinned on step 1 for ~86-89 coder
calls with the README structurally unreachable.

The contract now enforced here:
- the reading step IS driven (framed, critic-gated) — that was 08-03's legitimate fix;
- the moment the current item is the RAW TASK, the session flips to the synthetic single-item
  drive (raw-task framing, plan-off off-ramps, no step cage);
- the living re-derivation NEVER runs on a plan-off session — the tail is the user's own task,
  not a planner guess to refine.
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
    def test_two_item_plan_off_session_is_marked(self):
        sess = _two_item_sess()
        self.assertTrue(sess.plan_off)
        self.assertFalse(sess.synthetic)          # the reading step IS driven by the step machinery

    def test_reading_step_cleared_hands_back_to_raw_task_drive(self):
        # FAILS BEFORE THE FIX: the task item was framed "step 2 of 2 … then stop" by the
        # multi-item driver; now the session flips to synthetic and the coder sees the raw task.
        store = LoopStore()
        coder = _Scripted([_toolcall()])
        ctx = LoopContext(planner=_Planner(), coder_chat=coder, reasoner_chat=_Scripted([_toolcall()]),
                          runs_dir="")
        loop = Loop(ctx, store)
        sess = _two_item_sess()
        sess.plan.items[0].done = True            # the reading step verified
        store.put("sid:k", sess)
        rlog = _Rlog()
        loop.drive(_body(), "sid:k", None, rlog)
        self.assertTrue(sess.synthetic)           # handed back to the single-item drive
        self.assertIn("loop.plan_off_handback", rlog.kinds())
        sent = json.loads(json.dumps(coder.__dict__))  # coder was called via the synthetic path
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
        sess.plan.items[0].done = True
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


class ReadingCheckClearsPlanOffStepTests(unittest.TestCase):
    """The reading check may COMPLETE the plan-off reading step (and only that).

    Walked run ada-handles_gemma4_codex_poff_1785861503: the reading was ledger-complete by call
    12, the repo went red on step-2 work, and weak critics refused the reading step for 247 calls
    — the hand-back never fired. Scope guards keep 1785812224's second-completion-authority defect
    dead: plan-off only, never the task item, DONE only (grounded sources required upstream)."""

    def _loop_with_verdict(self, verdict):
        reasoner = _Scripted([{"choices": [{"message": {"content": json.dumps({"verdict": verdict})}}]}])
        ctx = LoopContext(planner=_Planner(), coder_chat=_Scripted([_toolcall()]),
                          reasoner_chat=reasoner, runs_dir="")
        from cria.config import Role
        ctx.reasoner_role = Role(name="reasoner", backend="local")
        return Loop(ctx, LoopStore())

    def _grounded(self):
        # the deterministic gather, patched: the unit under test is the DONE branch, not the
        # ledger parser (which has its own tests)
        from unittest import mock
        return mock.patch("cria.loop.research.sources_read",
                          return_value=[("https://api.handle.me/openapi.json",
                                         "/handles/{handle}", "holder, resolved_addresses.ada")])

    def test_done_clears_the_reading_step_on_plan_off(self):
        import cria.research as research
        loop = self._loop_with_verdict("DONE")
        sess = _two_item_sess()
        sess.coder_turns = research.RESEARCH_CHECK_EVERY   # the check's cadence tick
        rlog = _Rlog()
        with self._grounded():
            out = loop._research_check(sess, "k", _body(), 1, 2, rlog)
        self.assertTrue(sess.plan.items[0].done)           # the reading step is VERIFIED
        self.assertIn("loop.reading_step_cleared", rlog.kinds())
        self.assertIsNotNone(out)                          # the driven next turn came back

    def test_done_on_planner_on_session_still_only_reports(self):
        import cria.research as research
        loop = self._loop_with_verdict("DONE")
        plan = Plan(id="x", task=TASK, created="c",
                    items=[PlanItem(text="Read the spec to learn the shapes"), PlanItem(text="build it")])
        sess = _plan_off_session(plan, "")
        sess.plan_off = False                              # a genuine planner session
        sess.coder_turns = research.RESEARCH_CHECK_EVERY
        rlog = _Rlog()
        with self._grounded():
            out = loop._research_check(sess, "k", _body(), 1, 2, rlog)
        self.assertFalse(sess.plan.items[0].done)          # 1785812224 regression guard: report only
        self.assertIsNone(out)
        self.assertIn("loop.research_satisfied", rlog.kinds())


if __name__ == "__main__":
    unittest.main()
