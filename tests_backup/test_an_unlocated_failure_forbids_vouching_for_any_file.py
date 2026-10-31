"""An unlocated build failure may not become a lexical vouch for any file.

The old symbol matcher declared pom.xml unflagged because Maven's artifact-resolution failure had no
file:line.  There is no safe deterministic attribution to record.  The whole candidate and raw gate
fact now go to the focused validator instead.
"""
import json
import unittest

from cria import loop
from cria.config import Role


class _Rlog:
    phase = ""
    def emit(self, *args, **kwargs):
        pass


class UnlocatedFailureValidationTests(unittest.TestCase):
    def test_the_judge_gets_the_unlocated_failure_without_a_file_attribution(self):
        seen = []
        failure = "Could not find artifact org.opencsv:opencsv:jar:5.9.3"
        candidate = "pom.xml is fine; do not change it."
        def chat(body, rlog):
            seen.append(body)
            verdict = "RETROSPECTIVE" if len(seen) == 1 else "UNFAITHFUL"
            return json.dumps({"choices": [{"message": {"content": verdict}}]}).encode()

        accepted = loop.validate_compaction_briefing(
            chat,
            Role(name="reasoner", backend="local"), candidate, files="pom.xml",
            checks=failure, transcript_blocks=["tool: " + failure], rlog=_Rlog())
        self.assertFalse(accepted)
        text = "\n".join(m["content"] for m in seen[-1]["messages"])
        self.assertIn(candidate, text)
        self.assertIn(failure, text)
        self.assertNotIn("checks do NOT report a problem", text)

    def test_gate_state_no_longer_carries_a_lexical_attribution_bit(self):
        self.assertFalse(hasattr(loop.GuardState(), "last_gate_unlocated"))


if __name__ == "__main__":
    unittest.main()
