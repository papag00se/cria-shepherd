"""The compaction note handed the model the STARTING file, four times, with no caveat.

`shipping-rates-rb x ternary-bonsai` 1787111689, the run's last stretch. At the top of the prompt,
under the heading "Summary of what those turns contained":

    module Shipping
      ZONE_BASE = { "domestic" => 4.99, "eu" => 9.99, "international" => 19.99 }.freeze
      …
        return surcharge if order_total > FREE_SHIPPING_THRESHOLD

That is the file as it shipped: no `express`, no `zone_for`, and the `>` the model had fixed in its
very first edit. Three of the four carried no caveat at all — because the caveat line fires only when
the DROPPED span itself contains a write, and those spans held only reads. Staleness does not work
that way: a turn that merely READ a file is summarised here with that file's contents, and any LATER
turn can have rewritten it.

The model was chasing a stale-state bug at the time.

The caveat is unconditional now because it is unconditionally true: the note describes the past.

ALSO FIXED HERE, from the same note: the bullets rendered as
`• {"path":"spec/shipping_spec.rb"}read_file`. `_msg_text` appended the tool name AFTER its
arguments and joined with "" — harmless for counting tokens, which is what it was written for, and
garbage for the model, which reads the same string through `digest_reduce`.
"""

import unittest

from cria import contextfloor


class TheNoteAdmitsItIsHistoryTests(unittest.TestCase):
    def _note(self, dropped):
        return contextfloor._compacted_note(dropped, len(dropped), 20000)["content"]

    def test_a_dropped_read_still_gets_the_caveat(self):
        """The measured case: the span held reads only, so the old file-list line never fired."""
        # A payload the reducer can actually shrink, so a digest is produced and the caveat is
        # reachable. What matters to this test is that the span holds NO write — which is the shape
        # that got no caveat in the walked run.
        dropped = [{"role": "tool", "tool_call_id": "c1",
                    "content": "<html><body>" + "<div class='x'>hello world</div>" * 200 + "</body></html>"}]
        note = self._note(dropped)
        self.assertIn("read_file is the only current answer", note)
        self.assertIn("what the file said THEN", note)

    def test_a_dropped_write_keeps_its_own_file_list_too(self):
        import json
        dropped = [{"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "write_file",
                         "arguments": json.dumps({"path": "lib/x.rb", "content": "puts 1\n"})}}]},
                   {"role": "tool", "tool_call_id": "c1",
                    "content": "<html><body>" + "<div class='x'>ok</div>" * 200 + "</body></html>"}]
        note = self._note(dropped)
        self.assertIn("Files modified in them", note)
        self.assertIn("lib/x.rb", note)
        self.assertIn("read_file is the only current answer", note)

    def test_a_note_with_nothing_summarised_makes_no_claim(self):
        """#3 — no digests, nothing to caveat."""
        note = self._note([{"role": "user", "content": ""}])
        self.assertNotIn("read_file is the only current answer", note)


class TheBulletsReadAsToolCallsTests(unittest.TestCase):
    def test_the_name_comes_before_its_arguments(self):
        import json
        m = {"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "read_file",
                         "arguments": json.dumps({"path": "spec/shipping_spec.rb"})}}]}
        text = contextfloor._msg_text(m)
        self.assertTrue(text.startswith("read_file("), text[:60])
        self.assertNotIn('}read_file', text)

    def test_a_missing_name_does_not_render_as_nothing(self):
        m = {"role": "assistant", "tool_calls": [{"id": "c", "type": "function",
                                                  "function": {"arguments": "{}"}}]}
        self.assertIn("?(", contextfloor._msg_text(m))

    def test_the_arguments_are_still_counted(self):
        """Its first job is token accounting — the payload must still be in the string."""
        import json
        big = json.dumps({"path": "x", "content": "y" * 500})
        m = {"role": "assistant", "tool_calls": [{"id": "c", "type": "function",
                                                  "function": {"name": "write_file", "arguments": big}}]}
        self.assertIn("y" * 500, contextfloor._msg_text(m))


if __name__ == "__main__":
    unittest.main()
