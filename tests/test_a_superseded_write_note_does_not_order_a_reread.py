"""A removal notice must not become the most salient order to reread an unchanged file.

Walked on feed-pipeline-java x ornith15, run 1788984830. In coder calls 0094, 0096, and 0102,
the read ledger said not to rediscover Importer.java and the complete current bytes were visible.
`_drop_superseded_writes` then appended its notice after those facts with "To be sure, read the file".
The coder quoted that freshness concern and reread Importer.java again.
"""

import json
import unittest

from cria import focustrim


BIG = "class Current {\n" + ("    // body\n" * 200) + "}\n"
READ_RECORD = {
    "role": "user",
    "content": "⟦ctx:facts⟧ FILES YOU HAVE ALREADY READ FROM THIS WORKSPACE\n- Current.java",
}
INVENTORY = {
    "role": "user",
    "content": "⟦ctx:files⟧ YOUR WORKSPACE RIGHT NOW\n  Current.java",
}


def write(call_id: str, body: str) -> dict:
    return {
        "role": "assistant",
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "Current.java", "content": body}),
            },
        }],
    }


class TheSupersededWriteNoticeIsHistoricalContextTests(unittest.TestCase):
    def setUp(self):
        messages = [
            write("old", BIG),
            {"role": "tool", "tool_call_id": "old", "content": "Wrote Current.java"},
            write("new", BIG.replace("Current", "Newest")),
            {"role": "tool", "tool_call_id": "new", "content": "Wrote Current.java"},
            READ_RECORD,
            INVENTORY,
        ]
        self.out, dropped = focustrim._drop_superseded_writes(messages)
        self.assertEqual(dropped, 1)
        self.note = next(
            message for message in self.out
            if "earlier write(s) in this conversation have been removed"
            in str(message.get("content") or "")
        )

    def test_the_notice_precedes_newer_read_and_inventory_facts(self):
        note_index = self.out.index(self.note)
        self.assertLess(note_index, self.out.index(READ_RECORD))
        self.assertLess(note_index, self.out.index(INVENTORY))

    def test_the_notice_describes_history_without_ordering_a_reread(self):
        text = self.note["content"]
        self.assertIn("whole-file write", text)
        self.assertIn("remains above in full", text)
        self.assertNotIn("To be sure", text)
        self.assertNotIn("read the file", text)
        self.assertNotIn("what is on disk", text)


if __name__ == "__main__":
    unittest.main()
