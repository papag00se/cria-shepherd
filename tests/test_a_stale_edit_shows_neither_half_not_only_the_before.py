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

Both stubbing paths — `focustrim._stub_superseded_writes` and `selfcompact`'s write-arg folding —
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


class TheSupersededEditHidesBothHalvesTests(unittest.TestCase):
    def test_the_before_is_no_longer_the_only_half_kept(self):
        msgs = [edit("lib/x.rb", BIG_OLD, BIG_NEW, "a"), edit("lib/x.rb", BIG_NEW, BIG_OLD, "b")]
        out, n = focustrim._stub_superseded_writes(msgs)
        self.assertEqual(n, 1)
        stale = args_of(out[0])
        self.assertIn("elided", stale["old_string"])
        self.assertIn("elided", stale["new_string"])

    def test_the_newest_write_keeps_both_halves_whole(self):
        """Where the diff actually lives — this one is what is on disk."""
        msgs = [edit("lib/x.rb", BIG_OLD, BIG_NEW, "a"), edit("lib/x.rb", BIG_NEW, BIG_OLD, "b")]
        out, _ = focustrim._stub_superseded_writes(msgs)
        newest = args_of(out[1])
        self.assertEqual(newest["old_string"], BIG_NEW)
        self.assertEqual(newest["new_string"], BIG_OLD)

    def test_a_replaced_fragment_is_not_called_a_version_of_the_file(self):
        msgs = [edit("lib/x.rb", BIG_OLD, BIG_NEW, "a"), edit("lib/x.rb", BIG_NEW, BIG_OLD, "b")]
        out, _ = focustrim._stub_superseded_writes(msgs)
        stale = args_of(out[0])
        self.assertIn("the text this edit replaced", stale["old_string"])
        self.assertNotIn("an EARLIER version", stale["old_string"])
        self.assertIn("an EARLIER version", stale["new_string"])

    def test_a_short_fragment_is_left_alone(self):
        """Below the floor a pointer is longer than the thing it replaces."""
        msgs = [edit("lib/x.rb", "a = 1", BIG_NEW, "a"), edit("lib/x.rb", BIG_NEW, BIG_OLD, "b")]
        out, _ = focustrim._stub_superseded_writes(msgs)
        self.assertEqual(args_of(out[0])["old_string"], "a = 1")


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
                out, n = focustrim._stub_superseded_writes(msgs)
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
