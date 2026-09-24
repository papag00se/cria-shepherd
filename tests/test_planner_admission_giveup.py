"""C30 — an exhausted plan-admission guard must fall open toward guarded work, not re-plan
forever.

Root cause: every admission guard's EXHAUSTED verdict (``plan.rejected_exhausted`` for
url/host/coverage/test-execution, plus ``plan.test_execution_undecidable`` and
``plan.test_execution_not_applicable``) set ``Planner._retriable_failure = True`` and returned
``None``. ``Loop`` treats a retriable failure as "re-plan next turn" and skips its own synthetic
single-item guarded-drive fallback — so a guard that keeps rejecting (Cart P18: six
``plan.rejected_exhausted check=host`` over 35 minutes, 775 planner calls, 0 coder calls, no
``loop.start``) blocked all coding unboundedly.

These tests exercise ``Planner.plan_for``'s new behavior: on an admission-guard exhaustion, ONE
fresh gather-and-plan attempt runs immediately in the same request; a persistent per-task-key
counter (reset only when a plan is submitted) tracks how many admission exhaustions this task has
had; at ``ADMISSION_EXHAUSTION_GIVEUP`` cria gives up NON-retriably (negatively caches the key,
clears ``_retriable_failure``) so ``Loop``'s existing synthetic single-item guarded drive takes the
raw task instead of returning ``None`` to the unguarded proxy forever. Transport/model errors and a
survey deferral are untouched — they stay retriable / deferred and are never counted.
"""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from cria.config import Role
from cria.loop import Loop, LoopContext
from cria.planner import ADMISSION_EXHAUSTION_GIVEUP, PlanOutcome, Planner


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


class _ScriptedProvider:
    """Returns canned completions in order (repeating the last)."""

    def __init__(self, responses):
        self._r = list(responses)
        self.calls = 0
        self.bodies = []

    def chat(self, body, rlog):
        self.calls += 1
        self.bodies.append(body)
        r = self._r.pop(0) if len(self._r) > 1 else self._r[0]
        return json.dumps(r).encode()


def _tool_resp(name, args, call_id="c1"):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def _content_resp(text):
    return {"choices": [{"message": {"content": text}}]}


_FIXED = datetime(2026, 9, 24, 1, 25, 15, tzinfo=timezone.utc)
_CART_TASK = ("In the Go cart service, add a promo discount rule to discounts.json and update "
              "go.mod for the new dependency.")


class _P18HostLoopProvider:
    """Cart P18's exact shape (session 01a0d284): the host judge keeps naming the task's own
    files (discounts.json, go.mod) as unread hosts, forever — however many times it is asked."""

    def __init__(self):
        self.calls = 0

    def chat(self, body, rlog):
        self.calls += 1
        names = {((t.get("function") or {}).get("name")) for t in (body.get("tools") or [])}
        if "submit_plan" in names:
            return json.dumps(_tool_resp("submit_plan", {"steps": [
                "Add the promo discount rule to discounts.json",
                "Update the module requirement in go.mod",
            ]}, call_id=f"c{self.calls}")).encode()
        if names:  # the research phase's read-only gather tools are offered
            return json.dumps(_tool_resp("exec_command", {"cmd": "echo looked"},
                                         call_id=f"c{self.calls}")).encode()
        # A targeted, toolless _ask call. In this scenario the host guard exhausts before the
        # coverage/test-execution checks are ever reached, so this is always the host judge.
        return json.dumps(_content_resp("discounts.json,go.mod")).encode()


def _role():
    return Role(name="reasoner", backend="local")


