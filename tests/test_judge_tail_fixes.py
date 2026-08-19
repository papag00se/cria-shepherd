"""Four faults from the maple-preview 1786228135 walk — the run that spent 20 of its 35 minutes
inside cria's own completion machinery without a byte being written.

The coder stopped editing at minute 12. Over the final 30 calls the phase mix was 12
satisfaction-confirm, 10 satisfaction, 5 coder-s1, 2 exec-intent, 1 reasoner. Four gate cycles ran
against an unchanged workspace, and the only thing that differed between the three that were
rejected and the one that ended the run was which JSON key came back.
"""
import inspect
import json
import re
import tempfile
import unittest

from cria import loop, prompts, verifytools
from cria.config import Role


class _Rlog:
    phase = ""

    def emit(self, *a, **k):
        pass


class TheCloserAsksForTheSchemaTheJudgeDeclaresTests(unittest.TestCase):
    """Three judges share one tool loop and answer under three keys — `done`, `satisfied`,
    `consistent`. The default closer demands `{"done": …}`. The confirm judge passes its own one-word
    ask as `answer_now_simple`, but only the leaked-tool-call branch reached it; the ROUND CAP — the
    path a five-round inspection actually takes — sent the wrong template every time."""

    class _RoundCapChat:
        """Keeps inspecting (list_dir) until the round cap, then answers in prose."""

        def __init__(self, n_before_cap):
            self.bodies = []
            self.n = n_before_cap

        def __call__(self, body, rlog):
            self.bodies.append(body)
            if len(self.bodies) <= self.n:
                comp = {"choices": [{"message": {"role": "assistant", "tool_calls": [
                    {"id": f"c{len(self.bodies)}", "type": "function",
                     "function": {"name": "list_dir", "arguments": '{"path": "."}'}}]}}]}
            else:
                comp = {"choices": [{"message": {"role": "assistant", "content": "done inspecting"}}]}
            return json.dumps(comp).encode()

    def test_the_round_cap_prefers_the_judges_own_closer(self):
        """Drive a judge that never volunteers a verdict tool call, all the way to the round cap.
        The closer question the ROUND CAP sends (as opposed to the leaked-tool-call escalation,
        covered by test_the_confirm_judge_has_a_closer_that_matches_its_prompt below) must be the
        confirm judge's OWN one-word ask — not the generic {"done": …} closer."""
        chat = self._RoundCapChat(verifytools.VERIFY_MAX_ROUNDS)
        with tempfile.TemporaryDirectory() as root:
            loop._judge_completion(chat, None, "sys", "user", _Rlog(), phase="test",
                                    workspace_root=root, verdict_key="done",
                                    answer_now_simple="SIMPLE_CLOSER_MARKER",
                                    answer_now="GENERIC_CLOSER_MARKER")
        self.assertEqual(len(chat.bodies), verifytools.VERIFY_MAX_ROUNDS + 1,
                         "the round cap must be the one that ended the loop")
        cap_request = chat.bodies[verifytools.VERIFY_MAX_ROUNDS]["messages"][-1]["content"]
        self.assertEqual(cap_request, "SIMPLE_CLOSER_MARKER")

    def test_the_confirm_judge_has_a_closer_that_matches_its_prompt(self):
        self.assertIn("CONSISTENT", verifytools.ANSWER_NOW_CONSISTENT)
        self.assertNotIn('"done"', verifytools.ANSWER_NOW_CONSISTENT)
        self.assertIn('"consistent"', prompts.load_map("verify_confirm")["system"])

    def test_the_default_closer_still_asks_for_done(self):
        # the step critic really does answer `done` — this is not a rename, it is a routing fix
        self.assertIn('"done"', verifytools.ANSWER_NOW)


