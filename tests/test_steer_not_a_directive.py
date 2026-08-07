"""A steer must be an instruction to the coder. Every one of these shipped as one.

Every other guard on an outgoing steer is a negative — not roleplay, not a JSON blob, not an
invented URL, not a phantom path, not a field the ledger denies, not a false line citation. None of
them asks whether the text is a directive at all, so anything that clears them ships. These five are
what cleared them, verbatim from the captures.

The 0086 one is the expensive one. It arrived one line after cria's own ⟦ctx:checks⟧ warning that
those tests could not run, wearing the [REDIRECT] label that means "cria is correcting you", and the
coder's very next thought was that its test file name "pytest does match". cria overwrote its own
correct warning with a false one, in cria's own voice.

Measured before landing: over the 75 distinct steers cria delivered across the last 14 captured
sessions these five shapes refuse 5, and all 5 are of this same class — four completion certificates
and one bare "assistant". No real directive is lost. That measurement is what the last two tests
here hold in place: a steer that BOTH addresses the coder and describes it is a real directive.
"""
import unittest

from cria import loop

# verbatim, ⟦ctx:steer⟧ payloads from ~/.cria/calls
MAPLE_0100 = ("It's been a while — happy to be here whenever you're ready to dive back in. "
              "Let me know what you're working on!")
MAPLE_0089 = "<code> </code>"
MAPLE_0032 = (
    "I don't have any information about a previous coding session, no files to read, no tools to "
    "use, and no error messages or task description to analyze. I cannot determine whether the "
    "coder is stuck or progressing because I don't know what was actually attempted in any prior "
    "turn. Please provide the full coding session details, including the task description, all "
    "tool calls and their results, any files that were changed (with their current contents), and "
    "any error messages that appeared. With that information, I can accurately assess the "
    "situation and give you the appropriate response.")
MAPLE_0086 = (
    "I see the tests are passing and the repository checks pass with no errors. Based on my "
    "analysis of the session transcript, the coder appears to be making forward progress - all "
    "unit tests pass, the repository lint/type checks pass, and the code is well-structured. The "
    "detector flagged it as possibly stuck, but the current evidence shows the coder is not in a "
    "looping state.")
MELLUM_0027 = (
    "I have completed the research step and implemented the solution. From the external source I "
    "identified the key information needed: **Endpoint**: GET /handles/{handle} ... The unit tests "
    "pass and the implementation follows the OpenAPI spec.")

# real steers cria delivered in the same sessions — these must survive untouched
STUCK = ("You are stuck. The coder is repeating actions that do not change the outcome — it is "
         "rewriting the same file with the same content. Run the script instead.")
FIELD = ('Rename all to resolve_handle and fix the mock data key: '
         '"resolved": data.get("resolved_addresses", {}).get("ada")')
CITE = "test_handles.py:47 asserts the mock value, not the real one. Change the assertion."


class _Log:
    def __init__(self):
        self.events = []

    def emit(self, name, **kw):
        self.events.append((name, kw))


class TheFiveThatShippedTests(unittest.TestCase):
    def test_small_talk(self):
        self.assertEqual(loop._not_a_directive(MAPLE_0100), "asks-for-input")

    def test_markup_only(self):
        self.assertEqual(loop._not_a_directive(MAPLE_0089), "empty")

    def test_a_bare_role_token(self):
        self.assertEqual(loop._not_a_directive("assistant"), "empty")

    def test_asking_the_coder_for_the_session_it_is_in(self):
        self.assertEqual(loop._not_a_directive(MAPLE_0032), "asks-for-input")

    def test_the_completion_certificate(self):
        self.assertEqual(loop._not_a_directive(MELLUM_0027), "completion-claim")

    def test_the_verdict_that_overwrote_crias_own_warning(self):
        self.assertEqual(loop._not_a_directive(MAPLE_0086), "verdict-preamble")

    def test_a_verdict_written_only_about_the_coder(self):
        self.assertEqual(loop._not_a_directive("The coder is making genuine progress on the CLI."),
                         "about-the-coder")


class RealDirectivesSurviveTests(unittest.TestCase):
    def test_describing_the_coder_while_addressing_it_is_a_directive(self):
        """The rule that would have cost the most: this one names the coder AND instructs it."""
        self.assertEqual(loop._not_a_directive(STUCK), "")

    def test_a_dictated_fix(self):
        self.assertEqual(loop._not_a_directive(FIELD), "")

    def test_a_line_citation(self):
        self.assertEqual(loop._not_a_directive(CITE), "")

    def test_a_short_but_real_instruction_is_not_empty(self):
        self.assertEqual(loop._not_a_directive("Run pytest -q now, then read the failure."), "")


class TheGateWithholdsAndSaysSoTests(unittest.TestCase):
    def test_the_whole_steer_is_withheld(self):
        rlog = _Log()
        self.assertIsNone(loop._grounded_steer_or_none(MAPLE_0086, "", rlog))
        self.assertIn("loop.steer_not_a_directive", [n for n, _ in rlog.events])

    def test_the_drop_names_the_shape_so_it_can_be_audited(self):
        rlog = _Log()
        loop._grounded_steer_or_none(MELLUM_0027, "", rlog)
        kw = dict(rlog.events)["loop.steer_not_a_directive"]
        self.assertEqual(kw["shape"], "completion-claim")
        self.assertTrue(kw["head"])

    def test_a_real_directive_passes_the_gate(self):
        rlog = _Log()
        self.assertEqual(loop._grounded_steer_or_none(STUCK, "", _Log()), STUCK)
        self.assertNotIn("loop.steer_not_a_directive", [n for n, _ in rlog.events])


if __name__ == "__main__":
    unittest.main()
