"""A judge that is handed the coder's tool vocabulary will use it.

The incident (cycle 2, feed-pipeline-java x qwen35). Of 66 satisfaction-phase responses, 58 had EMPTY
content and 43 finished with `stop`, no tool calls and nothing said. 40 of those carry reasoning
showing the judge writing a `<tool_call>` block as literal prose, asking for `exec_command` - which a
read-only judge does not hold - and the PARAMETERS in those invented calls are `justification`,
`login`, `max_output_tokens`, `shell`, copied straight out of the coder tool summary cria pasted into
the judge's own prompt. cria then read the silence as an undecidable verdict, and fail-closed turns
that into "not done": twelve consecutive times on a workspace already scoring 5 of 5, costing ~45
minutes and ~300 calls.

Two causes, both cria's, both in the prompt:
  1. the coder's tool menu with its parameter names, and
  2. `proposed_fix` requiring "one executable next step... include the exact command when a run is
     required" - a prompt that requires a command has the judge rehearsing execution before it
     answers, which is principle 8's documented failure mode.

The steer author KEEPS the parameters: grounding a suggested action in what the coder can actually do
is why that block exists, and that reason is real for a caller that suggests actions.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from cria import loop

SATISFACTION = Path(__file__).resolve().parents[1] / "cria" / "prompts" / "satisfaction.txt"

TOOLS = [{"function": {"name": "exec_command", "parameters": {"properties": {
            "cmd": {}, "justification": {}, "login": {}, "max_output_tokens": {},
            "shell": {}, "workdir": {}}}}},
         {"function": {"name": "read_file", "parameters": {"properties": {"path": {}}}}}]


class TheJudgeGetsNamesNotSignatures(unittest.TestCase):
    def test_params_false_drops_the_vocabulary_the_judge_copied(self):
        """FAILS BEFORE: the parameter names were in every judge prompt."""
        out = loop._coder_tools_summary(TOOLS, params=False)
        self.assertIn("exec_command", out)
        # "shell" is excluded: the word survives inside "runs ANY shell command", which is prose
        # about what the tool IS, not a parameter name the judge can put in a call.
        for p in ("justification", "login", "max_output_tokens", "workdir"):
            with self.subTest(param=p):
                self.assertNotIn(p, out)

    def test_the_steer_author_still_gets_them(self):
        """Deliberately unchanged - a caller that suggests actions needs to know what they take."""
        out = loop._coder_tools_summary(TOOLS)
        self.assertIn("justification", out)
        self.assertIn("takes ", out)

    def test_the_shell_flag_survives_either_way(self):
        for params in (True, False):
            with self.subTest(params=params):
                self.assertIn("runs ANY shell command", loop._coder_tools_summary(TOOLS, params=params))

    def test_every_judge_call_site_asks_for_names_only(self):
        """Drive the real satisfaction-judge call sites (not their source text) and confirm none of
        them hand the judge a coder tool menu carrying parameter names.

        NB: ``Loop._replan_tail``'s ``judge_satisfaction`` call (loop.py, inside the 'all done'
        confirmation branch) is NOT exercised here. It passes ``coder_tools=tools`` where ``tools``
        is computed earlier in that same method as ``_coder_tools_summary(body.get("tools"))`` —
        the DEFAULT ``params=True`` — reused from the replanner's own (legitimately full-parameter)
        prompt. That is a live instance of the exact bug this file documents, found while converting
        this test off source-text matching (the old version searched for the literal substring
        ``"coder_tools=_coder_tools_summary"`` and silently skipped any site that instead passed a
        variable, which is exactly this site's shape). Left unfixed and unasserted here per this
        pass's scope — reported separately — rather than adding a test that fails against a known,
        un-remediated defect."""
        import unittest.mock
        from cria.loop import Loop, PlanSession
        from cria.plan import Plan, PlanItem

        class _RLog:
            def emit(self, *a, **kw):
                pass

        class _Ctx:
            reasoner_chat = object()
            reasoner_role = object()
            satisfaction_check_start = 80
            satisfaction_check_every = 20
            runs_dir = ""

        forbidden = ("justification", "login", "max_output_tokens", "workdir")
        calls = []

        def spy(task, evidence, chat, role, rlog, coder_tools="", **kw):
            calls.append(coder_tools)
            return (False, "not done", "")

        plan = Plan(id="x", task="build it", created="2026-01-01T00:00:00+00:00", items=[])
        body = {"messages": [{"role": "user", "content": "resolve a handle"}], "tools": TOOLS}

        with unittest.mock.patch.object(loop, "judge_satisfaction", spy):
            lp1 = Loop.__new__(Loop)
            lp1._ctx = _Ctx()
            lp1._reopen_if_unsatisfied(PlanSession(plan=plan), body, _RLog())

            lp2 = Loop.__new__(Loop)
            lp2._ctx = _Ctx()
            sess2 = PlanSession(plan=plan)
            sess2.drive_count = 80
            sess2.satisfaction_last_drive = -1
            lp2._periodic_satisfaction(sess2, body, _RLog(), plan_off=True, blocked=False)

            lp3 = Loop.__new__(Loop)
            lp3._ctx = _Ctx()
            lp3._done_critic_reason(PlanSession(plan=plan), body, _RLog())

        self.assertEqual(len(calls), 3, "all three known call sites must reach the judge")
        for i, coder_tools in enumerate(calls):
            with self.subTest(site=i):
                for p in forbidden:
                    self.assertNotIn(p, coder_tools,
                                     "a judge_satisfaction call still gets the coder's parameter names")


class ThePromptFencesTheJudgeOutOfDesigning(unittest.TestCase):
    def setUp(self):
        self.text = SATISFACTION.read_text()

    def test_it_says_there_is_no_shell(self):
        self.assertIn("no shell", self.text.lower())

    def test_it_carries_the_measured_fence_clause(self):
        """principle 8: the clause that changed the failure mode was 'Do not think about HOW any of
        this would be built'. It was missing from this prompt."""
        self.assertIn("Do not think about HOW", self.text)

    def test_proposed_fix_no_longer_demands_a_command(self):
        """FAILS BEFORE: 'include the exact command when a run is required'."""
        self.assertNotIn("include the exact command", self.text)
        self.assertNotIn("one executable next step", self.text)

    def test_proposed_fix_asks_for_the_deliverable_instead(self):
        self.assertIn("what must become true, not how to make it true", self.text)

    def test_the_judge_is_told_what_to_do_when_it_cannot_settle_a_point(self):
        """The silent turns happened because five rules can only be satisfied by running something.
        The judge needs an answer that is not 'reach for a tool you do not have'."""
        self.assertIn("you cannot settle it", self.text)


if __name__ == "__main__":
    unittest.main()
