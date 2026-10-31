"""A repeated call collapsed in SILENCE makes the next prompt byte-identical, and a temperature-0
model handed a constant is a deterministic function.

Focus-trim rule A folds duplicate tool calls to their last occurrence. When the duplicate is the
call the model JUST made, the conversation grew by an identical call and an identical result, rule A
removed the older copy, and the rendered body came out byte-identical to the one sent a moment
before. The model returns the same call again — it cannot do otherwise — and cria then counts those
repeats and steers it for "repeating the same action without changing anything".

MEASURED over the whole capture set on 2026-08-03: 76 of 118 runs (64%) sent a coder the identical
prompt twice in a row; 344 calls in all. Walked on ada-handles_fabliq_codex_pon_1785801960 calls
0015/0016 — same prompt md5, same 682-char reasoning, same tool call, then `loop.repetition` at
count 3 and a supervisor directive blaming the coder.

Rule B has always left a note for the failures it folds away. These tests pin that rule A now does
the same for the one case that matters, and stays silent for the stale duplicates it exists to
remove.
"""
import unittest

from cria import focustrim


def call(cid, name="web_fetch", args='{"url":"https://api.handle.me/openapi.json"}'):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}


def turn(cid, result="HTTP 200 OK\nthe same body every time", **kw):
    return [{"role": "assistant", "content": "", "tool_calls": [call(cid, **kw)]},
            {"role": "tool", "tool_call_id": cid, "content": result}]


class ARepeatedLastCallIsNamedTests(unittest.TestCase):
    def setUp(self):
        self.msgs = [{"role": "user", "content": "read the spec"}] + turn("a") + turn("b")

    def test_the_body_is_not_identical_after_the_collapse(self):
        """The whole point: the model must not be handed the same bytes it was handed last turn."""
        out, rep = focustrim._collapse_duplicates(self.msgs)
        self.assertTrue(rep.dropped_calls, "the duplicate should still be collapsed")
        before = [m for m in self.msgs if m.get("role") == "user"]
        after = [m for m in out if m.get("role") == "user"]
        self.assertGreater(len(after), len(before))

    def test_the_note_says_how_many_times_and_what(self):
        out, _rep = focustrim._collapse_duplicates(self.msgs)
        note = out[-1]
        self.assertEqual(note["role"], "user")
        self.assertIn("2 times", note["content"])
        self.assertIn("web_fetch", note["content"])
        self.assertIn("https://api.handle.me/openapi.json", note["content"])

    def test_the_note_tells_it_the_result_will_not_change(self):
        """A model that repeats does so because it does not know the answer is fixed. Naming the
        repetition without that is just a scold."""
        out, _ = focustrim._collapse_duplicates(self.msgs)
        self.assertIn("same result", out[-1]["content"])

    def test_the_kept_call_is_still_the_last_one(self):
        out, _ = focustrim._collapse_duplicates(self.msgs)
        ids = [tc["id"] for m in out if m.get("role") == "assistant" for tc in (m.get("tool_calls") or [])]
        self.assertEqual(ids, ["b"])

    def test_three_repeats_count_three(self):
        msgs = [{"role": "user", "content": "go"}] + turn("a") + turn("b") + turn("c")
        out, _ = focustrim._collapse_duplicates(msgs)
        self.assertIn("3 times", out[-1]["content"])


class AStaleDuplicateStaysSilentTests(unittest.TestCase):
    """Folding away an old duplicate deep in the history is what rule A is FOR. A note for every
    one of those would be noise (#3), and noise is what makes real notes get skipped."""

    def test_no_note_when_the_repeat_is_not_the_latest_call(self):
        msgs = ([{"role": "user", "content": "go"}] + turn("a") + turn("b")
                + turn("c", name="read_file", args='{"path":"./x.py"}'))
        out, rep = focustrim._collapse_duplicates(msgs)
        self.assertTrue(rep.dropped_calls)
        self.assertFalse(any(m.get("role") == "user" and "same result" in str(m.get("content"))
                             for m in out))

    def test_nothing_added_when_there_is_no_duplicate_at_all(self):
        msgs = ([{"role": "user", "content": "go"}] + turn("a")
                + turn("b", name="read_file", args='{"path":"./x.py"}'))
        out, rep = focustrim._collapse_duplicates(msgs)
        self.assertEqual(out, msgs)
        self.assertFalse(rep.applied)

    def test_a_repeat_with_a_DIFFERENT_result_is_not_collapsed_or_noted(self):
        """Rule A's existing contract: same args + different output is not a duplicate. A note there
        would be a false statement — the result DID change."""
        msgs = ([{"role": "user", "content": "go"}] + turn("a", result="3 failed")
                + turn("b", result="4 passed"))
        out, rep = focustrim._collapse_duplicates(msgs)
        self.assertEqual(out, msgs)
        self.assertFalse(rep.applied)


class TheWalkedCaseTests(unittest.TestCase):
    """calls 0015/0016 of ada-handles_fabliq_codex_pon_1785801960, in the shape they occurred."""

    ARGS = '{"url":"https://api.handle.me/openapi.json","find":"GET /handles/{handle}","raw":true}'

    def test_the_second_identical_fetch_produces_a_changed_body(self):
        msgs = ([{"role": "user", "content": "step 1 of 8: read the OpenAPI specification"}]
                + turn("t1", args=self.ARGS) + turn("t2", args=self.ARGS))
        out, rep = focustrim._collapse_duplicates(msgs)
        self.assertEqual(rep.dropped_calls, 1)
        self.assertNotEqual(out, msgs)
        self.assertIn("2 times", out[-1]["content"])
        self.assertIn("GET /handles/{handle}", out[-1]["content"])


if __name__ == "__main__":
    unittest.main()
