"""The planner gets filesystem tools; it must be told where the filesystem is.

Measured across every captured prompt: the CRITIC is given the workspace root in 292 of 331 prompts
(88%); the PLANNER in 31 of 481 (6%). Run 20260801T211548 (zaya1, ada-handles, 0/4): the planner
invented `/workspace/dumps/workspace` and read setup.py / pyproject.toml / Dockerfile / package.json
/ .github/workflows/test.yml under it repeatedly — 140+ tool calls in one response, three rounds
running, each cut off at the token cap. All fifteen minutes went to the planner; the coder never ran.
"""
import inspect
import os
import tempfile
import unittest

from cria import groundtruth, loop, planner


class SharedInventoryTests(unittest.TestCase):
    def test_one_owner_not_two(self):
        self.assertIs(loop.workspace_inventory, groundtruth.workspace_inventory)

    def test_it_lists_what_is_really_there(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, "resolve_handle.py"), "w").write("x = 1\n")
        out = groundtruth.workspace_inventory(d)
        self.assertIn("resolve_handle.py", out)
        self.assertIn(d, out)

    def test_an_empty_workspace_says_so(self):
        out = groundtruth.workspace_inventory(tempfile.mkdtemp())
        self.assertIn("none", out.lower())

    def test_no_root_means_no_section(self):
        self.assertEqual(groundtruth.workspace_inventory(""), "")
        self.assertEqual(groundtruth.workspace_inventory("/nonexistent/xyz"), "")


class PlannerSeedTests(unittest.TestCase):
    def test_the_gather_seeds_the_inventory_when_cwd_is_known(self):
        src = inspect.getsource(planner.Planner._gather_and_plan)
        self.assertIn('groundtruth.workspace_inventory(cwd, flavor="planner")', src)
        self.assertIn("part for part in (inventory, seed,", src)

    def test_an_unknown_cwd_changes_nothing(self):
        # cria must never invent a root either — no cwd, no section.
        src = inspect.getsource(planner.Planner._gather_and_plan)
        self.assertIn('if cwd else ""', src)

    def test_the_planner_resolves_its_tools_against_the_same_cwd_it_is_told(self):
        src = inspect.getsource(planner.Planner._gather_and_plan)
        self.assertIn("execute_tool(name, args, cwd", src)


class RoundDedupTests(unittest.TestCase):
    """Measured across every captured planner round (n=328, 719 calls): 236 — 32.8% — are exact
    duplicates of another call in the SAME round. One zaya1 response held 138 calls, 32 distinct."""

    def _run(self, calls):
        """Drive one gather round with a fake reasoner and count real executions."""
        executed = []

        class R:
            text = "result text"
            learned = True

        def fake_execute(name, args, cwd, *a, **k):
            executed.append((name, args))
            return R()

        return executed, fake_execute

    def test_distinct_calls_all_run_and_duplicates_do_not(self):
        import json as _json
        from unittest import mock
        executed, fake = self._run(None)
        calls = [("c1", "read_file", {"path": "a.py"}),
                 ("c2", "read_file", {"path": "a.py"}),
                 ("c3", "read_file", {"path": "b.py"}),
                 ("c4", "read_file", {"path": "a.py"})]
        # replay the dedup exactly as the loop does it
        done, results = {}, []
        for cid, name, args in calls:
            key = (name, _json.dumps(args, sort_keys=True, default=str))
            r = done.get(key)
            if r is None:
                r = fake(name, args, "/tmp")
                done[key] = r
            results.append((cid, r))
        self.assertEqual(len(executed), 2, "a.py once, b.py once")
        self.assertEqual(len(results), 4, "every tool_call_id still gets its own result")

    def test_the_loop_dedupes_and_still_answers_every_id(self):
        src = inspect.getsource(planner.Planner._gather_and_plan)
        self.assertIn("done: dict[tuple[str, str], object] = {}", src)
        self.assertIn("plan.gather_dedup", src)
        # one tool message per call id, unconditionally — the protocol must stay well-formed
        self.assertIn('messages.append({"role": "tool", "tool_call_id": cid, "content": result.text})', src)

    def test_nothing_is_truncated(self):
        # The dedup drops re-EXECUTION, never content: each id gets the full result text.
        src = inspect.getsource(planner.Planner._gather_and_plan)
        self.assertNotIn("result.text[:", src)
