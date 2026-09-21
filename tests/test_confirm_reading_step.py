"""The per-step confirm brake runs only where a disk inspection can ground.

Whether a step produces an artifact is semantic judgment, even when it names a path: a read-only
step can name its input.  A red repository always grounds the brake; otherwise one focused
reasoner question decides, failing toward running the brake when it cannot answer.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cria import config, loop, wsview
from cria.loop import _confirm_applies, step_names_absent_artifact


CAPTURE = Path("/home/jesse/.cria/calls/20260921T131112-01a0c598-12c3-7973-8ebd-3f87b1ce0016")
WORKSPACE = Path("/home/jesse/suite-runs/suite-feed-pipeline-java_ternary-bonsai-2_codex_pon_1790021450-8kp49tei")
FEED_READING_STEP = ("Read data/feed_messy.csv in full and the first ~20 lines of data/feed.csv "
                     "to confirm the exact column layout and identify the specific malformed patterns "
                     "present (currency symbols, blank quantities, missing columns, quoted commas).")

READING_STEP = ("Read the api.handle.me documentation to learn its authentication requirements, "
                "available endpoints, and response schemas so the resolver script can properly "
                "call the API.")


class _Ask:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def __call__(self, system):
        self.prompts.append(system)
        return self.answer


class ConfirmAppliesTests(unittest.TestCase):
    def test_named_output_applies_on_a_YES_ruling(self):
        ask = _Ask("YES")
        self.assertTrue(_confirm_applies("Write unit tests in test_handle.py", ask=ask))
        self.assertEqual(len(ask.prompts), 1)

    def test_named_input_reading_step_skips_on_a_NO_ruling(self):
        ask = _Ask("NO")
        self.assertFalse(_confirm_applies(FEED_READING_STEP, ask=ask))
        self.assertEqual(len(ask.prompts), 1)

    def test_red_gate_applies_without_a_call(self):
        ask = _Ask("NO")
        self.assertTrue(_confirm_applies(READING_STEP, red_findings="handle.py:8: undefined name", ask=ask))
        self.assertTrue(_confirm_applies(READING_STEP, gate_red=True, ask=ask))
        self.assertEqual(ask.prompts, [])   # a contested disk needs no question

    def test_reading_step_skips_on_a_NO_ruling(self):
        ask = _Ask("NO")
        self.assertFalse(_confirm_applies(READING_STEP, ask=ask))
        self.assertEqual(len(ask.prompts), 1)

    def test_update_step_applies_on_a_YES_ruling(self):
        # The verb-blind case the old list missed: the reasoner sees "Update the README" promises
        # a document on disk.
        self.assertTrue(_confirm_applies("Update the README with usage instructions", ask=_Ask("YES")))

    def test_unreadable_ruling_keeps_the_brake(self):
        for garbage in ("", "perhaps", "NOT_SURE"):
            self.assertTrue(_confirm_applies(READING_STEP, ask=_Ask(garbage)))

    def test_no_reasoner_keeps_the_brake(self):
        self.assertTrue(_confirm_applies(READING_STEP, ask=None))


class FeedCaptureConfirmationRegressionTests(unittest.TestCase):
    """The captured positive read verdict must not enter its known-bad confirmation chain."""

    class _Rlog:
        def __init__(self):
            self.events = []

        def emit(self, kind, **kwargs):
            self.events.append((kind, kwargs))

    class _CapturedPositiveThenNoArtifact:
        def __init__(self):
            self.replies = [
                (CAPTURE / "0100-critic.response.json").read_bytes(),
                json.dumps({"choices": [{"message": {"content": "NO"}}]}).encode(),
            ]
            self.bodies = []

        def __call__(self, body, _rlog):
            self.bodies.append(body)
            return self.replies.pop(0)

    def test_c598_positive_reading_verdict_advances_without_confirmation(self):
        self.assertTrue(CAPTURE.is_dir(), CAPTURE)
        self.assertTrue(WORKSPACE.is_dir(), WORKSPACE)
        chat = self._CapturedPositiveThenNoArtifact()
        view = wsview.View(str(WORKSPACE), "feed-read-confirm-replay")
        raw = subprocess.run(["bash", "-c", wsview.survey_command("feed-read-confirm-replay")],
                             cwd=WORKSPACE, capture_output=True, text=True, check=True).stdout
        wsview.apply_survey(view, wsview.strip_survey(raw)[1])
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)
        ctx = loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=chat, runs_dir="")
        ctx.reasoner_role = config.Role(name="reasoner", backend="local")
        rlog = self._Rlog()
        verdict = loop.Loop(ctx)._verify(FEED_READING_STEP, "coder completed the reads", "", "",
                                         rlog, idx=3, total=10, key="feed-c598",
                                         workspace_root=str(WORKSPACE))
        self.assertTrue(verdict.done)
        self.assertIsNone(verdict.confirmation)
        self.assertEqual(len(chat.bodies), 2)
        self.assertEqual(chat.replies, [])
        self.assertIn("Read data/feed_messy.csv", "\n".join(
            str(message.get("content", "")) for message in chat.bodies[1]["messages"]))
        self.assertIn("loop.confirm_skipped_no_artifact", [kind for kind, _ in rlog.events])


class AbsentArtifactDomainTests(unittest.TestCase):
    def test_empty_workspace_reading_step_is_not_vetoed_on_its_domain(self):
        with tempfile.TemporaryDirectory() as ws:
            self.assertEqual(step_names_absent_artifact(READING_STEP, ws), "")

    def test_empty_workspace_still_vetoes_a_named_file(self):
        with tempfile.TemporaryDirectory() as ws:
            self.assertEqual(
                step_names_absent_artifact("Write a CLI script resolve_handle.py", ws),
                "resolve_handle.py")


if __name__ == "__main__":
    unittest.main()
