"""cria ran the deliverable, watched it fail, and told only the judge.

THE resolver_cli FAILURE OF BOTH 2026-08-07 runs, walked line by line. On mellum2 call 0070 and on
maple-preview call 0085 cria built this and put it in the satisfaction judge's evidence:

    ⟦ctx:live-execution⟧ The delivered program was run and did not show the result it was meant to.
    Command: `python handle_resolver.py goose` — … — but it exited 1.

All three `live_execution_marker` call sites append it to `ev`/`evidence`. None of them reaches the
coder. So the only party that could fix the command-line entry point was never told cria had run it
and it failed — while the judge, invited by the marker's own closing hedge to treat it as "evidence,
not a verdict", discounted it and let the session end. Two models, two runs, same score line.

The steer the coder DID get in place of it, mellum call 0074, verbatim:

    ⟦ctx:steer⟧ The repo's automated checks pass, but the task is NOT fully done yet:
    The live tests … are intentionally disabled and documented as such.
    Proposed fix: Leave the live tests skipped … No code changes are required.

cria had the exit code and sent boilerplate. This is the "computed a fact, delivered it to nobody"
shape, in the one channel where the fact was an exit code cria observed itself.
"""
import unittest

from cria import execcheck, loop, prompts

# verbatim from ada-handles_mellum2_codex_poff_1786167643 call 0070
REAL_MARKER = (
    "⟦ctx:live-execution⟧ The delivered program was run and did not show the result it was meant "
    "to. Command: `python handle_resolver.py goose` — expected: {'resolved_address': 'addr1...', "
    "'holder_address': 'addr1...', 'total_handles': 42} — but it exited 1. Everything else the "
    "checks cover passed. This is evidence about the program, not a verdict on the whole task.")


class _Sess:
    def __init__(self, finding=""):
        self.exec_finding = finding


class TheFindingReachesTheCoderTests(unittest.TestCase):
    def test_the_completion_steer_carries_it(self):
        text = prompts.render("done_incomplete", reason="a deliverable is missing",
                              check_state=prompts.load_map("done_check_state")["passed"],
                              exec_finding=loop._exec_finding_line(_Sess(REAL_MARKER)))
        self.assertIn("but it exited 1", text)
        self.assertIn("python handle_resolver.py goose", text)

    def test_nothing_to_say_says_nothing(self):
        text = prompts.render("done_incomplete", reason="a deliverable is missing",
                              check_state=prompts.load_map("done_check_state")["passed"],
                              exec_finding=loop._exec_finding_line(_Sess("")))
        self.assertNotIn("live-execution", text)
        self.assertNotIn("{{EXEC_FINDING}}", text)   # the slot is filled, never left raw

    def test_it_is_consumed_once(self):
        """Parked, it would re-assert a failure the coder may have just fixed — the stale-ground-truth
        fault this same walk found four separate times."""
        sess = _Sess(REAL_MARKER)
        self.assertIn("exited 1", loop._exec_finding_line(sess))
        self.assertEqual(loop._exec_finding_line(sess), "")


class OnlyADefectInTheCodersProgramTests(unittest.TestCase):
    """`inconclusive` is a gap in what CRIA could establish. Telling the coder "I could not work out
    how to run your program" is noise it cannot act on — principle 3."""

    def test_not_observed_is_owed_to_the_coder(self):
        r = execcheck.ExecResult(execcheck.NOT_OBSERVED, command="python handle_resolver.py goose",
                                 expect="the resolved address", exit_code=1, why="it exited 1")
        self.assertIn("exited 1", r.marker)
        self.assertEqual(r.verdict, execcheck.NOT_OBSERVED)

    def test_inconclusive_is_not(self):
        r = execcheck.ExecResult(execcheck.INCONCLUSIVE, why="no command could be agreed")
        self.assertNotEqual(r.verdict, execcheck.NOT_OBSERVED)
        self.assertIn("inconclusive", r.marker.lower())

    def test_a_confirmed_run_stays_silent(self):
        self.assertEqual(execcheck.ExecResult(execcheck.CONFIRMED).marker, "")


class TheMarkerStillNeverGatesTests(unittest.TestCase):
    """Operator's ruling 2026-08-01: this check is evidence and nothing more. Delivering the finding
    to the coder must not have turned it into something that can refuse work."""

    def test_the_finding_is_only_ever_appended_to_a_steer_cria_was_already_sending(self):
        src = loop._exec_finding_line.__doc__ or ""
        self.assertIn("or \"\" when there is nothing to say", src)
        # it is rendered into done_incomplete, which only exists on a not-satisfied verdict
        self.assertIn("{{EXEC_FINDING}}", prompts.load("done_incomplete"))


if __name__ == "__main__":
    unittest.main()
