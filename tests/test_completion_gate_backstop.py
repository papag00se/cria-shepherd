"""A plan-ON session must not reach DONE on judgment alone while the repo's checks never ran.

Walked on ada-handles_ternary-bonsai_codex_poff_1785818931 (REGRESSION1 run 1): a replan returned
[] with the coder mid-step-1, the satisfaction judge + confirm checker + exec-intent all approved
files that were never executed, and the session exited 3/4 with ZERO gates run — pytest would have
printed "5 failed". Both plan-off done paths already run guard_gate_op before ending; the plan-ON
`item is None` completion was the one route without the objective backstop, and today's plan-off
routing change (a reading step makes a REAL 2-item plan) put plan-off runs on exactly that route.

The backstop keys on `gate_fresh` — a completion-gate result read since the coder's last forwarded
acting turn (green, or couldn't-run: the per-step fail-open posture unchanged; red clears it) — so
a normally-completing plan, whose final step just gate-verified, emits no duplicate probe.
"""

import json
import os
import tempfile
import unittest

from cria.loop import Loop, LoopContext, PlanSession, _COMPLETION_FIX_PREFIX
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


def _summary(text="built it; run pytest -q"):
    return {"choices": [{"message": {"content": text}}]}


_SHELL = {"type": "function", "function": {"name": "shell", "parameters": {
    "type": "object", "properties": {"command": {"type": "array"}}}}}


def _body():
    return {"messages": [{"role": "user", "content": "build an ada handle resolver"}],
            "tools": [_SHELL], "stream": True}


def _body_with_probe(call_id, output):
    b = _body()
    b["messages"] = b["messages"] + [{"role": "tool", "tool_call_id": call_id, "content": output}]
    return b


def _ctx(coder, reasoner, workspace_root=None):
    return LoopContext(planner=_Planner(), coder_chat=coder, reasoner_chat=reasoner, runs_dir="",
                       workspace_root=workspace_root)


def _emptied_sess():
    """The state the walked run died in: a replan emptied the tail on judgment alone — no step was
    ever verified, no gate ever ran."""
    return PlanSession(plan=Plan(id="x", task="build a resolver", created="c", items=[]))


