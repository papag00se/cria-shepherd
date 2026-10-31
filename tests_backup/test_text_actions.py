"""F5 — the remaining ways phi4 expresses an ACTION as text, recovered in the massage chain.

Fixtures (`fixtures/phi4_text_actions/replies.json`) are replies copied byte-for-byte out of ~/.cria/calls,
each with the request's own tool menu; `source` names the capture. Two units live here:

* the call object's SHAPE, not its key names (`{action, parameters}`, `{tool_call, arguments}`, …)
* a code fence before the call that the call's payload merely REPEATS (the draft-then-write reply)
"""
import json
import unittest
from pathlib import Path

from cria.massage import recover_leaked_tool_calls

FIX = json.loads((Path(__file__).parent / "fixtures" / "phi4_text_actions" / "replies.json").read_text())
READ_MENU = [{"type": "function", "function": {"name": "read_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]


class Rec:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def fields(self, kind):
        return next((f for k, f in self.events if k == kind), None)


def run(content, tools, finish="stop"):
    comp = {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}
    rec = Rec()
    ch = recover_leaked_tool_calls(comp, tools, rec)["choices"][0]
    calls = [(c["function"]["name"], json.loads(c["function"]["arguments"])) for c in ch["message"].get("tool_calls") or []]
    return ch, calls, rec


def fixture(name):
    fx = FIX["replies"][name]
    return fx["content"], FIX["menus"][fx["menu"]], fx["finish_reason"]


class ShapeTests(unittest.TestCase):
    def test_every_spelling_phi4_uses_for_the_same_call_is_recovered(self):
        for name, want in (("b_action_parameters_0141", "read_file"), ("b_action_args_0153", "read_file"),
                           ("b_action_arguments_0159", "read_file"), ("b_arguments_tool_call_0079", "edit_file")):
            with self.subTest(name):
                content, tools, fin = fixture(name)
                ch, calls, rec = run(content, tools, fin)
                self.assertEqual([c[0] for c in calls], [want])
                self.assertEqual(ch["finish_reason"], "tool_calls")
                self.assertIsNotNone(rec.fields("massage.fenced_call_recovered"))

    def test_objects_that_are_data_not_calls_stay_lost(self):
        """A package.json, a tool-schema echo, a bare patch body and a {name, content} file object."""
        for name in ("neg_dependencies_description_devDependencies_0002", "neg_description_name_parameters_0003",
                     "neg_content_name_0107", "neg_input_0011"):
            with self.subTest(name):
                content, tools, fin = fixture(name)
                ch, calls, _ = run(content, tools, fin)
                self.assertEqual(calls, [])
                self.assertEqual(ch["message"]["content"], content)

    def test_a_two_key_object_whose_string_is_not_a_menu_tool_is_refused_by_the_menu(self):
        ch, calls, rec = run('```json\n{"action": "deploy_prod", "parameters": {"path": "x"}}\n```', READ_MENU)
        self.assertEqual(calls, [])
        self.assertEqual(rec.fields("massage.fenced_call_refused")["reason"], "off_menu")


class EchoedDraftTests(unittest.TestCase):
    def test_the_a1_nudge_reply_recovers_its_first_write_only(self):
        """A1 call 0015: a ```java draft, then two write_file envelopes in ```json fences and a
        task_complete. The first write's `content` IS the java fence. Before: prefix_fence, lost."""
        content, tools, fin = fixture("a1_0015")
        ch, calls, rec = run(content, tools, fin)
        self.assertEqual([c[0] for c in calls], ["write_file"])
        draft = content.split("```java\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual("".join(calls[0][1]["content"].split()), "".join(draft.split()))
        self.assertNotIn("task_complete", json.dumps(ch["message"]))     # never toward done
        self.assertTrue(rec.fields("massage.fenced_call_recovered")["later_envelopes"] >= 1)

    def test_a_write_that_is_not_a_draft_above_it_is_still_refused(self):
        content, tools, fin = fixture("a1_0015")
        changed = content.replace('"name": "write_file"', '"name": "write_file"', 1)
        # a fresh payload: same reply, but the java draft no longer matches what the call writes
        altered = changed.replace("```java\n", "```java\n// edited after the fact\n", 1)
        ch, calls, rec = run(altered, tools, fin)
        self.assertEqual(calls, [])
        self.assertEqual(rec.fields("massage.fenced_call_refused")["reason"], "prefix_fence")

    def test_a_json_fence_before_the_call_is_a_result_not_a_draft(self):
        content = ('```text\nx\n```\n```json\n{"status": "success"}\n```\n' + "```java\n" + "int a;\n" * 30 + "```\n"
                   '```json\n{"name": "write_file", "arguments": {"path": "A.java", "content": "' +
                   "int a;\\n" * 30 + '"}}\n```')
        tools = [{"type": "function", "function": {"name": "write_file", "parameters": {
            "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}}]
        _, calls, rec = run(content, tools)
        self.assertEqual(calls, [])
        self.assertEqual(rec.fields("massage.fenced_call_refused")["reason"], "prefix_fence")

    def test_calls_written_as_syntax_inside_fences_stay_refused(self):
        """A1 call 0018: `write_file({...})` inside ```plaintext fences. Measured over every capture: 15
        replies, 3 with the call as the first fence — not built (see f5-text-actions.md §A5)."""
        content, tools, fin = fixture("a1_0018")
        _, calls, _ = run(content, tools, fin)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
