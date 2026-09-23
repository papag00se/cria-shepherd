"""C6/C7 capture-shaped replay for the declared JavaScript runner reset.

The real C6/C7 prompts contained a red configured ``npm run test`` result after incompatible
framework edits.  C7's later workspace also contained node_modules despite the task contract.
The assist must judge that context, retain the exact checker evidence, and never enter Go/Ruby.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cria import probediscovery, wsview
from cria.config import Role
from cria.loop import GuardState, runner_reset_steer
from cria.probegate import GateOutcome
from cria.probeparse import ProbeResult
from cria.proberun import ProbeReport
from wsfixture import survey


class _Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


class RunnerInterfaceResetTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.view = wsview.View(str(self.root), "runner-reset")
        self.token = wsview.bind(self.view)

    def tearDown(self):
        wsview.unbind(self.token)

    def _gate_outcome(self, *, ecosystem, exit_code=1, summary="test interface failed"):
        candidate = probediscovery.ProbeCandidate(
            kind=probediscovery.ProbeKind.Test,
            command=["npm", "run", "test"], working_dir=self.root,
            confidence=96, expected_value=88, cost=probediscovery.ProbeCost.Moderate,
            mutates_code=False, may_hang=False, may_need_services=False,
            reason="package.json script `test`", declared_interface=True,
            ecosystem=ecosystem)
        result = ProbeResult("npm run test", exit_code, summary)
        return GateOutcome(ran=True, report=ProbeReport([], [candidate], [result]))

    @staticmethod
    def _body():
        return {"messages": [
            {"role": "user", "content": (
                "Build the CLI. It must run with no node_modules directory present.")},
            {"role": "assistant", "content": "I changed the test package and assertions."},
            {"role": "tool", "content": "ReferenceError: test is not defined"},
        ]}

    def _reset(self, outcome):
        seen = []

        def reasoner(body, _rlog):
            seen.append(body)
            return json.dumps({"choices": [{"message": {"content": "RESET"}}]}).encode()

        steer = runner_reset_steer(
            GuardState(), outcome, self._body(), _Log(), reasoner_chat=reasoner,
            reasoner_role=Role(name="reasoner", backend="local"), workspace_root=str(self.root))
        return steer, seen

    def test_c7_replay_pins_declared_runner_and_contract_with_checker_evidence(self):
        self.assertTrue(wsview.apply_survey(self.view, survey("X\t0\tnode_modules")))
        steer, seen = self._reset(self._gate_outcome(
            ecosystem=probediscovery.Ecosystem.JsTs,
            summary="test/cli.test.js:4: ReferenceError: test is not defined"))
        self.assertEqual(len(seen), 1)
        judge_prompt = "\n".join(str(message.get("content") or "")
                                 for message in seen[0]["messages"])
        self.assertIn("npm run test", judge_prompt)
        self.assertIn("node_modules is present", judge_prompt)
        self.assertIn("npm run test", steer)
        self.assertIn("no-node_modules contract", steer)
        self.assertIn("ReferenceError: test is not defined", steer)

    def test_c6_replay_uses_the_same_declared_interface_without_a_directory_claim(self):
        self.assertTrue(wsview.apply_survey(self.view, survey()))
        steer, seen = self._reset(self._gate_outcome(
            ecosystem=probediscovery.Ecosystem.JsTs,
            summary="❌ Test suite failed: ReferenceError: output is not defined"))
        judge_prompt = "\n".join(str(message.get("content") or "")
                                 for message in seen[0]["messages"])
        self.assertIn("node_modules is absent", judge_prompt)
        self.assertIn("npm run test", steer)

    def test_go_and_ruby_failures_do_not_call_the_judge_or_reframe(self):
        for ecosystem in (probediscovery.Ecosystem.Go, probediscovery.Ecosystem.Ruby):
            called = False

            def reasoner(_body, _rlog):
                nonlocal called
                called = True
                raise AssertionError("non-JavaScript candidate reached runner reset")

            steer = runner_reset_steer(
                GuardState(), self._gate_outcome(ecosystem=ecosystem), self._body(), _Log(),
                reasoner_chat=reasoner, reasoner_role=Role(name="reasoner", backend="local"),
                workspace_root=str(self.root))
            self.assertIsNone(steer)
            self.assertFalse(called)

    def test_c9_shape_without_a_failed_configured_runner_does_not_call_the_judge(self):
        called = False

        def reasoner(_body, _rlog):
            nonlocal called
            called = True
            raise AssertionError("green runner reached runner reset")

        steer = runner_reset_steer(
            GuardState(), self._gate_outcome(ecosystem=probediscovery.Ecosystem.JsTs, exit_code=0),
            self._body(), _Log(), reasoner_chat=reasoner,
            reasoner_role=Role(name="reasoner", backend="local"),
            workspace_root=str(self.root))
        self.assertIsNone(steer)
        self.assertFalse(called)
