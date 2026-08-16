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
        _, user = execcheck.intent_prompt("resolve an ada handle",
                                          files="  resolve_handle.py (100 B)\n  README.md (10 B)")
        self.assertIn("resolve_handle.py", user)
        self.assertNotIn("README.md", user)   # a document is not a program to run

    def test_the_prompt_forbids_naming_a_file_that_is_not_listed(self):
        _, user = execcheck.intent_prompt("t", files="  a.py (10 B)")
        self.assertIn("Never a file that is not on the list", user)

    def test_an_unreadable_workspace_says_so_rather_than_leaving_a_hole(self):
        _, user = execcheck.intent_prompt("t")
        self.assertIn("nothing in the workspace is a program", user)
        self.assertNotIn("{{FILES}}", user)

    def test_the_loop_passes_the_real_inventory(self):
        import inspect
        from cria import loop
        src = inspect.getsource(loop.live_execution_marker)
        self.assertIn("workspace_inventory(root)", src)


class CriasOwnSpillIsNotTheDeliverableTests(unittest.TestCase):
    """maple-preview 1786062317 call 0035: the workspace held ZERO coder files, so the only entry
    cria listed was its own 96 KB spilled spec — and the rule said the command MUST name a file from
    the list. The probe argued with itself for ~2,000 tokens ("it's a JSON file, not a script. That
    would be incorrect.") and then named the spec anyway."""

    REAL = ("WORKSPACE FILES in /tmp/suite-x (on-disk ground truth at judging time, newest first):\n"
            "  tmp/read-only/api.handle.me_openapi.json (96221 B)\n"
            "This list is complete — a file not listed here does not exist in the workspace.")

    def test_the_spill_artifact_is_not_offered_as_a_program(self):
        self.assertEqual(execcheck.runnable_listing(self.REAL), "")
        _, user = execcheck.intent_prompt("resolve a handle", files=self.REAL)
        self.assertNotIn("openapi.json", user)
        self.assertIn("nothing in the workspace is a program", user)

    def test_an_empty_list_makes_runs_false_a_legal_answer(self):
        _, user = execcheck.intent_prompt("t", files=self.REAL)
        self.assertIn("nothing runnable has been written yet", user)

    def test_real_programs_survive_the_filter(self):
        listing = ("  resolve_handle.py (4389 B)\n  README.md (1200 B)\n"
                   "  tmp/read-only/api.handle.me_openapi.json (96221 B)\n  live_test.py (666 B)")
        kept = execcheck.runnable_listing(listing)
        self.assertIn("resolve_handle.py", kept)
        self.assertIn("live_test.py", kept)
        self.assertNotIn("openapi.json", kept)
        self.assertNotIn("README.md", kept)

    def test_the_naming_rule_still_binds_when_there_are_programs(self):
        _, user = execcheck.intent_prompt("t", files="  resolve_handle.py (4389 B)")
        self.assertIn("Never a file that is not on the list", user)


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


class ABuildToolsRunTargetIsAProgramTests(unittest.TestCase):
    """The rule said the command "must name a file from the list". In cargo, maven, npm and rake
    projects the thing that runs is a TARGET, not a path — and `_NOT_A_PROGRAM` had already deleted
    Cargo.toml from the list before the prompt saw it, so the only legitimate answer was both absent
    and forbidden. Measured on the six-language battery at rust 0016 and node 0026."""

    def test_the_prompt_admits_a_runner_target(self):
        _, user = execcheck.intent_prompt("t", files="  src/main.rs (900 B)")
        self.assertIn("cargo run", user)
        self.assertIn("run target", user)

    def test_it_still_forbids_inventing_a_path(self):
        _, user = execcheck.intent_prompt("t", files="  src/main.rs (900 B)")
        self.assertIn("Never a file that is not on the list", user)

    def test_it_still_forbids_running_a_data_file(self):
        """The original defect: cria listed its own spilled openapi.json and the probe named it."""
        _, user = execcheck.intent_prompt("t", files="  src/main.rs (900 B)")
        self.assertIn("never a data file as though it were a program", user)


if __name__ == "__main__":
    unittest.main()
