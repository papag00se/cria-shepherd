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
import os
import tempfile
import unittest

from cria import groundtruth, planner, prompts


class _CaptureProvider:
    """Every reasoner round is handed the SAME seed at index 1 of its messages (index 0 is the
    system prompt; the loop only ever APPENDS after the seed, never rewrites it) — so recording
    it on every call and reading any entry back gets the exact text the model reads. Answers
    every round with nothing usable, so the gather loop ends quickly without ever drafting a
    real plan (irrelevant to what this file checks)."""

    def __init__(self):
        self.captured = []

    def chat(self, body, rlog):
        import json
        self.captured.append(body["messages"][1]["content"])
        return json.dumps({"choices": [{"message": {"role": "assistant", "content": ""},
                                        "finish_reason": "stop"}]}).encode()


class _Rlog:
    def emit(self, kind, **kw):
        pass


def _seed(task, cwd=""):
    """Drive the real planner up to its first reasoner call and return the exact user-turn text
    it built — the seed the model actually reads, rather than the source line that claims to
    build it."""
    provider = _CaptureProvider()
    planner.Planner(provider)._gather_and_plan(task, cwd, _Rlog())
    assert provider.captured, "the stub provider was never called"
    return provider.captured[0]


class AskLastTests(unittest.TestCase):
    def test_the_seed_ends_with_crias_ask(self):
        """inventory, then the task, then cria's own closing ask — in that order, so the LAST
        instruction the model reads is cria's, not the user's task (the ordering bug zaya1 hit:
        a model obeys the last instruction it reads, and three runs planned nothing because the
        task — not cria's ask to plan it — came last)."""
        d = tempfile.mkdtemp()
        open(os.path.join(d, "existing_marker_file.py"), "w").close()
        seed = _seed("write a Python script that resolves handles, add a README", cwd=d)
        ask = prompts.load("plan_closing_ask")
        self.assertIn("existing_marker_file.py", seed)     # the inventory really is in there
        self.assertIn("write a Python script", seed)        # ...and the raw task...
        self.assertIn(ask, seed)                            # ...and the closing ask, verbatim
        self.assertLess(seed.index("existing_marker_file.py"), seed.index("write a Python script"))
        self.assertLess(seed.index("write a Python script"), seed.index(ask))

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
        """With no cwd (no workspace, no inventory), the empty inventory part must be DROPPED
        entirely, not joined in as a blank line ahead of the task."""
        seed = _seed("write a Python script that resolves handles", cwd="")
        self.assertFalse(seed.startswith("\n"), repr(seed[:20]))
        self.assertNotIn("\n\n\n", seed)


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
        """The planner's OWN seed must read the planner-flavored inventory ("nothing has been
        built yet"), never the critic's ("at judging time") — driven end to end rather than
        matched against the call's own spelling, which cannot tell a real flavor="planner" from
        one that silently regressed to the judge default while still naming the right function."""
        seed = _seed("write a Python script that resolves handles", cwd=tempfile.mkdtemp())
        self.assertIn("nothing has been built yet", seed)
        self.assertNotIn("at judging time", seed)
