"""A rumination abort is runaway (or empty/looping) THINKING. Re-prompting with reasoning still ON
lets a weak model ruminate straight into the same wall. Replay of feed-pipeline-java x ornith15
1788907072 call 0054-focus1, 8 samples each: reasoning ON, the retry emitted a tool call 1/8;
reasoning OFF, 7/8 (and it was the OFF, not the notice wording — the original notice worked 3/3
off). So the retry forces reasoning OFF — for the retry ONLY. The next turn must keep the role's
reasoning, so the original body must be untouched (the copy is what gets flipped).
"""
import json
import unittest

from cria import bodykeys, loop


class _Role:
    """A minimal coder role: reasoning on, chat_template protocol (ornith / the whole live fleet)."""
    reasoning = "on"
    think_protocol = "chat_template"


class _Rlog:
    phase = "coder"

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def _ruminating():
    comp = {"choices": [{"message": {"role": "assistant", "content": ""},
                         "finish_reason": "rumination"}]}
    comp[bodykeys.RUMINATION] = {"hits": 10, "reasoning_tokens": 2048}
    return comp


class RuminationRetryForcesReasoningOff(unittest.TestCase):
    def _run(self, coder_role):
        captured = {}

        def chat(body, rlog):
            # record the body the retry actually sent, then return a clean (non-ruminating) turn
            captured["body"] = json.loads(json.dumps(body))
            return json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"},
                                            "finish_reason": "stop"}]}).encode()

        body = {"messages": [{"role": "user", "content": "t"}], "tools": [{"x": 1}],
                "chat_template_kwargs": {"enable_thinking": True}}
        loop.guard_rumination(_ruminating(), body, chat, _Rlog(), coder_role=coder_role)
        return body, captured.get("body")

    def test_the_retry_is_sent_with_reasoning_off(self):
        body, sent = self._run(_Role())
        self.assertIsNotNone(sent)
        self.assertEqual(sent["chat_template_kwargs"]["enable_thinking"], False)

    def test_the_original_body_keeps_reasoning_on_so_the_next_turn_is_normal(self):
        body, _sent = self._run(_Role())
        # bounded + self-reverting: the flip lands on the retry copy, never the caller's body
        self.assertEqual(body["chat_template_kwargs"]["enable_thinking"], True)

    def test_without_a_role_the_retry_is_unchanged_backward_compatible(self):
        # every existing caller that omits coder_role must behave exactly as before
        _body, sent = self._run(None)
        self.assertEqual(sent["chat_template_kwargs"]["enable_thinking"], True)

    def test_a_role_already_reasoning_off_needs_no_flip(self):
        class Off(_Role):
            reasoning = "off"
        _body, sent = self._run(Off())
        # nothing to force; the body's own setting stands
        self.assertIn("chat_template_kwargs", sent)


if __name__ == "__main__":
    unittest.main()
