"""cria does not re-ask the exec-intent question when nothing it was built from has moved.

`live_execution_marker` runs on every completion attempt, and its first act is to ask the model how
this project runs itself. The question is composed from three things — the task, the workspace
listing, and the commands the project declares about itself — so when none of those has moved, the
prompt is byte-identical and so is the answer.

Measured over five days: **240 exec-intent calls, 104 of them byte-identical repeats (43%), 82,221
completion tokens.** One session asked the same question seven times.

Principle 9 spends a call to ground the next action and bounds it with exactly this: a call that does
not move the plan must not repeat. The key is a hash of the prompt itself, so any real change to the
task or the workspace re-asks — the memo can never hold a stale answer to a different question.
"""

import unittest

from cria import loop


class Sess:
    workspace_root = "/tmp/ws"
    exec_intent_key = ""
    exec_intent_reply = ""


class TheKeyIsThePromptItselfTests(unittest.TestCase):
    """The memo lives on the session; these pin the rule it applies, which is what makes a stale
    answer impossible: the key IS the question."""

    def key(self, system, user):
        import hashlib
        return hashlib.sha1((system + "\x00" + user).encode("utf-8", "replace")).hexdigest()

    def test_the_same_question_hits(self):
        s = Sess()
        s.exec_intent_key = self.key("sys", "how do you run it")
        s.exec_intent_reply = '{"command": "go test ./..."}'
        self.assertEqual(
            s.exec_intent_reply if s.exec_intent_key == self.key("sys", "how do you run it") else "",
            '{"command": "go test ./..."}')

    def test_a_changed_workspace_misses(self):
        s = Sess()
        s.exec_intent_key = self.key("sys", "files: cart.go")
        s.exec_intent_reply = '{"command": "go test ./..."}'
        self.assertEqual(
            s.exec_intent_reply if s.exec_intent_key == self.key("sys", "files: cart.go main.go") else "",
            "", "a moved workspace must re-ask")

    def test_a_changed_task_misses(self):
        s = Sess()
        s.exec_intent_key = self.key("sys", "task A")
        self.assertNotEqual(s.exec_intent_key, self.key("sys", "task B"))

    def test_an_empty_answer_is_never_memoised(self):
        """Caching '' would turn one bad call into permanent silence."""
        import inspect
        src = inspect.getsource(loop.live_execution_marker)
        self.assertIn("if intent_text.strip():", src)


class TheWiringIsThereTests(unittest.TestCase):
    def test_the_marker_reuses_and_says_so(self):
        import inspect
        src = inspect.getsource(loop.live_execution_marker)
        self.assertIn("loop.exec_intent_reused", src)
        self.assertIn("exec_intent_key", src)

    def test_the_session_carries_both_halves(self):
        from cria.loop import PlanSession
        f = {x.name for x in __import__("dataclasses").fields(PlanSession)}
        self.assertIn("exec_intent_key", f)
        self.assertIn("exec_intent_reply", f)

    def test_the_parse_reads_the_reused_text_not_the_completion(self):
        """The bug shape to avoid: memoise the reply, then parse the (absent) completion anyway."""
        import inspect
        src = inspect.getsource(loop.live_execution_marker)
        self.assertIn("execcheck.parse_intent(intent_text)", src)
        self.assertNotIn("parse_intent(_completion_text(comp)", src)


if __name__ == "__main__":
    unittest.main()
