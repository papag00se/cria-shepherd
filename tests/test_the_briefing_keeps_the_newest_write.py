"""cria elided the route's source, then a briefer described what the source must have done.

`orders-api-py x ternary-bonsai`, cycle 1. The compaction briefing asserted:

    It returns a JSON object with an `orders` array and a `total_value` field
    (sum of quantity × unit_price for that customer).

It returned neither — `app.py:26` slices `path[11:10]`, so the response is
`{"orders":[],"total_value":0.0}`. The sentence rode 37 later prompts and the file was never
edited again.

NOT AN INVENTION, AND NOT A FAITHFUL SUMMARY OF A CODER CLAIM. The coder never said the route worked;
its only prose was "Now update app.py with the new customer orders route:". What the briefer was
given in place of the source was cria's own stub:

    [elided 2579 chars — this exact content is on disk...]

So the briefer reconstructed behaviour from the task text, the test file's `total_value == 22.50`
assertions, and a disk listing. cria replaced source with cria's own claim, and a model then
described what the source must have done — #5b at one remove.

THE INVARIANT THAT BROKE. `stub_old_write_args` keeps "the live working set" verbatim and stubs
everything older. It implemented that as *the last turn with any tool call* — and cria's own gate
probe is a tool call, fired on a timer. Whenever a gate ran last in the span, EVERY write was
stubbed and the briefer saw no source at all.

Prevalence, all 37 cycle-1 briefings read: 20 assert behaviour of the coder's own work, 9 falsely,
and 8 of those 9 sit under "What now works" in a briefing that elsewhere reports the build broken.
"""

import json
import unittest

from cria import selfcompact


def call(name: str, args: dict, tid: str) -> dict:
    return {"id": tid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def content_of(msg: dict) -> str:
    """The write's `content` argument, DECODED. Comparing against the raw JSON string is a trap: the
    arguments are json-encoded, so a literal newline in the payload is `\\n` on the wire and a
    substring check fails on content that is perfectly intact. Cost me one false failure."""
    return json.loads(msg["tool_calls"][0]["function"]["arguments"]).get("content", "")


def wrote(tid: str, path: str) -> dict:
    return {"role": "tool", "tool_call_id": tid, "content": f"⟦ctx:wrote⟧ {path}"}


BIG = "def handler():\n    " + ("x" * 3000)


class AGateProbeIsNotTheWorkingSetTests(unittest.TestCase):
    """THE REGRESSION. A trailing gate used to stub the write in front of it."""

    def msgs(self):
        return [
            {"role": "assistant", "tool_calls": [call("write_file", {"path": "app.py", "content": BIG}, "w1")]},
            wrote("w1", "app.py"),
            {"role": "assistant", "tool_calls": [call("exec_command", {"cmd": "__cria_out=$(pytest -q)"}, "g1")]},
            {"role": "tool", "tool_call_id": "g1", "content": "5 passed"},
        ]

    def test_the_newest_write_survives_a_trailing_gate(self):
        out = selfcompact.stub_old_write_args(self.msgs())
        self.assertEqual(content_of(out[0]), BIG)

    def test_the_gate_turn_itself_is_untouched(self):
        out = selfcompact.stub_old_write_args(self.msgs())
        self.assertIn("pytest", out[2]["tool_calls"][0]["function"]["arguments"])


class OlderWritesAreStillElidedTests(unittest.TestCase):
    """The behaviour this function exists for has to survive the fix."""

    def msgs(self):
        return [
            {"role": "assistant", "tool_calls": [call("write_file", {"path": "old.py", "content": BIG}, "w1")]},
            wrote("w1", "old.py"),
            {"role": "assistant", "tool_calls": [call("write_file", {"path": "new.py", "content": BIG}, "w2")]},
            wrote("w2", "new.py"),
        ]

    def test_the_older_write_is_stubbed(self):
        out = selfcompact.stub_old_write_args(self.msgs())
        self.assertNotEqual(content_of(out[0]), BIG)

    def test_the_newest_write_is_kept_whole(self):
        out = selfcompact.stub_old_write_args(self.msgs())
        self.assertEqual(content_of(out[2]), BIG)


class TheTwoAnswersCannotDivergeTests(unittest.TestCase):
    def test_which_turn_is_live_uses_the_stubbers_own_tool_set(self):
        """"Which turn is the working set" and "which arguments get stubbed" must key on one set.
        They did not, which is the entire bug."""
        self.assertTrue(selfcompact._is_write_call(call("write_file", {}, "w")))
        self.assertFalse(selfcompact._is_write_call(call("exec_command", {}, "g")))
        self.assertFalse(selfcompact._is_write_call({}))

    def test_a_span_with_no_write_at_all_stubs_nothing(self):
        msgs = [{"role": "assistant", "tool_calls": [call("exec_command", {"cmd": "ls"}, "g1")]},
                {"role": "tool", "tool_call_id": "g1", "content": "a b c"}]
        self.assertEqual(selfcompact.stub_old_write_args(msgs), msgs)


if __name__ == "__main__":
    unittest.main()
