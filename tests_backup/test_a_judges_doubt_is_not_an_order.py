"""cria put a judge's prose in the coder's mouth and called it an instruction.

When the completion check cannot confirm the task is done, cria renders the judge's `reason` under
"the task is NOT fully done yet:" and closed with "finish exactly what is called out above". A
verdict written to justify a `false` became a mandate.

    qwen35/ruby, 3/3 on its own suite, call 0367 -> 0368.
    cria:   "The zone_for method hardcodes \\"EU\\" to return \\"eu\\" instead of using the countries
             gem for all two-letter codes as required."
    coder:  "Let me fix the code to not hardcode \\"EU\\" but instead let the gem handle it."
    result: a 22/22 suite went to 2 failures — one lost check each.

17 occurrences, four languages, three models. Working code broken in five runs; 15 model-written
tests reverted.

WHAT IS NOT CHANGED, because it is the part that works. The verdict still BLOCKS: fail closed on
completion (#13), the critic still re-runs on EVERY green 'done' with no once-bound (e0da427 removed
that bound after a false 'done' shipped a dropped requirement), and the coder still may not declare
done or stop (#14). Many not-satisfied verdicts are correct, so the fix is "do not relay prose as an
order", never "distrust the verdict".

WHAT CHANGED AGAIN. Free-form diagnoses no longer reach this prompt. A diagnosis arrives only with
an exact task quote and exact current-evidence provenance; unsupported prose is replaced by the
plain not-confirmed control. The prompt therefore tells the coder to act only on that exact pair
and never add a requirement or implementation.
"""

import json
import unittest
from unittest import mock

from cria import prompts
from cria.config import Role
from cria.loop import Loop, LoopContext, PlanSession
from cria.plan import Plan, PlanItem


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def _loop(reasoner_chat):
    ctx = LoopContext(planner=None, coder_chat=lambda b, r: b"{}", reasoner_chat=reasoner_chat,
                      reasoner_role=Role(name="reasoner", backend="local"), runs_dir="")
    return Loop(ctx)


def _session(n_items=1):
    plan = Plan(id="x", task="build the thing", created="c",
                items=[PlanItem(f"step {i + 1}") for i in range(n_items)])
    return PlanSession(plan=plan)


def _body():
    return {"messages": [{"role": "user", "content": "build the thing"}], "tools": []}


class TheReportIsAttributedNotCommandedTests(unittest.TestCase):
    def setUp(self):
        self.body = prompts.load("done_incomplete")

    def test_the_reason_is_named_as_a_report(self):
        self.assertIn("a completion check could not confirm", self.body)
        self.assertIn("It reported:", self.body)

    def test_it_requires_exact_task_and_evidence_provenance(self):
        self.assertIn("exact task requirement and current evidence", self.body)

    def test_the_mandate_sentence_is_gone(self):
        """The clause that converted a verdict into an order."""
        self.assertNotIn("finish exactly what is called out above", self.body)

    def test_it_forbids_new_requirements_and_implementations(self):
        self.assertIn("Do not add a requirement", self.body)
        self.assertIn("choose an implementation", self.body)

    def test_an_unsupported_report_is_only_not_confirmed(self):
        self.assertIn('treat this only as "not confirmed"', self.body)


