"""A judge's thinking often holds the verdict its answer did not. Recover it — one direction only."""
import unittest

from cria import loop


class _Rlog:
    def __init__(self): self.events = []
    def emit(self, kind, **kw): self.events.append((kind, kw))


# Verbatim from run 20260729T224807/0130-satisfaction. cria's prompt ended "Answer NOW with ONLY the
# JSON verdict"; the content field held a leaked <|tool_call>call:read_file{...} and this was the
# thinking that came with it.
REAL = ("The task is not done. The live test output shows Holder: unknown and Total Handles: 0 for "
        "papagoose, while the real data in papagoose.txt has holder=\"stake1...\" and a non-zero "
        "total (the API response contains it). This means resolve_handle is not correctly "
        "extracting the holder name.")


class RecoveryTests(unittest.TestCase):
    def test_the_real_discarded_verdict_is_recovered(self):
        out = loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "satisfaction")
        self.assertIsNotNone(out)
        self.assertIs(out["satisfied"], False)
        self.assertIn("not done", out["reason"])

    def test_the_reason_carries_the_DIAGNOSIS_not_just_a_refusal(self):
        out = loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "satisfaction")
        self.assertIn("Holder: unknown", out["reason"])

    def test_it_is_traced_never_silent(self):
        rlog = _Rlog()
        loop.verdict_from_reasoning(REAL, "satisfied", rlog, "satisfaction")
        self.assertIn("loop.verdict_from_reasoning", [k for k, _ in rlog.events])

    def test_the_phase_key_is_whatever_the_caller_needs(self):
        for flag in ("satisfied", "done", "consistent"):
            with self.subTest(flag=flag):
                self.assertIs(loop.verdict_from_reasoning(REAL, flag, _Rlog(), "x")[flag], False)


class OneDirectionOnlyTests(unittest.TestCase):
    """Principle 13: fail CLOSED on completion. An approval recovered from prose would be failing
    OPEN, which is the one thing this must never do."""

    APPROVALS = (
        "The task is done. Every deliverable is present and the tests pass.",
        "All requirements are met — script, tests, live test and README are all there.",
        "Nothing is missing. This is fully satisfied.",
        "The work is complete and correct.",
    )

    def test_no_approval_is_EVER_recovered(self):
        for text in self.APPROVALS:
            with self.subTest(text=text[:40]):
                self.assertIsNone(loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x"))

    def test_a_recovered_verdict_is_always_False(self):
        for text in (REAL, "The README does not exist.", "The task is not complete."):
            out = loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x")
            if out is not None:
                self.assertIs(out["satisfied"], False)


class QuietWhenThereIsNothingTests(unittest.TestCase):
    def test_empty_reasoning_recovers_nothing(self):
        for text in ("", "   ", None):
            self.assertIsNone(loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x"))

    def test_reasoning_with_no_ruling_recovers_nothing(self):
        # 10 of the 46 measured cases look like this — thinking present, no verdict in it.
        text = ("Let me look at the workspace. There is a handle_client.py and a test file. "
                "The API base URL is https://api.handle.me and the client uses requests.")
        self.assertIsNone(loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x"))

    def test_a_mere_mention_of_a_failing_test_is_not_a_ruling(self):
        # "the tests fail" inside a description must not become a verdict on the whole task.
        self.assertIsNone(loop.verdict_from_reasoning(
            "I ran pytest and looked at the output.", "satisfied", _Rlog(), "x"))


class WiringTests(unittest.TestCase):
    def test_the_satisfaction_parser_falls_back_to_the_reasoning(self):
        import inspect
        src = inspect.getsource(loop._satisfaction_verdict)
        self.assertIn("verdict_from_reasoning", src)
        self.assertIn("extract_json_object", src)   # the normal path is still tried FIRST