class AdmissionGiveUpTests(unittest.TestCase):
    def test_p18_host_guard_exhaustion_gives_up_and_negatively_caches(self):
        """Before this fix: every call returned None with ``_retriable_failure`` True, forever —
        775 planner calls and no plan in the real P18 capture. After: the bound gives up NON-
        retriably, negatively caches the task key, and a repeat call costs no more reasoner calls."""
        provider = _P18HostLoopProvider()
        planner = Planner(provider, role=_role(), search_key="", max_gather_rounds=1, clock=lambda: _FIXED)
        rlog = _Rlog()
        plan = planner.plan_for([{"role": "user", "content": _CART_TASK}], rlog)

        self.assertIsNone(plan)
        self.assertIn("plan.admission_given_up", rlog.kinds())
        given_up = [kw for k, kw in rlog.events if k == "plan.admission_given_up"]
        self.assertEqual(given_up[-1]["check"], "host")
        self.assertEqual(given_up[-1]["count"], ADMISSION_EXHAUSTION_GIVEUP)
        # The give-up is NON-retriable: Loop's fallback (below) only fires when this is False.
        self.assertFalse(planner._retriable_failure)
        self.assertEqual([k for k, _ in rlog.events].count("plan.rejected_exhausted"), ADMISSION_EXHAUSTION_GIVEUP)
        self.assertNotIn("plan.retriable", rlog.kinds())  # a give-up, not a transport retry

        # Negatively cached: a second call for the SAME task costs no further reasoner calls.
        calls_before = provider.calls
        rlog2 = _Rlog()
        plan2 = planner.plan_for([{"role": "user", "content": _CART_TASK}], rlog2)
        self.assertIsNone(plan2)
        self.assertEqual(provider.calls, calls_before)
        self.assertEqual(rlog2.events, [])

    def test_p18_shaped_exhaustion_falls_to_the_synthetic_guarded_drive(self):
        """Loop-level: once the admission guard gives up, the session must start the existing
        synthetic single-item guarded drive (``loop.start ... planner_fallback=True``) and reach
        the coder — not return None to the unguarded proxy the way the real P18/C22/C25 sessions
        did (0% each, zero coder calls)."""
        provider = _P18HostLoopProvider()
        planner = Planner(provider, role=_role(), search_key="", max_gather_rounds=1, clock=lambda: _FIXED)
        coder_bodies = []

        def coder(body, _rlog):
            coder_bodies.append(body)
            return json.dumps(_tool_resp("shell", {"command": "pwd"})).encode()

        loop = Loop(LoopContext(planner=planner, coder_chat=coder, reasoner_chat=lambda *_: b"", runs_dir=""))
        rlog = _Rlog()
        shell = {"type": "function", "function": {"name": "shell", "parameters": {
            "type": "object", "properties": {"command": {"type": "array"}}}}}
        body = {"messages": [{"role": "user", "content": _CART_TASK}], "tools": [shell]}
        classification = type("Task", (), {"engagement": "task", "task_type": "coding", "cached": False})()

        completion = loop.drive(body, "sid:p18-cart", classification, rlog)

        self.assertIn("plan.admission_given_up", rlog.kinds())
        starts = [kw for k, kw in rlog.events if k == "loop.start"]
        self.assertEqual(len(starts), 1)
        self.assertTrue(starts[0].get("synthetic"))
        self.assertTrue(starts[0].get("planner_fallback"))
        self.assertIsNotNone(completion)          # driven, not proxied
        self.assertEqual(len(coder_bodies), 1)     # the coder actually ran
        self.assertTrue(loop.has_session("sid:p18-cart"))

    def test_draft_rejected_once_then_admitted_on_fresh_gather_still_yields_the_plan(self):
        """Recovery preserved: ONE admission exhaustion (count=1, below the bound) still gets its
        fresh in-request gather attempt, and a clean re-gather that the guard actually accepts
        still lands as the session's plan."""
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo looked"}),          # cycle 1: research
            _tool_resp("submit_plan", {"steps": ["Call api.handle.me to resolve the handle"]}),
            _content_resp("api.handle.me"),                              # host judge: challenge
            _tool_resp("submit_plan", {"steps": ["Call api.handle.me to resolve the handle"]}),
            _content_resp("api.handle.me"),                              # host judge again: exhausted
            _tool_resp("exec_command", {"cmd": "echo fetched api.handle.me/openapi.json"}),  # cycle 2 (fresh): research
            _tool_resp("submit_plan", {"steps": ["Fetch api.handle.me/openapi.json, then resolve the handle"]}),
            _content_resp("NONE"),                                       # host judge: satisfied this time
            _content_resp('{"missing": []}'),                            # coverage judge: nothing missing
            _content_resp("NONE"),                                       # noise judge
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=_role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(
            [{"role": "user", "content": "resolve an ada handle using api.handle.me"}], rlog)

        self.assertIsNotNone(plan, rlog.events)
        self.assertIn("plan.admission_retry", rlog.kinds())
        self.assertEqual(rlog.kinds().count("plan.rejected_exhausted"), 1)   # only the FIRST cycle exhausted
        self.assertNotIn("plan.admission_given_up", rlog.kinds())            # recovered before the bound
        self.assertIn("Fetch api.handle.me/openapi.json", plan.items[0].text)

    def test_rejected_draft_is_never_returned_as_steps(self):
        """C7 invariant, preserved across a fresh gather: the draft cria rejected never becomes
        the plan cursor, whether cria gives up or a later attempt recovers."""
        rejected_text = "Call api.handle.me to resolve the handle"
        recovered_text = "Fetch api.handle.me/openapi.json, then resolve the handle"
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo looked"}),
            _tool_resp("submit_plan", {"steps": [rejected_text]}),
            _content_resp("api.handle.me"),
            _tool_resp("submit_plan", {"steps": [rejected_text]}),
            _content_resp("api.handle.me"),
            _tool_resp("exec_command", {"cmd": "echo fetched api.handle.me/openapi.json"}),
            _tool_resp("submit_plan", {"steps": [recovered_text]}),
            _content_resp("NONE"),
            _content_resp('{"missing": []}'),
            _content_resp("NONE"),
        ])
        plan = Planner(prov, role=_role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(
            [{"role": "user", "content": "resolve an ada handle using api.handle.me"}], _Rlog())
        self.assertIsNotNone(plan)
        joined = " ".join(item.text for item in plan.items)
        self.assertNotIn(rejected_text, joined)
        self.assertIn(recovered_text, joined)

    def test_transport_error_remains_retriable_and_is_not_counted(self):
        """A transport/model error (``_reason`` returns None) is a DIFFERENT outcome from an
        admission-guard exhaustion — it must stay retriable on every call and never advance the
        admission-exhaustion counter."""
        planner = Planner(object(), role=_role(), clock=lambda: _FIXED)

        def fake_gather(task, cwd, rlog, prior_work="", rewrite_summary="", outcome=None):
            planner._retriable_failure = True   # cria/planner.py:1228 — transport/model error
            return None

        with patch.object(planner, "_gather_and_plan", side_effect=fake_gather):
            for _ in range(3):
                rlog = _Rlog()
                plan = planner.plan_for([{"role": "user", "content": "t"}], rlog)
                self.assertIsNone(plan)
                self.assertIn("plan.retriable", rlog.kinds())
                self.assertNotIn("plan.admission_retry", rlog.kinds())
                self.assertNotIn("plan.admission_given_up", rlog.kinds())
        self.assertEqual(planner._admission_exhaustions, {})   # never counted
        key = list(planner._plans.keys())
        self.assertEqual(key, [])                              # never poison-cached either

    def test_survey_deferral_between_two_exhaustions_does_not_reset_the_count(self):
        """A survey deferral occurring on the FRESH in-request retry (after the first admission
        exhaustion) must not erase that exhaustion's count — the next turn's exhaustion must still
        reach the bound and give up, not restart at 1."""
        planner = Planner(object(), role=_role(), clock=lambda: _FIXED)
        effects = iter(["exhaust", "defer", "exhaust"])

        def fake_gather(task, cwd, rlog, prior_work="", rewrite_summary="", outcome=None):
            effect = next(effects)
            if effect == "exhaust":
                planner._retriable_failure = True
                planner._admission_exhausted_check = "host"
                rlog.emit("plan.rejected_exhausted", level="warn", check="host")
                return None
            if effect == "defer":
                outcome.survey_pending = True
                return None
            raise AssertionError("unexpected extra gather call")

        with patch.object(planner, "_gather_and_plan", side_effect=fake_gather):
            rlog1 = _Rlog()
            self.assertIsNone(planner.plan_for([{"role": "user", "content": "t"}], rlog1))
            self.assertIn("plan.survey_deferred", rlog1.kinds())
            self.assertNotIn("plan.admission_given_up", rlog1.kinds())
            key = next(iter(planner._admission_exhaustions))
            self.assertEqual(planner._admission_exhaustions[key], 1)   # the deferral did not reset it

            rlog2 = _Rlog()
            self.assertIsNone(planner.plan_for([{"role": "user", "content": "t"}], rlog2))
            given_up = [kw for k, kw in rlog2.events if k == "plan.admission_given_up"]
            self.assertEqual(len(given_up), 1)
            self.assertEqual(given_up[0]["count"], ADMISSION_EXHAUSTION_GIVEUP)
            self.assertFalse(planner._retriable_failure)


if __name__ == "__main__":
    unittest.main()
