"""A repo-wide RED gate used to veto EVERY plan step, including steps that write no code.

`loop._verify_after_probe` returned on `nudge is not None` BEFORE `_verify` — so the step critic,
which already carries the rule "Ignore failures NOT related to this step's goal", never got to
apply it. The checks run over the whole repository and nothing in probegate/proberun attributes a
finding to a step, so a failing pytest held steps that could not possibly have caused it.

Measured over the seven captured log-days in ~/.cria/logs: 872 `loop.step_incomplete
{"reason": "probe failed"}` holds across 64 step-positions in 40 sessions. 27 of those
step-positions (167 holds) never received a single critic verdict. Reading all 64 step texts,
~190 holds sit on READMEs, requirements.txt / pyproject.toml and pure read/confirm research steps.

Walked on ada-handles_fabliq_codex_pon_1785721353: step 1 "Read the Ada Handles API documentation"
was held nine times by a red pytest whose fix was steps 3 and 4, sitting behind it. 267 calls, the
plan never left step 1, the last critic call in the run was 0060, and the live test and README —
steps 4 and 5 — do not exist.

The gate is now EVIDENCE the critic weighs, under a label that asks the one question the findings
cannot answer for themselves: whose step is this? A wrong NOT-done is the old behaviour exactly; a
wrong DONE costs one step advance and cannot complete the run, because `last_gate_red` stays set.
"""
import json
import os
import tempfile
import unittest

from cria import proberun, loop as loopmod, prompts, proberun
from cria.loop import Loop
from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S

from test_loop import (_Classification, _Recorder, _Rlog, _body, _body_with_probe, _ctx, _done,
                       _plan, _tc_id, _toolcall)


def _ws():
    t = tempfile.mkdtemp()
    with open(os.path.join(t, "x.py"), "w") as f:
        f.write("print(1)\n")
    with open(os.path.join(t, "pyproject.toml"), "w") as f:
        f.write("[tool.pytest.ini_options]\n")
    return t


RED_TESTS = "FAILED tests/test_x.py::t - AssertionError: boom\n1 failed\nEXIT:1"


def _gate(probe_body):
    """The harness's reply to cria's composed gate script: syntax floor clean, pytest red."""
    return "\n".join([f"{P}probe-0{S}", "EXIT:0",          # compileall
                      f"{P}probe-1{S}", "EXIT:0",          # pyproject.toml floor
                      f"{P}probe-2{S}", "EXIT:0",          # pyflakes
                      f"{P}probe-3{S}", probe_body,        # pytest
                      f"{P}git{S}", "abc"])


class _Reasoner:
    """Answers the step critic, its approve-path confirm, and the living-plan re-derive with one
    object carrying every shape — and records every prompt it was handed."""

    def __init__(self, done):
        self.done = done
        self.prompts = []
        self.calls = 0

    def __call__(self, body, rlog):
        self.calls += 1
        self.prompts.append(body["messages"][-1].get("content") or "")
        return json.dumps({"choices": [{"message": {"content": json.dumps(
            {"done": self.done, "reason": "the failing tests belong to a later step", "proposed_fix": "",
             "consistent": True, "why": ""})}}]}).encode()

    def critic_prompt(self):
        return self.prompts[0]


def _run_to_red_gate(reasoner, plan_items=2):
    """Drive a plan until the coder claims done and the gate comes back RED. Returns the loop, the
    coder stub, the rlog and the completion the red gate produced."""
    coder = _Recorder([_toolcall(), _done(), _toolcall()])
    loop = Loop(_ctx(coder, reasoner, _plan(plan_items), workspace_root=_ws()))
    rlog = _Rlog()
    loop.drive(_body(), "k", _Classification(), rlog)            # coder acts
    c2 = loop.drive(_body(), "k", _Classification(), rlog)       # coder claims done → gate goes out
    out = loop.drive(_body_with_probe(_tc_id(c2), _gate(RED_TESTS)), "k", _Classification(), rlog)
    return loop, coder, rlog, out


class RedGateReachesTheCriticTests(unittest.TestCase):
    def test_the_step_critic_is_consulted_on_a_red_gate(self):
        reasoner = _Reasoner(done=False)
        _loop, _coder, _rlog, _out = _run_to_red_gate(reasoner)
        self.assertGreater(reasoner.calls, 0, "a red gate must no longer skip the critic")

    def test_the_critic_gets_the_checkers_own_failing_lines(self):
        reasoner = _Reasoner(done=False)
        _run_to_red_gate(reasoner)
        self.assertIn("tests/test_x.py", reasoner.critic_prompt())

    def test_it_is_told_the_findings_are_repo_wide_and_asked_whose_step(self):
        reasoner = _Reasoner(done=False)
        _run_to_red_gate(reasoner)
        head = prompts.load_map("verify_user")["probe_red"].split("{{FINDINGS}}")[0]
        self.assertIn(head.strip(), reasoner.critic_prompt())

    def test_the_coder_facing_imperative_never_reaches_the_judge(self):
        # block_nudge_preamble tells the CODER to "resolve exactly what it names". An imperative reads
        # as a task briefing to a weak judge and it starts fixing instead of ruling (principle 8).
        reasoner = _Reasoner(done=False)
        _run_to_red_gate(reasoner)
        self.assertNotIn(proberun.BLOCK_NUDGE_PREAMBLE.strip(), reasoner.critic_prompt())


