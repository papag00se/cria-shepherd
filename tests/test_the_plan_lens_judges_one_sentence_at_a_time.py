"""The plan lens asks about ONE SENTENCE at a time, with the task beside it (O4).

Measured on captured harness-compaction validations (2026-10-08..12): the whole-candidate
"PLAN or RETROSPECTIVE" verdict, with "if uncertain, answer PLAN", called PLAN on 187 of 569
briefings, including every one that merely restated the task's requirements in the imperative
("Implement ...", "Add `REVIEW.md` ..."). On a labelled replay (10 hand-read real briefings + 24
injected plans, live model) it kept 24/24 plans and false-rejected 7/10 restatements; per sentence,
with a second "is this already in the original task?" question, 23/24 plans and 3/10. The texts
below are real captured sentences (session 20261011T062857 call 0092 and 20261009T225945 call 0133).
"""
import json
import unittest

from cria import loop
from cria.config import Role

TASK = ("Make these five changes to the shipping module:\n"
        "1. Add an express service costing 14.99 base plus 2.50 per kilogram.\n"
        "2. Add a README rate table listing every zone with its base rate and per-kilogram rate.\n"
        "3. Add Shipping.zone_for(code) for two-letter country codes.")

RESTATED = "Add a README rate table listing every zone with its base rate and per-kilogram rate."
PRESCRIBED = "Import the `Arrays` class to resolve the missing symbol error in `Importer.java`."
STATE = "The test at test/test_rates.rb:23 fails: expected 12.0, actual 0.0."

REAL_CANDIDATE = """### Briefing

#### Current State
- **Tests:**
  - The tests have not been run successfully due to the above compilation errors.

#### Outstanding Requirements
- **Fix Compilation Errors:**
  - Import the `Arrays` class to resolve the missing symbol error in `Importer.java`.
```
Importer.java:92: cannot find symbol
```
"""


class _Rlog:
    phase = ""

    def emit(self, *a, **k):
        pass


def _reply(text):
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": text},
                                     "finish_reason": "stop"}]}).encode()


class _SentenceJudge:
    """Answers by the SENTENCE it was shown — the way a closed per-sentence question is answered."""

    def __init__(self, plans, restated=()):
        self.plans, self.restated, self.calls = plans, restated, []

    def __call__(self, body, _rlog):
        system = body["messages"][0]["content"]
        text = next((m["content"] for m in body["messages"] if m["content"].startswith("SENTENCE:")), "")
        self.calls.append(system.split(".")[0])
        if "PLAN or STATE" in system:
            return _reply("PLAN" if any(p in text for p in self.plans) else "STATE")
        if "TASK or NEW" in system:
            return _reply("TASK" if any(r in text for r in self.restated) else "NEW")
        return _reply("PRESERVES" if "NARROWS or PRESERVES" in system else "FAITHFUL")


def _validate(chat, briefing, task=TASK):
    return loop.validate_compaction_briefing(
        chat, Role(name="reasoner", backend="local"), briefing, files="Importer.java",
        checks="BUILD EXIT: 1", transcript_blocks=["assistant: edited"], task=task, rlog=_Rlog())


class SentenceSplitTests(unittest.TestCase):
    def test_headings_labels_and_fenced_output_are_not_sentences(self):
        got = loop.briefing_sentences(REAL_CANDIDATE)
        self.assertIn("The tests have not been run successfully due to the above compilation errors.", got)
        self.assertIn(PRESCRIBED, got)
        self.assertFalse(any("cannot find symbol" in s for s in got))   # fenced tool output
        self.assertFalse(any(s.startswith("#") for s in got))

    def test_a_short_imperative_is_still_judged(self):
        self.assertEqual(loop.briefing_sentences("Run mvn test.\nBuild OK."), ["Run mvn test.", "Build OK."])

    def test_multiple_sentences_on_one_line_are_split_whole(self):
        self.assertEqual(loop.briefing_sentences("The build failed. Add the import and rerun."),
                         ["The build failed.", "Add the import and rerun."])


class PlanLensTests(unittest.TestCase):
    def test_a_restated_task_requirement_is_not_a_plan(self):
        """Real false-reject: a 'Remaining Requirements' list that only restates the task."""
        chat = _SentenceJudge(plans=[RESTATED], restated=[RESTATED])
        self.assertTrue(_validate(chat, f"{STATE}\n- {RESTATED}"))

    def test_a_prescription_the_task_does_not_state_is_a_plan(self):
        """Real true-reject: 'Import the Arrays class' is the writer's repair, not the task's."""
        chat = _SentenceJudge(plans=[PRESCRIBED], restated=[RESTATED])
        self.assertFalse(_validate(chat, f"{STATE}\n- {PRESCRIBED}"))

    def test_the_rejection_names_the_sentence_that_caused_it(self):
        rlog = type("R", (), {"phase": "", "events": []})()
        rlog.emit = lambda kind, **kw: rlog.events.append((kind, kw))
        chat = _SentenceJudge(plans=[PRESCRIBED])
        loop.validate_compaction_briefing(
            chat, Role(name="reasoner", backend="local"), f"{STATE}\n{PRESCRIBED}", files="",
            checks="", transcript_blocks=[], task=TASK, rlog=rlog)
        answers = rlog.events[-1][1]["answers"]
        self.assertIn("Arrays", answers["retrospective-plan"])

    def test_no_task_means_a_plan_sentence_cannot_be_exempted(self):
        chat = _SentenceJudge(plans=[RESTATED], restated=[RESTATED])
        self.assertFalse(_validate(chat, f"- {RESTATED}", task=""))

    def test_an_unreadable_sentence_answer_fails_closed(self):
        self.assertFalse(_validate(lambda body, rlog: _reply("probably fine"), STATE))
        self.assertFalse(_validate(None, STATE))

    def test_a_repeated_sentence_is_judged_once(self):
        chat = _SentenceJudge(plans=[])
        _validate(chat, "\n".join([STATE] * 30))
        self.assertEqual(sum("checking ONE sentence" in c for c in chat.calls), 1)


if __name__ == "__main__":
    unittest.main()
