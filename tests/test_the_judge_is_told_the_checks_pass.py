"""The judge deciding whether the task is FINISHED was shown every failure and never the pass.

`_gate_notes` had three wordings — `red`, `testless`, `skipped` — all failures, and returned nothing
at all on a clean gate, on the rule "never a doubt-hedge on a clean run". That rule is right for the
CODER, which must not be taught to distrust a pass. It is wrong for this seat: the question here is
whether the work is done, and the current pass is the load-bearing fact for it.

Watched live on the targeted re-run of `rust-toml-cli × ternary-bonsai`. The model declared done at
call 0032 with the gate green — cria knew it, and said so to the coder in the very same breath:

    ⟦ctx:steer⟧ The repo's automated checks pass, but a completion check could not confirm the task
    is finished.

The judge, meanwhile, got `_work_log(keep_checks=True)` — every check result of the whole run,
including an `unclosed delimiter at src/main.rs:184` from calls 0018–0023 that had long been fixed —
and nothing saying the checks now pass. Its tools are `list_dir`, `read_file`, `verdict`: it cannot
run anything. So it read the current file, saw valid Rust, and talked itself out of it —

    "the actual compilation fails — indicating either stale build artifacts or a hidden character
     issue that isn't visible in the displayed text"

— and returned `satisfied: false`. The cell had 4 of 4 at the fifteen-minute milestone and ran a
further twenty-six minutes.

NOT A TOOL. Giving the judge a `check_build_and_tests` call was considered and rejected: it puts
GATHERING behind the model's judgement, and the failure being fixed is a weak model not doing the
obvious thing. #8 is deterministic code gathers, the reasoner judges. cria already holds this fact at
that exact moment — the completion gate has just run — so the fix is to stop withholding it.

ONLY WHEN IT IS TRUE NOW: gated on the gate having actually RUN, being clean, and `gate_fresh` — which
goes false the moment the workspace may have moved under the reading. A green cria cannot vouch for
right now is worse than none (#5b, #11b).
"""

import unittest

from cria import loop, prompts


class _Sess:
    def __init__(self, ran=True, red=False, fresh=True, flag="", testless=False, skipped=0):
        self.last_gate_ran, self.last_gate_red, self.gate_fresh = ran, red, fresh
        self.last_gate_flag, self.last_gate_testless, self.last_gate_skipped = flag, testless, skipped


GREEN = "reported no error-class problems"


class TheGreenReachesTheJudgeTests(unittest.TestCase):
    def test_a_clean_fresh_gate_is_stated_as_ground_truth(self):
        note = loop._gate_notes(_Sess())
        self.assertIn(GREEN, note)
        self.assertIn("[GROUND TRUTH]", note)

    def test_it_says_the_older_output_may_predate_the_edits(self):
        """The whole defect: the judge weighed stale failures against nothing."""
        self.assertIn("may predate edits", loop._gate_notes(_Sess()))

    def test_it_says_the_result_is_live_not_a_transcript_claim(self):
        self.assertIn("not a claim from the transcript", loop._gate_notes(_Sess()))


class ItNeverClaimsAGreenItCannotVouchForTests(unittest.TestCase):
    def test_a_stale_green_says_nothing(self):
        """`gate_fresh` goes false the moment the workspace may have moved (#5b)."""
        self.assertEqual(loop._gate_notes(_Sess(fresh=False)), "")

    def test_a_gate_that_never_ran_says_nothing(self):
        self.assertEqual(loop._gate_notes(_Sess(ran=False)), "")

    def test_red_still_wins(self):
        note = loop._gate_notes(_Sess(red=True, flag="src/main.rs:12: mismatched types"))
        self.assertIn("currently FAILING", note)
        self.assertNotIn(GREEN, note)

    def test_the_vacuous_green_disclosures_still_win(self):
        """A pass with no tests executed is not the pass this wording describes."""
        self.assertIn("NO tests were actually executed", loop._gate_notes(_Sess(testless=True)))
        self.assertIn("SKIPPED", loop._gate_notes(_Sess(skipped=3)))
        self.assertNotIn(GREEN, loop._gate_notes(_Sess(skipped=3)))


class ItIsNotATooLTests(unittest.TestCase):
    def test_the_judge_still_runs_nothing(self):
        """Read-only stays read-only — the judge asks for no execution and gets none (#23)."""
        from cria import verifytools
        names = sorted((t.get("function") or t).get("name") for t in verifytools.VERIFY_TOOLS)
        self.assertEqual(names, ["list_dir", "read_file"])

    def test_the_wording_is_in_a_prompt_file(self):
        self.assertIn("green", prompts.load_map("gate_notes"))

    def test_it_never_names_the_shim(self):
        import re
        self.assertIsNone(re.search(r"\bcria\b", prompts.load_map("gate_notes")["green"], re.I))


if __name__ == "__main__":
    unittest.main()
