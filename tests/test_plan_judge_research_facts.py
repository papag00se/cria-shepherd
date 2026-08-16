"""The plan judges are told to delete a step that bakes in "a guessed API endpoint/path, a guessed
field name". They were handed the task and the plan and nothing else, so a real endpoint and an
invented one were the same string to them — the rule could not be applied.

Measured over the recorded drops: 57% named a snake_case field, 17% named a URL path. One deleted
`GET /holders/{address} … extract the total_handles field`, where both names came out of the
fetched spec.
"""
import inspect
import unittest

from cria import groundtruth, loop, planner

LEDGER = {"https://api.handle.me/openapi.json": (
    "HTTP 200 OK",
    "/handles/{handle} /holders/{address}",
    "/handles/{handle} → name(string), holder(string), resolved_addresses{ada(string)}",
    "")}


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

    def test_EVERY_call_site_supplies_them(self):
        # 'Before shipping any fix, grep for its sibling.' There are three callers of this judge.
        self.assertIn("facts=groundtruth.researched_facts",
                      inspect.getsource(planner.Planner._reasoned_noise_indices))
        self.assertIn("facts=facts", inspect.getsource(loop.reassess_remaining))
        self.assertIn("facts=session_research_facts",
                      inspect.getsource(loop.Loop._reopen_if_unsatisfied))

    def test_the_living_replan_passes_the_sessions_ledger_through(self):
        """No hasattr fallback. It used to widen to the WHOLE Loop class when the method could not be
        found, which is a rename hiding behind a default — the assertion would still pass on some
        OTHER call site's line and say nothing about this one (#4: a fallback that hides the failure
        it was written to catch)."""
        src = inspect.getsource(loop.Loop._replan_tail)
        self.assertIn("facts=session_research_facts", src)

    def test_the_replan_reaches_the_judge_through_reassess(self):
        """The link the source scan above cannot see: _replan_tail hands its facts to
        reassess_remaining, which is what actually calls the judge."""
        self.assertIn("reassess_remaining(", inspect.getsource(loop.Loop._replan_tail))
        self.assertIn("reasoned_noise_indices(", inspect.getsource(loop.reassess_remaining))

    def test_the_loop_reader_abstains_on_an_empty_session(self):
        self.assertEqual(loop.session_research_facts([], None), "")

    def test_ONE_reader_of_the_ledger_tuple(self):
        # loop._fetch_facts and groundtruth.fetch_facts were the same six lines twice; planner
        # cannot import loop, which is why the surviving copy lives in groundtruth.
        self.assertIs(loop._fetch_facts, groundtruth.fetch_facts)


if __name__ == "__main__":
    unittest.main()
