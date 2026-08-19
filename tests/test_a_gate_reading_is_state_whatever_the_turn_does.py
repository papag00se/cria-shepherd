"""A gate cria READ and then threw away, because the turn returned through a different door.

`guard_probe_steer` handles the turn after a repetition-redirect or wheel-spin probe. It reads the
SAME probe result the completion gate reads — same `probe_call_id`, same `gate_plan`, same
`read_gate` call — and it recorded none of it:

    outcome = read_gate(gs.gate_plan, probe, rlog)     # ← read
    if gs.redirect_probe:
        ...
        return f"[REDIRECT]\\n{redirect}"              # ← and gone

`_verify_after_probe` then returns on that steer, ABOVE its own state mirror, so a gate that went
green → red on a guard-probe turn left `last_gate_red` False and `gate_fresh` True. Everything
downstream that asks "was the last check red?" — the completion backstop, the satisfaction judge's
evidence, the anti-laundering rollup override, the steer author's findings slot — was answered with
the PREVIOUS gate. Failing open toward "done" is the one direction #13 forbids.

THE SHAPE OF THE BUG, not just the instance: three readers of one fact, two writing the state inline
in their own words with their own idea of which fields mattered, and the third writing none. So this
is fixed by extraction rather than by adding a fourth copy — `record_gate_state` is now the only
place a reading becomes state, and `gate_error_text` the only place "is it red" is decided.
(A FOURTH reader turned up while wiring it: `guard_periodic_result`, whose omission was
`last_gate_ran` — a check-in that ran was indistinguishable from one that never happened.)

Two things that were plan-off-only now hold on both paths, and both are the fail-CLOSED direction:
the stall streak (`track_gate_progress`, whose docstring already said it must be the one funnel), and
the second red arm — a check that RAN and exited non-zero with nothing parseable. `_verify_after_probe`
kept `completion_block_nudge` for the STEP verdict; only the recorded state uses the fuller reading.
"""

import json
import os
import tempfile
import unittest

from cria import loop, proberun
from cria.loop import GuardState, Loop, LoopContext, gate_error_text, record_gate_state
from cria.plan import Plan, PlanItem
from cria.probegate import GateOutcome, SECTION_PREFIX, SECTION_SUFFIX


class _Report:
    def __init__(self, results=(), selected=()):
        self.results = list(results)
        self.selected = list(selected)


def outcome(ran=True, **kw):
    return GateOutcome(ran=ran, report=_Report(), **kw)


class TheReadingIsRecordedTests(unittest.TestCase):
    def test_a_red_reading_sets_red_and_clears_fresh(self):
        gs = GuardState()
        gs.last_gate_red = False
        gs.gate_fresh = True
        record_gate_state(gs, outcome(), "x.py:3 SyntaxError: bad")
        self.assertTrue(gs.last_gate_red)
        self.assertFalse(gs.gate_fresh)
        self.assertTrue(gs.last_gate_ran)
        self.assertIn("SyntaxError", gs.last_gate_flag)

    def test_a_green_reading_clears_red(self):
        gs = GuardState()
        gs.last_gate_red = True
        record_gate_state(gs, outcome(), "")
        self.assertFalse(gs.last_gate_red)
        self.assertTrue(gs.gate_fresh)
        self.assertEqual(gs.last_gate_flag, "")

    def test_a_gate_that_could_not_run_is_neither(self):
        """A neutral non-signal: never red, never green, and it must not touch the stall streak —
        track_gate_progress says so in its own words. Still ATTEMPTED, so gate_fresh is set."""
        gs = GuardState()
        gs.last_gate_red = True
        gs.last_gate_flag = "the previous finding"
        gs.gate_stall = 2
        record_gate_state(gs, outcome(ran=False), "")
        self.assertTrue(gs.last_gate_red)                  # unchanged — no evidence either way
        self.assertEqual(gs.last_gate_flag, "the previous finding")
        self.assertEqual(gs.gate_stall, 2)
        self.assertTrue(gs.gate_fresh)
        self.assertFalse(gs.last_gate_ran)

    def test_the_stall_streak_advances_on_an_unchanged_finding(self):
        gs = GuardState()
        record_gate_state(gs, outcome(), "same error")
        record_gate_state(gs, outcome(), "same error")
        self.assertEqual(gs.gate_stall, 2)
        record_gate_state(gs, outcome(), "a different error")
        self.assertEqual(gs.gate_stall, 1)


