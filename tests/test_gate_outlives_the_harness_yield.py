"""C28: the completion gate must observe a check that outlives the harness exec yield.

Capture-proven (`docs/goals/nemotron-l5-75-loop-report.md`, "Candidate C28"): P18 Orders, session
`20260924T023334-01a0d2c3-618e-7c41-b2b8-d99642fe1fdc`, raw inbound
`inbound-ce7f6c3d-responses.json`. The coder's integration test hung forever; cria's composed gate
`exec_command` asked for `yield_time_ms: 300000` and Codex answered (call `call_4b4fca253d184e38`,
verbatim):

    Chunk ID: 34454d
    Wall time: 30.0008 seconds
    Process running with session ID 51757
    Original token count: 0
    Output:

— no transport opener at all. Before this fix, `probegate.ingest_transport` treated ANY missing
opener as immediately terminal (`fail_transport("transport page opener did not arrive")`), so
`guard_gate_transport` gave up and the coder only ever saw `probe_transport_unknown.txt` (UNKNOWN).
28 of 29 gates in that session were `gate.transport_unknown`. The composed script's own
`timeout -k 5 240` would have produced exit 124 plus the partial pytest output, which
`interpret_gate` already renders as a timed-out check with real output — that byte stream just
never reached cria, because nothing polled the still-running script across turns.

This file proves: (1) the exact captured shape is now retried instead of terminal, (2) it converges
on the SAME timed-out rendering the gate already knows how to produce once the check actually
finishes, (3) a cria-side deadline (derived from the plan's own probe timeouts) still fails closed,
(4) only the "no opener" failure is softened — every other malformed/cut/hash/offset check stays
exactly as strict, (5) a fast gate is unchanged, (6) the launch really does return promptly while a
slow probe keeps running detached (real subprocess), and (7) a running poll is wire-cleaned like any
other gate transport call.
"""
import base64
import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from cria import loop, probegate, shelltool
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind

# Verbatim from inbound-ce7f6c3d-responses.json, function_call_output for call_4b4fca253d184e38
# (session 01a0d2c3...): the composed gate's own exec_command, cut by the harness's exec yield
# before the transport reader printed a single byte of its envelope.
P18_LAUNCH_NO_OPENER = (
    "Chunk ID: 34454d\n"
    "Wall time: 30.0008 seconds\n"
    "Process running with session ID 51757\n"
    "Original token count: 0\n"
    "Output:\n"
)


def _plan(deadline_s: float = 600.0) -> probegate.GatePlan:
    plan = probegate.GatePlan(workspace="/ws", transport_required=True)
    plan.transport_deadline_s = deadline_s
    return plan


def _running_envelope(plan: probegate.GatePlan, elapsed: str = "12.3", *, path: str = "") -> str:
    """C28b: the reader's own typed `running` envelope now also carries the resolved spool path
    (defaults to this plan's OWN expected spool name; pass ``path=`` to simulate a foreign one)."""
    spool_path = path or f"/tmp/.cria-gate-{plan.transport_id}.spool"
    return "\n".join([
        probegate._transport_marker(plan.transport_id),
        "path\t" + base64.b64encode(spool_path.encode()).decode(),
        f"running\t{elapsed}",
        probegate._transport_marker(plan.transport_id, end=True),
    ])


def _page(plan: probegate.GatePlan, body: str, *, offset: int = 0) -> str:
    payload = body.encode()
    return "\n".join([
        probegate._transport_marker(plan.transport_id),
        "path\t" + base64.b64encode(f"/tmp/.cria-gate-{plan.transport_id}.spool".encode()).decode(),
        "offset\t" + str(offset),
        "total\t" + str(len(payload)),
        "sha256\t" + hashlib.sha256(payload).hexdigest(),
        "data\t" + base64.b64encode(payload[offset:]).decode(),
        probegate._transport_marker(plan.transport_id, end=True),
    ])


_TIMED_OUT_GATE_BODY = (
    f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\nEXIT:0\n"
    f"{probegate.SECTION_PREFIX}probe-1{probegate.SECTION_SUFFIX}\n"
    "..\ntests/test_orders_integration.py::test_polls_forever\nEXIT:124\n"
)


class CaptureShapedFailsBeforePassesAfterTests(unittest.TestCase):
    """The exact P18 harness shape, replayed against `ingest_transport` before and after C28."""

    def test_the_capture_shows_no_opener_at_all(self):
        plan = _plan()
        opening = probegate._transport_marker(plan.transport_id)
        self.assertNotIn(opening, P18_LAUNCH_NO_OPENER)

    def test_before_the_fix_this_shape_was_terminal_unknown(self):
        """Reproduces the pre-C28 body of `ingest_transport`: a missing opener was UNCONDITIONALLY
        `fail_transport(...)`, with no notion of a plan-wide deadline to retry against."""
        plan = _plan()
        opening = probegate._transport_marker(plan.transport_id)

        def legacy_ingest(text: str) -> str:
            if opening not in text:
                return probegate.fail_transport(plan, "transport page opener did not arrive")
            raise AssertionError("legacy fixture: opener unexpectedly present")

        self.assertEqual(legacy_ingest(P18_LAUNCH_NO_OPENER), "unknown")
        self.assertTrue(plan.transport_error)
        self.assertTrue(plan.transport_complete is False)

    def test_after_the_fix_the_same_shape_is_retried_not_terminal(self):
        plan = _plan()
        state = probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER)
        self.assertEqual(state, "running")
        self.assertEqual(plan.transport_error, "")
        self.assertFalse(plan.transport_complete)
        # Non-terminal all the way up through interpret_gate/GateOutcome too.
        outcome = probegate.interpret_gate(plan, P18_LAUNCH_NO_OPENER)
        self.assertFalse(outcome.ran)
        self.assertTrue(outcome.transport_pending)
        self.assertFalse(outcome.transport_unknown)

    def test_it_converges_on_the_existing_timed_out_rendering_with_real_output(self):
        """launch (silent) -> a typed running poll -> the composed timeout firing with partial
        pytest output -> the SAME rendering `interpret_gate` already produces for a timed-out check."""
        plan = _plan()
        self.assertEqual(probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER), "running")
        self.assertEqual(probegate.ingest_transport(plan, _running_envelope(plan)), "running")
        page = _page(plan, _TIMED_OUT_GATE_BODY)
        self.assertEqual(probegate.ingest_transport(plan, page), "complete")

        rendered = probegate.clean_gate_output(probegate.transported_result(plan))
        self.assertIn("did not finish (timed out)", rendered)
        self.assertIn("tests/test_orders_integration.py::test_polls_forever", rendered)
        self.assertNotIn("fix", rendered.lower())   # not a pass, not a fix demand — cria's own words