class ASentinelAtTheEndIsADecisionTests(unittest.TestCase):
    """`ON_TRACK` last means the text before it is the reasoning that produced it. `ON_TRACK` first
    is the hedge this stripper exists for, and still ships its directive."""

    # verbatim, call 0085
    ENDS_WITH = ("The coder has already completed the task—files are created, tests pass, and live "
                 "tests succeed. No indication of being stuck.\n\nON_TRACK")
    # the same shape at 0057, whose thinking read "the coder is NOT stuck. I should output ON_TRACK"
    PRAISE = "You're making forward progress on all fronts.\nON_TRACK"
    # Fabliq's hedge — the reason the stripper exists
    HEDGE = "ON_TRACK. You keep re-fetching; write it now."

    def test_reasoning_then_sentinel_is_withheld(self):
        self.assertIsNone(loop._steer_or_none(self.ENDS_WITH))

    def test_praise_then_sentinel_is_withheld(self):
        self.assertIsNone(loop._steer_or_none(self.PRAISE))

    def test_the_hedge_still_delivers_its_directive(self):
        self.assertEqual(loop._steer_or_none(self.HEDGE), "You keep re-fetching; write it now.")

    def test_a_bare_sentinel_is_still_silence(self):
        for t in ("ON_TRACK", "  on track  ", "NOT_STUCK"):
            self.assertIsNone(loop._steer_or_none(t), t)

    def test_a_real_directive_is_untouched(self):
        d = "You are stuck. Read resolve_handle.py, then run pytest -q and fix what it names."
        self.assertEqual(loop._steer_or_none(d), d)


class ClosedQuestionsGoInTheUserTurnTests(unittest.TestCase):
    """Call 0092's recovery prompt was `system(2658 chars) + user(0 chars)`. The model answered:
    "We need to parse the user's message. It's just a single period." A model looks for the ask where
    an ask lives."""

    def test_no_closed_question_is_sent_with_an_empty_user_turn(self):
        src = inspect.getsource(loop)
        self.assertNotIn(', "", rlog', src,
                         "a reasoner call still sends an empty user turn")

    def test_there_is_one_primitive_for_asking(self):
        self.assertTrue(callable(loop.ask_closed))
        self.assertTrue(loop._ASK_USER_TURN.strip())

    def test_it_forces_reasoning_off_and_temperature_zero(self):
        """The role handed in has reasoning ON and a nonzero temperature — ask_closed must force
        both regardless of what the role otherwise carries, so a one-word verdict never spends the
        role's own sampling on a closed question."""
        class _Chat:
            def __init__(self):
                self.bodies = []

            def __call__(self, body, rlog):
                self.bodies.append(body)
                return json.dumps({"choices": [{"message": {
                    "role": "assistant", "content": "YES"}}]}).encode()

        role = Role(name="reasoner", backend="b", reasoning="on", temperature=0.7)
        chat = _Chat()
        loop.ask_closed(chat, role, "Is the coder stuck?", _Rlog(), phase="test")
        sent = chat.bodies[0]
        self.assertEqual(sent["temperature"], 0.0)
        self.assertFalse(sent["chat_template_kwargs"]["enable_thinking"])


class ASteerMustNameSomethingTests(unittest.TestCase):
    """`unverified_step` names nothing, and the coder got it three times verbatim. cria was holding a
    concrete finding each time — its execution probe had reported the README documents no command
    that runs the deliverable — and sent the generic paragraph instead.

    This APPENDS; it does not replace. A fact about the code is not a fact about the task, so cria's
    finding rides alongside the instruction rather than standing in for a judgement."""

    def test_a_held_finding_is_named(self):
        out = loop._named_gap("test_x.py:12: undefined name 'requests'")
        self.assertIn("undefined name 'requests'", out)
        self.assertIn("unresolved", out.lower())

    def test_holding_nothing_says_nothing(self):
        for empty in ("", "   ", None):
            self.assertEqual(loop._named_gap(empty), "")

    def test_the_generic_instruction_still_ships(self):
        both = prompts.load("unverified_step") + loop._named_gap("pyflakes: 2 problems")
        self.assertIn("not yet verified as complete", both)   # the instruction survives
        self.assertIn("pyflakes: 2 problems", both)           # …with something to act on


if __name__ == "__main__":
    unittest.main()