class TheGuardProbeTurnRecordsItTests(unittest.TestCase):
    """THE REGRESSION, driven through guard_probe_steer itself."""

    def _gs(self, *, spin: bool):
        gs = GuardState()
        gs.gate_plan = object()          # any non-None plan; read_gate is patched below
        gs.probe_call_id = "c1"
        gs.spin_path = "handler.py"
        gs.spin_probe = spin
        gs.redirect_probe = not spin
        gs.last_gate_red = False         # the PREVIOUS gate was green — this is what used to survive
        gs.gate_fresh = True
        return gs

    def _run(self, gs, findings):
        red = outcome()

        def fake_read_gate(plan, probe_text, rlog):
            return red

        def fake_findings(o):
            return findings

        real_read, real_find = loop.read_gate, loop.gate_error_text
        loop.read_gate, loop.gate_error_text = fake_read_gate, fake_findings
        try:
            return loop.guard_probe_steer(gs, {"messages": []}, _Rlog(), author=loop.CANNED, step=1)
        finally:
            loop.read_gate, loop.gate_error_text = real_read, real_find

    def test_a_wheel_spin_turn_records_a_red_gate(self):
        gs = self._gs(spin=True)
        steer = self._run(gs, "handler.py:3 SyntaxError: bad")
        self.assertIsNotNone(steer)                 # it still steers
        self.assertTrue(gs.last_gate_red)           # ...and no longer forgets what it just read
        self.assertFalse(gs.gate_fresh)
        self.assertIn("SyntaxError", gs.last_gate_flag)

    def test_a_repetition_redirect_turn_records_it_too(self):
        gs = self._gs(spin=False)
        steer = self._run(gs, "handler.py:3 SyntaxError: bad")
        self.assertTrue(steer.startswith("[REDIRECT]"))
        self.assertTrue(gs.last_gate_red)

    def test_a_green_guard_probe_clears_a_stale_red(self):
        gs = self._gs(spin=True)
        gs.last_gate_red = True
        self._run(gs, "")
        self.assertFalse(gs.last_gate_red)

    def test_a_non_guard_probe_turn_reads_nothing(self):
        """The completion gate's own turn: guard_probe_steer must return before touching anything —
        the loop owns that reading."""
        gs = GuardState()
        gs.last_gate_red = True
        self.assertIsNone(loop.guard_probe_steer(gs, {"messages": []}, _Rlog(), author=loop.CANNED))
        self.assertTrue(gs.last_gate_red)


class TheRednessDecisionHasOneOwnerTests(unittest.TestCase):
    def test_a_gate_that_never_ran_is_not_red(self):
        self.assertEqual(gate_error_text(outcome(ran=False)), "")

    def test_there_is_no_second_redness_function(self):
        """The first cut of this fix added one — a private copy of gate_error_text with a
        hand-written prefix, which is the fifth copy of a rule that already had an owner. Worse, it
        reproduced the bug gate_error_text exists to fix: it returned the located findings OR the
        unparseable failures, never both."""
        self.assertFalse(hasattr(loop, "gate_findings_text"))

    def test_both_failure_classes_are_surfaced_together(self):
        """A located finding and a check that failed with nothing parseable are not alternatives.

        Covered end to end, with real content (not a source snippet), by
        tests/test_gate_never_denies_a_line_it_parsed.py::GateErrorTextTests — in particular
        test_both_present_says_neither_is_the_whole_story, which is the exact incident this
        docstring names (Importer.java:96 + a failed `mvn -q compile` in the same reading)."""
        import unittest.mock as mock
        with mock.patch.object(proberun, "completion_block_nudge", lambda *a, **k: "Importer.java:96 cannot find symbol"), \
             mock.patch.object(proberun, "failed_unparsed_probes", lambda *a, **k: ["$ mvn -q compile — exited 1"]):
            out = gate_error_text(outcome())
        self.assertIn("Importer.java:96", out)
        self.assertIn("mvn -q compile", out)

    def test_no_reader_writes_the_state_inline_any_more(self):
        """Each reader delegates to the shared mirror rather than keeping its own copy of the
        assignment. Checked by AST rather than string search — a reformatted line, or a comment that
        happens to quote the old assignment (this file's own module docstring does, twice), must not
        be able to fool it either way."""
        import ast
        import inspect
        import textwrap

        def calls_the_owner(fn) -> bool:
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                      and n.func.id == "record_gate_state" for n in ast.walk(tree))

        def assigns_state_inline(fn) -> bool:
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            return any(isinstance(t, ast.Attribute) and t.attr == "last_gate_red"
                      for node in ast.walk(tree) if isinstance(node, ast.Assign)
                      for t in node.targets)

        for fn in (loop.guard_gate_verdict, loop.guard_probe_steer, loop.Loop._verify_after_probe,
                   loop.guard_periodic_result):
            with self.subTest(fn=fn.__name__):
                self.assertTrue(calls_the_owner(fn), f"{fn.__name__} never calls record_gate_state")
                self.assertFalse(assigns_state_inline(fn),
                                 f"{fn.__name__} still assigns last_gate_red itself")


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


