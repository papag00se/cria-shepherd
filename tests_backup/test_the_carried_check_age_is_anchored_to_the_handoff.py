"""P2 (phi4/Java A6 seg-11/18/19): the carried check note said "gathered 8 of your calls ago ... You
have run 8 of your own commands since" in EVERY later call — it is baked into the briefing the harness
keeps in history, so a now-relative count froze while the coder ran 0, 1, 2... more commands. The age
is now stated as of the moment the handoff was written, which stays true however long it is carried."""
import unittest

from cria import server
from tests.test_a_stale_check_block_says_it_is_stale import _Server, _Sess, FLAG


class TheCarriedAgeIsAnchored(unittest.TestCase):
    def test_no_now_relative_phrase_survives_into_the_baked_text(self):
        note = server._last_checks_note(_Server(_Sess(10, 2, FLAG)), "k")
        self.assertNotIn("calls ago", note)
        self.assertIn("8 of your calls before this handoff was written", note)
        self.assertIn("When this handoff was written you had run 8 of your own commands", note)

    def test_fresh_note_is_anchored_too(self):
        note = server._last_checks_note(_Server(_Sess(2, 2, FLAG)), "k")
        self.assertIn("when this handoff was written", note)
        self.assertNotIn("just now", note)