class DeadlineExhaustionTests(unittest.TestCase):
    def test_total_silence_past_the_deadline_is_terminal_unknown(self):
        plan = _plan(deadline_s=5.0)
        plan.transport_started = time.monotonic() - 10.0   # already past the 5s budget
        state = probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER)
        self.assertEqual(state, "unknown")
        self.assertIn("exceeded", plan.transport_error)
        outcome = probegate.interpret_gate(plan, P18_LAUNCH_NO_OPENER)
        self.assertTrue(outcome.transport_unknown)
        self.assertFalse(outcome.ran)

    def test_a_running_envelope_past_the_deadline_is_also_terminal(self):
        plan = _plan(deadline_s=5.0)
        plan.transport_started = time.monotonic() - 10.0
        state = probegate.ingest_transport(plan, _running_envelope(plan, "9.9"))
        self.assertEqual(state, "unknown")

    def test_a_deadline_exceeded_gate_never_reads_clean(self):
        """Fail closed (#13): exhausting the deadline must never be mistaken for a passing check."""
        plan = _plan(deadline_s=1.0)
        plan.transport_started = time.monotonic() - 100.0
        probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER)
        outcome = probegate.interpret_gate(plan, "")
        self.assertFalse(outcome.ran)
        self.assertTrue(outcome.transport_unknown)
        self.assertFalse(probegate.transported_result(plan))

    def test_a_hand_built_plan_with_no_deadline_never_times_out_on_its_own(self):
        """`transport_deadline_s` defaults to 0.0 (hand-built plans, historical replay in
        `clean_gate_results`) — those callers only care whether replay ever reached completion, not
        how long it took, so a running transport is retried forever rather than guessing a bound."""
        plan = probegate.GatePlan(workspace="/ws", transport_required=True)
        plan.transport_started = time.monotonic() - 10_000.0
        self.assertEqual(probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER), "running")


class OnlyTheNoOpenerFailureIsSoftenedTests(unittest.TestCase):
    """Requirement: a poll with no opener while running is retried; every other malformed/cut/
    hash/offset failure stays exactly as strict as before."""

    def test_a_page_cut_before_its_closing_marker_is_still_terminal(self):
        plan = _plan()
        opening = probegate._transport_marker(plan.transport_id)
        cut = opening + "\npath\tAAAA\noffset\t0\n"   # no closing marker at all
        self.assertEqual(probegate.ingest_transport(plan, cut), "unknown")
        self.assertIn("cut before its closing marker", plan.transport_error)

    def test_duplicate_envelope_markers_are_still_terminal(self):
        plan = _plan()
        page = _page(plan, "x")
        doubled = page + "\n" + page
        self.assertEqual(probegate.ingest_transport(plan, doubled), "unknown")
        self.assertIn("duplicate envelope markers", plan.transport_error)

    def test_a_bad_hash_is_still_terminal(self):
        plan = _plan()
        page = _page(plan, "hello world")
        tampered = page.replace(hashlib.sha256(b"hello world").hexdigest(), "0" * 64)
        self.assertEqual(probegate.ingest_transport(plan, tampered), "unknown")

    def test_an_offset_regression_is_still_terminal(self):
        plan3 = _plan()
        spool = f"/tmp/.cria-gate-{plan3.transport_id}.spool".encode()
        wrong_offset_page = "\n".join([
            probegate._transport_marker(plan3.transport_id),
            "path\t" + base64.b64encode(spool).decode(),
            "offset\t5",     # cria has received 0 bytes so far — offset must be 0
            "total\t10",
            "sha256\t" + hashlib.sha256(b"01234").hexdigest(),
            "data\t" + base64.b64encode(b"01234").decode(),
            probegate._transport_marker(plan3.transport_id, end=True),
        ])
        self.assertEqual(probegate.ingest_transport(plan3, wrong_offset_page), "unknown")
        self.assertIn("inconsistent", plan3.transport_error)


def _test_candidate() -> ProbeCandidate:
    return ProbeCandidate(
        kind=ProbeKind.Test, command=["python3", "-c", "print('ok')"],
        working_dir=tempfile.gettempdir(), confidence=90, expected_value=80,
        cost=ProbeCost.Cheap, mutates_code=False, may_hang=False, may_need_services=False,
        reason="test",
    )


class FastGateIsUnchangedTests(unittest.TestCase):
    """Bonsai-2 regression bar: a gate that finishes within the first wait must produce the same
    number of harness turns and the same interpreted result as before C28."""

    def test_a_fast_real_gate_completes_in_one_turn(self):
        with tempfile.TemporaryDirectory() as ws:
            with open(os.path.join(ws, "x.py"), "w") as f:
                f.write("print(1)\n")
            plan = probegate.plan_gate(ws)
            proc = subprocess.run(["bash", "-c", plan.script], capture_output=True, text=True,
                                  timeout=60)
            state = probegate.ingest_transport(plan, proc.stdout)
            self.assertEqual(state, "complete", proc.stdout)
            out = probegate.interpret_gate(plan, proc.stdout)
            self.assertTrue(out.ran)
            # No continuation is needed — same one-turn shape as before C28.
            self.assertEqual(probegate.continue_transport_command(plan), "")

    def test_guard_gate_transport_asks_for_nothing_more_once_complete(self):
        plan = _plan()
        page = _page(plan, f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\nEXIT:0\n")
        gs = mock.Mock()
        gs.gate_plan = plan
        gs.probe_call_id = "call_x"
        body = {
            "messages": [{"role": "tool", "tool_call_id": "call_x", "content": page}],
            "tools": [{"type": "function", "function": {"name": "shell", "parameters": {}}}],
        }
        rlog = mock.Mock()
        result = loop.guard_gate_transport(gs, body, rlog)
        self.assertIsNone(result)   # complete — no extra turn requested


class RealShellDetachmentTests(unittest.TestCase):
    """The launch really does return promptly while a slow probe keeps running detached, and a
    later read observes `running` then `complete` — proven against a real subprocess, not a
    simulated envelope."""

    def setUp(self):
        self._ws = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._ws, ignore_errors=True)

    def _slow_plan(self, sleep_s: float, poll_wait_s: float):
        candidate = ProbeCandidate(
            kind=ProbeKind.Test, command=["sh", "-c", f"sleep {sleep_s}; echo done"],
            working_dir=self._ws, confidence=90, expected_value=80,
            cost=ProbeCost.Cheap, mutates_code=False, may_hang=False, may_need_services=False,
            reason="test",
        )
        with mock.patch.object(probegate.proberun, "select_completion_probes",
                               return_value=[candidate]):
            plan = probegate.plan_gate(self._ws)
        # Shrink the poll wait so the test doesn't need to wait out the real GATE_POLL_WAIT_S.
        plan.script = plan.script.replace(f"time.monotonic() + {probegate.GATE_POLL_WAIT_S!r}",
                                          f"time.monotonic() + {poll_wait_s!r}")
        return plan

    def test_launch_returns_promptly_and_a_later_read_sees_running_then_complete(self):
        plan = self._slow_plan(sleep_s=2.0, poll_wait_s=0.3)
        start = time.monotonic()
        launch = subprocess.run(["bash", "-c", plan.script], capture_output=True, text=True,
                                timeout=30)
        launch_elapsed = time.monotonic() - start
        self.assertLess(launch_elapsed, 2.0, "the launch call must return before the probe finishes")
        state = probegate.ingest_transport(plan, launch.stdout)
        self.assertEqual(state, "running", launch.stdout)

        # C28b: the real reader's own `running` envelope carries the resolved spool path, so ONE
        # running reply is enough to switch every later poll to the narrow offset-0 re-read —
        # never the whole multi-KB launch script again (the P24 wedge: ~12 full-script polls before
        # a compaction dropped them all).
        self.assertTrue(plan.transport_path, "the real running envelope must have taught cria the path")
        cmd = probegate.continue_transport_command(plan)
        self.assertTrue(cmd)
        self.assertNotIn("__CRIA_GATE_BODY__", cmd,
                         "a poll after the first running reply must never resend the launch script")
        again = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30)
        # By now up to ~0.9s have elapsed since the probe started; it may or may not be done yet —
        # either state is a legitimate transport outcome, but it must not be terminal.
        state2 = probegate.ingest_transport(plan, again.stdout)
        self.assertIn(state2, ("running", "pending", "complete"))

        # Wait out the probe for real, then read to completion.
        deadline = time.monotonic() + 15
        while not plan.transport_complete and time.monotonic() < deadline:
            cmd = probegate.continue_transport_command(plan)
            self.assertTrue(cmd)
            page = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30)
            state2 = probegate.ingest_transport(plan, page.stdout)
            self.assertNotEqual(state2, "unknown", page.stdout)
            if state2 == "complete":
                break
        self.assertTrue(plan.transport_complete, "the detached probe never reported completion")
        self.assertIn("done", probegate.transported_result(plan))

        # Reviewer 6510f2dd follow-up: the reader no longer self-deletes on the final read (a
        # lost-and-repolled final page must be able to re-read the SAME bytes) — the spool and its
        # `.done` marker persist until the NEXT gate's launch leg reclaims them.
        self.assertTrue(os.path.exists(plan.transport_path))
        self.assertTrue(os.path.exists(plan.transport_path + ".done"))
        self.assertEqual(probegate._SPOOL_CLEANUP_QUEUE.get(self._ws), [plan.transport_path])
        os.unlink(plan.transport_path)
        os.unlink(plan.transport_path + ".done")
        probegate._SPOOL_CLEANUP_QUEUE.pop(self._ws, None)


