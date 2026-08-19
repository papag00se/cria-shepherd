"""The planner gets filesystem tools; it must be told where the filesystem is.

Measured across every captured prompt: the CRITIC is given the workspace root in 292 of 331 prompts
(88%); the PLANNER in 31 of 481 (6%). Run 20260801T211548 (zaya1, ada-handles, 0/4): the planner
invented `/workspace/dumps/workspace` and read setup.py / pyproject.toml / Dockerfile / package.json
/ .github/workflows/test.yml under it repeatedly — 140+ tool calls in one response, three rounds
running, each cut off at the token cap. All fifteen minutes went to the planner; the coder never ran.
"""
import os
import tempfile
import unittest
from datetime import datetime, timezone

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
    """Asserted on the prompt the planner actually SENDS, not on the line that builds it.

    Reading the source for `workspace_inventory(cwd, flavor="planner")` proves the call is written;
    it cannot prove the result reaches the model, which is the whole claim. The measured defect was
    exactly that gap — the planner had filesystem tools and no location, and invented one."""

    @staticmethod
    def _env(cwd):
        """A harness turn that advertises its workspace, exactly as Codex does."""
        return ([{"role": "user", "content": f"<environment_context><cwd>{cwd}</cwd></environment_context>"}]
                if cwd else []) + [{"role": "user", "content": "build the thing"}]

    def _first_prompt(self, cwd):
        import json as _json
        bodies = []
        plan = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "p1", "type": "function", "function": {"name": "submit_plan",
             "arguments": _json.dumps({"steps": ["do the thing"]})}}]}}]}

        class _P:
            def chat(_self, b, _rlog):
                bodies.append(b)
                return _json.dumps(plan).encode()

        planner.Planner(_P(), clock=lambda: _FIXED).plan_for(self._env(cwd), _Rlog())
        return " ".join(str(m.get("content") or "") for m in bodies[0]["messages"])

    def test_the_gather_seeds_the_inventory_when_cwd_is_known(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "resolve_handle.py"), "w") as f:
            f.write("x = 1\n")
        prompt = self._first_prompt(d)
        self.assertIn("resolve_handle.py", prompt)   # the real file, from the real directory
        self.assertIn(d, prompt)                     # ...and where it is

    def test_an_unknown_cwd_changes_nothing(self):
        """cria must never invent a root either — no cwd, no section, no invented path."""
        prompt = self._first_prompt("")
        self.assertNotIn("WORKSPACE FILES", prompt)

    def test_the_planner_resolves_its_tools_against_the_same_cwd_it_is_told(self):
        """The root it announces and the root its tools read must be one root — announcing one and
        reading another is the same defect wearing a fix."""
        import json as _json
        from unittest import mock
        d = tempfile.mkdtemp()
        seen = []
        round1 = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read_file",
             "arguments": _json.dumps({"path": "a.py"})}}]}}]}
        done_gathering = {"choices": [{"message": {"role": "assistant", "content": "ready"}}]}
        plan = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "p1", "type": "function", "function": {"name": "submit_plan",
             "arguments": _json.dumps({"steps": ["do the thing"]})}}]}}]}
        seq, n = [round1, done_gathering, plan, plan], {"i": 0}

        class _P:
            def chat(_self, _b, _rlog):
                r = seq[min(n["i"], len(seq) - 1)]; n["i"] += 1
                return _json.dumps(r).encode()

        class _R:
            learned, text = True, "t"

        with mock.patch("cria.planner.planner_tools.execute_tool",
                        side_effect=lambda name, args, cwd, *a, **k: (seen.append(cwd), _R())[1]):
            planner.Planner(_P(), clock=lambda: _FIXED).plan_for(self._env(d), _Rlog())
        self.assertEqual(seen, [d])


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


_FIXED = datetime(2026, 7, 7, 0, 45, 12, tzinfo=timezone.utc)


