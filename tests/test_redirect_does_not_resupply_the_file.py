"""The redirect quotes the offending call back to the coder. For a write it carried the WHOLE
file body.

Walked on ada-handles_fabliq_codex_pon_1785732102 call 0079: cria re-sent the exact 3.2 KB of
handle_resolver.py it was telling the model to stop producing, under the words "Choose a DIFFERENT
next action and take it now via a tool call." The model satisfied that literally — same 3.2 KB, new
filename `test_handle.py` — and did it again three calls later into `resolver.py`. cria supplied the
content and asked for something different, so the only thing left to vary was the name.

The emit on the very next line already clipped the same string to 120 chars for cria's own log. It
was bounded for the record and unbounded for the model.
"""
import unittest

from cria import loop, prompts


class RepeatActionIsBoundedTests(unittest.TestCase):
    def test_the_constant_exists_and_is_modest(self):
        self.assertTrue(0 < loop.REPEAT_ACTION_CHARS <= 400)

    def test_the_quoted_action_is_clipped_where_it_is_set(self):
        """Driven through the real _refusals_in_window: a refused 3.2KB write must come back
        bounded, at the one place that decides what the redirect quotes."""
        from cria import denial
        body = "x" * 3200
        messages = [
            {"role": "assistant", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "write_file",
                 "arguments": '{"path": "handle_resolver.py", "content": "%s"}' % body}}]},
            {"role": "tool", "tool_call_id": "c1", "content": denial.mark("outside the workspace")},
        ]
        n, last = loop._refusals_in_window(messages)
        self.assertEqual(n, 1)
        self.assertLess(len(last), 400)
        self.assertNotIn(body, last)
        self.assertIn("handle_resolver.py", last)   # bounded, not blank — the path still survives

    def test_a_3kb_write_cannot_be_re_supplied_through_the_redirect(self):
        body = "x" * 3200
        action = loop._clip(f'write_file {{"path": "handle_resolver.py", "content": "{body}"}}',
                            loop.REPEAT_ACTION_CHARS)
        self.assertLess(len(action), 400)
        self.assertNotIn(body, action)

    def test_the_path_still_survives_so_the_redirect_stays_specific(self):
        action = loop._clip(
            'write_file {"path": "handle_resolver.py", "content": "%s"}' % ("x" * 3200),
            loop.REPEAT_ACTION_CHARS)
        self.assertIn("write_file", action)
        self.assertIn("handle_resolver.py", action)

    def test_the_rendered_redirect_carries_the_bounded_form(self):
        action = loop._clip('write_file {"path": "a.py", "content": "%s"}' % ("y" * 3200),
                            loop.REPEAT_ACTION_CHARS)
        out = prompts.render("redirect_canned", repeat_action=action, ground_truth="")
        self.assertIn("a.py", out)
        self.assertNotIn("y" * 500, out)
