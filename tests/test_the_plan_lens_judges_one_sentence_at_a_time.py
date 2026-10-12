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
        return _reply("COVERED" if "COVERED or MISSING" in system else "FAITHFUL")


def _validate(chat, briefing, task=TASK):
    return loop.validate_compaction_briefing(
        chat, Role(name="reasoner", backend="local"), briefing, files="Importer.java",
        checks="BUILD EXIT: 1", transcript_blocks=["assistant: edited"], task=task, rlog=_Rlog())


class SentenceSplitTests(unittest.TestCase):
    def test_headings_are_judged_not_dropped(self):
        got = loop.briefing_sentences(REAL_CANDIDATE)
        self.assertIn("Current State", got)
        self.assertIn("Fix Compilation Errors:", got)
        self.assertIn(PRESCRIBED, got)
        self.assertEqual(loop.briefing_sentences("# Fix Cart.java by adding a null check"),
                         ["Fix Cart.java by adding a null check"])

    def test_a_colon_line_is_judged_and_a_fence_is_one_unit(self):
        got = loop.briefing_sentences("Next step:\n```\nsed -i s/a/b/ Cart.java\nmake\n```")
        self.assertEqual(got, ["Next step:", "sed -i s/a/b/ Cart.java\nmake"])

    def test_a_fence_verbatim_in_the_transcript_is_quoted_output_not_the_writer(self):
        out = "Importer.java:92: cannot find symbol"
        self.assertEqual(loop.briefing_sentences(f"```\n{out}\n```", [f"tool: {out}\n$ mvn"]), [])
        self.assertEqual(loop.briefing_sentences(f"```\n{out}\n```", ["unrelated"]), [out])

    def test_a_bare_list_number_joins_its_item(self):
        self.assertEqual(loop.briefing_sentences("1.\nAdd the import.\n2.\nRerun."),
                         ["1. Add the import.", "2. Rerun."])

    def test_a_short_imperative_is_still_judged(self):
        self.assertEqual(loop.briefing_sentences("Run mvn test.\nBuild OK."), ["Run mvn test.", "Build OK."])

    def test_multiple_sentences_on_one_line_are_split_whole(self):
        self.assertEqual(loop.briefing_sentences("The build failed. Add the import and rerun."),
                         ["The build failed.", "Add the import and rerun."])


class PlanLensTests(unittest.TestCase):
    def test_a_heading_that_is_an_instruction_is_rejected(self):
        chat = _SentenceJudge(plans=["Fix Cart.java"])
        self.assertFalse(_validate(chat, "# Fix Cart.java by adding a null check"))

    def test_a_fenced_command_after_a_colon_is_rejected(self):
        chat = _SentenceJudge(plans=["sed -i"])
        self.assertFalse(_validate(chat, "Next step:\n```\nsed -i s/a/b/ Cart.java\n```"))

    def test_a_non_empty_briefing_with_nothing_to_judge_fails_closed(self):
        calls = []
        self.assertFalse(_validate(lambda b, r: calls.append(b) or _reply("STATE"), "---\n* \n```\n```"))
        self.assertEqual(calls, [])

    def test_beyond_the_judgment_cap_fails_closed(self):
        chat = _SentenceJudge(plans=[])
        text = "\n".join(f"Fact number {i} holds." for i in range(loop.MAX_PLAN_JUDGMENTS + 1))
        self.assertFalse(_validate(chat, text))
        self.assertEqual(chat.calls, [])
        self.assertTrue(_validate(chat, "\n".join(text.splitlines()[:loop.MAX_PLAN_JUDGMENTS])))

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


RUBY_TASK = """Make these five changes to the shipping module:

1. Fix the failing repository tests. Do not change assertions in tests that came with the repo.
2. Add an `express` service costing `14.99` base plus `2.50` per kilogram.
3. Add a README rate table listing every zone with its base rate and per-kilogram rate.
4. Add `Shipping.zone_for(code)` for two-letter country codes:
   - `GB` returns `domestic`
   - EU members returns `eu`
5. Make `Shipping.shipping_cost` accept either a zone name or country code.

Do not hardcode EU membership. Add a third-party Ruby gem that determines whether a country is in the EU."""

# Real captured candidates (20261009T225945 call 0086: omits the gem; 20261010T083620 call 0131: lists all).
OMITS_GEM = "Fix the failing tests. Add an express service. Add a README rate table. Implement Shipping.zone_for. Make shipping_cost accept a zone name or country code."
LISTS_ALL = OMITS_GEM + " Do not hardcode EU membership: add a third-party Ruby gem for EU lookup (unverified)."


class _CoverageJudge:
    """A requirement is COVERED iff its distinguishing word appears in the candidate."""

    def __call__(self, body, _rlog):
        system = body["messages"][0]["content"]
        if "PLAN or STATE" in system:
            return _reply("STATE")
        if "COVERED or MISSING" in system:
            blocks = [m["content"] for m in body["messages"]]
            unit = next(b for b in blocks if b.startswith("REQUIREMENT FROM"))
            cand = next(b for b in blocks if b.startswith("CANDIDATE"))
            key = ("gem" if "gem" in unit else "README" if "README" in unit else
                   "express" if "express" in unit else "zone_for" if "zone_for" in unit else
                   "shipping_cost" if "shipping_cost" in unit else "failing")
            return _reply("COVERED" if key in cand else "MISSING")
        return _reply("FAITHFUL")


class CoverageLensTests(unittest.TestCase):
    def test_units_are_top_level_requirements_with_their_sub_bullets(self):
        units = loop.task_units(RUBY_TASK)
        self.assertEqual(len(units), 6)    # the lead-in line is not a requirement; sub-bullets stay inside item 4
        self.assertIn("EU members returns `eu`", units[3])
        self.assertTrue(units[5].startswith("Do not hardcode EU membership."))

    def test_a_briefing_that_omits_a_deliverable_is_rejected(self):
        self.assertFalse(_validate(_CoverageJudge(), OMITS_GEM, task=RUBY_TASK))

    def test_a_briefing_that_lists_every_deliverable_is_accepted_even_if_none_is_done(self):
        """Real false-reject class: 13 of 20 read NARROWS rejections listed every deliverable."""
        self.assertTrue(_validate(_CoverageJudge(), LISTS_ALL, task=RUBY_TASK))

    def test_each_requirement_is_asked_separately_with_the_candidate(self):
        seen = []
        judge = _CoverageJudge()
        _validate(lambda b, r: seen.append(b) or judge(b, r), LISTS_ALL, task=RUBY_TASK)
        asked = [next(m["content"] for m in b["messages"] if m["content"].startswith("REQUIREMENT"))
                 for b in seen if "COVERED or MISSING" in b["messages"][0]["content"]]
        self.assertEqual(len(asked), 6)

    def test_an_unreadable_coverage_answer_fails_closed(self):
        def chat(body, rlog):
            sysm = body["messages"][0]["content"]
            return _reply("STATE" if "PLAN or STATE" in sysm else "maybe")
        self.assertFalse(_validate(chat, LISTS_ALL, task=RUBY_TASK))

    def test_more_requirements_than_the_cap_fails_closed(self):
        task = "\n".join(f"Requirement number {i} applies." for i in range(loop.MAX_TASK_UNITS + 1))
        calls = []

        def chat(body, rlog):
            calls.append(body["messages"][0]["content"])
            return _reply("STATE" if "PLAN or STATE" in calls[-1] else "COVERED")

        self.assertFalse(_validate(chat, "Done.", task=task))
        self.assertFalse(any("COVERED or MISSING" in c for c in calls))   # refused, not clipped


if __name__ == "__main__":
    unittest.main()
