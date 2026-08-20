"""Every seat asked whether the coder was looping was shown the BEFORE and never the AFTER.

`shipping-rates-rb x ternary-bonsai` 1787111689. The reasoner's view of the session's edits, over and
over:

    old_string= def self.shipping_cost(zone_or_code, weight_kilos, order_total, oversize: false)
        zone = if zone_or_code.is_a?(String) && zone_or_code.length == 2
                 zone_for(zone_or_code)
               else
                 zone_or_code
               end
    …
      end; new_string=[elided 597 chars — an EARLIER version of …/lib/shipping/rates.rb, replaced by
      a later write in this session; read_file for what is actually on disk now]

Both folding paths — `focustrim._drop_superseded_writes` and `selfcompact`'s write-arg folding —
listed `content`, `new_string`, `patch` and **not** `old_string`. So a historical `edit_file` reached
its reader as the text being replaced, in full, and the replacement as a pointer. The seat convened
to decide whether an edit changed anything was handed the one half that cannot answer that.

Both halves are equally historical, and both now get a pointer. The newest call to a path still
keeps its arguments whole — that one is what is on disk, and it is where a real diff lives.

The replaced fragment gets its own sentence: calling it "an EARLIER version of <path>" would be a
small false fact about what the model is looking at. It is a piece of a file, not a version of one.
"""

import json
import unittest

from cria import focustrim, prompts, selfcompact

BIG_OLD = "def self.shipping_cost(zone_or_code, weight_kilos, order_total)\n" + ("  # before\n" * 60)
BIG_NEW = "def self.shipping_cost(zone_or_code, weight_kilos, order_total)\n" + ("  # after\n" * 60)


def edit(path, old, new, cid="c1"):
    return {"role": "assistant", "tool_calls": [{
        "id": cid, "type": "function",
        "function": {"name": "edit_file",
                     "arguments": json.dumps({"path": path, "old_string": old, "new_string": new})}}]}


def args_of(msg, i=0):
    return json.loads(msg["tool_calls"][i]["function"]["arguments"])


def edit_key(path, key, value, cid="c1"):
    return {"role": "assistant", "tool_calls": [{
        "id": cid, "type": "function",
        "function": {"name": "edit_file", "arguments": json.dumps({"path": path, key: value})}}]}


def _write(path, content, cid="w1"):
    return {"role": "assistant", "tool_calls": [{
        "id": cid, "type": "function",
        "function": {"name": "write_file",
                     "arguments": json.dumps({"path": path, "content": content})}}]}


class TheSupersededEditGOESTests(unittest.TestCase):
    """The fix this file recorded — hide BOTH halves of a stale edit, not only the after — was right
    about the diagnosis and wrong about the remedy. Eliding a half still leaves cria's prose in an
    argument slot, and on feed-pipeline-java x qwen35 call 0095 the coder copied one forward as the
    content of a new write and destroyed the file. Operator, 2026-08-19: "There is not supposed to be
    any elision. It's all or nothing." So a superseded edit is REMOVED, both halves with it."""

    def _edit_then_write(self):
        """A stale edit to a file, then a later whole-file write to the same path."""
        return [edit("lib/shipping/rates.rb", BIG_OLD, BIG_NEW),
                {"role": "tool", "tool_call_id": "c1", "content": "ok"},
                _write("lib/shipping/rates.rb", "NEWEST" + ("\n# v2" * 200))]

    def test_the_superseded_edit_is_gone_entirely(self):
        out, n = focustrim._drop_superseded_writes(self._edit_then_write())
        self.assertEqual(n, 1)
        blob = json.dumps(out)
        self.assertNotIn("# before", blob, "the old_string survived")
        self.assertNotIn("# after", blob, "the new_string survived")

    def test_neither_half_is_replaced_by_a_pointer(self):
        """The distinction that matters: not "hidden behind a stub" — ABSENT."""
        out, _n = focustrim._drop_superseded_writes(self._edit_then_write())
        blob = json.dumps(out)
        self.assertNotIn("elided", blob)
        self.assertNotIn("the text this edit replaced", blob)

    def test_the_newest_write_keeps_its_payload_whole(self):
        out, _n = focustrim._drop_superseded_writes(self._edit_then_write())
        calls = [tc for m in out for tc in (m.get("tool_calls") or [])]
        self.assertEqual(len(calls), 1, "only the newest write survives")
        self.assertIn("NEWEST", calls[0]["function"]["arguments"])

    def test_a_short_edit_is_left_alone(self):
        """Dropping every superseded call regardless of size would throw away the small ones, which
        cost nothing to keep and show the model the shape of what it has been doing."""
        msgs = [edit("lib/x.rb", "a = 1", "a = 2"),
                {"role": "tool", "tool_call_id": "c1", "content": "ok"},
                _write("lib/x.rb", "NEWEST" + "x" * 900)]
        out, n = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(n, 0)
        self.assertEqual(out, msgs)


class TheCompactViewFoldsItTooTests(unittest.TestCase):
    def test_both_keys_are_in_the_write_arg_list(self):
        self.assertIn("old_string", selfcompact._WRITE_ARG_KEYS)
        self.assertIn("new_string", selfcompact._WRITE_ARG_KEYS)

    def test_the_two_stubbing_paths_agree_on_which_keys_are_payload(self):
        """They drifted once already; a test is cheaper than the next walk (#23). Drive
        focustrim's stubber with a real superseded payload under EACH key selfcompact treats as
        write payload, and confirm it actually gets replaced — not just that the key's name
        appears somewhere in the function's source."""
        for key in selfcompact._WRITE_ARG_KEYS:
            with self.subTest(key=key):
                msgs = [edit_key("lib/x.rb", key, "x" * 500, "a"),
                        edit_key("lib/x.rb", key, "y" * 500, "b")]
                out, n = focustrim._drop_superseded_writes(msgs)
                self.assertEqual(n, 1, f"{key} was not recognized as a stubbable write payload")
                stale = args_of(out[0])
                self.assertNotIn("x" * 500, stale[key])


class TheWordingExistsTests(unittest.TestCase):
    def test_both_sentences_are_in_the_prompt_file(self):
        words = prompts.load_map("compact_view")
        self.assertIn("write_stub_superseded", words)
        self.assertIn("write_stub_replaced", words)
        self.assertIn("read_file", words["write_stub_replaced"])


if __name__ == "__main__":
    unittest.main()
