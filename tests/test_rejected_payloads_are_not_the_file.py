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
verified content was dropped by compaction. The model still sees that it attempted an edit on that
path and that the attempt failed.

AND THE REPLACEMENT MAY NOT BE PROSE. The first fix put a sentence — `[985 characters — this edit
was REJECTED, nothing was written to <path>]` — into the `content` slot, which is the exact position
a file body occupies, and the model read it as one. `20260819T063347` calls 0046/0047 emitted
`write_file {"content": "[2254 characters — this edit was REJECTED…]"}` twice in a row: cria's
sentence WAS the file it wrote. `20260817T020431/0012` reasoned "The current pom.xml is: ```[1107
characters — this edit was REJECTED…]```". `20260822T001226/0078` attributed the sentence to a
read_file result. The stub's em dash is the documented cause of `Importer.java:[1,20] illegal
character: '\u2014'`. 858 prompt files, 1,770 occurrences, 85 coder prompts on 2026-08-22/23.

Operator, 2026-08-19, on the identical shape in `focustrim`: *"There is not supposed to be any
elision. It's all or nothing."* There the whole call could go, because a superseded write loses
nothing. Here the failure is information the coder needs, so the CALL stays and only the payload
leaves — the same rule applied to the only part of it that can be misread.
"""
import json
import unittest

from cria import writeproxy

BIG = "package cartsvc\n\ntype Item struct {\n\tID string\n\tName string\n\tPricePerUnit float64\n}\n" * 8
SMALL = "func (c *Cart) Total() float64 {"


class ARejectedPayloadIsNotFileContentTests(unittest.TestCase):
    def test_a_large_rejected_old_string_is_removed(self):
        tc = {"id": "e1", "type": "function", "function": {
            "name": "edit_file",
            "arguments": json.dumps({"path": "cart.go", "old_string": BIG, "new_string": "x"})}}
        out = writeproxy._collapse_rejected_payload(tc, "cart.go")
        args = json.loads(out["function"]["arguments"])
        self.assertNotIn("old_string", args)
        self.assertNotIn("PricePerUnit", out["function"]["arguments"])

    def test_no_sentence_is_left_where_a_file_body_goes(self):
        """The whole of the second defect: nothing readable as content, in any payload slot."""
        for key in ("content", "old_string", "new_string"):
            with self.subTest(key=key):
                tc = {"id": "w1", "type": "function", "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "cart.go", key: BIG})}}
                out = writeproxy._collapse_rejected_payload(tc, "cart.go")
                args = json.loads(out["function"]["arguments"])
                self.assertNotIn(key, args)
                self.assertNotIn("REJECTED", out["function"]["arguments"])
                self.assertNotIn("\u2014", out["function"]["arguments"])
                self.assertNotIn("—", out["function"]["arguments"])

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
        """Built by the REAL composer, not hand-typed. The old fixture was a bare sentence with no
        `⟦ctx:edit⟧` marker — a body the production path cannot emit — so the test certified the
        substring scan rather than the mechanism, which is how the scan survived being the rule."""
        from cria import editrecovery
        for mode, extra in (("no_anchor", {}),
                            ("anchor_noline", {"anchor": "func Total() int {"}),
                            ("multi", {"n": 3}),
                            ("identical", {}),
                            ("phantom", {"anchor": "x := 1"})):
            with self.subTest(mode=mode):
                body = editrecovery.compose({"mode": mode, "path": "cart.go", **extra}, 0)
                msgs = [{"role": "tool", "tool_call_id": "e1", "content": body}]
                self.assertIn("e1", writeproxy._failed_edit_ids(msgs))

    def test_a_denied_call_counts_too(self):
        """cria's OWN refusal of a call that never ran — a different marker, same fact: the payload
        is not on disk. Preserved from the old rule, which is why it is pinned here."""
        from cria import denial
        body = denial.DENIED_MARKER + " the path is outside the workspace"
        self.assertTrue(denial.is_denied(body), "fixture no longer looks like a denial")
        msgs = [{"role": "tool", "tool_call_id": "e1", "content": body}]
        self.assertIn("e1", writeproxy._failed_edit_ids(msgs))

    def test_reading_a_file_that_mentions_the_argument_is_not_a_failure(self):
        """`old_string` is an ordinary token. A source file documenting the edit tool used to
        collapse the coder's own successful payloads for saying the word."""
        msgs = [{"role": "tool", "tool_call_id": "r1",
                 "content": "def edit(path, old_string, new_string):\n    ...  # not an exact match"}]
        self.assertNotIn("r1", writeproxy._failed_edit_ids(msgs))

    def test_no_dead_attribute_probe_remains(self):
        """`hasattr(editrecovery, "is_edit_failure")` guarded a name that has never existed, so the
        fallback WAS the rule — a mitigation for a problem that isn't there (#4). No input can
        exercise this (the attribute is always absent, so a reintroduced guard would be dead code
        either way) — genuinely structural, so this checks the parsed AST for a `hasattr(...)` call
        rather than searching source text, which cannot be fooled by the function's own docstring
        narrating the removed pattern in prose (that prose literally contains the string
        'hasattr(editrecovery, "is_edit_failure")' — a text search has to dodge its own evidence)."""
        import ast
        import inspect
        import textwrap
        from cria import editrecovery
        self.assertFalse(hasattr(editrecovery, "is_edit_failure"))
        tree = ast.parse(textwrap.dedent(inspect.getsource(writeproxy._failed_edit_ids)))
        calls = [n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "hasattr"]
        self.assertEqual(calls, [], "a hasattr(...) guard has crept back into _failed_edit_ids")


if __name__ == "__main__":
    unittest.main()
