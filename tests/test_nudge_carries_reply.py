"""nemotron-nano 1786243834, call 0073: the unexecuted-write nudge fired — the ONE right steer of
the run — saying "your last message contained the file's contents as text … send that same content
again as a write tool call". But the re-framed view rebuilds history from the harness body, which
never saw the internal prose turn: 0073's 12 messages contain no assistant prose at all. Ordered
to resend text it could not see, the model re-read the spec file a 7th time and the run died.

Rule 5b: cria never states a false fact — "your last message contained X" requires that message to
be in the frame. Both drive paths now put the coder's own no-tool-call reply in front of the nudge.
"""
import inspect
import unittest

from cria import loop, prompts


class TheNudgeRidesBehindTheReplyTests(unittest.TestCase):
    def test_the_session_carries_the_reply_field(self):
        import dataclasses
        f = {x.name: x for x in dataclasses.fields(loop.PlanSession)}
        self.assertIn("nudge_reply", f)
        self.assertEqual(f["nudge_reply"].default, "")

    def test_the_multi_step_path_stashes_the_reply(self):
        src = inspect.getsource(loop.Loop)
        i = src.index('rlog.emit("loop.unexecuted_write", step=idx')
        window = src[i:i + 600]
        self.assertIn("sess.nudge_reply = _completion_text(coder)", window)

    def test_the_work_frame_emits_reply_then_nudge(self):
        src = inspect.getsource(loop.Loop)
        i = src.index("if sess.nudge_reason:")
        window = src[i:i + 700]
        self.assertIn("sess.nudge_reply", window)
        self.assertLess(window.index("nudge_reply"), window.index('prompts.render("nudge"'),
                        "the reply must precede the nudge that talks about it")

    def test_the_plan_off_path_appends_the_reply_before_the_nudge(self):
        src = inspect.getsource(loop.Loop._gate_single_done)
        i = src.index('rlog.emit("loop.unexecuted_write", plan_off=True')
        window = src[i:i + 700]
        self.assertIn('{"role": "assistant", "content": _completion_text(comp)}', window)
        self.assertLess(window.index("_completion_text(comp)"),
                        window.index("unexecuted_write_nudge"))

    def test_the_nudge_text_still_references_the_last_message(self):
        """If the prompt is ever reworded to stop referencing the reply, the carrying mechanism
        should be reconsidered — this pins the coupling both ways."""
        self.assertIn("your last message", prompts.load("unexecuted_write_nudge"))


if __name__ == "__main__":
    unittest.main()
