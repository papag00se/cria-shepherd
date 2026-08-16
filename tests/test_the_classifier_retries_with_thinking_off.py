"""A classifier that spent its whole budget thinking gets one retry with thinking off.

A reasoning model can burn the entire `max_tokens` on its private thoughts and emit no content at
all. Measured over five days: 14 of 119 classifier calls came back `finish_reason=length` with empty
content — **229,376 tokens for zero verdicts** — and one session did it six times with byte-identical
prompts, each falling straight through to the engagement bias.

`summarize` has owned the reasoning-off retry for exactly this failure since the truncation audit.
This call site never used it. Same pattern, same place: one retry with thinking forced off, then the
bias as before (#9 — the purposeful call is cheap next to spending the budget again on the same
question; #4 — the bias is the safe null, not a fallback that replaces the answer).
"""

import json
import unittest

from cria.classify import Classifier


class _Rlog:
    def __init__(self):
        self.events, self.decisions, self.phase = [], [], None

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def decide(self, *a, **kw):
        self.decisions.append((a, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def reply(content):
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


VERDICT = '{"engagement": "deep", "task_type": "code", "reason": "multi-file change"}'


class _Provider:
    """Returns each scripted reply in order; records what it was asked."""

    def __init__(self, *replies):
        self.replies, self.bodies = list(replies), []

    def chat(self, body, rlog):
        self.bodies.append(body)
        return self.replies[min(len(self.bodies) - 1, len(self.replies) - 1)]


def classifier(provider):
    c = Classifier.__new__(Classifier)
    c._provider, c._role, c._bias = provider, None, "deep"
    c._consec_fail = 0
    import threading
    c._lock = threading.Lock()
    return c


class TheEmptyReplyIsRetriedTests(unittest.TestCase):
    def test_an_empty_first_answer_is_retried_with_thinking_off(self):
        p = _Provider(reply(""), reply(VERDICT))
        rlog = _Rlog()
        out = classifier(p)._call("build the thing", rlog)
        self.assertEqual(len(p.bodies), 2)
        self.assertFalse(p.bodies[0].get("chat_template_kwargs", {}).get("enable_thinking", True) is False)
        self.assertIs(p.bodies[1]["chat_template_kwargs"]["enable_thinking"], False)
        self.assertEqual(out.engagement, "deep")
        self.assertEqual(out.reason, "multi-file change")
        self.assertIn("route.classify_recovered_noreason", rlog.kinds())

    def test_a_good_first_answer_costs_exactly_one_call(self):
        p = _Provider(reply(VERDICT))
        classifier(p)._call("build the thing", _Rlog())
        self.assertEqual(len(p.bodies), 1)

    def test_two_failures_fall_through_to_the_bias_as_before(self):
        p = _Provider(reply(""), reply(""))
        rlog = _Rlog()
        out = classifier(p)._call("build the thing", rlog)
        self.assertEqual(len(p.bodies), 2)
        self.assertEqual(out.engagement, "deep")            # the bias, unchanged
        self.assertNotIn("route.classify_recovered_noreason", rlog.kinds())

    def test_the_unparsed_event_records_which_pass_it_was(self):
        rlog = _Rlog()
        classifier(_Provider(reply(""), reply("")))._call("x", rlog)
        flags = [kw.get("reasoning_off") for k, kw in rlog.events if k == "route.classify_unparsed"]
        self.assertEqual(flags, [False, True])

    def test_an_empty_task_still_never_calls_the_model(self):
        p = _Provider(reply(VERDICT))
        classifier(p)._call("   ", _Rlog())
        self.assertEqual(p.bodies, [])


if __name__ == "__main__":
    unittest.main()
