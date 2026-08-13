"""cria spent 131 minutes classifying turns it had already identified.

A compaction turn announces itself: the operator wires the harness's compaction prompt to lead with
`<<<LOCAL_COMPACT>>>`, and `_route` sends it to the compactor WITHOUT EVER READING the classifier's
verdict. Classifying it anyway asked the model an unanswerable question — pick coding|reasoning|
question for "Summarize the thread for continuation" — with a 16,384-token budget and reasoning on.

Measured over the 08-11..08-13 suite (58 streams that produced no first token):

    phase         count   minutes
    classifier       39       131      ← this
    coder-s1          8        91
    proxy            11        70

Every one of the 39 ended `finish_reason: length` with `content`, `reasoning_content` AND
`tool_calls` all null. The answer was never used even when it arrived.

A ceiling on the classifier's budget would have made the wasted call cheaper. Not making the call is
the fix.

The second half: cria KNOWS this is a compaction, so cria's own words ask for the briefing — the
harness's wording never reaches the model. The buffered transport did this; the streaming transport
passed the harness's raw prompt and the full structured history. `_compaction_body` is now the one
owner both call.
"""

import types
import unittest

from cria import prompts, server


COMPACT = "<<<LOCAL_COMPACT>>> Summarize the thread for continuation. Preserve edits, blockers."


def body(*, compaction: bool = True) -> dict:
    ask = COMPACT if compaction else "add a --json flag to the CLI"
    return {"messages": [
        {"role": "system", "content": "You are a coding agent."},
        {"role": "user", "content": "build the shipping calculator"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "write_file", "arguments": '{"path":"a.py"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "wrote a.py"},
        {"role": "user", "content": ask},
    ]}


class Rlog:
    def __init__(self):
        self.events = []
        self.phase = None

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class TheClassifierIsNotAskedTests(unittest.TestCase):
    def handler(self, classifier):
        h = server.CriaHandler.__new__(server.CriaHandler)
        h.server = types.SimpleNamespace(classifier=classifier)
        return h

    def test_a_compaction_turn_makes_no_classifier_call(self):
        calls = []
        h = self.handler(types.SimpleNamespace(classify=lambda m, r: calls.append(m)))
        self.assertIsNone(h._classify(body(), Rlog()))
        self.assertEqual(calls, [], "the 39 runaway calls: a verdict _route never reads")

    def test_the_skip_is_recorded(self):
        rlog = Rlog()
        h = self.handler(types.SimpleNamespace(classify=lambda m, r: None))
        h._classify(body(), rlog)
        self.assertIn("classify.skipped", [k for k, _ in rlog.events])

    def test_an_ordinary_turn_is_still_classified(self):
        calls = []
        verdict = object()
        h = self.handler(types.SimpleNamespace(
            classify=lambda m, r: (calls.append(m), verdict)[1]))
        self.assertIs(h._classify(body(compaction=False), Rlog()), verdict)
        self.assertEqual(len(calls), 1)

    def test_no_classifier_configured_is_unchanged(self):
        self.assertIsNone(self.handler(None)._classify(body(), Rlog()))


class NoVerdictStillReachesTheCompactorTests(unittest.TestCase):
    """Skipping the classifier hands `_route` a None verdict — the compaction branch must sit ABOVE
    the None check, or the turn falls to a bare passthrough with server-default sampling."""

    def test_a_none_verdict_routes_to_the_compactor(self):
        compactor_up, shared = object(), object()
        h = server.CriaHandler.__new__(server.CriaHandler)
        h.server = types.SimpleNamespace(
            compactor_upstream=compactor_up, upstream=shared, router=None,
            cfg=types.SimpleNamespace(
                routing=types.SimpleNamespace(roles={"compactor": object()}),
                indicators=types.SimpleNamespace(enabled=True, metrics=True, route=True, assists=True)))
        provider, indic = h._route(body(), None, Rlog())
        self.assertIs(provider, compactor_up)
        self.assertEqual(indic.role, "compactor")


class CriaAsksInItsOwnWordsTests(unittest.TestCase):
    def test_the_harness_wording_never_reaches_the_model(self):
        out = server._compaction_body(body())
        self.assertNotIn("LOCAL_COMPACT", str(out["messages"]))
        self.assertNotIn("Preserve edits, blockers", str(out["messages"]))

    def test_the_system_line_is_crias_own_briefing_prompt(self):
        out = server._compaction_body(body())
        self.assertEqual(out["messages"][0]["role"], "system")
        self.assertEqual(out["messages"][0]["content"], prompts.load("selfcompact_summary"))

    def test_the_history_is_flattened_to_one_user_turn(self):
        """89 structured turns, 42 of them tool calls, taught the model to answer with a tool call."""
        out = server._compaction_body(body())
        self.assertEqual(len(out["messages"]), 2)
        self.assertEqual(out["messages"][1]["role"], "user")
        self.assertNotIn("tool_calls", str(out["messages"][1]))

    def test_the_work_itself_survives(self):
        text = server._compaction_body(body())["messages"][1]["content"]
        self.assertIn("build the shipping calculator", text)

    def test_everything_else_on_the_request_is_untouched(self):
        out = server._compaction_body({**body(), "model": "m", "temperature": 0.2})
        self.assertEqual(out["model"], "m")
        self.assertEqual(out["temperature"], 0.2)


class BothTransportsUseTheOneOwnerTests(unittest.TestCase):
    """The streaming transport passed the harness's prompt and the raw structured history for months
    while the buffered one rebuilt it. Same drift the compaction transcript helper was written to
    end — assert both call sites, so a future edit to one cannot silently orphan the other."""

    def test_both_producers_call_compaction_body(self):
        import inspect
        for fn in (server.CriaHandler._produce_stream, server.CriaHandler._produce_completion):
            with self.subTest(producer=fn.__name__):
                self.assertIn("_compaction_body(", inspect.getsource(fn))


if __name__ == "__main__":
    unittest.main()
