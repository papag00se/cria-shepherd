"""Two faults from the maple 1/4 walk, both cria letting prose overwrite a fact it holds exactly.

1. THE ROLLUP DENYING FILES CRIA CAN SEE. maple-preview 1786218955, call 0029: cria injected

     ⟦ctx:rollup⟧ … The Python script that resolves an Ada Handle to a Cardano address has not been
     written. Unit tests have not been added. … The implementation has not yet been started; only
     the plan and API analysis remain.

   over a ⟦ctx:files⟧ block six hundred lines above it in the SAME prompt listing
   `ada_handle_resolver.py (4633 B)` and `test_da_hash_resolver.py (6968 B)`, and over a real run
   reading `2 failed, 7 passed`. Repeated at call 0059 with three files on disk including the
   README. cria composes both halves; the listing is read off the disk this turn and the briefing is
   a small model's prose about the past, so where they disagree the disk wins.

2. THE DANGLING JSON STEER. Call 0065 (finish_reason `stop`, not a length cut): the steer author
   wrote a first-person verdict essay and then opened a JSON object it never closed. cria shipped
   the whole thing as ⟦ctx:steer⟧ [REDIRECT]. Inside the fragment was the false claim that ended the
   run — "a list with 2 items is returned instead of 1" — and the coder, which had just reasoned its
   way to the real bug, deferred to it and wrote nothing more before the 30-minute wall.
"""
import unittest

from cria import loop

FILES = ("ada_handle_resolver.py (4633 B)\n"
         "test_da_hash_resolver.py (6968 B)\n"
         "README.md (2612 B)")

# the real call-0029 rollup, abbreviated to its claims
ROLLUP = ("The openapi.json has been read and analyzed.\n"
          "The Python script ada_handle_resolver.py has not been written.\n"
          "Unit tests have not been added to test_da_hash_resolver.py.\n"
          "A live test for the handles goose and papagoose has not been created.\n"
          "The resolver returns the raw payload.")


class TheDiskRefutesTheBriefingTests(unittest.TestCase):
    def test_a_denial_of_a_file_on_disk_is_dropped(self):
        dropped = loop._briefing_denies_real_files(ROLLUP, FILES)
        self.assertEqual(len(dropped), 2)
        self.assertTrue(any("ada_handle_resolver.py has not been written" in d for d in dropped))
        self.assertTrue(any("test_da_hash_resolver.py" in d for d in dropped))

    def test_a_TRUE_denial_survives(self):
        """No live-test file existed — that sentence was right and must not be scrubbed."""
        kept = loop._scrub_briefing(ROLLUP, FILES)
        self.assertIn("A live test for the handles goose and papagoose has not been created", kept)

    def test_the_rest_of_the_briefing_survives(self):
        kept = loop._scrub_briefing(ROLLUP, FILES)
        self.assertIn("The openapi.json has been read", kept)
        self.assertIn("The resolver returns the raw payload", kept)
        self.assertNotIn("has not been written", kept)

    def test_with_no_file_list_nothing_is_touched(self):
        """No listing → cria cannot refute anything → the briefing stands whole."""
        self.assertEqual(loop._scrub_briefing(ROLLUP, ""), ROLLUP)
        self.assertEqual(loop._briefing_denies_real_files(ROLLUP, ""), [])

    def test_a_file_not_on_the_listing_is_left_alone(self):
        b = "The deployment script deploy.sh has not been written."
        self.assertEqual(loop._scrub_briefing(b, FILES), b)

    def test_a_positive_statement_about_a_file_is_untouched(self):
        b = "ada_handle_resolver.py is written and the CLI parses its argument."
        self.assertEqual(loop._scrub_briefing(b, FILES), b)


class TheDanglingJsonSteerTests(unittest.TestCase):
    # verbatim shape of call 0065: essay, then an unterminated object
    ESSAY = ('Looking at this situation, I need to decide if the coder is stuck or making progress. '
             "The test failures reveal specific issues. I'll give the imperative directive to fix "
             'these concrete issues. { "Fix the ada_handle_resolver.py code: redefine the '
             'resolve_handle method. Check that hex mode handling matches the expected behavior '
             'where a list with 2 items is returned instead of 1."')

    def test_it_is_refused_whole(self):
        self.assertIsNone(loop._steer_or_none(self.ESSAY))

    def test_a_real_directive_is_delivered(self):
        d = "You are stuck. Read resolve_handle, then run pytest -q and fix what it names."
        self.assertEqual(loop._steer_or_none(d), d)

    def test_balanced_json_inside_a_directive_survives(self):
        d = ('Fix the mock so it returns:\n```json\n{"name": "goose"}\n```\nthen rerun the tests.')
        out = loop._steer_or_none(d)
        self.assertIsNotNone(out)
        self.assertIn('"name": "goose"', out)

    def test_a_brace_in_prose_survives(self):
        d = "Replace the placeholder {handle} in the URL with the real value, then run it."
        self.assertIsNotNone(loop._steer_or_none(d))


if __name__ == "__main__":
    unittest.main()