class WireCleaningTests(unittest.TestCase):
    """A running-poll call/result pair is cleaned from the coder-bound body like any other gate
    transport call — it carries the same `# ⟦ctx:gate⟧…` provenance stamp."""

    def test_a_running_poll_result_is_recognised_and_dropped_pending_completion(self):
        with tempfile.TemporaryDirectory() as ws:
            plan = probegate.plan_gate(ws)
        launch_cmd = plan.script
        self.assertTrue(launch_cmd.lstrip().startswith("# " + probegate.GATE_SENTINEL))
        running_result = _running_envelope(plan)
        messages = [
            {"role": "assistant", "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "shell", "arguments": __import__("json").dumps({"cmd": launch_cmd})}},
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": running_result},
        ]
        cleaned = probegate.clean_gate_results(messages, plan)
        # The raw running envelope (cria's own transport plumbing) must never reach the model.
        joined = __import__("json").dumps(cleaned)
        self.assertNotIn(probegate.TRANSPORT_PREFIX, joined)
        self.assertNotIn("running\\t12.3", joined)

    def test_a_running_poll_then_a_completed_page_renders_once_as_the_real_result(self):
        with tempfile.TemporaryDirectory() as ws:
            plan = probegate.plan_gate(ws)
        launch_cmd = plan.script
        running_result = _running_envelope(plan)
        page = _page(plan, f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\nEXIT:0\n")
        # `clean_gate_results` uses the LIVE `plan` state directly for its own current transport id
        # (the running bridge already consumed these pages by the time cleaning ever runs) — so
        # advance it exactly as `loop.guard_gate_transport` would have, turn by turn.
        self.assertEqual(probegate.ingest_transport(plan, running_result), "running")
        self.assertEqual(probegate.ingest_transport(plan, page), "complete")
        import json as _json
        messages = [
            {"role": "assistant", "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "shell", "arguments": _json.dumps({"cmd": launch_cmd})}},
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": running_result},
            {"role": "assistant", "tool_calls": [
                {"id": "call_2", "type": "function",
                 "function": {"name": "shell",
                             "arguments": _json.dumps({"cmd": probegate._gate_sentinel([])})}},
            ]},
            {"role": "tool", "tool_call_id": "call_2", "content": page},
        ]
        cleaned = probegate.clean_gate_results(messages, plan)
        joined = " ".join(_json.dumps(m) for m in cleaned)
        # No raw plumbing anywhere, and the clean summary landed exactly once.
        self.assertNotIn(probegate.SECTION_PREFIX, joined)
        self.assertNotIn(probegate.TRANSPORT_PREFIX, joined)
        self.assertEqual(joined.count("no error-class problems"), 1)


class ConsecutiveOpenerlessBoundTests(unittest.TestCase):
    """Supervisor review: the reader always answers within GATE_POLL_WAIT_S — well under the
    harness's own yield — so a genuinely OPENERLESS result (not even the reader's own typed
    ``running`` envelope) more than a couple of times in a row means the poll channel itself is
    broken (cut poll, no `python3`, an unrecognised sandbox rejection), not that the check is merely
    slow. That must be bounded far tighter than the multi-minute `transport_deadline_s`, or a broken
    channel wedges the session in ~100 cria-only poll turns before ever saying so.
    """

    def test_a_the_p18_shape_still_converges_within_the_openerless_bound(self):
        """(a) The captured launch (one openerless read) followed by the reader's own typed
        `running` envelopes still converges on the real, complete result — it never needs more
        than one openerless read before a real envelope arrives."""
        plan = _plan()
        self.assertEqual(probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER), "running")
        self.assertEqual(plan.transport_openerless_streak, 1)
        self.assertEqual(probegate.ingest_transport(plan, _running_envelope(plan)), "running")
        self.assertEqual(plan.transport_openerless_streak, 0)   # a real envelope reset it
        page = _page(plan, _TIMED_OUT_GATE_BODY)
        self.assertEqual(probegate.ingest_transport(plan, page), "complete")
        rendered = probegate.clean_gate_output(probegate.transported_result(plan))
        self.assertIn("did not finish (timed out)", rendered)

    def test_b_three_consecutive_openerless_reads_are_terminal_promptly(self):
        """(b) Even with a deadline far in the future, three consecutive openerless reads — the
        poll itself failing, not the check merely running long — end the transport terminally."""
        plan = _plan(deadline_s=100_000.0)      # deadline nowhere near exhausted
        self.assertEqual(probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER), "running")
        self.assertEqual(probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER), "running")
        self.assertLessEqual(plan.transport_openerless_streak, probegate.GATE_OPENERLESS_MAX)
        state = probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER)
        self.assertEqual(state, "unknown")
        self.assertIn("repeatedly", plan.transport_error)
        outcome = probegate.interpret_gate(plan, P18_LAUNCH_NO_OPENER)
        self.assertTrue(outcome.transport_unknown)
        self.assertFalse(outcome.ran)
        self.assertFalse(probegate.transported_result(plan))     # never a clean result

    def test_c_a_real_envelope_between_openerless_reads_resets_the_counter(self):
        """(c) openerless, running, openerless, running, … never trips — each real envelope
        (the reader's own typed `running`, or a page) proves the poll channel still works."""
        plan = _plan()
        for _ in range(5):
            self.assertEqual(probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER), "running")
            self.assertEqual(plan.transport_openerless_streak, 1)
            self.assertEqual(probegate.ingest_transport(plan, _running_envelope(plan)), "running")
            self.assertEqual(plan.transport_openerless_streak, 0)
        self.assertEqual(plan.transport_error, "")
        self.assertFalse(plan.transport_complete)

    def test_a_real_page_also_resets_the_streak(self):
        plan = _plan()
        self.assertEqual(probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER), "running")
        self.assertEqual(plan.transport_openerless_streak, 1)
        page = _page(plan, f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\nEXIT:0\n")
        self.assertEqual(probegate.ingest_transport(plan, page), "complete")
        self.assertEqual(plan.transport_openerless_streak, 0)


class DetachedInterpreterPreferenceTests(unittest.TestCase):
    """Supervisor review: the detached block ran inline in the HARNESS's own shell before C28
    (Codex's exec tool is `bash -lc`); detaching into a bare POSIX `sh` (dash, on Debian/Ubuntu)
    would silently swap the interpreter under commands that only worked under bash. The launch must
    prefer `bash` when it is on PATH, falling back to `sh`, independently of the `setsid` guard.
    """

    def test_the_launch_prefers_bash_when_available(self):
        with tempfile.TemporaryDirectory() as ws:
            plan = probegate.plan_gate(ws)
        self.assertIn('command -v bash', plan.script)
        self.assertIn('__cria_gate_sh="bash"', plan.script)
        self.assertIn('__cria_gate_sh="sh"', plan.script)     # the fallback still exists
        self.assertIn('__cria_gate_run="setsid $__cria_gate_sh"', plan.script)
        self.assertIn('__cria_gate_run="$__cria_gate_sh"', plan.script)

    def test_real_shell_selects_bash_when_on_path(self):
        """Mechanical proof against a real shell, not just a text assertion on the composed script."""
        probe = (
            'if command -v bash >/dev/null 2>&1; then __cria_gate_sh="bash"; '
            'else __cria_gate_sh="sh"; fi\n'
            'echo "CHOSE=$__cria_gate_sh"'
        )
        out = subprocess.run(["bash", "-c", probe], capture_output=True, text=True, timeout=10)
        self.assertIn("CHOSE=bash", out.stdout)


class NoUnexportedLauncherVariableTests(unittest.TestCase):
    """Supervisor review audit: the composed probe body now runs in a SEPARATE `bash`/`sh` PROCESS
    (the detached block), so any shell VARIABLE assigned in the outer launcher (not exported, and
    the outer launcher never exports anything) is invisible to it — only real environment
    variables (PATH, HOME, TMPDIR, …) cross that boundary. Every value the body needs (the
    workspace path, the transport id's markers, per-probe exit codes) must be either a literal baked
    into the composed text or a variable the body itself assigns and reads, never a reference to
    something only the launcher defined.
    """

    def _cmd_file_body(self, plan: probegate.GatePlan) -> str:
        script = plan.script
        start = script.index("<<'__CRIA_GATE_BODY__'") + len("<<'__CRIA_GATE_BODY__'")
        end = script.index("\n__CRIA_GATE_BODY__\n", start)
        return script[start:end].lstrip("\n")

    def test_the_launcher_defines_no_variable_the_body_reads(self):
        """The two launcher-only variables (`__cria_gate_file`, `__cria_gate_cmd`) are never
        referenced inside the body — the body is self-contained, so running it as a separate
        process changes nothing it depends on."""
        with tempfile.TemporaryDirectory() as ws:
            with open(os.path.join(ws, "x.py"), "w") as f:
                f.write("print(1)\n")
            plan = probegate.plan_gate(ws)
        body = self._cmd_file_body(plan)
        self.assertNotIn("__cria_gate_file", body)
        self.assertNotIn("__cria_gate_cmd", body)
        self.assertNotIn("__cria_gate_run", body)
        self.assertNotIn("__cria_gate_sh", body)

    def test_the_body_runs_standalone_under_set_dash_u(self):
        """Mechanical audit: `set -u` makes bash fail loudly on ANY variable reference that was
        never assigned. Running the extracted body standalone (no launcher context at all) under
        `set -u` proves every variable it touches is either assigned within itself or a real
        exported/environment value (`TMPDIR`, `PATH`, …) — never a launcher-only local."""
        with tempfile.TemporaryDirectory() as ws:
            with open(os.path.join(ws, "x.py"), "w") as f:
                f.write("print(1)\n")
            plan = probegate.plan_gate(ws)
        body = self._cmd_file_body(plan)
        proc = subprocess.run(["bash", "-c", "set -u\n" + body], capture_output=True, text=True,
                              timeout=30)
        self.assertNotIn("unbound variable", proc.stderr,
                         f"stdout={proc.stdout!r} stderr={proc.stderr!r}")


def _launch_script(spool: str, cmd_file: str, body_lines: list, guard_lines: list, tid: str,
                  wait_s: float) -> str:
    """A minimal standalone launch+read script, decoupled from real probe composition, for
    exercising `_gate_launch_guard`'s process-survival contract in isolation."""
    return "\n".join([
        f'__cria_gate_file="{spool}"',
        f'__cria_gate_cmd="{cmd_file}"',
        *guard_lines,
        probegate._transport_reader(f'"{spool}"', 0, tid, wait_s=wait_s),
    ])


def _pre_fix_launch_guard(spool_arg: str, cmd_arg: str, parts: list) -> list:
    """The EXACT pre-repair shape of `probegate._gate_launch_guard` (reconstructed from git history,
    commit 161169a4): `setsid` covers only the probe invocation, and the surrounding `( … ) &`
    subshell that writes `.done` and unlinks the cmd file afterward stays in the CALLER's own process
    group — it is what a harness reaping that group the instant the exec call returns (Codex 0.156,
    reviewer's `/tmp/c28rev/sim.py`) kills before the marker is ever written."""
    body = "\n".join(parts) if parts else ":"
    tag = "__CRIA_GATE_BODY__"
    return [
        f"if [ ! -e {spool_arg} ] && [ ! -e {spool_arg}.done ]; then",
        f": > {spool_arg} || exit 98",
        f"cat > {cmd_arg} <<'{tag}'",
        body,
        tag,
        'if command -v bash >/dev/null 2>&1; then __cria_gate_sh="bash"; '
        'else __cria_gate_sh="sh"; fi',
        'if command -v setsid >/dev/null 2>&1; then __cria_gate_run="setsid $__cria_gate_sh"; '
        'else __cria_gate_run="$__cria_gate_sh"; fi',
        f'( $__cria_gate_run {cmd_arg} </dev/null >{spool_arg} 2>&1',
        f': > {spool_arg}.done',
        f'python3 -c "import os, sys; os.unlink(sys.argv[1])" {cmd_arg} >/dev/null 2>&1',
        f') </dev/null >/dev/null 2>&1 &',
        "disown 2>/dev/null || true",
        "fi",
    ]


class ProcessGroupKillSurvivalTests(unittest.TestCase):
    """Supervisor-reproduced BLOCKING regression: the first shape of `_gate_launch_guard` detached
    only the probe invocation via `setsid`; the `( … ) &` wrapper that then wrote `.done` and
    unlinked the cmd file stayed a member of the HARNESS's own process group and was killed the
    instant the harness reaped it after the exec call returned — reproduced live on Codex 0.156
    (`codex exec --yolo` against a fake Responses server, reviewer's `/tmp/c28rev/sim.py` `killpg`
    and `pty` modes): the spool filled with the probe's real output but `.done` never appeared and
    the cmd file was never removed, so a gate that used to finish INLINE within the old harness yield
    instead polled all the way to `transport_deadline_s` and ended terminal UNKNOWN — P18 stayed
    UNKNOWN live. Fixed by making run+mark-done+cleanup ONE command that `setsid` (or its fallback)
    covers in full."""

    def setUp(self):
        self.tid = probegate.GatePlan(workspace="").transport_id  # a fresh, real 24-hex token
        tmp = tempfile.gettempdir()
        self.spool = f"{tmp}/.cria-gate-{self.tid}.spool"
        self.done = self.spool + ".done"
        self.cmd_file = f"{tmp}/.cria-gate-{self.tid}-cmd.sh"

    def tearDown(self):
        for p in (self.spool, self.done, self.cmd_file):
            try:
                os.unlink(p)
            except OSError:
                pass

    def _killpg_run(self, script: str, timeout: float = 30) -> str:
        p = subprocess.Popen(["bash", "-c", script], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, start_new_session=True, text=True)
        out, _ = p.communicate(timeout=timeout)
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return out

    def test_before_the_fix_killpg_right_after_launch_loses_the_done_marker(self):
        """Fails-before: with the PRE-repair guard, killing the launcher's own process group the
        instant it returns (simulating the harness reaping the exec call) leaves the probe's real
        output in the spool but NO `.done` marker, ever — the exact regression reproduced live."""
        script = _launch_script(
            self.spool, self.cmd_file, ["sleep 2", "echo PROBEDONE"],
            _pre_fix_launch_guard(f'"{self.spool}"', f'"{self.cmd_file}"', ["sleep 2", "echo PROBEDONE"]),
            self.tid, wait_s=0.3)
        self._killpg_run(script)
        time.sleep(3.0)      # long enough for the (killed-group-orphaned or not) probe to finish
        self.assertFalse(os.path.exists(self.done),
                         "pre-fix: the .done marker must be lost when the wrapper subshell is killed")

    def test_after_the_fix_killpg_right_after_launch_still_reaches_done(self):
        """Passes-after: same kill, same timing, the CURRENT `_gate_launch_guard` — run, mark done,
        and clean up the cmd file are now ONE command `setsid` covers end to end, so the marker and
        the cleanup both survive the group kill."""
        guard = probegate._gate_launch_guard(f'"{self.spool}"', f'"{self.cmd_file}"',
                                             ["sleep 2", "echo PROBEDONE"])
        script = _launch_script(self.spool, self.cmd_file, ["sleep 2", "echo PROBEDONE"], guard,
                                self.tid, wait_s=0.3)
        self._killpg_run(script)
        deadline = time.monotonic() + 8.0
        while not os.path.exists(self.done) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertTrue(os.path.exists(self.done),
                        "the .done marker must survive the launcher's process group being killed")
        self.assertIn("PROBEDONE", open(self.spool).read())
        # The cmd file cleans itself up (its own `os.unlink`, inside the same detached command).
        deadline = time.monotonic() + 3.0
        while os.path.exists(self.cmd_file) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertFalse(os.path.exists(self.cmd_file), "the cmd file must clean itself up too")

    def test_pty_mode_variant(self):
        """The same survival property when the launcher is attached to a PTY that is closed the
        instant the foreground read returns — another shape the harness's own exec plumbing can
        take (reviewer's `sim.py` `pty` mode)."""
        import pty
        guard = probegate._gate_launch_guard(f'"{self.spool}"', f'"{self.cmd_file}"',
                                             ["sleep 2", "echo PROBEDONE"])
        script = _launch_script(self.spool, self.cmd_file, ["sleep 2", "echo PROBEDONE"], guard,
                                self.tid, wait_s=0.3)
        try:
            pid, fd = pty.fork()
        except OSError:
            self.skipTest("pty allocation unavailable in this environment")
        if pid == 0:
            os.execvp("bash", ["bash", "-c", script])
            os._exit(127)
        try:
            out = b""
            while True:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
            os.waitpid(pid, 0)
        finally:
            os.close(fd)
        deadline = time.monotonic() + 8.0
        while not os.path.exists(self.done) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertTrue(os.path.exists(self.done),
                        f"the .done marker must survive PTY teardown; launcher said: {out!r}")


class SpoolPermissionsTests(unittest.TestCase):
    """The spool is a DETERMINISTIC name now (C28), not `mktemp`'s own owner-only-by-default file —
    `umask 077` in the launch leg restores that same owner-only guarantee for both the spool (the
    coder's own check output) and the cmd file (the composed probe commands)."""

    def test_the_launch_leg_sets_a_restrictive_umask(self):
        with tempfile.TemporaryDirectory() as ws:
            plan = probegate.plan_gate(ws)
        self.assertIn("umask 077", plan.script)

    def test_a_real_launch_creates_owner_only_files(self):
        """Stat the files WHILE the probe is still running (a slow probe, a short poll wait),
        before the final-page read can race in and unlink them."""
        tid = probegate.GatePlan(workspace="").transport_id
        tmp = tempfile.gettempdir()
        spool, cmd_file = f"{tmp}/.cria-gate-{tid}.spool", f"{tmp}/.cria-gate-{tid}-cmd.sh"
        self.addCleanup(lambda: [os.path.exists(p) and os.unlink(p)
                                 for p in (spool, cmd_file, spool + ".done")])
        guard = probegate._gate_launch_guard(f'"{spool}"', f'"{cmd_file}"', ["sleep 2", "echo ok"])
        script = _launch_script(spool, cmd_file, ["sleep 2", "echo ok"], guard, tid, wait_s=0.3)
        subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        self.assertTrue(os.path.exists(spool), "the spool must exist while the probe is still running")
        self.assertEqual(os.stat(spool).st_mode & 0o777, 0o600,
                         "the spool must be owner-only, like mktemp's own default")
        self.assertTrue(os.path.exists(cmd_file), "the cmd file must also still exist mid-flight")
        self.assertEqual(os.stat(cmd_file).st_mode & 0o777, 0o600,
                         "the cmd file must be owner-only too")

    def test_the_umask_is_restored_before_launch_so_probes_see_the_harness_umask(self):
        """Reviewer-reported regression: a bare `umask 077` with no restore LEAKED into the
        detached session and every probe it runs, silently narrowing the mode of every file the
        repo's OWN checks create in the coder's workspace (a probe's own `umask` printed 0077
        instead of the harness's 0022 on real Codex; a check asserting an output file's mode 0644
        went from green to red). Both facts must hold TOGETHER: cria's own two files stay
        owner-only, and the probe still runs under the harness's real umask, unchanged."""
        tid = probegate.GatePlan(workspace="").transport_id
        tmp = tempfile.gettempdir()
        spool, cmd_file = f"{tmp}/.cria-gate-{tid}.spool", f"{tmp}/.cria-gate-{tid}-cmd.sh"
        self.addCleanup(lambda: [os.path.exists(p) and os.unlink(p)
                                 for p in (spool, cmd_file, spool + ".done")])
        body = ["umask", "sleep 1", "echo ok"]
        guard = probegate._gate_launch_guard(f'"{spool}"', f'"{cmd_file}"', body)
        # The LAUNCHING shell's own umask — the harness's umask — is 0022, not cria's narrowed 0077.
        script = "umask 022\n" + _launch_script(spool, cmd_file, body, guard, tid, wait_s=0.3)
        subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        # Mid-flight (the probe is still sleeping): cria's own two files are still owner-only.
        self.assertEqual(os.stat(spool).st_mode & 0o777, 0o600,
                         "the spool must stay owner-only even with the umask restored before launch")
        self.assertEqual(os.stat(cmd_file).st_mode & 0o777, 0o600,
                         "the cmd file must stay owner-only even with the umask restored before launch")
        deadline = time.monotonic() + 8.0
        while not os.path.exists(spool + ".done") and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertTrue(os.path.exists(spool + ".done"), "the probe never finished")
        # ...and the PROBE's own umask matches the LAUNCHING (harness's) shell's 0022 — not the
        # narrowed 0077 that leaked into the detached session before this repair.
        self.assertIn("0022", open(spool).read())


class RunningEnvelopeLearnsThePathTests(unittest.TestCase):
    """C28b (a): the reader's own typed `running` envelope now also carries the resolved spool
    path, validated exactly like a page's own — so ONE running reply is enough for cria to switch
    every later poll to the narrow offset-0 re-read, never resending the whole multi-KB launch
    script again. Live P24 Orders (session 01a0d4fa): ~12 full-script polls (~95s) landed because
    the OLD running envelope carried no path at all."""

    def test_total_silence_then_a_running_reply_teaches_the_path(self):
        plan = _plan()
        plan.script = "echo placeholder-launch-script __CRIA_GATE_BODY__"  # a real plan's own text
        self.assertEqual(probegate.ingest_transport(plan, P18_LAUNCH_NO_OPENER), "running")
        self.assertFalse(plan.transport_path)                     # silence taught nothing
        self.assertIn("__CRIA_GATE_BODY__", probegate.continue_transport_command(plan))

        self.assertEqual(probegate.ingest_transport(plan, _running_envelope(plan)), "running")
        self.assertTrue(plan.transport_path)                      # LEARNED from the running envelope
        narrow = probegate.continue_transport_command(plan)
        self.assertNotIn("__CRIA_GATE_BODY__", narrow)             # narrow read now, never a relaunch
        self.assertIn(plan.transport_id, narrow)

    def test_a_running_envelope_with_a_foreign_path_is_terminal(self):
        plan = _plan()
        foreign = _running_envelope(plan, path="/tmp/.cria-gate-deadbeefdeadbeefdeadbeef.spool")
        self.assertEqual(probegate.ingest_transport(plan, foreign), "unknown")
        self.assertIn("unexpected spool", plan.transport_error)

    def test_a_running_envelope_changing_an_already_learned_path_is_terminal(self):
        plan = _plan()
        self.assertEqual(probegate.ingest_transport(plan, _running_envelope(plan)), "running")
        self.assertTrue(plan.transport_path)
        changed = _running_envelope(plan, path=f"/tmp/.cria-gate-{plan.transport_id}.spool2")
        self.assertEqual(probegate.ingest_transport(plan, changed), "unknown")
        self.assertIn("spool changed", plan.transport_error)


class CompactionDuringRunningTransportPollsNotReplansTests(unittest.TestCase):
    """C28b (b): live P24 Orders, session 01a0d4fa. A harness compaction (probe result missing,
    `rewritten=True`) while the CURRENT plan's transport is still open must re-issue a POLL of
    that SAME plan — idempotent and read-only — not compose a brand new gate. The old behavior
    (`guard_probe_reissue` → a NEW plan → `guard_gate_op` → survey-only → another new plan)
    abandoned the still-running detached probe block every ~100s with ZERO coder progress."""

    def _tool(self):
        return {"type": "function", "function": {
            "name": "exec_command",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}}

    def test_compaction_after_running_polls_the_same_transport_not_a_new_gate(self):
        with tempfile.TemporaryDirectory() as ws:
            gs = loop.GuardState()
            gs.gate_plan = probegate.plan_gate(ws)
            gs.awaiting_probe = True
            gs.probe_call_id = "call_launch"
            original_transport_id = gs.gate_plan.transport_id

            # 1) launch: total silence — the exact P18/P24 shape (harness cut the exec before the
            #    reader printed anything).
            self.assertEqual(probegate.ingest_transport(gs.gate_plan, P18_LAUNCH_NO_OPENER), "running")
            # 2) a real running reply, teaching cria the resolved spool path.
            self.assertEqual(
                probegate.ingest_transport(gs.gate_plan, _running_envelope(gs.gate_plan)), "running")
            self.assertTrue(gs.gate_plan.transport_path)

            # 3) harness compaction: the probe's RESULT is gone (empty content), rewritten=True.
            body = {"messages": [], "tools": [self._tool()]}
            poll = loop._poll_running_plan_after_rewrite(gs, body, mock.Mock())
            self.assertIsNotNone(poll, "the still-running plan must be polled, not abandoned")
            self.assertEqual(gs.gate_plan.transport_id, original_transport_id,  # SAME plan
                             "compaction must not abandon the still-running gate for a new one")
            args = json.loads(poll["function"]["arguments"])
            cmd_text = args.get("cmd") or " ".join(args.get("command") or [])
            self.assertNotIn("__CRIA_GATE_BODY__", cmd_text)       # a narrow read, not a relaunch
            self.assertTrue(gs.awaiting_probe)

            # 4) later: the composed timeout fires, delivering the real partial pytest output —
            #    the SAME rendering the gate already knows how to produce for a timed-out check.
            page = _page(gs.gate_plan, _TIMED_OUT_GATE_BODY)
            self.assertEqual(probegate.ingest_transport(gs.gate_plan, page), "complete")
            rendered = probegate.clean_gate_output(probegate.transported_result(gs.gate_plan))
            self.assertIn("did not finish (timed out)", rendered)
            self.assertIn("tests/test_orders_integration.py::test_polls_forever", rendered)

    def test_no_plan_or_a_terminal_plan_falls_through_to_none(self):
        gs = loop.GuardState()
        body = {"messages": [], "tools": [self._tool()]}
        self.assertIsNone(loop._poll_running_plan_after_rewrite(gs, body, mock.Mock()))

        gs.gate_plan = _plan()
        probegate.fail_transport(gs.gate_plan, "terminal for this test")
        self.assertIsNone(loop._poll_running_plan_after_rewrite(gs, body, mock.Mock()))

    def test_the_poll_path_is_bounded_independently_of_max_probe_reissues(self):
        """A harness that compacts EVERY turn must not wedge in endless polling — bounded by its
        OWN cap (`probe_poll_reissues`), never touching `probe_reissues` (the new-gate budget)."""
        gs = loop.GuardState()
        gs.gate_plan = _plan()
        gs.gate_plan.script = "echo placeholder-launch-script"  # a real plan's own non-empty text
        body = {"messages": [], "tools": [self._tool()]}
        seen = 0
        for _ in range(loop.MAX_PROBE_REISSUES + 3):
            if loop._poll_running_plan_after_rewrite(gs, body, mock.Mock()) is None:
                break
            seen += 1
        self.assertEqual(seen, loop.MAX_PROBE_REISSUES)
        self.assertEqual(gs.probe_reissues, 0, "polling must never spend the new-gate budget")


class PollWaitFromToolSchemaTests(unittest.TestCase):
    """C28b (c): the poll reader's wait is chosen at COMPOSE time from the tool's own schema —
    never a harness name — the long wait (~25s, under the ~30s Codex was measured honoring) when
    the schema declares an ms-unit time-budget field, the short default (8s, under the harness's
    own unbudgeted default yield) otherwise."""

    def _tool(self, *, with_budget: bool) -> dict:
        props = {"cmd": {"type": "string"}}
        if with_budget:
            props["yield_time_ms"] = {"type": "integer"}
        return {"type": "function", "function": {
            "name": "exec_command", "parameters": {"type": "object", "properties": props}}}

    def test_a_tool_with_yield_time_ms_gets_the_long_wait(self):
        with tempfile.TemporaryDirectory() as ws:
            gs = loop.GuardState()
            body = {"messages": [], "tools": [self._tool(with_budget=True)]}
            call = loop.guard_gate_op(gs, body, mock.Mock(), workspace_root=ws)
        self.assertIsNotNone(call)
        self.assertEqual(gs.gate_plan.transport_poll_wait_s, probegate.GATE_POLL_WAIT_LONG_S)
        self.assertIn(f"time.monotonic() + {probegate.GATE_POLL_WAIT_LONG_S!r}", gs.gate_plan.script)

    def test_a_tool_without_the_field_keeps_the_short_default(self):
        with tempfile.TemporaryDirectory() as ws:
            gs = loop.GuardState()
            body = {"messages": [], "tools": [self._tool(with_budget=False)]}
            call = loop.guard_gate_op(gs, body, mock.Mock(), workspace_root=ws)
        self.assertIsNotNone(call)
        self.assertEqual(gs.gate_plan.transport_poll_wait_s, probegate.GATE_POLL_WAIT_S)
        self.assertIn(f"time.monotonic() + {probegate.GATE_POLL_WAIT_S!r}", gs.gate_plan.script)
        self.assertNotIn(f"time.monotonic() + {probegate.GATE_POLL_WAIT_LONG_S!r}", gs.gate_plan.script)

    def test_continuation_reads_reuse_the_wait_the_plan_learned(self):
        with tempfile.TemporaryDirectory() as ws:
            gs = loop.GuardState()
            body = {"messages": [], "tools": [self._tool(with_budget=True)]}
            loop.guard_gate_op(gs, body, mock.Mock(), workspace_root=ws)
        plan = gs.gate_plan
        probegate.ingest_transport(plan, _running_envelope(plan))
        cmd = probegate.continue_transport_command(plan)
        self.assertIn(f"time.monotonic() + {probegate.GATE_POLL_WAIT_LONG_S!r}", cmd)

    def test_poll_calls_also_get_the_schema_time_budget(self):
        """`with_time_budget` must apply to poll calls too, not only the launch."""
        with tempfile.TemporaryDirectory() as ws:
            gs = loop.GuardState()
            body = {"messages": [], "tools": [self._tool(with_budget=True)]}
            loop.guard_gate_op(gs, body, mock.Mock(), workspace_root=ws)
        plan = gs.gate_plan
        probegate.ingest_transport(plan, _running_envelope(plan))
        body2 = {"messages": [{"role": "tool", "tool_call_id": gs.probe_call_id,
                              "content": _running_envelope(plan, "5.0")}],
                "tools": [self._tool(with_budget=True)]}
        call = loop.guard_gate_transport(gs, body2, mock.Mock())
        self.assertIsNotNone(call)
        args = json.loads(call["function"]["arguments"])
        self.assertEqual(args.get("yield_time_ms"), shelltool.GATE_TIME_BUDGET_MS)


def _old_reader_6510f2dd(path_arg: str, offset: int, transport_id: str, *,
                        wait_s: float = probegate.GATE_POLL_WAIT_S) -> str:
    """The EXACT 6510f2dd reader shape (reconstructed from git history): self-deletes the spool and
    its ``.done`` marker on the completing read, and treats ANY missing ``.done`` — including a
    spool that no longer exists at all — identically as `running`. This is the fails-before half of
    the reviewer's lost-final-page finding."""
    program = f'''import base64, hashlib, os, sys, time
path = sys.argv[1]
offset = int(sys.argv[2])
opening = {probegate._transport_marker(transport_id)!r}
closing = {probegate._transport_marker(transport_id, end=True)!r}
done_path = path + ".done"
deadline = time.monotonic() + {wait_s!r}
while not os.path.exists(done_path) and time.monotonic() < deadline:
    time.sleep(0.2)
if not os.path.exists(done_path):
    try:
        started = os.path.getctime(path)
        elapsed = max(0.0, time.time() - started)
    except OSError:
        elapsed = 0.0
    print(opening)
    print("path\\t" + base64.b64encode(path.encode()).decode())
    print("running\\t" + str(round(elapsed, 1)))
    print(closing)
    sys.exit(0)
try:
    total = os.path.getsize(path)
    if offset < 0 or offset > total:
        raise ValueError("offset outside spool")
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
        source.seek(offset)
        chunk = source.read({probegate.TRANSPORT_CHUNK_BYTES})
    final = offset + len(chunk) == total
    if final:
        os.unlink(path)
        try:
            os.unlink(done_path)
        except OSError:
            pass
    print(opening)
    print("path\\t" + base64.b64encode(path.encode()).decode())
    print("offset\\t" + str(offset))
    print("total\\t" + str(total))
    print("sha256\\t" + digest.hexdigest())
    print("data\\t" + base64.b64encode(chunk).decode())
    print(closing)
except Exception as exc:
    print(opening)
    print("error\\t" + base64.b64encode(str(exc).encode()).decode())
    print(closing)
'''
    return (f"python3 - {path_arg} {offset} <<'{probegate._TRANSPORT_HEREDOC}'\n"
            f"{program}{probegate._TRANSPORT_HEREDOC}")


class LostFinalPageRecoveryTests(unittest.TestCase):
    """Reviewer follow-up to 6510f2dd: the final read used to unlink the spool AND its ``.done``
    marker. If that harness response was itself lost to a compaction (plausible — the final page
    is usually the largest result), a re-poll found no spool and no ``.done`` — indistinguishable
    from "not finished yet" — and answered `running 0.0` forever until the plan's multi-minute
    deadline discarded a check that had ALREADY passed."""

    def setUp(self):
        self.tid = probegate.GatePlan(workspace="").transport_id
        self.spool = f"{tempfile.gettempdir()}/.cria-gate-{self.tid}.spool"

    def tearDown(self):
        for p in (self.spool, self.spool + ".done"):
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_before_the_fix_a_lost_final_page_becomes_a_phantom_running_gate(self):
        with open(self.spool, "wb") as f:
            f.write(b"complete gate output")
        open(self.spool + ".done", "w").close()
        reader = _old_reader_6510f2dd(f'"{self.spool}"', 0, self.tid, wait_s=0.3)

        first = subprocess.run(["bash", "-c", reader], capture_output=True, text=True, timeout=10)
        self.assertIn("data\t", first.stdout)          # delivered the complete page...
        self.assertFalse(os.path.exists(self.spool))    # ...and self-deleted it immediately
        self.assertFalse(os.path.exists(self.spool + ".done"))

        # That delivery is the one lost to a compaction: cria never ingests `first`, so its plan
        # is still waiting for the SAME offset. A re-poll now finds nothing at all.
        plan = _plan()
        plan.transport_id = self.tid
        second = subprocess.run(["bash", "-c", reader], capture_output=True, text=True, timeout=10)
        state = probegate.ingest_transport(plan, second.stdout)
        self.assertEqual(state, "running",
                         "pre-fix: a FINISHED check reads as merely still running, forever")
        self.assertFalse(plan.transport_complete)

    def test_after_the_fix_a_lost_final_page_is_recovered_by_a_repoll(self):
        with open(self.spool, "wb") as f:
            f.write(b"complete gate output")
        open(self.spool + ".done", "w").close()
        reader = probegate._transport_reader(f'"{self.spool}"', 0, self.tid, wait_s=0.3)

        first = subprocess.run(["bash", "-c", reader], capture_output=True, text=True, timeout=10)
        self.assertIn("data\t", first.stdout)
        self.assertTrue(os.path.exists(self.spool), "the fix must NOT self-delete on the final read")
        self.assertTrue(os.path.exists(self.spool + ".done"))

        # Simulate the SAME loss: cria never ingests `first`.
        plan = _plan()
        plan.transport_id = self.tid
        second = subprocess.run(["bash", "-c", reader], capture_output=True, text=True, timeout=10)
        state = probegate.ingest_transport(plan, second.stdout)
        self.assertEqual(state, "complete", "the re-poll must recover the SAME bytes at the SAME offset")
        self.assertEqual(bytes(plan.transport_data), b"complete gate output")


class GoneEnvelopeTests(unittest.TestCase):
    """(1) A genuinely missing spool must never be folded into `running` — a distinct typed `gone`
    envelope stops the transport immediately (fail closed, #13) instead of riding the deadline."""

    def test_a_gone_envelope_is_terminal_not_running(self):
        plan = _plan()
        gone = "\n".join([
            probegate._transport_marker(plan.transport_id),
            "gone\t1",
            probegate._transport_marker(plan.transport_id, end=True),
        ])
        state = probegate.ingest_transport(plan, gone)
        self.assertEqual(state, "unknown")
        self.assertIn("gone", plan.transport_error)
        self.assertFalse(plan.transport_complete)

    def test_a_real_missing_spool_produces_the_gone_envelope(self):
        tid = probegate.GatePlan(workspace="").transport_id
        missing = f"/tmp/.cria-gate-{tid}-does-not-exist.spool"
        self.assertFalse(os.path.exists(missing))
        reader = probegate._transport_reader(f'"{missing}"', 0, tid, wait_s=0.3)
        out = subprocess.run(["bash", "-c", reader], capture_output=True, text=True, timeout=10)
        self.assertIn("gone\t1", out.stdout)
        plan = _plan()
        plan.transport_id = tid
        self.assertEqual(probegate.ingest_transport(plan, out.stdout), "unknown")

    def test_gone_lets_poll_after_rewrite_fall_through_to_a_new_gate(self):
        """(3) Once `gone` has marked the plan terminal, the NEXT compaction-triggered recovery
        must decline to poll it further and fall through to the existing capped new-gate reissue."""
        gs = loop.GuardState()
        gs.gate_plan = _plan()
        gs.gate_plan.script = "echo placeholder-launch-script"
        gone = "\n".join([
            probegate._transport_marker(gs.gate_plan.transport_id),
            "gone\t1",
            probegate._transport_marker(gs.gate_plan.transport_id, end=True),
        ])
        self.assertEqual(probegate.ingest_transport(gs.gate_plan, gone), "unknown")
        body = {"messages": [], "tools": [{"type": "function", "function": {
            "name": "exec_command",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}}]}
        self.assertIsNone(loop._poll_running_plan_after_rewrite(gs, body, mock.Mock()),
                          "a plan the reader reported gone must never be polled again")


class SpoolCleanupAcrossGatesTests(unittest.TestCase):
    """(2)/(4): the spool is no longer self-deleted, so cleanup happens one gate later — the NEXT
    plan composed for this workspace reclaims exactly the spools cria has fully ingested. No
    accumulation across consecutive real gates, no `rm`, no glob."""

    def test_no_spool_accumulation_across_consecutive_gates(self):
        with tempfile.TemporaryDirectory() as ws:
            with open(os.path.join(ws, "x.py"), "w") as f:
                f.write("print(1)\n")
            plans = []
            for _ in range(3):
                plan = probegate.plan_gate(ws)
                proc = subprocess.run(["bash", "-c", plan.script], capture_output=True, text=True,
                                      timeout=30)
                state = probegate.ingest_transport(plan, proc.stdout)
                self.assertEqual(state, "complete", proc.stdout)
                plans.append(plan)
            # Every plan except the LAST has had its spool reclaimed by the gate composed after it.
            for p in plans[:-1]:
                self.assertFalse(os.path.exists(p.transport_path), p.transport_path)
                self.assertFalse(os.path.exists(p.transport_path + ".done"))
            self.assertTrue(os.path.exists(plans[-1].transport_path))
            os.unlink(plans[-1].transport_path)
            os.unlink(plans[-1].transport_path + ".done")
            probegate._SPOOL_CLEANUP_QUEUE.pop(ws, None)

    def test_cleanup_command_names_only_paths_cria_itself_ingested(self):
        """Never a glob: the composed cleanup program lists exact, cria-validated paths."""
        with tempfile.TemporaryDirectory() as ws:
            with open(os.path.join(ws, "x.py"), "w") as f:
                f.write("print(1)\n")
            plan = probegate.plan_gate(ws)
            proc = subprocess.run(["bash", "-c", plan.script], capture_output=True, text=True,
                                  timeout=30)
            self.assertEqual(probegate.ingest_transport(plan, proc.stdout), "complete", proc.stdout)
            cmd = probegate.spool_cleanup_command(ws)
            self.assertIn(plan.transport_path, cmd)
            self.assertNotIn("glob", cmd)
            self.assertNotIn("*", cmd.replace("__CRIA_SPOOL_CLEANUP__", ""))
            os.unlink(plan.transport_path)
            os.unlink(plan.transport_path + ".done")
            probegate._SPOOL_CLEANUP_QUEUE.pop(ws, None)


if __name__ == "__main__":
    unittest.main()
