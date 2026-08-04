"""The per-step confirm brake does not run where nothing it checks can exist.

Walked on ada-handles_ornith_codex_poff_1785830161 (REGRESSION1, 0/4 at the 15-min milestone): the
critic ruled the model-authored reading step done THREE times on real fetch-ledger evidence, and the
read-only confirm checker vetoed each one by inventing artifacts the step never promised ("no
resolver script exists" — the resolver is step 2's work; "move or symlink the file from
tmp/read-only/"; a wrong-schema reply that failed closed). ~30 judge calls; coding started with 7 of
15 minutes left. Measured over every captured confirm chain: on claims naming no artifact the final
verdicts are a coin flip (155 confirmed / 158 blocked, 36 sessions) — noise with veto power.

The fix is deterministic applicability, scoped to the PER-STEP confirm: it runs only when the claim
promises something the disk could hold — a production verb ("write unit tests") or a file token
that is not the claim's own named DOMAIN — or when the repo's checks are currently RED (then the
disk state is contested regardless of the step's wording). The whole-task satisfaction confirm is
untouched: tasks name deliverables as nouns ("script plus README") and its measured wins are
exactly that shape.
"""

import os
import tempfile
import unittest

from cria.loop import _claim_promises_artifacts, _confirm_applies, step_names_absent_artifact

READING_STEP = ("Read the api.handle.me documentation to learn its authentication requirements, "
                "available endpoints, and response schemas so the resolver script can properly "
                "call the API.")


class ClaimPromisesArtifactsTests(unittest.TestCase):
    def test_reading_step_promises_nothing(self):
        self.assertFalse(_claim_promises_artifacts(READING_STEP))

    def test_production_verb_promises(self):
        self.assertTrue(_claim_promises_artifacts("Write unit tests for the resolver"))

    def test_file_token_promises(self):
        self.assertTrue(_claim_promises_artifacts("Fix the retry loop in src/handle.py"))

    def test_domain_is_not_a_file(self):
        self.assertFalse(_claim_promises_artifacts(
            "Fetch the spec from api.handle.me and learn its schemas"))

    def test_url_path_is_not_a_file(self):
        self.assertFalse(_claim_promises_artifacts(
            "Read https://api.handle.me/openapi.json to learn the response schemas"))


class ConfirmAppliesTests(unittest.TestCase):
    def test_reading_step_clean_repo_skips_the_brake(self):
        # FAILS BEFORE THE FIX (as behavior): the checker was consulted on the reading step and its
        # invented-artifact veto stood, blocking a step the critic had verified against the ledger.
        self.assertFalse(_confirm_applies(READING_STEP, red_findings=""))

    def test_red_gate_grounds_the_brake_even_on_a_reading_step(self):
        self.assertTrue(_confirm_applies(READING_STEP, red_findings="handle.py:8: undefined name"))

    def test_artifact_claim_always_applies(self):
        self.assertTrue(_confirm_applies("Write unit tests in test_handle.py"))


class AbsentArtifactDomainTests(unittest.TestCase):
    def test_empty_workspace_reading_step_is_not_vetoed_on_its_domain(self):
        # FAILS BEFORE THE FIX: "api.handle.me" matched the file-token pattern, so an empty
        # workspace deterministically vetoed a reading step for lacking a file named after a domain.
        with tempfile.TemporaryDirectory() as ws:
            self.assertEqual(step_names_absent_artifact(READING_STEP, ws), "")

    def test_empty_workspace_still_vetoes_a_named_file(self):
        with tempfile.TemporaryDirectory() as ws:
            self.assertEqual(
                step_names_absent_artifact("Write a CLI script resolve_handle.py", ws),
                "resolve_handle.py")


if __name__ == "__main__":
    unittest.main()
