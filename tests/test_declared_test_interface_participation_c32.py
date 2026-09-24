"""C32: a completed declared test command that directly runs its mapped test files must count
as test participation.

P23 Handles (capture 20260924T113235-01a0d4b0-dd38-7783-985e-9203ccf8bc2f): ``package.json``
declares ``"test": "node test/real.test.js"``.  The script has no framework tally line -- it just
exits 0 or 1 -- so ``participation.collect`` used to leave ``test.participated`` at ``"unknown"``
even though the declared runner interface ran the declared test file to a known exit code.  The
C23 barrier (``_test_participation_blocks_completion``) then holds a genuinely green run as
unproven and tells the coder its required test was never executed.

The fix keys ONLY on: this candidate is the project's declared test interface
(``candidate.declared_interface``), its declared body maps to an existing test file
(``candidate.test_source_paths``), and that file sits in the one operand position the command
line actually executes (``candidate.test_source_paths_executed`` --
:func:`cria.probediscovery.executed_test_source_paths`).  No runner/language name, no keyword
list.  Tally evidence, when present, still wins; timeouts and launch failures stay unknown.
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


def _satisfied():
    return json.dumps({"satisfied": True, "reason": "all deliverables are present"})


def _session(report):
    state = loop.GuardState()
    state.last_gate_participation = report
    state.gate_fresh = True
    return state


def _capture_view(root, files, session="capture"):
    tree, blobs = [], []
    for rel, body in files.items():
        raw = body.encode()
        tree.append(f"F\t1\t{len(raw)}\t{rel}")
        blobs += ["@" + base64.b64encode(rel.encode()).decode(), base64.b64encode(raw).decode()]
    view = wsview.View(root, session)
    assert wsview.apply_survey(view, survey("\n".join(tree), blob="\n".join(blobs), root=root))
    return view


def _declared_test_candidate(root):
    candidates = []
    probediscovery.build_js(Path(root),
                            probediscovery.ProjectDir(Path(root), {"package.json"}), candidates)
    return next(c for c in candidates if c.kind is probediscovery.ProbeKind.Test)


TASK = ("Build a Node CLI that resolves a handle. Add a test that verifies the CLI's behavior.")


class DeclaredDirectTestCommandParticipatesTests(unittest.TestCase):
    """P23-shaped: ``node test/real.test.js`` under ``npm test``, no framework tally."""

    def _bind(self, extra_files=None):
        root = "/workspace"
        files = {
            "test/real.test.js": "require('assert').ok(true);\n",
            "package.json": '{"scripts":{"test":"node test/real.test.js"}}',
        }
        files.update(extra_files or {})
        token = wsview.bind(_capture_view(root, files))
        self.addCleanup(wsview.unbind, token)
        return root

    def test_exit_zero_with_no_tally_proves_participation_and_pass(self):
        root = self._bind()
        candidate = _declared_test_candidate(root)
        self.assertTrue(candidate.declared_interface)
        self.assertEqual(candidate.test_source_paths_executed, (root + "/test/real.test.js",))

        event = participation.observe(candidate, "", 0)

        self.assertIs(event.test.participated, True)
        self.assertIs(event.test.passed, True)
        self.assertEqual(event.test.participant_kind, "file")
        self.assertEqual(event.test.participants, (root + "/test/real.test.js",))
        self.assertIs(event.test.participants_complete, False)
        report = participation.report([event])
        self.assertIs(report.support("test"), participation.Support.PROVEN)

    def test_exit_one_with_no_tally_proves_participation_and_fail(self):
        root = self._bind()
        candidate = _declared_test_candidate(root)

        event = participation.observe(candidate, "", 1)

        self.assertIs(event.test.participated, True)
        self.assertIs(event.test.passed, False)
        report = participation.report([event])
        self.assertIs(report.support("test"), participation.Support.FAILED)

    def test_tally_evidence_still_wins_over_declared_mapping(self):
        root = self._bind()
        candidate = _declared_test_candidate(root)

        event = participation.observe(candidate, "Tests:       1 passed, 1 total", 0)

        self.assertIs(event.test.participated, True)
        self.assertIs(event.test.passed, True)
        # Tally path supplies its own count -- the C32 inference must not clobber it.
        self.assertEqual(event.test.count, 1)

    def test_timeout_stays_unknown(self):
        root = self._bind()
        candidate = _declared_test_candidate(root)

        event = participation.observe(candidate, "", 124)

        self.assertIsNone(event.test.participated)
        report = participation.report([event])
        self.assertIs(report.support("test"), participation.Support.UNKNOWN)

    def test_no_mapped_test_source_leaves_participation_unknown(self):
        root = "/workspace"
        files = {"package.json": '{"scripts":{"test":"echo no test files here"}}'}
        token = wsview.bind(_capture_view(root, files))
        self.addCleanup(wsview.unbind, token)
        candidate = _declared_test_candidate(root)

        self.assertEqual(candidate.test_source_paths, ())
        self.assertEqual(candidate.test_source_paths_executed, ())
        event = participation.observe(candidate, "", 0)

        self.assertIsNone(event.test.participated)
        report = participation.report([event])
        self.assertIs(report.support("test"), participation.Support.UNKNOWN)

    def test_mapped_token_only_reachable_as_a_flag_value_stays_unknown(self):
        """``--ignore test/skip.test.js`` maps a test file cria must NOT credit as executed: it
        occupies the operand slot right after the program name with an OPTION, so no operand in
        this segment is structurally trustworthy -- the real file never gets credited either, by
        design (a false negative, never a false positive)."""
        root = "/workspace"
        files = {
            "test/skip.test.js": "require('assert').ok(true);\n",
            "test/real.test.js": "require('assert').ok(true);\n",
            "package.json": json.dumps({"scripts": {
                "test": "node --ignore test/skip.test.js test/real.test.js"}}),
        }
        token = wsview.bind(_capture_view(root, files))
        self.addCleanup(wsview.unbind, token)
        candidate = _declared_test_candidate(root)

        # Both files are DECLARED-mapped (broad provenance)...
        self.assertEqual(set(candidate.test_source_paths),
                         {root + "/test/skip.test.js", root + "/test/real.test.js"})
        # ...but neither is structurally EXECUTED, so the new inference stays silent.
        self.assertEqual(candidate.test_source_paths_executed, ())

        event = participation.observe(candidate, "", 0)
        self.assertIsNone(event.test.participated)

    def test_c32_the_c23_barrier_releases_a_true_completed_declared_run(self):
        root = self._bind()
        candidate = _declared_test_candidate(root)
        report = participation.report([participation.observe(candidate, "", 0)])
        self.assertIs(report.support("test"), participation.Support.PROVEN)

        # PROVEN routes judge_satisfaction into the E2E-scope question (not "REQUIRED"), and a
        # bound current test source is available for that judge -- exactly the C24 path, now
        # reachable for a plain script this run used to strand at "unknown".
        chat = _Chat([_satisfied(), "NOT_REQUIRED"])
        satisfied, _reason, _fix = loop.judge_satisfaction(
            TASK, "exit 0", chat, None, _Rlog(), sess=_session(report))

        self.assertTrue(satisfied)
        self.assertEqual(len(chat.bodies), 2)

    def test_c32_still_fail_closed_when_the_run_actually_failed(self):
        root = self._bind()
        candidate = _declared_test_candidate(root)
        report = participation.report([participation.observe(candidate, "", 1)])
        self.assertIs(report.support("test"), participation.Support.FAILED)


if __name__ == "__main__":
    unittest.main()
