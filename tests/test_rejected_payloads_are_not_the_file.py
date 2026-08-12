"""The nearest copy wins, and cria was keeping the fabrications closest.

A weak model resolves "the current file" to whichever rendering of it sits nearest the end of the
prompt. `represent_inbound` restores a rejected `edit_file` call into replayed history with its
arguments intact — and `old_string` is the model's OWN idea of the file, formatted exactly like a
listing, sitting closer to the generation point than the real content.

Measured on the six-language battery, nemotron-elastic cart-billing-go call 0021: the coder read its
own rejected old_string back as authority — "the earlier snippet we saw in the instruction shows the
Item struct with ID, Name, PricePerUnit float64 … Perhaps the original code is missing; we need to
restore that structure" — and rebuilt a struct that never existed in the project.

The asymmetry is the defect: model-authored text that never reached disk persisted verbatim, while
verified content was dropped by compaction. This is disclosure rather than deletion — the model
still sees that it attempted an edit on that path and that the attempt failed.
"""
import json
import unittest

from cria import writeproxy

BIG = "package cartsvc\n\ntype Item struct {\n\tID string\n\tName string\n\tPricePerUnit float64\n}\n" * 8
SMALL = "func (c *Cart) Total() float64 {"


class ARejectedPayloadIsNotFileContentTests(unittest.TestCase):
    def test_a_large_rejected_old_string_is_collapsed(self):
        tc = {"id": "e1", "type": "function", "function": {
            "name": "edit_file",
            "arguments": json.dumps({"path": "cart.go", "old_string": BIG, "new_string": "x"})}}
        out = writeproxy._collapse_rejected_payload(tc, "cart.go")
        args = json.loads(out["function"]["arguments"])
        self.assertNotIn("PricePerUnit", args["old_string"])
        self.assertIn("REJECTED", args["old_string"])
        self.assertIn("cart.go", args["old_string"])

    def test_the_attempt_itself_is_still_visible(self):
        """Disclosure, not deletion: the path and the fact of the failed edit survive."""
        tc = {"id": "e1", "type": "function", "function": {
            "name": "edit_file",
            "arguments": json.dumps({"path": "cart.go", "old_string": BIG})}}
        out = writeproxy._collapse_rejected_payload(tc, "cart.go")
        self.assertEqual(out["function"]["name"], "edit_file")
        self.assertIn("cart.go", json.loads(out["function"]["arguments"])["path"])

    def test_a_short_snippet_is_left_alone(self):
        """A targeted old_string is real context for the retry and too short to read as the file."""
        tc = {"id": "e1", "type": "function", "function": {
            "name": "edit_file",
            "arguments": json.dumps({"path": "cart.go", "old_string": SMALL})}}
        out = writeproxy._collapse_rejected_payload(tc, "cart.go")
        self.assertEqual(json.loads(out["function"]["arguments"])["old_string"], SMALL)

    def test_a_successful_write_is_never_collapsed(self):
        """Content that DID reach disk is the file, and must survive verbatim."""
        msgs = [{"role": "tool", "tool_call_id": "w1", "content": writeproxy._WROTE}]
        self.assertNotIn("w1", writeproxy._failed_edit_ids(msgs))

    def test_a_failed_edit_is_recognised(self):
        msgs = [{"role": "tool", "tool_call_id": "e1",
                 "content": "your old_string is not an exact match"}]
        self.assertIn("e1", writeproxy._failed_edit_ids(msgs))


if __name__ == "__main__":
    unittest.main()
