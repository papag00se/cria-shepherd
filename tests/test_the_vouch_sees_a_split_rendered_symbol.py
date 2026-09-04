"""A compiler/briefing disagreement is judged, never settled by token containment.

The Java L5 capture put these three claims in one coder prompt: a rollup said ``net.opencsv`` was
correct, javac said ``package net.opencsv does not exist``, and cria's lexical vouch said the checks
did not report an OpenCSV problem.  The validator is a closed, fail-closed question over the exact
candidate, transcript, disk inventory, and check facts; it cannot author a replacement.
"""
import json
import unittest

from cria import loop
from cria.config import Role


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def _reply(text):
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": text},
                                     "finish_reason": "stop"}]}).encode()


class CompactionBriefingValidationTests(unittest.TestCase):
    def setUp(self):
        self.role = Role(name="reasoner", backend="local")
        self.rlog = _Rlog()
        self.candidate = "The correct imports are net.opencsv; the build now compiles."
        self.checks = "Importer.java:10: package net.opencsv does not exist\nBUILD EXIT: 1"

    def test_the_java_falsehood_is_withheld_when_the_judge_rejects_it(self):
        seen = []

        def chat(body, _rlog):
            seen.append(body)
            # The candidate is retrospective; the independent fidelity lens catches its false fact.
            return _reply("RETROSPECTIVE" if len(seen) == 1 else "UNFAITHFUL")

        accepted = loop.validate_compaction_briefing(
            chat, self.role, self.candidate, files="pom.xml\nsrc/main/java/pipeline/Importer.java",
            checks=self.checks, transcript_blocks=["tool: " + self.checks], rlog=self.rlog)
        self.assertFalse(accepted)
        rendered = "\n".join(m["content"] for m in seen[-1]["messages"])
        self.assertIn(self.candidate, rendered)
        self.assertIn(self.checks, rendered)
        self.assertNotIn("checks do NOT report a problem", rendered)

    def test_only_unanimous_focused_accept_verdicts_adopt_the_briefing(self):
        seen = []
        self.assertTrue(loop.validate_compaction_briefing(
            lambda body, rlog: seen.append(body) or _reply(
                ("RETROSPECTIVE", "PRESERVES", "FAITHFUL")[len(seen) - 1]), self.role,
            "Importer.java was edited.", files="Importer.java", checks="BUILD EXIT: 1",
            transcript_blocks=["assistant: edited Importer.java"],
            task="Repair the importer and document its risks.", rlog=self.rlog))
        self.assertEqual(len(seen), 3)
        systems = [call["messages"][0]["content"] for call in seen]
        self.assertIn("PLAN or RETROSPECTIVE", systems[0])
        self.assertIn("NARROWS or PRESERVES", systems[1])
        self.assertIn("UNFAITHFUL or FAITHFUL", systems[2])

    def test_a_forward_plan_is_rejected_before_the_long_evidence_call(self):
        seen = []

        def chat(body, _rlog):
            seen.append(body)
            return _reply("PLAN")

        accepted = loop.validate_compaction_briefing(
            chat, self.role, "Next step: add the dependency and rerun the build.",
            files="Importer.java", checks=self.checks,
            transcript_blocks=["X" * 10000], task="Repair the importer.", rlog=self.rlog)
        self.assertFalse(accepted)
        self.assertEqual(len(seen), 1)
        rendered = "\n".join(m["content"] for m in seen[0]["messages"])
        self.assertIn("Next step", rendered)
        self.assertNotIn("X" * 100, rendered,
                         "the candidate-only retrospective lens must not bury the defect in history")

    def test_ambiguous_or_unavailable_judgment_fails_closed(self):
        self.assertFalse(loop.validate_compaction_briefing(
            lambda body, rlog: _reply("RETROSPECTIVE, but consider checking it"), self.role,
            self.candidate, files="Importer.java", checks=self.checks,
            transcript_blocks=[], rlog=self.rlog))
        self.assertFalse(loop.validate_compaction_briefing(
            None, self.role, self.candidate, files="Importer.java", checks=self.checks,
            transcript_blocks=[], rlog=self.rlog))

    def test_the_question_keeps_evidence_in_independently_reducible_turns(self):
        seen = []
        def chat(body, rlog):
            seen.append(body)
            return _reply("RETROSPECTIVE" if len(seen) == 1 else "UNFAITHFUL")

        loop.validate_compaction_briefing(
            chat, self.role, self.candidate, files="Importer.java", checks=self.checks,
            transcript_blocks=["A" * 1000, "B" * 1000], rlog=self.rlog)
        messages = seen[-1]["messages"]
        self.assertGreater(len(messages), 5)
        self.assertEqual(messages[-1]["content"].strip(),
                         "Classify the candidate now. Answer with exactly one of the two allowed words from the question above.")
        self.assertTrue(any(m["content"] == "A" * 1000 for m in messages[1:-1]))
        self.assertTrue(any(m["content"] == "B" * 1000 for m in messages[1:-1]))


if __name__ == "__main__":
    unittest.main()
