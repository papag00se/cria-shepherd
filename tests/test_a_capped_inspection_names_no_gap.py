"""cria told a coder its finished work did not exist, six times, and it edited a 5/5 down to 4/5.

Cycle 4 cell 10, feed-pipeline-java x qwen35. The suite measured **all five checks passing at the
15-minute milestone**, by running them. The model said `task_complete`. Over the next 62 minutes
cria's satisfaction judge refused that completion six times, and these are its reasons, verbatim
from the log:

    02:36  "the current implementation is sequential"
    02:42  "The Importer.java is the original unmodified code (WORKERS_ENABLED=false,
            no OpenCSV usage, no malformed input handling, ...)"
    02:50  "The code claims tests pass but I cannot verify this without running tests"
    03:04  "The 4x speedup requirement cannot be verified - no baseline comparison exists"
    03:22  "current implementation is ~2.5x faster (0.4s vs 1.0s baseline), task requires 4x"

The verifier had already observed 4 threads spawned, opencsv importing the quoted-comma row, and an
**18.7x** speedup against a 4x bar. Every one of those sentences is a claim about a workspace the
judge had not finished reading — `loop.verify_inspect_capped` fired FIVE times in that session.
cria handed each one to the coder as the named gap, the coder went to work on code that was already
right, and the cell finished at 4/5. **cria took a 5/5 run and made it worse.**

THE MECHANISM: the inspection loop bounds a wandering judge with VERIFY_MAX_ROUNDS and then FORCES
an answer. That is correct — an unbounded judge is its own failure — but the forced answer was
allowed to assert things the judge never read, and the caller could not tell a finished look from an
interrupted one.

THE FIX, at both ends. `_judge_completion` tells its caller when it capped. `judge_satisfaction`
keeps the VERDICT (not satisfied — completion still fails closed, #13) and withholds the invented
REASON, falling back to the plain instruction. And the forced-answer prompt now says: if you did not
manage to read something, say "could not verify X" rather than stating it as fact.

#11b in one line: a mechanism that could not observe the thing it was asked about must not answer as
if it had.
"""

import unittest

from cria import loop, prompts, verifytools


class TheCapReachesTheCallerTests(unittest.TestCase):
    def test_the_judge_signature_carries_it(self):
        import inspect
        self.assertIn("capped", inspect.signature(loop._judge_completion).parameters)
        self.assertIn("capped", inspect.signature(loop._satisfaction_verdict).parameters)

    def test_it_is_appended_where_the_cap_is_logged(self):
        import inspect
        src = inspect.getsource(loop._judge_completion)
        i = src.index("loop.verify_inspect_capped")
        self.assertIn("capped.append(rounds)", src[i:i + 1200])


class AnUnfinishedLookNamesNoGapTests(unittest.TestCase):
    def test_the_reason_is_withheld_but_the_verdict_stands(self):
        import inspect
        src = inspect.getsource(loop.judge_satisfaction)
        self.assertIn("if inspection_capped and not satisfied:", src)
        # the VERDICT is still False — completion fails closed
        i = src.index("if inspection_capped and not satisfied:")
        self.assertIn('return False, prompts.load("unverified_step"), ""', src[i:i + 700])

    def test_it_is_logged_so_the_suppression_is_countable(self):
        import inspect
        self.assertIn("loop.satisfaction_gap_withheld",
                      inspect.getsource(loop.judge_satisfaction))

    def test_a_finished_look_still_names_its_gap(self):
        """The mechanism must not go quiet on the judges that DID read what they cite — a named,
        grounded gap is the whole reason the seat exists."""
        import inspect
        src = inspect.getsource(loop.judge_satisfaction)
        self.assertIn("_verdict_nudge(obj, satisfied, routes", src)


class TheForcedAnswerMayAbstainTests(unittest.TestCase):
    def test_it_is_told_to_say_it_could_not_verify(self):
        t = prompts.load_map("verify_tools")["answer_now"]
        self.assertIn("could not verify", t)
        self.assertIn("did not actually read", t)

    def test_it_still_demands_the_verdict_shape(self):
        t = prompts.load_map("verify_tools")["answer_now"]
        self.assertIn('"done": true|false', t)

    def test_the_cap_itself_is_unchanged(self):
        """Bounding a wandering judge is correct and stays. What changed is what a capped judge is
        allowed to assert, not whether it is capped."""
        self.assertEqual(verifytools.VERIFY_MAX_ROUNDS, 6)


if __name__ == "__main__":
    unittest.main()
