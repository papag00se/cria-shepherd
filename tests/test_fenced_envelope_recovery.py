"""F4 — a call the model fenced as a JSON envelope in `content` is recovered (first call only).

phi4 writes its tool call as ```json {"name": "list_dir", "arguments": {…}} ``` with no tool_calls
(feed-pipeline-java_phi4_codex_poff_1791646575 calls 0004, 0141…0180; 196 of 44,234 captured
coder/proxy replies, every one phi4). The harness persona is not the cause and a text steer does not
convert it (replay-f2: 0/14, 0/6), so the recovery is deterministic, in the existing owner
`massage.recover_leaked_tool_calls`.

Every fixture in `fixtures/phi4_fenced_calls/replies.json` is a reply copied out of ~/.cria/calls with
the menu THAT request advertised. Every refusal has a positive control (a reply the same function
does recover) so a refusal cannot be mistaken for the function doing nothing.
"""
import copy
import json
import unittest
from pathlib import Path

from cria.massage import recover_leaked_tool_calls

FIX = json.loads((Path(__file__).parent / "fixtures" / "phi4_fenced_calls" / "replies.json").read_text())
FEED = "/home/jesse/suite-runs/suite-feed-pipeline-java_phi4_codex_poff_1791646575-sa3gzou3"


class Rec:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [k for k, _ in self.events]

    def fields(self, kind):
        return next(f for k, f in self.events if k == kind)


def _run(name, *, content=None, finish=None, tools=None, extra=None):
    fx = FIX["replies"][name]
    msg = {"role": "assistant", "content": fx["content"] if content is None else content}
    msg.update(extra or {})
    comp = {"choices": [{"message": msg, "finish_reason": finish or fx["finish_reason"]}]}
    rec = Rec()
    menu = FIX["menus"][fx["menu"]] if tools is None else tools
    out = recover_leaked_tool_calls(comp, menu, rec)
    return out["choices"][0], rec


def _calls(choice):
    return [(c["function"]["name"], json.loads(c["function"]["arguments"]))
            for c in choice["message"].get("tool_calls") or []]


class RecoveredTests(unittest.TestCase):
    def check(self, name, want, *, not_in=(), later=None):
        ch, rec = _run(name)
        self.assertEqual(_calls(ch), [want])                       # the first call, and only it
        self.assertEqual(ch["finish_reason"], "tool_calls")
        content = ch["message"]["content"] or ""
        original = FIX["replies"][name]["content"]
        self.assertTrue(original.startswith(content))              # the prose before the fence, verbatim
        self.assertNotIn("```json", content)
        for text in not_in:
            self.assertNotIn(text, content)
        f = rec.fields("massage.fenced_call_recovered")
        self.assertEqual(f["calls"], [want[0]])
        self.assertEqual(f["dropped_chars"], len(original) - original.index("```json"))   # disclosed, not silent
        if later is not None:
            self.assertEqual(f["later_envelopes"], later)
        return ch

    def test_the_incident_call_feed_java_0004(self):
        # plaintext "Preamble" fence then the list_dir envelope, later a read_file and a task_complete
        ch = self.check("feed_java_0004_incident", ("list_dir", {"path": FEED}), later=3)
        self.assertIn("```plaintext", ch["message"]["content"])    # the model's own preamble is kept

    def test_a_single_list_dir_call(self):
        self.check("feed_java_0220_list_dir", ("list_dir", {"path": FEED}), later=0)

    def test_a_read_with_a_line_range(self):
        self.check("shipping_rb_0045_read_file_range",
                   ("read_file", {"path": "test/test_rates.rb", "start_line": 15, "end_line": 15}), later=0)

    def test_the_waiting_tail_is_not_forwarded(self):
        self.check("orders_py_0086_waiting_tail", ("read_file", {"path": "orders/app.py"}),
                   not_in=("Waiting for tool result",), later=0)

    def test_four_queued_reads_become_one(self):
        self.check("orders_py_0164_preamble_four_reads", ("read_file", {"path": "orders/app.py"}), later=3)

    def test_a_later_edit_built_on_unseen_content_is_not_promoted(self):
        ch = self.check("shipping_rb_0027_read_then_unseen_edit",
                        ("read_file", {"path": "test/test_rates.rb", "start_line": 15, "end_line": 15}),
                        not_in=("Assuming the test case",))
        self.assertEqual(len(_calls(ch)), 1)

    def test_a_fabricated_tool_result_after_the_first_call_is_dropped(self):
        self.check("shipping_rb_0035_fabricated_tool_tail",
                   ("read_file", {"path": "lib/shipping/rates.rb"}), not_in=("**[tool]**", "BASE_RATES"))

    def test_a_trailing_task_complete_is_never_forwarded(self):
        """Never toward done: the completion claim at the end is a tail, the write before it is the call."""
        ch = self.check("cart_go_0104_write_then_task_complete",
                        ("write_file", {"path": "go.mod", "content":
                         "module suite-cart-billing-go\n\ngo 1.20\n\nrequire github.com/shopspring/decimal v1.3.1\n"}))
        self.assertNotIn("task_complete", json.dumps(ch["message"]))


