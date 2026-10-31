"""A planner round that spends its whole budget THINKING and emits nothing is retried thinking-off.

The critic has had this since the false-completion bug and its own note says why: "a reasoning model
under the max_tokens cap can burn its whole budget THINKING and never emit the closing JSON". The
planner never got it — 21 uses of the reasoning-off retry in loop.py, zero in planner.py.

Measured over every captured planner round (n=499): 15 cut off at the cap, and 5 of those produced
nothing usable at all, behind 26,337 / 28,936 / 31,248 / 31,475 and 106,829 characters of reasoning.
On zaya1 it is the dominant failure: run 20260801T221447 lost 2 of 7 planner rounds this way and
never reached the coder inside its 15 minutes.
"""
import json
import unittest
from dataclasses import dataclass

from cria import planner
from cria.config import Role


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
        """Drive the REAL `_reason_once` (not the stub the rest of this file uses) through a real
        `Role` and provider: `think_off=True` must turn thinking off in THAT call's wire body, and
        the role object itself must come out unchanged — a later call with `think_off=False` (or a
        read of `p._role.reasoning`) must still see "on". A source-text grep for the `replace(...)`
        expression can't tell "builds a fresh Role" from "mutates the shared one and forgets to
        put it back"; only calling it twice can."""
        class _Provider:
            def __init__(self):
                self.bodies = []

            def chat(self, body, rlog):
                self.bodies.append(body)
                return json.dumps({"choices": [{"message": {"content": "1. step"},
                                                "finish_reason": "stop"}]}).encode()

        prov = _Provider()
        p = planner.Planner(prov, role=Role(name="reasoner", backend="local", reasoning="on"))
        p._reason_once([], FakeLog(), think_off=True)
        p._reason_once([], FakeLog(), think_off=False)
        off_body, on_body = prov.bodies
        self.assertFalse(off_body["chat_template_kwargs"]["enable_thinking"])
        self.assertTrue(on_body["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(p._role.reasoning, "on", "the configured role must survive the off-call")
