"""N1 — the gate's invariant programs live on the harness, not in every call.

phi4 / Java A6 (session 01a12a7e…, 147 Codex requests, 18 compactions in 30 min). Measured over the A4/A5/A6
captures: a Codex compaction follows EXACTLY the requests where cria's reported usage plus chars/4 of the
function_call_output items appended since that report reaches the 13,926 trigger (A4 27/27 above and 0/129
below; A6 17/17 above and 1 of 111 below). Call ARGUMENTS are not in that estimate (adding them makes it
fire 73 times for 27 compactions). So what crosses the trigger is gate OUTPUT — a page was 6,000 raw
bytes as 8,000 base64 characters (4.5-7.6 KB per call) and a spool took 2-8 of them — while the survey
program (~4.8 KB) and page reader (~1.6 KB) re-sent in every call's ARGUMENTS (10.4-11.0 KB per launch,
1.9 KB per poll) cost request bytes and harness history, not trigger tokens.

The fix writes ONE content-addressed helper into the harness temp dir (a harness-executed leg of the
first gate's own call), invokes it by name afterwards, and packs pages with zlib. Every integrity check
(offset/total/sha256 over the RAW spool) is unchanged. A helper that has gone missing is typed
``helper-gone`` -> terminal UNKNOWN, never clean.

Fixture: ``tests/fixtures/n1_a6_maven_compile_failure.txt`` is the probe output of a real A6 gate
(transport c08084…, the maven compile failure, home paths scrubbed).
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from cria import loop, probegate, proberun, wsview
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind

FIXTURE = Path(__file__).parent / "fixtures" / "n1_a6_maven_compile_failure.txt"

# Measured on the A6 capture (inbound-*-responses.json, 46 launches / 42 polls): a launch call's
# arguments averaged 10,653 chars, a poll's 1,939, and a page's output 4.5–7.6 KB per call.
A6_LAUNCH_ARGS = 10_653
A6_POLL_ARGS = 1_939


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def _candidate(workspace: str, cmd: list[str]) -> ProbeCandidate:
    return ProbeCandidate(kind=ProbeKind.Test, command=cmd, working_dir=workspace, confidence=90,
                          expected_value=80, cost=ProbeCost.Cheap, mutates_code=False,
                          may_hang=False, may_need_services=False, reason="test")


def _plan(workspace: str, cmd: list[str], **kw):
    with mock.patch.object(proberun, "select_completion_probes",
                           return_value=[_candidate(workspace, cmd)]), \
            mock.patch.object(probegate.probediscovery, "undiscoverable_tests", return_value=[]), \
            mock.patch.object(probegate.probediscovery, "tests_with_no_command", return_value=[]):
        return probegate.plan_gate(workspace, **kw)


def _run(command: str, workspace: str, tmpdir: str, env_extra: dict | None = None) -> str:
    env = {**os.environ, "TMPDIR": tmpdir, **(env_extra or {})}
    return subprocess.run(["bash", "-c", command], cwd=workspace, env=env, capture_output=True,
                          text=True, timeout=60, check=False).stdout


def _drive(plan, workspace: str, tmpdir: str, first: str | None = None) -> list[tuple[str, str]]:
    """Launch + every poll against a REAL shell. ``[(call text, result text)]``, in order."""
    calls = []
    cmd = plan.script
    result = first if first is not None else _run(cmd, workspace, tmpdir)
    calls.append((cmd, result))
    while probegate.ingest_transport(plan, result) in ("pending", "running"):
        cmd = probegate.continue_transport_command(plan)
        result = _run(cmd, workspace, tmpdir)
        calls.append((cmd, result))
    return calls


class PerCycleHarnessBytesShrinkTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.ws, True)
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cmd = ["cat", str(FIXTURE)]

    def test_a_session_that_already_has_the_helper_sends_a_short_launch(self):
        plan = _plan(self.ws, self.cmd, helpers_ready=True)
        # A6 measured 10,653 per launch. The probe line + launch guard + one helper call remain.
        self.assertLess(len(plan.script), A6_LAUNCH_ARGS // 2, len(plan.script))
        self.assertNotIn(wsview.SURVEY_OPEN, plan.script)           # no survey program
        self.assertNotIn("time.sleep", plan.script)                # no reader program
        self.assertNotIn("__CRIA_GATE_HELPER_PY__", plan.script)       # no install leg

    def test_the_first_launch_writes_the_helper_once_and_polls_name_it(self):
        plan = _plan(self.ws, self.cmd)
        self.assertIn(".cria-helper-", plan.script)
        calls = _drive(plan, self.ws, self.tmp)
        self.assertTrue(plan.transport_complete)
        self.assertTrue(plan.helpers_ready, "a real envelope proves the helper is on the harness")
        helpers = [n for n in os.listdir(self.tmp) if n.startswith(".cria-helper-")]
        self.assertEqual(helpers, [probegate._helper_name()])
        for call, _ in calls[1:]:
            self.assertLess(len(call), 700, "a poll names the helper, it does not carry it")

    def test_a_whole_gate_cycle_is_a_fraction_of_what_a6_sent(self):
        # What A6 put in Codex's history for ONE already-warm cycle on a ~8 KB gate: a launch
        # (10,653 args) + its first page, then a poll (1,939 args) + its page — the 8.4 KB spool took
        # two 8 KB base64 pages. Here the same-sized evidence, session already holding the helper.
        plan = _plan(self.ws, self.cmd, helpers_ready=True)
        _run(probegate._helper_install_leg(), self.ws, self.tmp)       # an earlier gate wrote it
        calls = _drive(plan, self.ws, self.tmp)
        harness_bytes = sum(len(c) + len(r) for c, r in calls)
        a6_cycle = A6_LAUNCH_ARGS + A6_POLL_ARGS + 2 * 8_700
        self.assertTrue(plan.transport_complete)
        self.assertLess(harness_bytes * 3, a6_cycle, (harness_bytes, a6_cycle))
        self.assertEqual(len(calls), 1, "one gate is one page now, not launch + polls")

    def test_pages_pack_raw_bytes_up_to_the_wire_bound_and_the_gate_still_verifies(self):
        plan = _plan(self.ws, ["cat", str(FIXTURE)])
        calls = _drive(plan, self.ws, self.tmp)
        sizes = [len(r) for _, r in calls]
        self.assertTrue(all(n < 8_500 for n in sizes), sizes)
        data = probegate.transported_result(plan)
        self.assertIn("CsvValidationException", data)
        self.assertEqual(hashlib.sha256(bytes(plan.transport_data)).hexdigest(), plan.transport_sha256)

    def test_incompressible_evidence_still_crosses_in_bounded_pages(self):
        noise = "import hashlib\nfor i in range(1500): print(hashlib.sha256(str(i).encode()).hexdigest())"
        plan = _plan(self.ws, ["python3", "-c", noise])
        calls = _drive(plan, self.ws, self.tmp)
        self.assertGreater(len(calls), 2)
        self.assertTrue(plan.transport_complete)
        for _, result in calls:
            wire = [ln for ln in result.splitlines() if ln.startswith("data\t")]
            if wire:
                self.assertLessEqual(len(base64.b64decode(wire[0][5:])), probegate.TRANSPORT_CHUNK_BYTES)
        self.assertIn(hashlib.sha256(b"1499").hexdigest(), probegate.transported_result(plan))

    def test_a_harness_without_zlib_gets_raw_pages_and_the_same_verified_bytes(self):
        stub = Path(self.tmp) / "nozlib"
        stub.mkdir()
        (stub / "zlib.py").write_text("raise ImportError('no zlib here')\n")
        plan = _plan(self.ws, self.cmd)
        cmd, env = plan.script, {"PYTHONPATH": str(stub)}
        result = _run(cmd, self.ws, self.tmp, env)
        self.assertIn("enc\traw", result)
        self.assertEqual(probegate.ingest_transport(plan, result), "pending")
        while True:
            result = _run(probegate.continue_transport_command(plan), self.ws, self.tmp, env)
            state = probegate.ingest_transport(plan, result)
            if state != "pending":
                break
        self.assertEqual(state, "complete")
        self.assertIn("CsvValidationException", probegate.transported_result(plan))


class AVanishedHelperIsUnknownNeverCleanTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.ws, True)
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def test_a_poll_after_the_helper_was_deleted_is_terminal_unknown(self):
        noise = "import hashlib\nfor i in range(1500): print(hashlib.sha256(str(i).encode()).hexdigest())"
        plan = _plan(self.ws, ["python3", "-c", noise])
        first = _run(plan.script, self.ws, self.tmp)
        self.assertEqual(probegate.ingest_transport(plan, first), "pending")
        os.unlink(os.path.join(self.tmp, probegate._helper_name()))        # the harness cleaned its tmp
        poll = _run(probegate.continue_transport_command(plan), self.ws, self.tmp)
        self.assertIn("helper-gone", poll)
        self.assertEqual(probegate.ingest_transport(plan, poll), "unknown")
        self.assertIn("helper", plan.transport_error)
        self.assertFalse(plan.transport_complete)
        self.assertEqual(probegate.transported_result(plan), "")
        outcome = probegate.interpret_gate(plan, poll)
        self.assertTrue(outcome.transport_unknown)
        self.assertFalse(outcome.ran)
        self.assertTrue(probegate.gate_is_partial(outcome))

    def test_a_launch_composed_for_a_helper_that_is_not_there_is_unknown(self):
        plan = _plan(self.ws, ["cat", str(FIXTURE)], helpers_ready=True)   # session believed it was there
        result = _run(plan.script, self.ws, self.tmp)                      # ...but nothing was installed
        self.assertIn("helper-gone", result)
        self.assertEqual(probegate.ingest_transport(plan, result), "unknown")
        self.assertFalse(plan.helpers_ready)
        self.assertFalse(probegate.interpret_gate(plan, result).ran)

    def test_the_session_reinstalls_for_its_next_gate(self):
        gs = loop.GuardState(gate_helpers_ready=True)
        shell = {"type": "function", "function": {"name": "exec_command", "parameters": {
            "type": "object", "properties": {"cmd": {"type": "string"}}}}}
        call = loop.guard_gate_op(gs, {"messages": [], "tools": [shell]}, mock.Mock(),
                                  workspace_root=self.ws)
        self.assertNotIn("<<'__CRIA_GATE_HELPER_PY__'", json.loads(call["function"]["arguments"])["cmd"])
        gone = probegate._transport_marker(gs.gate_plan.transport_id)
        end = probegate._transport_marker(gs.gate_plan.transport_id, end=True)
        body = {"messages": [{"role": "tool", "tool_call_id": gs.probe_call_id or "x",
                              "content": f"{gone}\nhelper-gone\t1\n{end}\n"}], "tools": [shell]}
        self.assertIsNone(loop.guard_gate_transport(gs, body, _Rlog(), call_id=gs.probe_call_id or "x"))
        self.assertFalse(gs.gate_helpers_ready)
        again = loop.guard_gate_op(gs, {"messages": [], "tools": [shell]}, mock.Mock(),
                                   workspace_root=self.ws)
        self.assertIn("os.replace", json.loads(again["function"]["arguments"])["cmd"])


class PageDecodingIsBoundedTests(unittest.TestCase):
    def _plan(self):
        plan = probegate.GatePlan(workspace="", transport_required=True)
        return plan

    def _page(self, plan, raw: bytes, wire: bytes, enc: str, total: int | None = None) -> str:
        path = "/tmp/.cria-gate-" + plan.transport_id + ".spool"
        fields = [("path", base64.b64encode(path.encode()).decode()), ("offset", "0"),
                  ("total", str(len(raw) if total is None else total)),
                  ("sha256", hashlib.sha256(raw).hexdigest()), ("enc", enc),
                  ("data", base64.b64encode(wire).decode())]
        body = "\n".join(f"{k}\t{v}" for k, v in fields)
        return (f"{probegate._transport_marker(plan.transport_id)}\n{body}\n"
                f"{probegate._transport_marker(plan.transport_id, end=True)}\n")

    def test_a_zlib_page_round_trips(self):
        plan = self._plan()
        raw = b"line of output\n" * 3000
        self.assertEqual(probegate.ingest_transport(
            plan, self._page(plan, raw, zlib.compress(raw), "zlib")), "complete")
        self.assertEqual(bytes(plan.transport_data), raw)

    def test_a_decompression_bomb_is_unknown(self):
        plan = self._plan()
        raw = b"\0" * (probegate.TRANSPORT_RAW_PAGE_MAX * 20)
        wire = zlib.compress(raw)
        self.assertLessEqual(len(wire), probegate.TRANSPORT_CHUNK_BYTES)
        self.assertEqual(probegate.ingest_transport(plan, self._page(plan, raw, wire, "zlib")), "unknown")

    def test_trailing_bytes_after_the_stream_are_unknown(self):
        plan = self._plan()
        raw = b"abc" * 50
        self.assertEqual(probegate.ingest_transport(
            plan, self._page(plan, raw, zlib.compress(raw) + b"extra", "zlib")), "unknown")

    def test_an_unknown_encoding_is_unknown(self):
        plan = self._plan()
        self.assertEqual(probegate.ingest_transport(
            plan, self._page(plan, b"abc", b"abc", "lz4")), "unknown")

    def test_the_hash_is_over_the_raw_bytes_not_the_wire(self):
        plan = self._plan()
        raw = b"abc" * 50
        page = self._page(plan, raw, zlib.compress(raw), "zlib").replace(
            hashlib.sha256(raw).hexdigest(), hashlib.sha256(zlib.compress(raw)).hexdigest())
        self.assertEqual(probegate.ingest_transport(plan, page), "unknown")


class TheShortCallsStayCriasOwnTests(unittest.TestCase):
    def test_the_sentinel_still_strips_a_helper_call_down_to_the_probes(self):
        ws = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, ws, True)
        plan = _plan(ws, ["make", "check"], helpers_ready=True)
        self.assertEqual(probegate._strip_gate_plumbing(plan.script), "make check")
        poll = probegate.GatePlan(workspace="", transport_required=True, transport_path="/tmp/x",
                                  helpers_ready=True)
        poll.transport_id = plan.transport_id
        self.assertIn(probegate.GATE_SENTINEL, probegate.continue_transport_command(poll))

    def test_the_helper_text_is_identical_in_every_render(self):
        a = probegate._helper_source()
        wsview._BODY_MISSES["other-session"] = ["pom.xml"]
        self.addCleanup(wsview._BODY_MISSES.pop, "other-session", None)
        self.assertEqual(a, probegate._helper_source())
        self.assertTrue(a.endswith("\n"))
        compile(a, "helper", "exec")

    def test_the_survey_asks_through_its_argument_and_gets_the_same_answer(self):
        ws = tempfile.mkdtemp()
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, ws, True)
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        Path(ws, "pom.xml").write_text("<project/>")
        Path(ws, "a.txt").write_text("x")
        sess = "n1-survey"
        wsview._BODY_MISSES[sess] = ["pom.xml"]
        self.addCleanup(wsview._BODY_MISSES.pop, sess, None)
        helper_cmd = probegate._helper_install_leg() + wsview.survey_command(
            sess, cd=ws, helper=probegate.helper_path_expr())
        out_helper = _run(helper_cmd, ws, tmp)
        wsview._BODY_MISSES[sess] = ["pom.xml"]
        out_inline = _run(wsview.survey_command(sess, cd=ws), ws, tmp)
        self.assertIn(base64.b64encode(b"<project/>").decode(), out_helper)
        norm = lambda t: [ln for ln in t.splitlines() if not ln.startswith(("F\t", "root\t"))]  # noqa: E731
        self.assertEqual(norm(out_helper), norm(out_inline))


if __name__ == "__main__":
    unittest.main()
