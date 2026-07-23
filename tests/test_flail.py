import types
import unittest

from cria.config import Role
from cria.loop import (FLAIL_WINDOW, _flail_candidate, _reasoning_of, _record_reasoning,
                       author_flail_steer)


class _Rlog:
    def emit(self, *a, **k):
        pass


# Real-ish reasoning windows drawn from the calibration sessions.
CAPSYS = [
    "capsys does not have a .stdout attribute; let me check what it exposes",
    "the fix is to assert capsys.out instead",
    "I keep guessing the attribute name and failing — must be .captured_text",
    "tried stdout and out on the fixture and both failed with AttributeError",
]
HEALTHY = [
    "created hello.py with the print statement",
    "run it to confirm it outputs Hello, world",
    "add a README with install and run instructions",
    "everything the task asked for is present; summarize and finish",
]


class PreFilterTests(unittest.TestCase):
    """The cheap lexical pre-filter — LENIENT by design: skip clearly-healthy windows so the reasoner
    isn't spent on progress; it does NOT judge (the reasoner does)."""

    def test_fires_on_circling(self):
        self.assertTrue(_flail_candidate(CAPSYS))

    def test_skips_healthy_progress(self):
        self.assertFalse(_flail_candidate(HEALTHY))

    def test_needs_a_full_window(self):
        self.assertFalse(_flail_candidate(CAPSYS[:FLAIL_WINDOW - 1]))

    def test_a_single_struggle_turn_is_not_enough(self):
        # one struggle turn among progress → below the >=2 bar → no reasoner call
        win = HEALTHY[:3] + ["that failed with an error"]
        self.assertFalse(_flail_candidate(win))


class ReasoningCaptureTests(unittest.TestCase):
    def test_reasoning_of_reads_reasoning_content(self):
        self.assertEqual(_reasoning_of({"choices": [{"message": {"reasoning_content": "hi"}}]}), "hi")
        self.assertEqual(_reasoning_of({"choices": [{"message": {"reasoning": "fallback"}}]}), "fallback")
        # a model with a reasoning channel: content is the ANSWER, reasoning_content wins
        self.assertEqual(_reasoning_of({"choices": [{"message": {"reasoning_content": "R", "content": "C"}}]}), "R")
        # a model that does NOT split reasoning out: fall back to content so the flail detector still sees
        # its thinking (the model-agnosticism fix — reading only reasoning_content disabled it for such models)
        self.assertEqual(_reasoning_of({"choices": [{"message": {"content": "inlined thinking"}}]}), "inlined thinking")

    def test_record_keeps_last_window(self):
        sess = types.SimpleNamespace(recent_reasoning=[])
        for i in range(FLAIL_WINDOW + 3):
            _record_reasoning(sess, {"choices": [{"message": {"reasoning_content": f"turn {i}"}}]})
        self.assertEqual(len(sess.recent_reasoning), FLAIL_WINDOW)          # bounded
        self.assertEqual(sess.recent_reasoning[-1], f"turn {FLAIL_WINDOW + 2}")  # newest kept

    def test_truly_empty_completion_records_nothing(self):
        sess = types.SimpleNamespace(recent_reasoning=[])
        _record_reasoning(sess, {"choices": [{"message": {"content": ""}}]})   # no reasoning AND no content
        self.assertEqual(sess.recent_reasoning, [])
        _record_reasoning(sess, {"choices": [{"message": {}}]})
        self.assertEqual(sess.recent_reasoning, [])

    def test_content_recorded_when_no_reasoning_channel(self):
        # a non-splitting model's inlined thinking IS captured (fallback), so the flail window can fill
        sess = types.SimpleNamespace(recent_reasoning=[])
        _record_reasoning(sess, {"choices": [{"message": {"content": "x"}}]})
        self.assertEqual(sess.recent_reasoning, ["x"])


class ReasonerJudgeTests(unittest.TestCase):
    """The reasoner is the real judge: NOT_STUCK → no steer; a diagnosis → the steer verbatim."""

    ROLE = Role(name="reasoner", backend="local", reasoning="on")

    def _chat(self, content):
        import json
        return lambda body, rlog: json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def test_not_stuck_yields_no_steer(self):
        self.assertIsNone(author_flail_steer(self._chat("NOT_STUCK"), self.ROLE, CAPSYS, {"messages": []}, _Rlog()))

    def test_diagnosis_becomes_the_steer(self):
        d = "You keep guessing the capsys attribute. Stop guessing and run dir(capsys) from a scratch file."
        self.assertEqual(author_flail_steer(self._chat(d), self.ROLE, CAPSYS, {"messages": []}, _Rlog()), d)

    def test_empty_reasoner_output_yields_no_steer(self):
        self.assertIsNone(author_flail_steer(self._chat(""), self.ROLE, CAPSYS, {"messages": []}, _Rlog()))

    def test_reasoner_is_given_the_actual_session_not_just_reasoning(self):
        # the reasoner must SEE the conversation (task + tool results), so it grounds instead of guessing
        import json
        seen = {}

        def capture(body, rlog):
            seen["user"] = body["messages"][-1]["content"]
            return json.dumps({"choices": [{"message": {"content": "NOT_STUCK"}}]}).encode()

        body = {"messages": [
            {"role": "user", "content": "Build the resolver in /home/jesse/src/proj"},
            {"role": "tool", "tool_call_id": "1", "content": "bash: syntax error near unexpected token"},
        ]}
        author_flail_steer(capture, self.ROLE, CAPSYS, body, _Rlog())
        self.assertIn("/home/jesse/src/proj", seen["user"])          # the real task/path is in front of it
        self.assertIn("syntax error", seen["user"])                  # the actual tool result too
        self.assertIn("keep guessing", seen["user"])                 # plus the reasoning window


if __name__ == "__main__":
    unittest.main()