class _Scripted:
    """Returns canned completions in order; repeats the last when exhausted."""

    def __init__(self, responses):
        self._r = list(responses)

    def __call__(self, body, rlog):
        r = self._r.pop(0) if len(self._r) > 1 else self._r[0]
        return json.dumps(r).encode()


class _Recorder(_Scripted):
    """Like _Scripted, but remembers what it was handed — so a test can read what the coder was told."""

    def __init__(self, responses):
        super().__init__(responses)
        self.bodies = []

    def __call__(self, body, rlog):
        self.bodies.append(body)
        return super().__call__(body, rlog)

    def last_user(self):
        return self.bodies[-1]["messages"][-1]["content"]


class _Planner:
    def __init__(self, plan):
        self._plan = plan

    def plan_for(self, messages, rlog, prior_work="", rewrite_summary=""):
        return self._plan


class _Classification:
    engagement = "task"
    task_type = "coding"
    cached = False


_SHELL = {"type": "function", "function": {"name": "shell",
          "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}


def _plan(n=1):
    return Plan(id="20260707T0000-abcd1234", task="build it", created="2026-07-07T00:00:00+00:00",
                items=[PlanItem(f"step {i + 1}") for i in range(n)])


def _ctx(coder, reasoner, plan, workspace_root):
    return LoopContext(planner=_Planner(plan), coder_chat=coder, reasoner_chat=reasoner, runs_dir="",
                       workspace_root=workspace_root)


def _body():
    return {"messages": [{"role": "user", "content": "build a resolver"}], "tools": [_SHELL], "stream": True}


def _body_with_probe(call_id, output):
    b = _body()
    b["messages"] = b["messages"] + [{"role": "tool", "tool_call_id": call_id, "content": output}]
    return b


def _tc_id(completion):
    return completion["choices"][0]["message"]["tool_calls"][0]["id"]


def _toolcall():
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]}}]}


def _done(text="looks done"):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def _verdict(done=True, reason="ok"):
    return {"choices": [{"message": {"content": json.dumps({"done": done, "reason": reason})}}]}


def _ws():
    t = tempfile.mkdtemp()
    with open(os.path.join(t, "x.py"), "w") as f:
        f.write("print(1)\n")
    with open(os.path.join(t, "pyproject.toml"), "w") as f:
        f.write("[tool.pytest.ini_options]\n")
    return t


def _gate_result(floor_exit=0, probe_body=None):
    # Same shape as GateFlowTests._gate_result in test_loop.py: candidate order for the _ws fixture is
    # [compileall(SyntaxCheck), TOML(SyntaxCheck), pyflakes(Lint), pytest(Test)].
    P, S = SECTION_PREFIX, SECTION_SUFFIX
    parts = [f"{P}probe-0{S}",
             "EXIT:0" if floor_exit == 0 else '  File "x.py", line 3\nSyntaxError: bad\nEXIT:1',
             f"{P}probe-1{S}", "EXIT:0",
             f"{P}probe-2{S}", "EXIT:0"]
    if probe_body is not None:
        parts += [f"{P}probe-3{S}", probe_body]
    parts += [f"{P}git{S}", "abc"]
    return "\n".join(parts)


class TheStallComparisonReadsThePreviousFlagTests(unittest.TestCase):
    """`_verify_after_probe` captures `prev_flag` BEFORE `record_gate_state` overwrites it, because
    the stall signal is "the same finding as last time" — comparing the fresh flag against itself
    would always be true, and would fire the FIRST time a red gate is ever read, not the second.

    Driven through the real Loop, not the source: the same red finding, twice in a row, must stay
    silent on stall the first time and only fire it the second. This is also the plan-on step-verdict
    path (the RED gate keeps holding the step, via completion_block_nudge, exactly as before) — the
    coder is re-driven with the exact SyntaxError text on both turns, proving the wiring survived."""

    def test_no_stall_on_the_first_red_reading_only_the_second(self):
        ws = _ws()
        coder = _Recorder([_toolcall(), _done()])   # keeps claiming done, never actually fixes it
        reasoner = _Scripted([_verdict(True)])
        run = Loop(_ctx(coder, reasoner, _plan(1), ws))
        rlog = _Rlog()
        c = run.drive(_body(), "k", _Classification(), rlog)
        c = run.drive(_body(), "k", _Classification(), rlog)             # claims done → gate probe
        same = _gate_result(floor_exit=1)
        c = run.drive(_body_with_probe(_tc_id(c), same), "k", _Classification(), rlog)  # 1st red
        self.assertNotIn("loop.gate_stalled", rlog.kinds())
        self.assertIn("loop.step_incomplete", rlog.kinds())
        self.assertIn("SyntaxError", coder.last_user())          # the step still holds on the finding
        c = run.drive(_body_with_probe(_tc_id(c), same), "k", _Classification(), rlog)  # 2nd red, SAME finding
        self.assertIn("loop.gate_stalled", rlog.kinds())
        self.assertIn("SyntaxError", coder.last_user())