class CompletionGateBackstopTests(unittest.TestCase):
    def test_judgment_emptied_plan_probes_before_completing(self):
        # FAILS BEFORE THE FIX: _work returned the final "plan complete" completion straight from
        # the LLM judges; the repo's checks were never attempted.
        loop = Loop(_ctx(_Scripted([_toolcall()]), _Scripted([_summary()])))
        sess = _emptied_sess()
        rlog = _Rlog()
        out = loop._work(sess, "k", _body(), rlog)
        tcs = out["choices"][0]["message"].get("tool_calls")
        self.assertTrue(tcs, "the completion must be gated — expected the checks probe, not a final answer")
        self.assertTrue(sess.completion_probe_id)  # the backstop's OWN id — never done_probe
        self.assertFalse(sess.done_probe)          # (that flag belongs to the plan-off/satisfaction paths)
        self.assertIn("loop.completion_probe", rlog.kinds())

    def test_red_backstop_reopens_with_the_findings(self):
        # The probe came back RED → the plan reopens with the ONE reused corrective step and the
        # coder is re-driven with the real findings — never DONE.
        with tempfile.TemporaryDirectory() as ws:   # a real root, so the gate plan carries probes
            with open(os.path.join(ws, "app.py"), "w") as f:
                f.write("x = 1\n")
            coder = _Scripted([_toolcall()])          # the re-driven fix attempt
            loop = Loop(_ctx(coder, _Scripted([_summary()]), workspace_root=ws))
            sess = _emptied_sess()
            rlog = _Rlog()
            probe = loop._work(sess, "k", _body(), rlog)      # backstop emits the checks probe
            call_id = probe["choices"][0]["message"]["tool_calls"][0]["id"]
            red = ("___CRIA_GATE_probe-0___\napp.py:3: undefined name 'x'\nEXIT:1\n"
                   "___CRIA_GATE_git___\nabc\n")
            out = loop._work(sess, "k", _body_with_probe(call_id, red), rlog)
            self.assertNotIn("loop.done", rlog.kinds())
            self.assertTrue(out["choices"][0]["message"].get("tool_calls"))  # coder re-driven to fix
            self.assertEqual(sess.plan.status, "in_progress")
            fixes = [it for it in sess.plan.items if it.text.startswith(_COMPLETION_FIX_PREFIX)]
            self.assertEqual(len(fixes), 1)
            self.assertIsNotNone(sess.plan.current())          # a step to drive again
            self.assertFalse(sess.gate_fresh)                  # red never counts as fresh ground truth

    def test_green_backstop_completes(self):
        # The probe ran and found nothing (or could not run — the per-step fail-open) → the
        # completion proceeds; the backstop is a gate, not a wedge.
        loop = Loop(_ctx(_Scripted([_toolcall()]), _Scripted([_summary()])))
        sess = _emptied_sess()
        rlog = _Rlog()
        probe = loop._work(sess, "k", _body(), rlog)
        call_id = probe["choices"][0]["message"]["tool_calls"][0]["id"]
        clean = "___CRIA_GATE_probe-0___\nEXIT:0"
        out = loop._work(sess, "k", _body_with_probe(call_id, clean), rlog)
        self.assertIn("loop.done", rlog.kinds())
        self.assertIn("plan complete", out["choices"][0]["message"]["content"])

    def test_fresh_green_gate_skips_the_extra_probe(self):
        # A normally-completing plan (final step just gate-verified green → gate_fresh) must NOT
        # pay a duplicate probe round-trip at the end.
        loop = Loop(_ctx(_Scripted([_toolcall()]), _Scripted([_summary()])))
        plan = Plan(id="x", task="build a resolver", created="c",
                    items=[PlanItem("step 1", done=True, note="verified")])
        sess = PlanSession(plan=plan)
        sess.gate_fresh = True
        rlog = _Rlog()
        out = loop._work(sess, "k", _body(), rlog)
        self.assertNotIn("loop.completion_probe", rlog.kinds())
        self.assertIn("loop.done", rlog.kinds())
        self.assertIn("plan complete", out["choices"][0]["message"]["content"])

    def test_stale_satisfaction_done_probe_is_not_misread(self):
        # AUDIT 2026-08-04: the plan-ON periodic satisfaction check sets done_probe and nothing on
        # the plan path consumes it; the backstop keying off done_probe read whatever stale result
        # probe_call_id pointed at. The backstop must ignore done_probe and emit ITS OWN probe.
        loop = Loop(_ctx(_Scripted([_toolcall()]), _Scripted([_summary()])))
        sess = _emptied_sess()
        sess.done_probe = True            # stranded by an earlier satisfied periodic check
        sess.probe_call_id = "stale-id"   # points at some long-gone result
        rlog = _Rlog()
        out = loop._work(sess, "k", _body(), rlog)
        self.assertIn("loop.completion_probe", rlog.kinds())          # a FRESH probe was emitted
        self.assertNotEqual(sess.completion_probe_id, "stale-id")
        self.assertTrue(out["choices"][0]["message"].get("tool_calls"))

    def test_compaction_lost_result_is_reissued_not_failopened(self):
        # AUDIT 2026-08-04: a harness compaction between probe emit and read erased the result and
        # the backstop fail-opened (couldn't-run → gate_fresh → judge) — the exact hole it closes.
        loop = Loop(_ctx(_Scripted([_toolcall()]), _Scripted([_summary()])))
        sess = _emptied_sess()
        rlog = _Rlog()
        probe = loop._work(sess, "k", _body(), rlog)                  # backstop emits its probe
        first_id = sess.completion_probe_id
        out = loop._work(sess, "k", _body(), rlog, rewritten=True)    # result erased by compaction
        # C28b: the plan's transport is still open (never ingested a real result), so the recovery
        # POLLS that same plan instead of abandoning it for a brand new gate.
        self.assertIn("gate.transport_poll_after_rewrite", rlog.kinds())
        self.assertTrue(sess.completion_probe_id)                     # a check is still in flight
        self.assertNotEqual(sess.completion_probe_id, first_id)
        self.assertNotIn("loop.done", rlog.kinds())

    def test_acting_turn_stales_the_gate(self):
        # gate_fresh is freshness, not history: any forwarded acting turn clears it.
        from cria.loop import guard_gate_verdict
        sess = _emptied_sess()
        sess.gate_fresh = True
        loop = Loop(_ctx(_Scripted([_toolcall()]), _Scripted([_summary()])))
        plan = Plan(id="y", task="t", created="c", items=[PlanItem("step 1")])
        sess2 = PlanSession(plan=plan)
        sess2.gate_fresh = True
        loop._work(sess2, "k", _body(), _Rlog())   # coder acts (tool call forwarded)
        self.assertFalse(sess2.gate_fresh)


if __name__ == "__main__":
    unittest.main()
