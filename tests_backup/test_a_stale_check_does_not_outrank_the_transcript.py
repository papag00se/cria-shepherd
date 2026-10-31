"""The pinned check block may claim to beat the transcript only while nothing newer has run.

Walked on the sub-40 pass: feed-pipeline-java x nemotron-elastic, scored 28. At call 0091 the
transcript handed to the compaction writer ended with a complete `mvn clean compile` from the turn
before, listing every real error including the decisive one — `com.opencsv.CSVParser cannot be
converted to java.lang.AutoCloseable`, which proves the jar was on the classpath and the code was
calling classes it does not have.

Above that, cria pinned a gate result four of the coder's own calls old, under the sentence:

    "if this section and the transcript disagree, this section is right"

The writer obeyed. Its briefing — the session's entire memory from then on — deleted all ten real
errors and said "The code compiles and runs". The build had never once compiled. The last 29 calls
were spent inside that invented frame, and the single line-numbered finding in the shipped REVIEW.md
is a defect cria made up.

The OUTPUT half of this fact was fixed long ago: `server._last_checks_note` stamps the age and, past
the same threshold, tells the reader its own newer result wins. The INPUT framing is the half that
went on asserting precedence unconditionally. One number now gates both.
"""

import unittest

from cria import loop, selfcompact


FLAG = "$ mvn clean compile — Importer.java:130:24: incompatible types: CSVParser"


class _Sess:
    def __init__(self, action_seq=0, last_gate_seq=0):
        self.action_seq, self.last_gate_seq = action_seq, last_gate_seq


class ThePrecedenceClauseIsConditionalTests(unittest.TestCase):
    def test_a_fresh_check_still_outranks_the_transcript(self):
        out = selfcompact.checks_input(FLAG, 0)
        self.assertIn("this section is right", out)
        self.assertIn(FLAG, out)

    def test_the_measured_case_does_not(self):
        """Four of the coder's own calls, which is what call 0091 actually had."""
        out = selfcompact.checks_input(FLAG, 4)
        self.assertNotIn("this section is right", out)
        self.assertIn("4 of the coder's own commands ago", out)
        self.assertIn("that later result is the current state", out)

    def test_the_verdict_itself_is_carried_either_way(self):
        for since in (0, 1, 2, 40):
            with self.subTest(since=since):
                self.assertIn(FLAG, selfcompact.checks_input(FLAG, since))

    def test_no_gate_says_nothing(self):
        self.assertEqual(selfcompact.checks_input("", 9), "")
        self.assertEqual(selfcompact.checks_input("   ", 0), "")

    def test_the_threshold_is_the_one_the_output_side_uses(self):
        """Two halves of one fact may not disagree about when it went stale."""
        from cria import server
        self.assertEqual(server._CHECKS_STALE_AFTER, selfcompact.CHECKS_STALE_AFTER)
        self.assertIn("this section is right",
                      selfcompact.checks_input(FLAG, selfcompact.CHECKS_STALE_AFTER - 1))
        self.assertNotIn("this section is right",
                         selfcompact.checks_input(FLAG, selfcompact.CHECKS_STALE_AFTER))


class TheAgeHasOneOwnerTests(unittest.TestCase):
    def test_it_counts_the_coders_calls_since_the_gate(self):
        self.assertEqual(loop.gate_age(_Sess(action_seq=91, last_gate_seq=87)), 4)

    def test_a_gate_that_has_not_run_is_not_negative(self):
        self.assertEqual(loop.gate_age(_Sess(action_seq=3, last_gate_seq=9)), 0)

    def test_no_session_is_zero_not_a_guess(self):
        self.assertEqual(loop.gate_age(None), 0)

    def test_both_compaction_paths_ask_the_same_function(self):
        """`server._gate_age` is a session lookup around it; nothing recomputes the subtraction."""
        import inspect

        from cria import server
        self.assertIn("gate_age(sess)", inspect.getsource(server._gate_age))
        for fn in (server._last_checks_note, server._compaction_body, server._compaction_transcript):
            # The SUBTRACTION, not the field name — the docstrings are free to name the incident.
            self.assertNotIn("action_seq", inspect.getsource(fn))


class BothCompactionPathsPassItTests(unittest.TestCase):
    def test_the_harness_path_hands_the_age_down(self):
        import inspect

        from cria import server
        self.assertIn("checks_age", inspect.getsource(server._compaction_transcript))
        self.assertIn("checks_age", inspect.getsource(server._compaction_body))

    def test_the_loops_own_compaction_hands_it_down(self):
        import inspect

        from cria.loop import Loop
        src = inspect.getsource(Loop)
        self.assertIn("gate_age(sess)", src)


if __name__ == "__main__":
    unittest.main()
