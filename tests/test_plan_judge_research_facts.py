"""The plan judges are told to delete a step that bakes in "a guessed API endpoint/path, a guessed
field name". They were handed the task and the plan and nothing else, so a real endpoint and an
invented one were the same string to them — the rule could not be applied.

Measured over the recorded drops: 57% named a snake_case field, 17% named a URL path. One deleted
`GET /holders/{address} … extract the total_handles field`, where both names came out of the
fetched spec.
"""
import json
import tempfile
import unittest

from cria import groundtruth, loop, planner
from cria.config import Role
from cria.plan import Plan, PlanItem

LEDGER = {"https://api.handle.me/openapi.json": (
    "HTTP 200 OK",
    "/handles/{handle} /holders/{address}",
    "/handles/{handle} → name(string), holder(string), resolved_addresses{ada(string)}",
    "")}


class _Rlog:
    def emit(self, *a, **k):
        pass


class RenderTests(unittest.TestCase):
    def test_the_block_carries_routes_AND_field_names(self):
        out = groundtruth.researched_facts(LEDGER)
        self.assertIn("/holders/{address}", out)
        self.assertIn("resolved_addresses", out)

    def test_an_empty_ledger_renders_NOTHING(self):
        # Cria knowing nothing is not evidence a name is invented. A judge shown an empty block
        # would read every field as unverified and delete correct steps.
        self.assertEqual(groundtruth.researched_facts({}), "")
        self.assertEqual(groundtruth.researched_facts(None), "")

    def test_a_status_only_entry_renders_nothing(self):
        self.assertEqual(groundtruth.researched_facts({"u": ("HTTP 404", "", "", "")}), "")

    def test_short_legacy_tuples_still_read(self):
        self.assertIn("/x", groundtruth.researched_facts({"u": ("HTTP 200", "/x")}))

    def test_absence_is_explicitly_NOT_called_evidence(self):
        # Without this the judge treats "not in the list" as "invented" and the fix inverts into
        # a deletion engine.
        out = groundtruth.researched_facts(LEDGER).lower()
        self.assertIn("absence is not evidence", out)


class WiringTests(unittest.TestCase):
    def test_the_facts_lead_the_judges_user_message(self):
        seen = {}

        def ask(system, user):
            seen["user"] = user
            return "NONE"

        planner.reasoned_noise_indices(ask, "the task", ["step one"],
                                       facts=groundtruth.researched_facts(LEDGER))
        self.assertTrue(seen["user"].startswith("WHAT WAS ACTUALLY READ"))
        self.assertIn("TASK:", seen["user"])
        self.assertIn("PLAN:", seen["user"])

    def test_no_ledger_means_the_message_is_exactly_what_it_always_was(self):
        seen = {}

        def ask(system, user):
            seen["user"] = user
            return "NONE"

        planner.reasoned_noise_indices(ask, "the task", ["step one"])
        self.assertEqual(seen["user"], "TASK:\nthe task\n\nPLAN:\n1. step one")

    def test_the_planners_own_noise_judge_sees_the_gathered_facts(self):
        """The planner's own noise judge is fed from the gather's research ledger
        (self._gather_facts). Drive the REAL method — a fixture beats a source-text grep: it
        would have caught a caller that kept the `facts=` spelling but stopped supplying real
        data just as surely as one that dropped the kwarg outright."""
        seen = {}

        class _Provider:
            def chat(self, body, rlog):
                seen["user"] = body["messages"][-1]["content"]
                return json.dumps({"choices": [{"message": {"content": "NONE"}}]}).encode()

        p = planner.Planner(_Provider(), role=Role(name="reasoner", backend="local"))
        p._gather_facts = LEDGER
        p._reasoned_noise_indices("the task", ["step one"], _Rlog())
        self.assertIn("resolved_addresses", seen["user"])

    def test_the_completion_critic_does_not_submit_its_accepted_action_to_a_second_judge(self):
        """The satisfaction path validates its authored action once.  Reopening the plan reuses that
        exact action instead of giving a second provider veto over it."""
        bodies = []

        def reasoner(body, rlog):
            bodies.append(body)
            return json.dumps({"choices": [{"message": {"content": json.dumps({
                "satisfied": False, "reason": "REPORT.md is missing",
                "proposed_fix": "raw provider action", "diagnosis_kind": "missing_file",
                "subject": "REPORT.md", "task_quote": "Add REPORT.md.",
                "evidence_source": "workspace_absence", "evidence_quote": ""})}}]}).encode()

        ctx = loop.LoopContext(planner=None, coder_chat=lambda b, r: b"{}", reasoner_chat=reasoner,
                               runs_dir="", workspace_root=None)
        ctx.reasoner_role = Role(name="reasoner", backend="local")
        plan = Plan(id="x", task="Add REPORT.md.", created="c",
                    items=[PlanItem("step 1", done=True, note="verified")])
        sess = loop.PlanSession(plan=plan)
        sess.fetched_pages = dict(LEDGER)
        with tempfile.TemporaryDirectory() as root:
            sess.workspace_root = root
            loop.Loop(ctx)._reopen_if_unsatisfied(sess, {"messages": []}, _Rlog())
        self.assertEqual(len(bodies), 1, "only the satisfaction judge should run")
        self.assertEqual(sess.plan.items[-1].text,
                         loop._COMPLETION_FIX_PREFIX + "Add REPORT.md.")

    def test_the_living_replans_noise_judge_sees_the_session_ledger(self):
        """The third caller, reached through two hops: Loop._replan_tail hands the session's
        ledger to loop.reassess_remaining as `facts=`, and reassess_remaining is what actually
        calls the shared judge with it. A source-text grep for each hop's spelling cannot tell
        a real handoff from two calls that happen to use the same keyword; driving the real
        chain end to end can."""
        bodies = []

        def reasoner(body, rlog):
            bodies.append(body)
            if len(bodies) == 1:
                return json.dumps({"choices": [{"message": {"content": json.dumps(
                    {"steps": ["step 3"]})}}]}).encode()
            return json.dumps({"choices": [{"message": {"content": "NONE"}}]}).encode()

        ctx = loop.LoopContext(planner=None, coder_chat=lambda b, r: b"{}", reasoner_chat=reasoner,
                               runs_dir="", workspace_root=None)
        ctx.reasoner_role = Role(name="reasoner", backend="local")
        plan = Plan(id="x", task="build it", created="c",
                    items=[PlanItem("step 1", done=True, note="verified"),
                          PlanItem("step 2"), PlanItem("step 3")])
        sess = loop.PlanSession(plan=plan)
        sess.fetched_pages = dict(LEDGER)
        loop.Loop(ctx)._replan_tail(sess, {"messages": []}, 1, _Rlog())
        self.assertGreaterEqual(len(bodies), 2, "re-derivation, then the noise judge")
        self.assertIn("resolved_addresses", bodies[1]["messages"][-1]["content"])

    def test_the_loop_reader_abstains_on_an_empty_session(self):
        self.assertEqual(loop.session_research_facts([], None), "")

    def test_ONE_reader_of_the_ledger_tuple(self):
        # loop._fetch_facts and groundtruth.fetch_facts were the same six lines twice; planner
        # cannot import loop, which is why the surviving copy lives in groundtruth.
        self.assertIs(loop._fetch_facts, groundtruth.fetch_facts)


if __name__ == "__main__":
    unittest.main()