class RoundDedupTests(unittest.TestCase):
    """Measured across every captured planner round (n=328, 719 calls): 236 — 32.8% — are exact
    duplicates of another call in the SAME round. One zaya1 response held 138 calls, 32 distinct.

    DRIVEN THROUGH THE REAL GATHER LOOP. The first version of these tests re-implemented the dedup
    inside the test — "replay the dedup exactly as the loop does it" — and asserted on its own copy,
    which cannot fail when the real loop breaks. The source-text assertions beside it existed
    precisely because nothing was driving the real code. `planner_tools.execute_tool` is patched (it
    touches the filesystem and the network); everything else here is the shipped path.
    """

    LONG = "x" * 5000 + "\nEND-OF-RESULT-SENTINEL\n"

    class _Result:
        learned = True

        def __init__(self, text):
            self.text = text

    CALLS = [("c1", "read_file", {"path": "a.py"}),
             ("c2", "read_file", {"path": "a.py"}),
             ("c3", "read_file", {"path": "b.py"}),
             ("c4", "read_file", {"path": "a.py"})]

    def _drive(self, calls, text=None):
        """One gather round carrying ``calls``, then a plan. Returns (executed, bodies, rlog)."""
        import json as _json
        from unittest import mock
        executed, bodies, rlog = [], [], _Rlog()
        body = text if text is not None else self.LONG

        round1 = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": _json.dumps(args)}}
            for cid, name, args in calls]}}]}
        # round 2 carries no tool call, which ENDS the gather — so the body it arrives in is the
        # one holding the results of round 1, and nothing after it can disturb what is asserted.
        done_gathering = {"choices": [{"message": {"role": "assistant", "content": "ready"}}]}
        plan = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "p1", "type": "function", "function": {"name": "submit_plan",
             "arguments": _json.dumps({"steps": ["do the thing"]})}}]}}]}
        seq = [round1, done_gathering, plan, plan, plan]

        class _P:
            def chat(_self, b, _rlog):
                bodies.append(b)
                return _json.dumps(seq[min(len(bodies) - 1, len(seq) - 1)]).encode()

        def fake_execute(name, args, cwd, *a, **k):
            executed.append((name, args))
            return RoundDedupTests._Result(body)

        with mock.patch("cria.planner.planner_tools.execute_tool", side_effect=fake_execute):
            planner.Planner(_P(), clock=lambda: _FIXED).plan_for(
                [{"role": "user", "content": "build the thing"}], rlog)
        return executed, bodies, rlog

    def _fed_results(self, bodies):
        """The tool results the gather fed back — read off the request that FOLLOWED the calls."""
        return [m for m in bodies[1]["messages"] if m.get("role") == "tool"]

    def test_each_distinct_call_runs_exactly_once(self):
        executed, _b, _r = self._drive(self.CALLS)
        self.assertEqual([a["path"] for _n, a in executed], ["a.py", "b.py"])

    def test_every_tool_call_id_still_gets_its_own_result(self):
        """The protocol must stay well-formed: the dedup drops re-EXECUTION, never a reply."""
        _e, bodies, _r = self._drive(self.CALLS)
        self.assertEqual([m["tool_call_id"] for m in self._fed_results(bodies)],
                         ["c1", "c2", "c3", "c4"])

    def test_nothing_is_truncated(self):
        """Each id gets the FULL result text — cria never truncates what the model reads (#5)."""
        _e, bodies, _r = self._drive(self.CALLS)
        fed = self._fed_results(bodies)
        self.assertTrue(fed)
        for m in fed:
            with self.subTest(cid=m["tool_call_id"]):
                self.assertEqual(len(m["content"]), len(self.LONG))
                self.assertIn("END-OF-RESULT-SENTINEL", m["content"])

    def test_the_dedup_is_recorded(self):
        """A drop cria makes silently cannot be told apart from a drop that never happened."""
        _e, _b, rlog = self._drive(self.CALLS, text="short")
        self.assertEqual(sum(1 for k, _ in rlog.events if k == "plan.gather_dedup"), 2)
        self.assertEqual(sum(1 for k, _ in rlog.events if k == "plan.gather"), 2)


