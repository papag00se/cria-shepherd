"""The execution probe must not be asked to name a file it cannot see.

This probe decides whether cria RUNS the delivered program — the one mechanism that would have
caught a CLI printing the handle name where an address belongs. Across the two maple-preview runs
(1786047359, 1786053138) it was handed the user's request and nothing else, and it invented
`resolve_ada_handle.py`, `resolve_handles.py` and `resolve_ada.py`; twice it answered `runs:false`
while its own `success` field described a run. Its reasoning says why out loud: "I don't have the API
details", "I'll assume the script is in the current directory". Four firings across two runs, zero
executions of the deliverable.
"""
import unittest

from cria import execcheck, prompts


class TheProbeIsGivenTheWorkspaceTests(unittest.TestCase):
    def test_the_file_list_reaches_the_prompt(self):
        _, user = execcheck.intent_prompt("resolve an ada handle", files="resolve_handle.py\nREADME.md")
        self.assertIn("resolve_handle.py", user)
        self.assertIn("README.md", user)

    def test_the_prompt_forbids_naming_a_file_that_is_not_listed(self):
        _, user = execcheck.intent_prompt("t", files="a.py")
        self.assertIn("Do not name a file that is not on the list", user)

    def test_an_unreadable_workspace_says_so_rather_than_leaving_a_hole(self):
        _, user = execcheck.intent_prompt("t")
        self.assertIn("could not read the workspace", user)
        self.assertNotIn("{{FILES}}", user)

    def test_the_loop_passes_the_real_inventory(self):
        import inspect
        from cria import loop
        src = inspect.getsource(loop.live_execution_marker)
        self.assertIn("workspace_inventory(root)", src)


class AVerdictThatContradictsItselfIsNotAVerdictTests(unittest.TestCase):
    """`runs` is the field cria acts on and `false` switches the probe OFF entirely, so a false whose
    own narrative describes a run is the fail-open shape. Fail CLOSED, like an unparseable verdict."""

    CAPTURED = ('{"runs": false, "command": "", "success": "Yes, finishing it depends on running a '
                'program. The exact command would be `python3 resolve_ada.py`, and a correct run '
                'would produce output like:\\n\\nResolved address: <address>"}')

    def test_the_captured_contradiction_is_rejected(self):
        self.assertEqual(execcheck.parse_intent(self.CAPTURED), {})

    def test_an_honest_false_still_passes(self):
        for ok in ('{"runs": false, "command": "", "success": "No work was finished."}',
                   '{"runs": false, "command": "", "success": ""}',
                   '{"runs": false, "command": "", "success": "a library, nothing to execute"}'):
            self.assertEqual(execcheck.parse_intent(ok).get("runs"), False, ok)

    def test_an_honest_true_still_passes(self):
        got = execcheck.parse_intent(
            '{"runs": true, "command": "python3 resolve_handle.py goose", "success": "prints addr1…"}')
        self.assertTrue(got.get("runs"))
        self.assertEqual(got.get("command"), "python3 resolve_handle.py goose")

    def test_a_rejected_verdict_reads_as_inconclusive_not_as_nothing_to_run(self):
        """The empty dict must reach the branch that SAYS cria could not establish a run."""
        r = execcheck.evaluate("/nonexistent", execcheck.parse_intent(self.CAPTURED))
        self.assertEqual(r.verdict, execcheck.INCONCLUSIVE)


if __name__ == "__main__":
    unittest.main()
