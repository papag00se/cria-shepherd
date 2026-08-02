"""cria's ask goes LAST for the planner too — the same ordering bug, in a third place.

The planner's seed ENDS with the user's own request, which for a coding task is literally "write a
Python script ... add a README". The planner instruction lives in the system message, far above it.
A model obeys the last instruction it reads.

zaya1 says so in its own reasoning, run 20260801T221447 call 0002 — 27,089 characters, zero tool
calls:

    "We can place everything in a single response."
    "We'll call web_search with query ... Let's simulate in our mind."
    "We'll use web_fetch. But we might not have internet access. However, we can simulate."
    "We must be careful not to include any extraneous text like 'Step 1: ...'. The answer is just
     the deliverables."

It was actively AVOIDING a plan. Word counts in that reasoning: "script" 86, "readme" 35, "plan" 4.
Three attempts, three runs, zero coder calls in any of them.
"""
import inspect
import tempfile
import unittest

from cria import groundtruth, planner, prompts


class AskLastTests(unittest.TestCase):
    SRC = inspect.getsource(planner.Planner._gather_and_plan)

    def test_the_seed_ends_with_crias_ask(self):
        self.assertIn('prompts.load("plan_closing_ask")', self.SRC)
        # inventory, then the task, then the ask — in that order
        parts = self.SRC[self.SRC.index('part for part in ('):]
        self.assertLess(parts.index("inventory"), parts.index("seed"))
        self.assertLess(parts.index("seed"), parts.index("plan_closing_ask"))

    def test_the_ask_forbids_doing_the_work_WITHOUT_naming_the_work(self):
        # It must forbid producing the deliverables generically. Naming them — "the script, the
        # tests, the README" — is this task's shape leaking into cria, which the operator caught
        # on sight. See tests/test_prompts.py::NoDevTaskLeakTests.
        low = prompts.load("plan_closing_ask").lower()
        self.assertIn("must not carry it out", low)
        self.assertIn("do not produce any of the things it asks for", low)
        self.assertNotIn("cria", low)

    def test_the_ask_forbids_SIMULATING_a_tool_call(self):
        # "Let's simulate in our mind" is why three runs made zero calls.
        self.assertIn("a real call, not a description of one", prompts.load("plan_closing_ask"))

    def test_empty_parts_are_dropped_not_left_as_blank_lines(self):
        self.assertIn("if part", self.SRC)


class PlannerInventoryWordingTests(unittest.TestCase):
    """"at judging time" is the CRITIC's wording. The planner is not judging anything."""

    def test_the_planner_flavor_does_not_say_judging(self):
        d = tempfile.mkdtemp()
        out = groundtruth.workspace_inventory(d, flavor="planner")
        self.assertNotIn("judging", out)
        self.assertIn("nothing has been built yet", out)

    def test_the_judge_flavor_is_unchanged(self):
        self.assertIn("at judging time", groundtruth.workspace_inventory(tempfile.mkdtemp()))

    def test_a_populated_planner_listing_also_avoids_it(self):
        import os
        d = tempfile.mkdtemp()
        open(os.path.join(d, "a.py"), "w").close()
        out = groundtruth.workspace_inventory(d, flavor="planner")
        self.assertNotIn("judging", out)
        self.assertIn("a.py", out)

    def test_the_gather_asks_for_the_planner_flavor(self):
        self.assertIn('workspace_inventory(cwd, flavor="planner")',
                      inspect.getsource(planner.Planner._gather_and_plan))
