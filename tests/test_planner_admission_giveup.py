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

        # #23: the give-up is CALL-scoped, not a process-wide poison cache — it never wrote
        # self._plans (that would leak this session's give-up onto every other session with the same
        # task text). A second call for the same task on the SAME Planner instance re-investigates and
        # bounded-gives-up again on its own; it is not silently starved.
        self.assertEqual(planner._plans, {})
        self.assertEqual(planner._admission_exhaustions, {})   # no session_key given \u2014 nothing persisted
        calls_before = provider.calls
        rlog2 = _Rlog()
        plan2 = planner.plan_for([{"role": "user", "content": _CART_TASK}], rlog2)
        self.assertIsNone(plan2)
        self.assertGreater(provider.calls, calls_before)          # it looked again \u2014 not starved
        self.assertIn("plan.admission_given_up", rlog2.kinds())   # and bounded again on its own

    def test_a_later_session_with_the_same_task_text_is_never_silenced_by_an_earlier_giveup(self):
        """#23, the blocking finding: two DIFFERENT sessions sharing task text must not share fate.
        Session A's give-up must not cost session B's admitting reasoner a single call \u2014 reviewer
        reproduced the opposite (session B got ``plan_for -> None`` with 0 reasoner calls, no event) on
        the committed C30, because the give-up poisoned ``self._plans`` keyed on task text alone."""
        planner = Planner(_P18HostLoopProvider(), role=_role(), search_key="", max_gather_rounds=1,
                          clock=lambda: _FIXED)
        rlog_a = _Rlog()
        self.assertIsNone(planner.plan_for([{"role": "user", "content": _CART_TASK}], rlog_a))
        self.assertIn("plan.admission_given_up", rlog_a.kinds())

        # Session B: same task text, a DIFFERENT (admitting) provider swapped onto the SAME shared
        # Planner \u2014 the real deployment shape (server.py ~701: one Planner for the whole process).
        admitting = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo looked"}),
            _tool_resp("submit_plan", {"steps": [
                "Add the promo discount rule to discounts.json",
                "Update the module requirement in go.mod",
            ]}),
            _content_resp("NONE"),                     # host judge: nothing needs reading this time
            _content_resp('{"missing": []}'),           # coverage judge
            _content_resp("NONE"),                       # noise judge
        ])
        planner._provider = admitting
        rlog_b = _Rlog()
        plan_b = planner.plan_for([{"role": "user", "content": _CART_TASK}], rlog_b)

        self.assertIsNotNone(plan_b, rlog_b.events)      # NOT silenced by session A's give-up
        self.assertGreater(admitting.calls, 0)           # the reasoner was actually asked
        self.assertIn("plan.submitted", rlog_b.kinds())

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
        reach the bound and give up, not restart at 1. This cross-call memory only exists when the
        caller threads a real ``session_key`` through (#23) — bounded WITHIN that one session, never
        shared with any other session or keyed on task text alone."""
        planner = Planner(object(), role=_role(), clock=lambda: _FIXED)
        session = "sid:survey-defer-test"
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
            self.assertIsNone(planner.plan_for([{"role": "user", "content": "t"}], rlog1,
                                               session_key=session))
            self.assertIn("plan.survey_deferred", rlog1.kinds())
            self.assertNotIn("plan.admission_given_up", rlog1.kinds())
            admission_key = next(iter(planner._admission_exhaustions))
            self.assertEqual(admission_key[0], session)                   # #23: keyed by session, never bare task text
            self.assertEqual(planner._admission_exhaustions[admission_key], 1)  # the deferral did not reset it

            rlog2 = _Rlog()
            self.assertIsNone(planner.plan_for([{"role": "user", "content": "t"}], rlog2,
                                               session_key=session))
            given_up = [kw for k, kw in rlog2.events if k == "plan.admission_given_up"]
            self.assertEqual(len(given_up), 1)
            self.assertEqual(given_up[0]["count"], ADMISSION_EXHAUSTION_GIVEUP)
            self.assertFalse(planner._retriable_failure)
            self.assertEqual(planner._admission_exhaustions, {})            # cleared on give-up, not left dangling


_SHELL = {"type": "function", "function": {"name": "shell", "parameters": {
    "type": "object", "properties": {"command": {"type": "array"}}}}}


def _toolcall_completion():
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]}}]}).encode()


class LoopSurveyDeferralGiveUpTests(unittest.TestCase):
    """Supervisor follow-up (#23): P18's real capture logged 325 ``plan.survey_deferred`` events. If
    the ``Planner``'s admission-exhaustion counter is not threaded through ``Loop`` by SESSION, a
    deferral landing between the first exhaustion and its in-request fresh retry (or on the next
    turn) resets the call-local count to 0 every time \u2014 the session can then re-plan forever with
    no coder, exactly the original P18 failure. ``Loop._plan_for`` now threads its real
    ``session_key`` into ``Planner.plan_for``, so the count persists across turns of ONE session."""

    def _loop_and_planner(self):
        planner = Planner(object(), role=_role(), clock=lambda: _FIXED)
        return Loop(LoopContext(planner=planner, coder_chat=lambda body, _rlog: _toolcall_completion(),
                                reasoner_chat=lambda *_: b"", runs_dir="")), planner

    def _body(self):
        return {"messages": [{"role": "user", "content": _CART_TASK}], "tools": [_SHELL]}

    def _classification(self):
        return type("Task", (), {"engagement": "task", "task_type": "coding", "cached": False})()

    def test_p18_every_turn_defers_after_at_most_one_exhaustion_still_gives_up_bounded(self):
        """P18 shape: every gather ends in a survey deferral after at most one admission exhaustion
        (alternating exhaust/defer, exactly what 325 real ``plan.survey_deferred`` events looked
        like). The session must still reach the bound and start the synthetic guarded drive within a
        FEW turns \u2014 not loop forever."""
        loop, planner = self._loop_and_planner()
        calls = {"n": 0}

        def fake_gather(task, cwd, rlog, prior_work="", rewrite_summary="", outcome=None):
            calls["n"] += 1
            if calls["n"] % 2 == 1:            # every gather's FIRST attempt: admission-exhausts
                planner._retriable_failure = True
                planner._admission_exhausted_check = "host"
                rlog.emit("plan.rejected_exhausted", level="warn", check="host")
                return None
            outcome.survey_pending = True        # the in-request fresh retry: defers instead of resolving
            return None

        session = "sid:p18-defer-loop"
        started = False
        MAX_TURNS = 6                            # bounded generously; the real fix needs far fewer
        with patch.object(planner, "_gather_and_plan", side_effect=fake_gather):
            for _ in range(MAX_TURNS):
                rlog = _Rlog()
                out = loop.drive(self._body(), session, self._classification(), rlog)
                self.assertIsNotNone(out)        # never silently dropped to the unguarded proxy
                starts = [kw for k, kw in rlog.events if k == "loop.start"]
                if starts:
                    self.assertTrue(starts[0].get("synthetic"))
                    self.assertTrue(starts[0].get("planner_fallback"))
                    self.assertIn("plan.admission_given_up", rlog.kinds())
                    started = True
                    break
        self.assertTrue(started, "never started the synthetic guarded drive within the turn bound")
        # The give-up cleared its own session-scoped counter \u2014 nothing left dangling.
        self.assertEqual(planner._admission_exhaustions, {})

    def test_a_second_session_with_the_same_task_text_is_unaffected_by_the_first(self):
        """#23: session A grinds through the P18 defer/exhaust shape to its give-up; a SECOND,
        unrelated session sharing the exact same task text must plan normally on its very first
        turn, unaffected by session A's exhaustion count or give-up."""
        loop, planner = self._loop_and_planner()
        calls = {"n": 0}

        def fake_gather(task, cwd, rlog, prior_work="", rewrite_summary="", outcome=None):
            calls["n"] += 1
            if calls["n"] % 2 == 1:
                planner._retriable_failure = True
                planner._admission_exhausted_check = "host"
                rlog.emit("plan.rejected_exhausted", level="warn", check="host")
                return None
            outcome.survey_pending = True
            return None

        session_a = "sid:p18-defer-session-a"
        with patch.object(planner, "_gather_and_plan", side_effect=fake_gather):
            for _ in range(6):
                rlog = _Rlog()
                out = loop.drive(self._body(), session_a, self._classification(), rlog)
                if any(k == "loop.start" for k, _ in rlog.events):
                    break
        self.assertTrue(any(k == "plan.admission_given_up" for k, _ in rlog.events))

        # Session B: the SAME shared Planner, the SAME task text, a session that plans cleanly.
        def admitting_gather(task, cwd, rlog, prior_work="", rewrite_summary="", outcome=None):
            rlog.emit("plan.submitted", steps=2)
            return ["Add the promo discount rule to discounts.json",
                    "Update the module requirement in go.mod"]

        session_b = "sid:p18-defer-session-b"
        with patch.object(planner, "_gather_and_plan", side_effect=admitting_gather):
            rlog_b = _Rlog()
            out_b = loop.drive(self._body(), session_b, self._classification(), rlog_b)

        self.assertIsNotNone(out_b)
        self.assertIn("plan.submitted", rlog_b.kinds())
        self.assertNotIn("plan.admission_given_up", rlog_b.kinds())   # never inherited session A's fate
        starts_b = [kw for k, kw in rlog_b.events if k == "loop.start"]
        self.assertEqual(len(starts_b), 1)
        self.assertFalse(starts_b[0].get("synthetic", False))          # a REAL multi-item plan, not the fallback
        self.assertTrue(loop.has_session(session_b))


if __name__ == "__main__":
    unittest.main()
