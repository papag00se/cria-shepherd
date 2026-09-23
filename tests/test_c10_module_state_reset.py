"""C10 replay: a red read-only Go test must interrupt dependency speculation, not parse it."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from cria import probediscovery
from cria.config import Role
from cria.loop import GuardState, guard_periodic_result, module_state_steer
from cria.probegate import GateOutcome, GatePlan, SECTION_PREFIX, SECTION_SUFFIX
from cria.probeparse import ProbeResult
from cria.proberun import ProbeReport


class _Log:
    def emit(self, *_args, **_kwargs):
        pass


def _candidate(kind, command, ecosystem=probediscovery.Ecosystem.Go):
    return probediscovery.ProbeCandidate(
        kind=kind, command=command, working_dir=Path("."), confidence=90,
        expected_value=90, cost=probediscovery.ProbeCost.Moderate,
        mutates_code=False, may_hang=False, may_need_services=False,
        reason="go.mod found", ecosystem=ecosystem)


def _outcome(ecosystem=probediscovery.Ecosystem.Go, exit_code=1):
    command = ["go", "test", "-mod=readonly", "-count=1", "-v", "./..."]
    candidate = _candidate(probediscovery.ProbeKind.Test, command, ecosystem)
    result = ProbeResult(" ".join(command), exit_code, "billing/money.go:8: missing go.sum entry")
    return GateOutcome(ran=True, report=ProbeReport([], [candidate], [result]))


def _body(extra=()):
    return {"messages": [
        {"role": "user", "content": "Implement the cart billing endpoint."},
        {"role": "assistant", "content": "Maybe another decimal package is needed."},
        *extra,
    ]}


class C10ModuleStateResetTests(unittest.TestCase):
    def test_c10_periodic_gate_matches_failed_test_by_command_after_omitted_preceding_probe(self):
        """The actual periodic transition must not zip the test onto absent `go vet` output."""
        seen = []

        def reasoner(body, _rlog):
            seen.append(body)
            return json.dumps({"choices": [{"message": {"content": "REANCHOR"}}]}).encode()

        lint = _candidate(probediscovery.ProbeKind.Lint,
                          ["go", "vet", "-mod=readonly", "./..."])
        test = _candidate(probediscovery.ProbeKind.Test,
                          ["go", "test", "-mod=readonly", "-count=1", "-v", "./..."])
        state = GuardState(periodic_probe=True, probe_call_id="c10-gate")
        state.gate_plan = GatePlan(workspace=".", candidates=[lint, test])
        # probe-0 is deliberately absent (a cut result); probe-1 is the actual C10-shaped failure.
        raw = (f"{SECTION_PREFIX}probe-1{SECTION_SUFFIX}\n"
               "billing/money.go:8: missing go.sum entry\nEXIT:1\n"
               f"{SECTION_PREFIX}git{SECTION_SUFFIX}\nabc\n")
        steer = guard_periodic_result(
            state, _body(({"role": "tool", "tool_call_id": "c10-gate", "content": raw},)),
            _Log(), reasoner_chat=reasoner, reasoner_role=Role(name="reasoner", backend="local"))

        self.assertFalse(state.periodic_probe)
        self.assertEqual(len(seen), 1)
        prompt = "\n".join(str(x.get("content") or "") for x in seen[0]["messages"])
        self.assertIn("go test -mod=readonly -count=1 -v ./... exited 1", prompt)
        self.assertIn("missing go.sum entry", prompt)
        self.assertIn("missing go.sum entry", steer)
        self.assertIn("Do not guess a package, version", steer)

    def test_c8_c9_and_green_go_do_not_reach_the_reasoner(self):
        for outcome in (_outcome(probediscovery.Ecosystem.Ruby),
                        _outcome(probediscovery.Ecosystem.JsTs), _outcome(exit_code=0)):
            def reasoner(*_args):
                raise AssertionError("out-of-scope gate reached module-state reasoner")
            self.assertIsNone(module_state_steer(
                GuardState(), outcome, _body(), _Log(), reasoner_chat=reasoner,
                reasoner_role=Role(name="reasoner", backend="local")))

    def test_identical_failure_is_judged_once(self):
        calls = 0
        def reasoner(*_args):
            nonlocal calls
            calls += 1
            return json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode()
        state = GuardState()
        for _ in range(2):
            self.assertIsNone(module_state_steer(state, _outcome(), _body(), _Log(),
                reasoner_chat=reasoner, reasoner_role=Role(name="reasoner", backend="local")))
        self.assertEqual(calls, 1)
