"""The per-step confirm brake runs only where a disk inspection can ground — and the verbless
question is JUDGED, not pattern-matched.

Walked on ada-handles_ornith_codex_poff_1785830161: the critic ruled the reading step done three
times on real fetch-ledger evidence and the confirm vetoed each one by inventing artifacts a
research step never promises (measured coin flip on such claims: 155 pass / 158 block). The first
fix gated the brake on a production-VERB list — fuzzy-deterministic (operator, 2026-08-04), and
verb-blind: "Update the README" read as artifact-free. Now: a named FILE is exact and keeps the
deterministic path; the repo being red (this call's findings OR the session's standing red state)
always grounds the brake; otherwise ONE reasoner question rules, failing toward running the brake.
"""

import os
import tempfile
import unittest

from cria.loop import _claim_promises_artifacts, _confirm_applies, step_names_absent_artifact

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


class ClaimPromisesArtifactsTests(unittest.TestCase):
    """The deterministic half: file tokens only, exact — verbs are no longer its business."""

    def test_file_token_promises(self):
        self.assertTrue(_claim_promises_artifacts("Fix the retry loop in src/handle.py"))

    def test_domain_is_not_a_file(self):
        self.assertFalse(_claim_promises_artifacts(
            "Fetch the spec from api.handle.me and learn its schemas"))

    def test_url_path_is_not_a_file(self):
        self.assertFalse(_claim_promises_artifacts(
            "Read https://api.handle.me/openapi.json to learn the response schemas"))

    def test_verbless_prose_names_no_artifact(self):
        self.assertFalse(_claim_promises_artifacts("Update the README with usage instructions"))


class ConfirmAppliesTests(unittest.TestCase):
    def test_named_file_applies_without_a_call(self):
        ask = _Ask("NO")
        self.assertTrue(_confirm_applies("Write unit tests in test_handle.py", ask=ask))
        self.assertEqual(ask.prompts, [])

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
