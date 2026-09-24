"""C23: a positive satisfaction verdict cannot promote an unexecuted required test.

The captured Handles task wrote a direct-HTTP ``test/lookup.test.js`` without any
runner.  The completion gate ran only ``node --check`` and recorded test
participation as unknown, but CALL0043 still returned satisfied=true.
"""
import json
import unittest

from cria import loop, participation, probediscovery


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
        return json.dumps({"choices": [{"message": {"content": reply}}]}).encode()


def _candidate(kind, command):
    return probediscovery.ProbeCandidate(
        kind=kind, command=command.split(), working_dir="/workspace", confidence=90,
        expected_value=90, cost=probediscovery.ProbeCost.Cheap, mutates_code=False,
        may_hang=False, may_need_services=False, reason="fixture",
        ecosystem=probediscovery.Ecosystem.JsTs)


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

    def test_executed_tests_do_not_add_a_requirement_question(self):
        report = participation.report([participation.observe(
            _candidate(probediscovery.ProbeKind.Test, "npm test"), "Tests:       1 passed, 1 total", 0)])
        self.assertIs(report.support("test"), participation.Support.PROVEN)
        chat = _Chat([_satisfied()])

        satisfied, _reason, _fix = loop.judge_satisfaction(
            self.TASK, "Tests: 1 passed", chat, None, _Rlog(), sess=_session(report))

        self.assertTrue(satisfied)
        self.assertEqual(len(chat.bodies), 1)


if __name__ == "__main__":
    unittest.main()
