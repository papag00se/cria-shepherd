"""A turn that finished with its words only in the reasoning channel is not a turn cria may discard.

`recover_reasoning_tool_calls` already rescues an ACTION left in the reasoning channel, and its own
docstring is the argument for this sibling: "a lost turn forwards none … this function's only job is
to stop losing the action". Nothing rescued a CONCLUSION left there, so a turn that reached one and
emitted nothing was thrown away whole — cria destroying model output at the wire (#5).

Measured across the three walked runs of 2026-08-27, java/go/ruby against nemotron-elastic: all 249
coder turns produced reasoning and zero visible content — 1.54 million characters — and every
assistant turn in the model's own history is `content: ''` plus a tool call. 28 of those turns
emitted no tool call either: 15 finished normally, 13 were cut by the rumination guard.

One of the 15 decided a run. go call 0046:

    "But we need to call loadDiscounts before using Discounts. We can call loadDiscounts at the
     start of Total. Thus, inside Total, first call loadDiscounts(), then use Discounts."

That is exactly the defect the shipped cart.go has. The turn went back empty. The model reached the
same conclusion again at 0047, 0053, 0056, 0073, 0088 and 0091 and never wrote the call, because
nothing it had concluded was ever in front of it again.
"""

import unittest

from cria import massage


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def completion(finish, content=None, tool_calls=None, reasoning=""):
    return {"choices": [{"finish_reason": finish,
                         "message": {"content": content, "tool_calls": tool_calls,
                                     "reasoning_content": reasoning}}]}


LOST = "We need to call loadDiscounts before using Discounts, at the start of Total."


class AFinishedTurnKeepsItsWordsTests(unittest.TestCase):
    def test_the_measured_case(self):
        rlog = _Rlog()
        out = massage.apply(completion("stop", reasoning=LOST), [], rlog)
        self.assertEqual(out["choices"][0]["message"]["content"], LOST)
        self.assertIn("massage.reasoning_text_recovered", rlog.kinds())

    def test_a_turn_that_wrote_content_is_untouched(self):
        out = massage.apply(completion("stop", content="I read the file.", reasoning=LOST), [], _Rlog())
        self.assertEqual(out["choices"][0]["message"]["content"], "I read the file.")

    def test_a_turn_that_acted_is_untouched(self):
        """An action is the turn's output. Its reasoning stays where it was."""
        call = [{"function": {"name": "read_file", "arguments": "{}"}}]
        out = massage.apply(completion("stop", tool_calls=call, reasoning=LOST), [], _Rlog())
        self.assertIsNone(out["choices"][0]["message"]["content"])

    def test_a_turn_with_nothing_in_either_channel_stays_empty(self):
        """Nothing is manufactured — there is no text to keep."""
        rlog = _Rlog()
        out = massage.apply(completion("stop", reasoning="   "), [], rlog)
        self.assertFalse(out["choices"][0]["message"]["content"])
        self.assertNotIn("massage.reasoning_text_recovered", rlog.kinds())


class TheRuminationGuardStillWinsTests(unittest.TestCase):
    """A turn the backstop cut was cut because the output degenerated, and carrying that forward is
    the one thing the guard exists to prevent."""

    def test_a_cut_turn_is_not_promoted(self):
        rlog = _Rlog()
        out = massage.apply(completion("rumination", reasoning="aaaa " * 400), [], rlog)
        self.assertIsNone(out["choices"][0]["message"]["content"])
        self.assertNotIn("massage.reasoning_text_recovered", rlog.kinds())

    def test_the_discriminator_is_the_finish_reason_not_the_text(self):
        """The authoritative field on the choice, never a scan for a marker in the words (#12)."""
        import inspect
        src = inspect.getsource(massage.recover_reasoning_text)
        self.assertIn('finish_reason', src)
        for scan in ("ABORTED", "backstop", "degenerate"):
            self.assertNotIn(f'"{scan}"', src)

    def test_a_length_cut_is_not_promoted_either(self):
        """`length` means the model was still talking when the window ran out — the turn did not
        finish, so there is no conclusion to keep."""
        out = massage.apply(completion("length", reasoning=LOST), [], _Rlog())
        self.assertIsNone(out["choices"][0]["message"]["content"])


class ItRunsAfterEveryChanceAtAToolCallTests(unittest.TestCase):
    def test_a_call_left_in_the_reasoning_channel_is_still_recovered_as_a_call(self):
        """The sibling runs first. A turn whose reasoning holds a real call becomes an ACTION, and
        this pass must then leave it alone — otherwise cria would turn an action into prose."""
        tools = [{"type": "function", "function": {
            "name": "read_file", "parameters": {"type": "object",
                                                "properties": {"path": {"type": "string"}}}}}]
        reasoning = 'I should look. <tool_call>{"name": "read_file", ' \
                    '"arguments": {"path": "cart.go"}}</tool_call>'
        out = massage.apply(completion("stop", reasoning=reasoning), tools, _Rlog())
        msg = out["choices"][0]["message"]
        self.assertTrue(msg.get("tool_calls"), "the action must still be recovered first")
        self.assertFalse((msg.get("content") or "").strip(),
                         "a turn that acts keeps its reasoning in the reasoning channel")


class ItChangesNoRoutingTests(unittest.TestCase):
    def test_the_toolless_turn_still_has_no_tool_call(self):
        """A turn with no tool call already reads as a completion claim one frame down. This only
        decides whether the words survive to be read there — and `loop.unexecuted_write`, which
        reads that content, has been blind on exactly these turns."""
        out = massage.apply(completion("stop", reasoning=LOST), [], _Rlog())
        self.assertFalse(out["choices"][0]["message"].get("tool_calls"))

    def test_the_pure_proxy_never_sees_it(self):
        """Level 0 forwards what the model said, byte for byte. This changes the message, so it may
        not run there."""
        out = massage.apply(completion("stop", reasoning=LOST), [], _Rlog(), tool_call_fixes=False)
        self.assertIsNone(out["choices"][0]["message"]["content"])


if __name__ == "__main__":
    unittest.main()
