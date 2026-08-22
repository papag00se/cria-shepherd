"""A quoted literal the step names, absent from the artifact it names — a FACT, not a verdict.

Measured need, run 20260801T235629 (mellum2, ada-handles, 3/4). The step read "Write live_test.py: a
standalone script that calls the real API ... to resolve the handle 'goose' and 'papagoose'". The
coder wrote a general CLI: run by hand with a handle it returns goose's real address, holder and 15
handles, but neither literal appears in the file, so run as a test it exits 1 and scored zero.

The critic approved it and its own reason contains the disproof:

    "live_test.py exists and calls the real API to resolve handles ... and prints a usage message
     when no handle is provided. The step is fully satisfied."

Base-rated across every captured critic approval (n=106 with a workspace and a parseable verdict):
fires ONCE, on exactly that verdict, with no false positives. Offered as evidence, not enforced as a
gate — deterministic code gathers, the reasoner judges.
"""
import json
import os
import tempfile
import unittest

from cria import groundtruth, loop, prompts
from cria.loop import Loop

from test_loop import _ctx, _Rlog


class AbsentLiteralTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def _write(self, name, body):
        with open(os.path.join(self.d, name), "w") as fh:
            fh.write(body)

    def test_the_measured_case(self):
        self._write("live_test.py", "import sys\nprint(sys.argv[1])\n")
        out = groundtruth.absent_step_literals(
            "Write live_test.py: a standalone script that calls the real API to resolve the handle "
            "'goose' and 'papagoose' and prints the results.", self.d)
        self.assertEqual(out, [("live_test.py", ["goose", "papagoose"])])

    def test_a_literal_that_IS_present_is_not_reported(self):
        self._write("ok.py", 'HANDLE = "goose"\n')
        self.assertEqual(groundtruth.absent_step_literals("Write ok.py resolving 'goose'", self.d), [])

    def test_partial_presence_reports_only_what_is_missing(self):
        self._write("t.py", 'h = "goose"\n')
        out = groundtruth.absent_step_literals("Write t.py for 'goose' and 'papagoose'", self.d)
        self.assertEqual(out, [("t.py", ["papagoose"])])

    def test_a_step_with_no_quoted_literal_reports_nothing(self):
        self._write("a.py", "x = 1\n")
        self.assertEqual(groundtruth.absent_step_literals("Write a.py that resolves a handle", self.d), [])

    def test_a_step_whose_artifact_does_not_exist_reports_nothing(self):
        # Absence of the FILE is the empty-workspace gate's job, not this one.
        self.assertEqual(groundtruth.absent_step_literals("Write gone.py using 'goose'", self.d), [])

    def test_quoted_filenames_and_paths_are_not_treated_as_values(self):
        self._write("a.py", "x = 1\n")
        for step in ("Write a.py importing 'utils.py'", "Write a.py reading 'src/data'"):
            with self.subTest(step=step):
                self.assertEqual(groundtruth.absent_step_literals(step, self.d), [])

    def test_no_workspace_reports_nothing(self):
        self.assertEqual(groundtruth.absent_step_literals("Write a.py using 'goose'", ""), [])


class ItIsEvidenceNotAGateTests(unittest.TestCase):
    def test_the_critic_is_told_it_may_still_approve(self):
        t = prompts.load_map("verify_user")["absent_literals"]
        self.assertIn("not a verdict", t)
        self.assertIn("not necessarily a failure", t)
        self.assertIn("Decide for yourself", t)

    def test_verify_appends_it_as_evidence_and_does_not_branch_on_it(self):
        """Driven for real, the measured case (mellum2 3/4): the artifact exists but neither
        quoted literal is in it, AND the critic itself approves anyway. Two claims, one fixture —
        the evidence reaches the critic's prompt, and its presence does not force a verdict: the
        critic's own DONE is what comes back, not an overridden one."""
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "live_test.py"), "w") as f:
            f.write("import sys\nprint(sys.argv[1])\n")
        replies = [
            {"choices": [{"message": {"content": json.dumps(
                {"done": True, "reason": "it exists and works", "proposed_fix": ""})}}]},
            # The confirm looks before approving — see loop._confirm_completion.
            {"choices": [{"message": {"content": "", "tool_calls": [
                {"id": "l1", "type": "function", "function": {
                    "name": "list_dir", "arguments": json.dumps({"path": "."})}}]}}]},
            {"choices": [{"message": {"content": json.dumps({"consistent": True, "why": ""})}}]},
        ]
        calls = []

        def chat(body, rlog):
            calls.append(body)
            return json.dumps(replies[min(len(calls) - 1, len(replies) - 1)]).encode()

        L = Loop(_ctx(None, chat, None))
        item = ("Write live_test.py: a standalone script that calls the real API to resolve the "
                "handle 'goose' and 'papagoose' and prints the results.")
        ok, reason = L._verify(item, "coder summary", "", "", _Rlog(), workspace_root=d)
        self.assertTrue(ok, "the critic's own DONE must not be overridden by the evidence alone")
        prompt = calls[0]["messages"][-1]["content"]
        # the FILLED evidence fragment, not just the literals — those two words are ALSO in the
        # raw step text, so checking for them alone would not distinguish "evidence appended" from
        # "the step was merely restated".
        self.assertIn("the step quotes 'goose', 'papagoose', and live_test.py does not contain "
                     "them anywhere", prompt)
        self.assertIn("not a verdict", prompt)        # the "evidence, not a gate" framing rode with it

    def test_it_reads_the_disk_not_a_claim(self):
        doc = groundtruth.absent_step_literals.__doc__
        self.assertIn("gathers", doc)
        self.assertIn("reasoner judges", doc)