class RefusedTests(unittest.TestCase):
    def refused(self, name, reason, **kw):
        ch, rec = _run(name, **kw)
        self.assertEqual(_calls(ch), [])
        base = FIX["replies"][name]["content"] if kw.get("content") is None else kw["content"]
        self.assertEqual(ch["message"]["content"], base)           # byte-identical: today's behaviour
        self.assertEqual(rec.fields("massage.fenced_call_refused")["reason"], reason)
        self.assertNotIn("massage.fenced_call_recovered", rec.kinds())

    def test_a_fabricated_session_is_refused_not_run(self):
        """feed-java 0093/0180: the FIRST JSON envelope is a write_file built on an invented read."""
        self.refused("feed_java_0093_fabricated_session", "prefix_fence")
        self.refused("feed_java_0180_fabricated_session", "prefix_fence")

    def test_drafts_then_writes_are_refused_unless_the_write_echoes_a_draft(self):
        """rust 0019: six drafts, then writes that are NOT any one of them. (shipping_rb 0003, a draft
        the write repeats verbatim, was a refusal until the identity rule — see test_text_actions.)"""
        self.refused("rust_0019_drafts_then_writes", "prefix_fence")

    def test_a_tool_schema_echo_and_drafts_are_refused(self):
        self.refused("node_0003_schema_echo_and_drafts", "prefix_fence")

    def test_a_patch_in_a_json_fence_is_refused(self):
        # The patch fence IS echoed by the apply_patch envelope (identity), so the leader rule no
        # longer decides this reply; the narrowed menu does — apply_patch is not on it.
        self.refused("cart_go_0154_patch_fence", "off_menu")

    def test_a_name_the_narrowed_menu_does_not_carry_is_refused(self):
        self.refused("orders_py_0201_offmenu_narrowed_menu", "off_menu")

    # --- each variant below has the positive control in RecoveredTests / test_controls ---
    def test_a_reply_cut_at_the_output_cap_is_refused(self):
        ch, rec = _run("feed_java_0220_list_dir", finish="length")
        self.assertEqual(_calls(ch), [])
        self.assertEqual(rec.fields("massage.fenced_call_refused")["reason"], "length")

    def test_a_nested_envelope_is_refused(self):
        env = '```json\n{"name": "list_dir", "arguments": {"path": "."}}\n```'
        ch, rec = _run("feed_java_0220_list_dir", content="Example:\n```markdown\n" + env + "\n```\n")
        self.assertEqual(_calls(ch), [])

    def test_string_arguments_undeclared_keys_and_missing_required_are_refused(self):
        for body, why in (('{"name": "list_dir", "arguments": "."}', None),
                          ('{"name": "list_dir", "arguments": {"dir": "."}}', "inadmissible"),
                          ('{"name": "read_file", "arguments": {"start_line": 1}}', "inadmissible"),
                          ('{"name": "list_dir", "arguments": {"path": "."}, "id": 1}', None)):
            ch, rec = _run("feed_java_0220_list_dir", content="I will look.\n```json\n" + body + "\n```")
            self.assertEqual(_calls(ch), [], body)

    def test_no_menu_no_action(self):
        ch, _ = _run("feed_java_0220_list_dir", tools=[])
        self.assertEqual(_calls(ch), [])

    def test_a_reply_that_already_has_a_tool_call_is_untouched(self):
        real = [{"id": "c1", "type": "function", "function": {"name": "list_dir", "arguments": "{}"}}]
        ch, rec = _run("feed_java_0220_list_dir", extra={"tool_calls": real})
        self.assertEqual(ch["message"]["tool_calls"], real)
        self.assertEqual(rec.events, [])


class ControlTests(unittest.TestCase):
    """The same refused replies, with the offending property removed, ARE recovered."""

    def test_the_fabricated_session_minus_its_prefix_fences_recovers(self):
        content = FIX["replies"]["feed_java_0093_fabricated_session"]["content"]
        body = content[content.index("```json\n{\n  \"name\": \"write_file\""):]
        ch, _ = _run("feed_java_0093_fabricated_session", content="Updating pom.xml.\n" + body)
        self.assertEqual([n for n, _a in _calls(ch)], ["write_file"])

    def test_the_off_menu_name_recovers_when_the_menu_carries_it(self):
        full = FIX["menus"][FIX["replies"]["feed_java_0220_list_dir"]["menu"]]
        ch, _ = _run("orders_py_0201_offmenu_narrowed_menu", tools=full)
        self.assertEqual([n for n, _a in _calls(ch)], ["list_dir"])

    def test_the_length_reply_recovers_when_it_was_not_cut(self):
        ch, _ = _run("feed_java_0220_list_dir", finish="stop")
        self.assertEqual(len(_calls(ch)), 1)

    def test_the_same_envelope_unnested_recovers(self):
        env = '```json\n{"name": "list_dir", "arguments": {"path": "."}}\n```'
        ch, _ = _run("feed_java_0220_list_dir", content="Listing.\n" + env)
        self.assertEqual(_calls(ch), [("list_dir", {"path": "."})])
        self.assertEqual(ch["message"]["content"], "Listing.")

    def test_any_model_a_fenced_envelope_with_parameters_key_recovers(self):
        ch, _ = _run("feed_java_0220_list_dir",
                     content='```json\n{"name": "list_dir", "parameters": {"path": "."}}\n```')
        self.assertEqual(_calls(ch), [("list_dir", {"path": "."})])
        self.assertIsNone(ch["message"]["content"])


if __name__ == "__main__":
    unittest.main()