class TheBlockIsStillClosedTests(unittest.TestCase):
    """Letting the coder disagree with the REASON must not let it disagree with the VERDICT."""

    def setUp(self):
        self.body = prompts.load("done_incomplete")

    def test_it_still_may_not_declare_done_or_stop(self):
        self.assertIn("Do NOT declare done", self.body)
        self.assertIn("or stop", self.body)

    def test_it_still_may_not_rationalise_a_missing_piece(self):
        self.assertIn("rationalize a missing piece as impossible", self.body)

    def test_it_still_re_reads_the_task_and_checks_every_deliverable(self):
        self.assertIn("re-read the ORIGINAL task", self.body)
        self.assertIn("every deliverable it named is present and genuinely works", self.body)

    def test_the_slots_still_exist(self):
        """{{EXEC_FINDING}} is NOT among them, and this line is why it survived a retirement. The seat
        that filled it was removed on 2026-08-18 and this test kept asserting the empty slot, so what
        the coder read was the literal braces — see
        tests/test_no_prompt_token_is_orphaned.py."""
        for slot in ("{{CHECK_STATE}}", "{{REASON}}"):
            with self.subTest(slot=slot):
                self.assertIn(slot, self.body)
        self.assertNotIn("{{EXEC_FINDING}}", self.body)

    def test_the_done_critiqued_bound_never_came_back(self):
        """e0da427 removed a `done_critiqued` once-bound field after a false 'done' shipped a
        dropped requirement. Checked against the real session fields, not a name search — a
        renamed bound with the same intent would slip past a string search either way."""
        import dataclasses
        names = {f.name for f in dataclasses.fields(PlanSession)}
        self.assertNotIn("done_critiqued", names)

    def test_the_critic_runs_on_every_green_done_no_once_bound(self):
        """cria never lets a still-incomplete task exit early on the strength of an EARLIER green
        'done' — the critic judges every single one. Driven twice on the same session: a once-bound
        would answer the second call without ever calling the reasoner again."""
        calls = []

        def chat(body, rlog):
            calls.append(1)
            return json.dumps({"choices": [{"message": {"content": json.dumps(
                {"satisfied": False, "reason": "still missing X"})}}]}).encode()

        run = _loop(chat)
        sess = _session()
        r1 = run._done_critic_reason(sess, _body(), _Rlog())
        r2 = run._done_critic_reason(sess, _body(), _Rlog())
        self.assertEqual(len(calls), 2)
        self.assertEqual(r1, prompts.load("done_no_named_gap"))
        self.assertEqual(r2, prompts.load("done_no_named_gap"))


class NoGapNamedMeansNoGapClaimedTests(unittest.TestCase):
    def test_the_default_does_not_invent_a_finding(self):
        text = prompts.load("done_no_named_gap")
        self.assertNotIn("is missing, stubbed", text)
        self.assertIn("did not name which deliverable", text)

    def test_it_still_sends_the_coder_to_verify(self):
        text = prompts.load("done_no_named_gap")
        self.assertIn("one by one", text)
        self.assertIn("a check that actually runs", text)

    def test_both_call_sites_use_the_one_owner(self):
        """The plan-off critic (_done_critic_reason) and its plan-ON parity sibling
        (_reopen_if_unsatisfied) must fall back to the SAME text when the judge names no gap —
        driven end to end, not counted in the source, so a copy that drifted (or a third call site
        that never adopted the owner) shows up as a text mismatch rather than a matching count."""
        from cria import loop as loopmod

        def blank_verdict(*a, **kw):
            return False, "", ""

        with mock.patch.object(loopmod, "judge_satisfaction", blank_verdict):
            plan_off = _loop(None)._done_critic_reason(_session(1), _body(), _Rlog())
            plan_on = _loop(None)._reopen_if_unsatisfied(_session(2), _body(), _Rlog())
        self.assertEqual(plan_off, plan_on)
        self.assertEqual(plan_off, prompts.load("done_no_named_gap"))

    def test_the_prompt_file_carries_no_comment_the_model_would_read(self):
        """prompts.load returns the file whole — a `#` note would ship to the model."""
        self.assertFalse(prompts.load("done_no_named_gap").lstrip().startswith("#"))


class TheRenderedResultReadsRightTests(unittest.TestCase):
    def test_a_named_gap_renders_as_a_report(self):
        out = prompts.render("done_incomplete",
                             reason="The CLI never prints the holder's address.",
                             check_state=prompts.load_map("done_check_state")["passed"],
                             exec_finding="")
        self.assertIn("It reported:\nThe CLI never prints the holder's address.", out)
        self.assertNotIn("{{", out)

    def test_an_unnamed_gap_renders_without_a_fabricated_one(self):
        out = prompts.render("done_incomplete",
                             reason=prompts.load("done_no_named_gap"),
                             check_state=prompts.load_map("done_check_state")["never_ran"],
                             exec_finding="")
        self.assertIn("did not name which deliverable", out)
        self.assertNotIn("{{", out)


if __name__ == "__main__":
    unittest.main()
