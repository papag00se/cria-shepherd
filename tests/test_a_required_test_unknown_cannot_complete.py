"""C23: a positive satisfaction verdict cannot promote an unexecuted required test.

The captured Handles task wrote a direct-HTTP ``test/lookup.test.js`` without any
runner.  The completion gate ran only ``node --check`` and recorded test
participation as unknown, but CALL0043 still returned satisfied=true.
"""
import base64
import hashlib
import json
from pathlib import Path
import unittest

from cria import loop, participation, probediscovery, probegate, wsview
from tests.wsfixture import survey


class _Rlog:
    def emit(self, *_args, **_kwargs):
        pass


class _Chat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.bodies = []

    def __call__(self, body, _rlog):
        self.bodies.append(body)
        reply = self.replies.pop(0)
        message = reply if isinstance(reply, dict) else {"content": reply}
        return json.dumps({"choices": [{"message": message}]}).encode()


class _ReasoningBeforeTerminalChat:
    """Replay the C24/C26 shape: reasoning fills 16 tokens before the verdict reaches content."""
    REASONING = "We need to decide if the task requires a test deliverable to be executed as"

    def __init__(self, terminal):
        self.terminal = terminal
        self.bodies = []
        self._satisfaction = True

    def __call__(self, body, _rlog):
        self.bodies.append(body)
        if self._satisfaction:
            self._satisfaction = False
            message = {"content": _satisfied()}
            return json.dumps({"choices": [{"message": message}]}).encode()
        if body["max_tokens"] <= 16:
            return json.dumps({"choices": [{
                "finish_reason": "length",
                "message": {"reasoning_content": self.REASONING, "content": ""},
            }]}).encode()
        return json.dumps({"choices": [{"message": {
            "reasoning_content": self.REASONING, "content": self.terminal,
        }}]}).encode()


def _candidate(kind, command, test_sources=()):
    candidate = probediscovery.ProbeCandidate(
        kind=kind, command=command.split(), working_dir="/workspace", confidence=90,
        expected_value=90, cost=probediscovery.ProbeCost.Cheap, mutates_code=False,
        may_hang=False, may_need_services=False, reason="fixture",
        ecosystem=probediscovery.Ecosystem.JsTs)
    candidate.test_source_paths = tuple(test_sources)
    return candidate


def _transport_page(transport_id, result):
    data = result.encode()
    return "\n".join([
        probegate._transport_marker(transport_id),
        "path\t" + base64.b64encode(
            f"/tmp/.cria-gate-{transport_id}.wire".encode()).decode(),
        "offset\t0", f"total\t{len(data)}",
        "sha256\t" + hashlib.sha256(data).hexdigest(),
        "data\t" + base64.b64encode(data).decode(),
        probegate._transport_marker(transport_id, end=True),
    ])


def _gate_result(plan, survey_text):
    probes = "\n".join(
        f"{probegate._marker(f'probe-{i}')}\nTests:       1 passed, 1 total\nEXIT:0"
        for i, _candidate in enumerate(plan.candidates))
    return _transport_page(plan.transport_id, probes + "\n" + wsview.SURVEY_OPEN + "\n" + survey_text)


def _declared_test_candidate(root):
    candidates = []
    probediscovery.build_js(Path(root), probediscovery.ProjectDir(Path(root), {"package.json"}), candidates)
    return next(candidate for candidate in candidates if candidate.kind is probediscovery.ProbeKind.Test)


def _capture_view(root, files, session="capture"):
    tree, blobs = [], []
    for rel, body in files.items():
        raw = body.encode()
        tree.append(f"F\t1\t{len(raw)}\t{rel}")
        blobs += ["@" + base64.b64encode(rel.encode()).decode(), base64.b64encode(raw).decode()]
    view = wsview.View(root, session)
    assert wsview.apply_survey(view, survey("\n".join(tree), blob="\n".join(blobs), root=root))
    return view


def _session(report):
    state = loop.GuardState()
    state.last_gate_participation = report
    state.gate_fresh = True
    return state


def _satisfied():
    return json.dumps({"satisfied": True, "reason": "all deliverables are present"})