class NotDoneKeepsTheOldContractTests(unittest.TestCase):
    def test_the_coder_is_re_driven_with_the_checkers_own_errors(self):
        reasoner = _Reasoner(done=False)
        _loop, coder, _rlog, out = _run_to_red_gate(reasoner)
        self.assertTrue(out["choices"][0]["message"].get("tool_calls"))   # re-driven, not advanced
        self.assertIn("tests/test_x.py", coder.last_user())               # the CHECKER's words
        self.assertIn(proberun.BLOCK_NUDGE_PREAMBLE.strip(), coder.last_user())

    def test_it_still_logs_probe_failed(self):
        reasoner = _Reasoner(done=False)
        _loop, _coder, rlog, _out = _run_to_red_gate(reasoner)
        reasons = [kw.get("reason") for k, kw in rlog.events if k == "loop.step_incomplete"]
        self.assertIn("probe failed", reasons)

    def test_a_red_gate_still_cannot_drive_the_stuck_step_rescue(self):
        # critic_fails was split from verify_fails precisely so a gate failure means FIX THE CODE, not
        # "this step may be impossible" (run 0727-170754: the rescue rewrote "Write unit tests…" into
        # "Add retry logic…"). Routing the red path through the critic must not have re-merged them.
        reasoner = _Reasoner(done=False)
        loop, _coder, _rlog, _out = _run_to_red_gate(reasoner)
        sess = loop._store.get("k")
        self.assertGreater(sess.verify_fails, 0)
        self.assertEqual(sess.critic_fails, 0)


class AdvanceOverRedTests(unittest.TestCase):
    def test_the_step_advances_when_the_critic_attributes_the_failure_elsewhere(self):
        reasoner = _Reasoner(done=True)
        _loop, _coder, rlog, _out = _run_to_red_gate(reasoner)
        self.assertIn("loop.step_done", rlog.kinds())

    def test_the_advance_is_recorded_loudly_with_the_findings(self):
        reasoner = _Reasoner(done=True)
        _loop, _coder, rlog, _out = _run_to_red_gate(reasoner)
        ev = [kw for k, kw in rlog.events if k == "loop.gate_red_advance"]
        self.assertTrue(ev, "the one place a step moves while the repo is red must be auditable")
        self.assertIn("tests/test_x.py", ev[0]["findings"])

    def test_the_run_still_knows_the_repo_is_red_afterwards(self):
        # The safety of advancing rests entirely on this: last_gate_red stays set, so
        # _periodic_satisfaction stays blocked and the completion judge is told (principle 13 —
        # advancing one step is not declaring the task done).
        reasoner = _Reasoner(done=True)
        loop, _coder, _rlog, _out = _run_to_red_gate(reasoner)
        sess = loop._store.get("k")
        self.assertTrue(sess.last_gate_red)
        self.assertIn("tests/test_x.py", sess.last_gate_flag)   # findings survive _advance while red

    def test_the_completion_judge_is_handed_the_red_findings(self):
        reasoner = _Reasoner(done=True)
        loop, _coder, _rlog, _out = _run_to_red_gate(reasoner)
        note = loopmod._gate_notes(loop._store.get("k"))
        self.assertIn("tests/test_x.py", note)

    def test_a_green_advance_still_clears_the_convergence_signature(self):
        sess = loopmod.PlanSession(plan=_plan(2))
        sess.last_gate_red, sess.last_gate_flag = False, "stale"
        loop = Loop(_ctx(_Recorder([_toolcall()]), _Reasoner(done=True), _plan(2)))
        loop._advance(sess, "k", _body(), 1, 2, _Rlog())
        self.assertEqual(sess.last_gate_flag, "")


class BlockFindingsSplitTests(unittest.TestCase):
    """One renderer, two framings — the findings are byte-identical for coder and judge."""

    def _report(self, probe_body):
        from cria import probegate
        gate = probegate.plan_gate(_ws())
        return probegate.interpret_gate(gate, _gate(probe_body)).report

    def test_the_nudge_is_the_preamble_plus_the_findings(self):
        report = self._report(RED_TESTS)
        body = proberun.block_findings(report)
        self.assertIsNotNone(body)
        self.assertEqual(proberun.completion_block_nudge(report),
                         proberun.BLOCK_NUDGE_PREAMBLE + body)

    def test_a_clean_report_yields_no_findings(self):
        clean = self._report("3 passed\nEXIT:0")
        self.assertIsNone(proberun.block_findings(clean))
        self.assertIsNone(proberun.completion_block_nudge(clean))


if __name__ == "__main__":
    unittest.main()
