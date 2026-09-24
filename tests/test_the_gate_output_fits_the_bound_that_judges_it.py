"""Lossless asynchronous gate transport over ordinary harness tool calls.

The old gate fit one response by clipping each probe. These tests pin the replacement: complete
bytes arrive across as many checked pages as needed; a missing, reordered, or corrupted page is
UNKNOWN and can never be interpreted as a clean gate.
"""

import os
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from cria import loop, probegate, proberun
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def candidate(workspace: str) -> ProbeCandidate:
    program = (
        "import sys\n"
        "for i in range(900):\n"
        " print(f'noise-{i:04d}-' + 'x' * 40)\n"
        " if i == 450: print('src/middle.py:73: MIDDLE_FAILURE')\n"
        "print('FINAL_TALLY: 1 failed')\n"
        "sys.exit(1)\n"
    )
    return ProbeCandidate(
        kind=ProbeKind.Test,
        command=["python3", "-c", program],
        working_dir=workspace,
        confidence=90,
        expected_value=80,
        cost=ProbeCost.Cheap,
        mutates_code=False,
        may_hang=False,
        may_need_services=False,
        reason="test",
    )


def run(command: str, workspace: str, tmpdir: str) -> str:
    env = {**os.environ, "TMPDIR": tmpdir}
    return subprocess.run(
        ["bash", "-c", command], cwd=workspace, env=env,
        capture_output=True, text=True, timeout=60, check=False,
    ).stdout


class CompleteEvidenceCrossesAsynchronousTurnsTests(unittest.TestCase):
    def test_every_byte_arrives_and_the_existing_parser_sees_the_middle_failure(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as spooldir:
            pathlib.Path(workspace, "src").mkdir()
            pathlib.Path(workspace, "src", "middle.py").write_text("pass\n")
            selected = [candidate(workspace)]
            with mock.patch.object(proberun, "select_completion_probes", return_value=selected), \
                    mock.patch.object(probegate.probediscovery, "undiscoverable_tests", return_value=[]), \
                    mock.patch.object(probegate.probediscovery, "tests_with_no_command", return_value=[]):
                plan = probegate.plan_gate(workspace, "transport-test")

            pages = []
            result = run(plan.script, workspace, spooldir)
            pages.append(result)
            outcome = probegate.interpret_gate(plan, result)
            while outcome.transport_pending:
                result = run(probegate.continue_transport_command(plan), workspace, spooldir)
                pages.append(result)
                outcome = probegate.interpret_gate(plan, result)

            self.assertGreater(len(pages), 2)
            self.assertTrue(outcome.ran)
            self.assertFalse(outcome.transport_unknown)
            complete = probegate.transported_result(plan)
            self.assertIn("noise-0000", complete)
            self.assertIn("src/middle.py:73: MIDDLE_FAILURE", complete)
            self.assertIn("noise-0899", complete)
            self.assertIn("FINAL_TALLY: 1 failed", complete)
            self.assertEqual(len(complete.encode()), plan.transport_total)
            self.assertTrue(any("middle.py" in finding.file
                                for finding in outcome.report.results[0].findings))
            # Reviewer 6510f2dd follow-up: the reader no longer self-deletes on the final read (a
            # lost-and-repolled final page must be able to re-read the SAME bytes), so the spool and
            # its .done marker persist — queued for the NEXT gate composed for this workspace to
            # reclaim, never an `rm`, never a glob.
            self.assertEqual(sorted(os.listdir(spooldir)),
                             sorted([os.path.basename(plan.transport_path),
                                     os.path.basename(plan.transport_path) + ".done"]))
            cleanup = probegate.spool_cleanup_command(workspace)
            self.assertTrue(cleanup)
            run(cleanup, workspace, spooldir)
            self.assertEqual(os.listdir(spooldir), [])

    def test_the_loop_requests_each_next_page_through_the_harness_shell(self):
        from cria.loop import GuardState, guard_gate_transport

        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as spooldir:
            selected = [candidate(workspace)]
            with mock.patch.object(proberun, "select_completion_probes", return_value=selected), \
                    mock.patch.object(probegate.probediscovery, "undiscoverable_tests", return_value=[]), \
                    mock.patch.object(probegate.probediscovery, "tests_with_no_command", return_value=[]):
                plan = probegate.plan_gate(workspace)
            state = GuardState(gate_plan=plan, probe_call_id="page-0")
            shell = {"type": "function", "function": {"name": "shell", "parameters": {
                "type": "object", "properties": {"command": {"type": "string"}}}}}
            current_id = state.probe_call_id
            result = run(plan.script, workspace, spooldir)
            pages = 1
            while True:
                body = {"messages": [{"role": "tool", "tool_call_id": current_id,
                                      "content": result}], "tools": [shell]}
                call = guard_gate_transport(state, body, _Rlog())
                if call is None:
                    break
                current_id = call["id"]
                command = json.loads(call["function"]["arguments"])["command"]
                result = run(command, workspace, spooldir)
                pages += 1
            self.assertGreater(pages, 2)
            self.assertTrue(plan.transport_complete)
            self.assertEqual(state.probe_call_id, current_id)
            self.assertTrue(probegate.interpret_gate(plan, result).ran)


class IncompleteEvidenceIsExplicitlyUnknownTests(unittest.TestCase):
    def test_a_cut_page_is_unknown_not_clean(self):
        plan = probegate.GatePlan(workspace="/remote", transport_required=True)
        opening = probegate._transport_marker(plan.transport_id)
        outcome = probegate.interpret_gate(plan, opening + "\npath\tcut-before-close")
        self.assertFalse(outcome.ran)
        self.assertTrue(outcome.transport_unknown)
        self.assertTrue(probegate.gate_is_partial(outcome))
        text = loop.gate_error_text(outcome)
        self.assertIn("UNKNOWN", text)
        self.assertNotIn("reported no error", text)
        state = loop.GuardState(gate_fresh=True)
        loop.record_gate_state(state, outcome, text)
        self.assertFalse(state.gate_fresh)
        self.assertFalse(state.last_gate_ran)

    def test_a_reordered_page_is_unknown(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as spooldir:
            selected = [candidate(workspace)]
            with mock.patch.object(proberun, "select_completion_probes", return_value=selected), \
                    mock.patch.object(probegate.probediscovery, "undiscoverable_tests", return_value=[]), \
                    mock.patch.object(probegate.probediscovery, "tests_with_no_command", return_value=[]):
                plan = probegate.plan_gate(workspace)
            first = run(plan.script, workspace, spooldir)
            self.assertTrue(probegate.interpret_gate(plan, first).transport_pending)
            next_command = probegate.continue_transport_command(plan)
            second = run(next_command, workspace, spooldir)
            # Replaying an already-consumed offset instead of the next page is a protocol gap.
            self.assertTrue(probegate.interpret_gate(plan, first).transport_unknown)
            self.assertFalse(probegate.interpret_gate(plan, second).ran)


if __name__ == "__main__":
    unittest.main()