class RequiredTestParticipationBarrierTests(unittest.TestCase):
    TASK = (
        "Build a Node CLI that resolves a handle. Add an end-to-end test that makes a real "
        "request and verifies the tool end to end.")
    C23_EVIDENCE = (
        "Wrote test/lookup.test.js: it calls fetch on /handles/${handle} and /holders/${holder} "
        "directly. [GROUND TRUTH] NO tests were actually executed (0 collected / no test probe ran).")

    def test_c23_unknown_test_participation_blocks_a_positive_satisfaction_verdict(self):
        report = participation.report([participation.observe(
            _candidate(probediscovery.ProbeKind.SyntaxCheck, "node --check lookup.js"), "", 0)])
        self.assertIs(report.support("test"), participation.Support.UNKNOWN)
        chat = _Chat([_satisfied(), "REQUIRED"])

        satisfied, _reason, _fix = loop.judge_satisfaction(
            self.TASK, self.C23_EVIDENCE, chat, None, _Rlog(), sess=_session(report))

        self.assertFalse(satisfied)
        self.assertEqual(len(chat.bodies), 2)

    def test_non_test_task_is_not_blocked_by_unknown_test_participation(self):
        report = participation.report([participation.observe(
            _candidate(probediscovery.ProbeKind.SyntaxCheck, "node --check lookup.js"), "", 0)])
        chat = _Chat([_satisfied(), "NOT_REQUIRED"])

        satisfied, _reason, _fix = loop.judge_satisfaction(
            "Add a --json option to the CLI.", "Wrote lookup.js.", chat, None,
            _Rlog(), sess=_session(report))

        self.assertTrue(satisfied)
        self.assertEqual(len(chat.bodies), 2)

    def test_participation_requirement_reaches_terminal_token_after_capture_shaped_reasoning(self):
        report = participation.report([participation.observe(
            _candidate(probediscovery.ProbeKind.SyntaxCheck, "node --check lookup.js"), "", 0)])
        chat = _ReasoningBeforeTerminalChat("NOT_REQUIRED")

        satisfied, _reason, _fix = loop.judge_satisfaction(
            "Add a --json option to the CLI.", "Wrote lookup.js.", chat, None,
            _Rlog(), sess=_session(report))

        self.assertTrue(satisfied)
        self.assertEqual(chat.bodies[1]["max_tokens"], 1024)

    def test_e2e_requirement_reaches_terminal_token_after_capture_shaped_reasoning(self):
        report = participation.report([participation.observe(
            _candidate(probediscovery.ProbeKind.Test, "npm test"), "Tests: 1 passed", 0)])
        chat = _ReasoningBeforeTerminalChat("NOT_REQUIRED")

        satisfied, _reason, _fix = loop.judge_satisfaction(
            self.TASK, "Tests: 1 passed", chat, None, _Rlog(), sess=_session(report))

        self.assertTrue(satisfied)
        self.assertEqual(chat.bodies[1]["max_tokens"], 1024)

    def test_missing_participation_terminal_token_remains_fail_closed(self):
        report = participation.report([participation.observe(
            _candidate(probediscovery.ProbeKind.SyntaxCheck, "node --check lookup.js"), "", 0)])
        chat = _Chat([_satisfied(), {"reasoning_content": _ReasoningBeforeTerminalChat.REASONING,
                                     "content": ""}])

        satisfied, _reason, _fix = loop.judge_satisfaction(
            "Add a --json option to the CLI.", "Wrote lookup.js.", chat, None,
            _Rlog(), sess=_session(report))

        self.assertFalse(satisfied)

    def test_unrelated_explicit_closed_question_cap_is_preserved(self):
        chat = _ReasoningBeforeTerminalChat("NOT_REQUIRED")
        chat._satisfaction = False

        answer = loop.ask_closed(chat, None, "Return one token.", _Rlog(), phase="unrelated",
                                 max_tokens=16, retry_off=False)

        self.assertEqual(answer, "")
        self.assertEqual(chat.bodies[0]["max_tokens"], 16)

    def test_c24_executed_direct_api_test_cannot_satisfy_cli_end_to_end_requirement(self):
        root = "/workspace"
        source = """const fetch = global.fetch;
async function run() {
  const handle = await fetch('https://api.handle.me/handles/goose');
  const holder = await fetch('https://api.handle.me/holders/example');
  if (!handle.ok || !holder.ok) process.exit(1);
  process.exit(0);
}
run();
"""
        token = wsview.bind(_capture_view(root, {
            "tests/lookup.test.cjs": source,
            "package.json": '{"scripts":{"test":"node tests/lookup.test.cjs"}}',
        }))
        self.addCleanup(wsview.unbind, token)
        report = participation.report([participation.observe(
            _declared_test_candidate(root), "Tests:       1 passed, 1 total", 0)])
        self.assertIs(report.support("test"), participation.Support.PROVEN)
        self.assertEqual(report.executed_test_sources()[0].body, source)
        chat = _Chat([_satisfied(), "E2E_REQUIRED", "UNVERIFIED"])

        satisfied, _reason, _fix = loop.judge_satisfaction(
            self.TASK, "Tests: 1 passed", chat, None, _Rlog(),
            workspace_root=root, sess=_session(report))

        self.assertFalse(satisfied)
        self.assertEqual(len(chat.bodies), 3)
        self.assertIn("lookup.test.cjs", str(chat.bodies[-1]["messages"]))

    def test_e2e_requirement_with_no_bound_current_test_source_is_unverified(self):
        report = participation.report([participation.observe(
            _candidate(probediscovery.ProbeKind.Test, "npm test"), "Tests:       1 passed, 1 total", 0)])
        chat = _Chat([_satisfied(), "E2E_REQUIRED"])

        satisfied, _reason, _fix = loop.judge_satisfaction(
            self.TASK, "Tests: 1 passed", chat, None, _Rlog(), sess=_session(report))

        self.assertFalse(satisfied)
        self.assertEqual(len(chat.bodies), 2)

    def test_declared_runner_forces_its_mapped_source_into_the_gate_survey(self):
        root, path = "/workspace", "tests/lookup.test.cjs"
        source = "const result = runCli(); assert.equal(result.status, 0);"
        view = _capture_view(root, {
            path: source,
            "package.json": '{"scripts":{"test":"node tests/lookup.test.cjs"}}',
        }, session="gate")
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)

        plan = probegate.plan_gate(root, "gate")
        candidate = next(c for c in plan.candidates if c.kind is probediscovery.ProbeKind.Test)
        self.assertEqual(candidate.test_source_paths, (root + "/" + path,))
        self.assertIn("WANT = ['tests/lookup.test.cjs']", plan.script)

        returned_survey = survey(
            f"F\t2\t{len(source)}\t{path}",
            blob="@" + base64.b64encode(path.encode()).decode() + "\n"
                 + base64.b64encode(source.encode()).decode(), root=root)
        outcome = probegate.interpret_gate(plan, _gate_result(plan, returned_survey))
        self.assertEqual(outcome.participation.executed_test_sources()[0].body, source)

    def test_e2e_gate_rejects_cached_test_bytes_absent_from_its_survey(self):
        root, path = "/workspace", "tests/lookup.test.cjs"
        view = _capture_view(root, {
            path: "old API-only source",
            "package.json": '{"scripts":{"test":"node tests/lookup.test.cjs"}}',
        })
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)
        plan = probegate.plan_gate(root, "capture")  # declared runner requests fresh source bytes
        candidate = next(c for c in plan.candidates if c.kind is probediscovery.ProbeKind.Test)
        outcome = probegate.interpret_gate(plan, _gate_result(plan, survey(
            f"F\t2\t{len('new CLI source')}\t{path}", root=root)))
        self.assertEqual(outcome.participation.executed_test_sources()[0].body, None)
        chat = _Chat([_satisfied(), "E2E_REQUIRED"])

        satisfied, _reason, _fix = loop.judge_satisfaction(
            self.TASK, "Tests: 1 passed", chat, None, _Rlog(),
            sess=_session(outcome.participation))

        self.assertFalse(satisfied)
        self.assertEqual(len(chat.bodies), 2)

    def test_executed_cli_end_to_end_test_is_preserved(self):
        root = "/workspace"
        source = """const { spawnSync } = require('node:child_process');
const result = spawnSync('node', ['lookup.js', '--json', 'goose']);
if (result.status !== 0 || !result.stdout.includes('goose')) process.exit(1);
"""
        token = wsview.bind(_capture_view(root, {
            "tests/lookup.test.cjs": source,
            "package.json": '{"scripts":{"test":"node tests/lookup.test.cjs"}}',
        }))
        self.addCleanup(wsview.unbind, token)
        report = participation.report([participation.observe(
            _declared_test_candidate(root), "Tests:       1 passed, 1 total", 0)])
        chat = _Chat([_satisfied(), "E2E_REQUIRED", "PROVEN", {
            "tool_calls": [{"id": "read-test", "type": "function", "function": {
                "name": "read_file", "arguments": '{"path":"tests/lookup.test.cjs"}'}}]},
            "CONSISTENT"])

        satisfied, _reason, _fix = loop.judge_satisfaction(
            self.TASK, "Tests: 1 passed", chat, None, _Rlog(),
            workspace_root=root, sess=_session(report))

        self.assertTrue(satisfied)
        self.assertEqual(len(chat.bodies), 5)

    def test_proven_test_for_a_non_end_to_end_task_is_preserved(self):
        report = participation.report([participation.observe(
            _candidate(probediscovery.ProbeKind.Test, "npm test"), "Tests:       1 passed, 1 total", 0)])
        chat = _Chat([_satisfied(), "NOT_REQUIRED"])

        satisfied, _reason, _fix = loop.judge_satisfaction(
            "Add a --json option to the CLI.", "Tests: 1 passed", chat, None,
            _Rlog(), sess=_session(report))

        self.assertTrue(satisfied)
        self.assertEqual(len(chat.bodies), 2)


if __name__ == "__main__":
    unittest.main()
