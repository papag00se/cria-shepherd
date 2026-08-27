"""The check block must not present an old finding as the current state.

`_last_checks_note` renders the last gate's finding-set into the coder's prompt. It was headed
"the repo's own checks, most recent run" — true of a finding gathered twenty calls earlier, and read
as CURRENT. The finding persists until another gate runs, and a gate can be cancelled.

L5 feed-pipeline-java x ternary-bonsai: a gate found a compile error at 10 minutes; the coder's own
`mvn clean compile` returned BUILD SUCCESS at 17.4 minutes; the periodic gate at 22.8 minutes that
would have refreshed it was cancelled by a compaction (`ran: false, why: history-rewritten`); the
stale block asserted the error in 24 of the run's 42 prompts. The coder believed cria over its own
compiler, rewrote the file at 26.8 minutes and re-broke a build that had been green for nine
minutes. Rebuilding the 17.4-minute state confirms it compiles and handles the messy feed.

cria cannot know whether a newer command contradicts a finding. It does know how old the finding is.
"""
import unittest

from cria import server


class _Sess:
    def __init__(self, seq, gate_seq, flag):
        self.action_seq, self.last_gate_seq, self.last_gate_flag = seq, gate_seq, flag


class _Server:
    def __init__(self, sess):
        self.loop = type("L", (), {"_store": {"k": sess}})()


FLAG = "[GROUND TRUTH] Importer.java:109: unreported exception CsvValidationException"


class AStaleCheckBlockSaysItIsStale(unittest.TestCase):

    def _note(self, seq, gate_seq):
        return server._last_checks_note(_Server(_Sess(seq, gate_seq, FLAG)), "k")

    def test_a_fresh_finding_is_not_hedged(self):
        note = self._note(2, 2)
        self.assertIn(FLAG, note)
        self.assertNotIn("since that check", note,
                         "a finding gathered this turn is the current state; saying otherwise is noise")

    def test_an_old_finding_carries_its_age_and_the_newer_result_wins(self):
        note = self._note(26, 2)
        self.assertIn(FLAG, note, "the finding is still reported — this is not silence")
        self.assertIn("24", note, "the coder is told how many of its own calls have passed")
        self.assertIn("your own newer result is the current state", note)

    def test_the_incident_shape_is_covered_at_its_own_distance(self):
        """24 prompts carried it in the walked run; the note must fire well before that."""
        self.assertIn("since that check", self._note(5, 2))

    def test_no_flag_means_no_block(self):
        self.assertEqual("", server._last_checks_note(_Server(_Sess(9, 1, "")), "k"))


if __name__ == "__main__":
    unittest.main()
