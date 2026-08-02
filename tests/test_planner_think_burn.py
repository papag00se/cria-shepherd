"""A planner round that spends its whole budget THINKING and emits nothing is retried thinking-off.

The critic has had this since the false-completion bug and its own note says why: "a reasoning model
under the max_tokens cap can burn its whole budget THINKING and never emit the closing JSON". The
planner never got it — 21 uses of the reasoning-off retry in loop.py, zero in planner.py.

Measured over every captured planner round (n=499): 15 cut off at the cap, and 5 of those produced
nothing usable at all, behind 26,337 / 28,936 / 31,248 / 31,475 and 106,829 characters of reasoning.
On zaya1 it is the dominant failure: run 20260801T221447 lost 2 of 7 planner rounds this way and
never reached the coder inside its 15 minutes.
"""
import inspect
import unittest
from dataclasses import dataclass

from cria import planner


@dataclass
class FakeRole:
    reasoning: str = "on"
    applied: tuple = ()

    def apply(self, body, internal=False, rlog=None):
        body.setdefault("_seen", []).append(self.reasoning)


class FakeLog:
    def __init__(self): self.events = []
    def emit(self, name, **kw): self.events.append(name)
    phase = ""


class ThinkBurnTests(unittest.TestCase):
    def _planner(self, replies):
        p = planner.Planner.__new__(planner.Planner)
        p._role = FakeRole()
        p._calls = []

        def once(messages, rlog, *, research=False, plan_only=False, think_off=False):
            p._calls.append(think_off)
            return replies.pop(0)

        p._reason_once = once
        return p

    def test_a_burnt_round_is_retried_with_thinking_off(self):
        burnt = {planner.FINISH_KEY: "length", "tool_calls": [], "content": ""}
        good = {planner.FINISH_KEY: "stop", "content": "1. do the thing"}
        p = self._planner([burnt, good])
        log = FakeLog()
        out = planner.Planner._reason(p, [], log, research=True)
        self.assertEqual(out, good)
        self.assertEqual(p._calls, [False, True], "second attempt must force thinking off")
        self.assertIn("plan.think_burn_retry", log.events)

    def test_a_cut_off_round_that_STILL_produced_calls_is_kept(self):
        kept = {planner.FINISH_KEY: "length",
                "tool_calls": [{"function": {"name": "read_file", "arguments": '{"path":"a"}'}}],
                "content": ""}
        p = self._planner([kept])
        out = planner.Planner._reason(p, [], FakeLog(), research=True)
        self.assertEqual(out, kept)
        self.assertEqual(p._calls, [False], "no retry — the round produced something usable")

    def test_a_normal_round_is_never_retried(self):
        ok = {planner.FINISH_KEY: "stop", "content": "1. step"}
        p = self._planner([ok])
        out = planner.Planner._reason(p, [], FakeLog(), research=True)
        self.assertEqual(out, ok)
        self.assertEqual(p._calls, [False])

    def test_it_is_bounded_to_ONE_retry(self):
        burnt = {planner.FINISH_KEY: "length", "tool_calls": [], "content": ""}
        p = self._planner([dict(burnt), dict(burnt)])
        out = planner.Planner._reason(p, [], FakeLog(), research=True)
        self.assertEqual(p._calls, [False, True], "exactly one retry, then take what came back")
        self.assertIsNotNone(out, "a still-empty retry must not become None — the caller decides")

    def test_the_retry_does_not_mutate_the_configured_role(self):
        src = inspect.getsource(planner.Planner._reason_once)
        self.assertIn('replace(self._role, reasoning="off") if think_off else self._role', src)


class ParityTests(unittest.TestCase):
    def test_the_planner_now_has_what_the_critic_had_all_along(self):
        self.assertIn("think_off", inspect.getsource(planner.Planner._reason_once))
        self.assertIn("plan.think_burn_retry", inspect.getsource(planner.Planner._reason))
