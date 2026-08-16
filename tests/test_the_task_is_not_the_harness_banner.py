"""One owner for "is this message the harness's environment banner rather than the task?".

`selfcompact.serialize` used to single out "the first user-role message" as the one rendered UNCUT,
on a comment asserting the harness frame was dropped upstream. `_drop_harness_frame` does not do
that — it drops system/developer roles and KEEPS a user-role `<environment_context>` banner — so on
any harness that sends one, the thing rendered as the north star was cwd/shell/date while the real
task was clipped like ordinary history. `loop` never trusted that assumption: it has an env-context
check and applies it at four sites for exactly this reason. Two owners, one of them wrong.

The exemption itself is now gone, because #5 removed every cut and there is nothing left to exempt
a message FROM. What remains is the question, which several callers still ask, and it has one owner.
"""

import unittest

from cria import loop, selfcompact


BANNER = ("<environment_context>\n  <cwd>/tmp/ws</cwd>\n  <shell>bash</shell>\n"
          "  <date>2026-08-16</date>\n</environment_context>")
TASK = "Add a third-party Go decimal module and use it for every money value."


class NoMessageIsPrivilegedTests(unittest.TestCase):
    def msgs(self):
        return [{"role": "user", "content": BANNER},
                {"role": "user", "content": TASK},
                {"role": "tool", "tool_call_id": "c1", "content": "ok"}]

    def test_both_the_banner_and_the_task_survive_whole(self):
        out = selfcompact.serialize(self.msgs(), defang=True)
        self.assertIn(TASK, out)
        self.assertIn("<cwd>/tmp/ws</cwd>", out)

    def test_every_line_carries_its_role_prefix(self):
        """The exemption is gone with the cut it existed to grant, so labelling is uniform."""
        out = selfcompact.serialize(self.msgs(), defang=True).splitlines()
        self.assertTrue(all(l.startswith(("the task/context said:", "→")) for l in out), out)

    def test_serialize_takes_no_whole_flag_any_more(self):
        import inspect
        self.assertNotIn("whole", inspect.signature(selfcompact._defanged_line).parameters)


class OneOwnerTests(unittest.TestCase):
    def test_loop_calls_the_shared_check_and_defines_none_of_its_own(self):
        self.assertFalse(hasattr(loop, "_is_env_context"))
        self.assertTrue(callable(selfcompact.is_env_context))

    def test_it_recognises_both_known_conventions(self):
        self.assertTrue(selfcompact.is_env_context({"content": BANNER}))
        self.assertTrue(selfcompact.is_env_context({"content": "<user_instructions>x</user_instructions>"}))
        self.assertFalse(selfcompact.is_env_context({"content": TASK}))

    def test_it_reads_structured_content_too(self):
        self.assertTrue(selfcompact.is_env_context(
            {"content": [{"type": "text", "text": BANNER}]}))


if __name__ == "__main__":
    unittest.main()