class TheWheelSpinMetricIsAMeasurementTests(unittest.TestCase):
    """`spoke=True` was a literal, so the log said `spoke` on 121 of 121 occasions and could not
    have said anything else. What varies is who wrote the steer and whether it carries any ground
    truth — cria talking with nothing to say is now countable (#12)."""

    def _gs(self):
        gs = GuardState()
        gs.gate_plan = object()
        gs.probe_call_id = "c1"
        gs.spin_path = "handler.py"
        gs.spin_probe = True
        return gs

    def _run(self, gs, *, truth, authored):
        got = outcome()
        real_read, real_truth = loop.read_gate, loop.guard_ground_truth
        loop.read_gate = lambda plan, probe, rlog: got
        loop.guard_ground_truth = lambda o: truth
        rlog = _Rlog()
        try:
            author = loop.CANNED if authored is None else (lambda *a, **k: authored)
            steer = loop.guard_probe_steer(gs, {"messages": []}, rlog, author=author, step=1)
        finally:
            loop.read_gate, loop.guard_ground_truth = real_read, real_truth
        return steer, next(kw for k, kw in rlog.events if k == "loop.spin_probe_result")

    def test_a_reasoned_steer_is_recorded_as_authored(self):
        steer, ev = self._run(self._gs(), truth="cart.go:3 boom", authored="Read cart.go first.")
        self.assertEqual(steer, "Read cart.go first.")
        self.assertTrue(ev["authored"])
        self.assertTrue(ev["grounded"])

    def test_a_declining_reasoner_falls_to_the_canned_floor_and_says_so(self):
        steer, ev = self._run(self._gs(), truth="cart.go:3 boom", authored="")
        self.assertIn("cart.go:3 boom", steer)      # the FACT still ships
        self.assertFalse(ev["authored"])
        self.assertTrue(ev["grounded"])

    def test_no_reasoner_and_no_ground_truth_is_the_countable_worst_case(self):
        steer, ev = self._run(self._gs(), truth="", authored=None)
        self.assertTrue(steer)                      # never None — that misroutes into the done gate
        self.assertFalse(ev["authored"])
        self.assertFalse(ev["grounded"])


class ThePeriodicCheckInKeepsItsOneDifferenceTests(unittest.TestCase):
    """A periodic check-in is a real gate run — so it records the reading — but the coder has NOT
    claimed done, and letting its clean result set `gate_fresh` would pre-satisfy the completion
    backstop for a 'done' that arrives later. That single field is the reason this reader is not
    simply the shared one."""

    def _gs(self):
        gs = GuardState()
        gs.periodic_probe = True
        gs.gate_plan = object()
        gs.probe_call_id = "c1"
        return gs

    def _run(self, gs, err, ran=True):
        got = outcome(ran=ran)
        real_read, real_err = loop.read_gate, loop.gate_error_text
        loop.read_gate = lambda plan, probe, rlog: got
        loop.gate_error_text = lambda o: err
        try:
            return loop.guard_periodic_result(gs, {"messages": []}, _Rlog())
        finally:
            loop.read_gate, loop.gate_error_text = real_read, real_err

    def test_a_clean_check_in_does_not_mark_ground_truth_fresh(self):
        gs = self._gs()
        gs.gate_fresh = False
        self._run(gs, "")
        self.assertFalse(gs.gate_fresh)
        self.assertFalse(gs.last_gate_red)
        self.assertTrue(gs.last_gate_ran)

    def test_a_red_check_in_records_the_finding(self):
        gs = self._gs()
        out = self._run(gs, "cart.go:12: undefined: Total")
        self.assertIn("undefined: Total", out)
        self.assertTrue(gs.last_gate_red)
        self.assertIn("undefined: Total", gs.last_gate_flag)

    def test_a_check_in_that_could_not_run_says_nothing_and_records_that_it_did_not(self):
        gs = self._gs()
        gs.last_gate_red = True
        self.assertIsNone(self._run(gs, "", ran=False))
        self.assertTrue(gs.last_gate_red)      # no evidence either way
        self.assertFalse(gs.last_gate_ran)


if __name__ == "__main__":
    unittest.main()
