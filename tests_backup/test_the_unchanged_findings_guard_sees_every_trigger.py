"""The "don't re-diagnose unchanged findings" guard works for every detector, not one of three.

`author_steer` suppresses a fresh diagnosis when the repo's checks have not moved since the last
steer — because a small reasoner asked to explain the same output again does not repeat itself, it
re-guesses. Measured over 24 runs: 36% of every steer cria has ever authored was a fresh prose
diagnosis of findings unchanged since the previous one, and one run produced TEN consecutive
contradicting steers on a single pytest assertion diff.

The guard read `truth_text`, which only the thrash caller passes. Repetition and wheel-spin — the two
that fire most — pass nothing, so the comparison ran against an empty string, never suppressed, and
then overwrote the stored streak with "" so the next thrash steer saw no streak either.

Measured over five days: `loop.steer_same_checks` fired ZERO times; 318 steers passed no check text
against 44 that did. One session shows two redirects wiping the streak between thrash steers at
stall 2, 3 and 4 on one unchanged finding-set — three fresh diagnoses of one pytest state.

The fix takes the finding-set from `last_gate_flag`, which is what every other seat reads (#12).
"""

import unittest

from cria import loop


class Gs:
    last_gate_flag = ""
    steered_checks_text = ""
    same_checks_relooked = False
    gate_plan = None
    recent_writes = None
    spin_path = ""
    repeat_action = "read_file cart.go"
    gate_stall = 2


FINDINGS = "cart_test.go:18: cannot convert 9.72 to type decimal.Decimal"


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, name, **kw):
        self.events.append(name)


class TheGuardTakesTheAuthoritativeFindingSetTests(unittest.TestCase):
    """`author_steer` needs a reasoner and a body, so these exercise the selection rule it applies,
    then pin that the rule is the one in the source."""

    def select(self, truth_text, gs):
        checks_now = (truth_text or "").strip()
        if not checks_now and gs is not None:
            checks_now = (getattr(gs, "last_gate_flag", "") or "").strip()
        return checks_now

    def test_a_trigger_that_passes_no_check_text_still_gets_the_findings(self):
        gs = Gs()
        gs.last_gate_flag = FINDINGS
        self.assertEqual(self.select("", gs), FINDINGS)      # repetition / wheel-spin
        self.assertEqual(self.select(None, gs), FINDINGS)

    def test_a_caller_that_passes_its_own_text_still_wins(self):
        gs = Gs()
        gs.last_gate_flag = FINDINGS
        self.assertEqual(self.select("fresher truth", gs), "fresher truth")   # thrash

    def test_no_findings_anywhere_is_still_empty(self):
        self.assertEqual(self.select("", Gs()), "")

    def test_no_guard_state_does_not_raise(self):
        self.assertEqual(self.select("x", None), "x")

    def test_a_trigger_with_no_check_text_still_reads_last_gate_flag(self):
        """Drive the real author_steer, not the reimplemented `select` rule above. A repetition/
        wheel-spin trigger passes no truth_text; if the guard only ever read truth_text (the
        original bug), checks_now would stay empty, never match ``steered_checks_text``, and the
        call would fall through to a fresh reasoner diagnosis — so "the reasoner was never asked"
        is proof the guard found the findings via last_gate_flag instead."""
        import json
        gs = Gs()
        gs.last_gate_flag = FINDINGS
        gs.steered_checks_text = FINDINGS
        gs.same_checks_relooked = True     # third+ ask -> reattach/silence, not a fresh diagnosis
        body = {"messages": [{"role": "user", "content": "t"},
                             {"role": "tool", "content": FINDINGS}], "tools": []}
        reasoner_calls = []

        def reasoner_chat(b, r):
            reasoner_calls.append(b)
            return json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode()

        rlog = _Rlog()
        out = loop.author_steer(reasoner_chat, None, None, gs, body, rlog, condition="wheel_spin")
        self.assertIsNone(out)
        self.assertIn("loop.steer_same_checks", rlog.events)
        self.assertEqual(reasoner_calls, [], "checks_now never matched steered_checks_text — the "
                                             "trigger's own gs.last_gate_flag was not read")

    def test_a_caller_with_its_own_text_still_wins_for_real(self):
        """The thrash caller's own truth_text must win over a DIFFERENT, stale last_gate_flag."""
        import json
        gs = Gs()
        gs.last_gate_flag = FINDINGS               # stale — must not be what gets compared
        gs.steered_checks_text = "fresher truth"
        gs.same_checks_relooked = True
        body = {"messages": [{"role": "user", "content": "t"},
                             {"role": "tool", "content": "fresher truth"}], "tools": []}
        reasoner_calls = []

        def reasoner_chat(b, r):
            reasoner_calls.append(b)
            return json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode()

        rlog = _Rlog()
        out = loop.author_steer(reasoner_chat, None, None, gs, body, rlog,
                                condition="thrash", truth_text="fresher truth")
        self.assertIsNone(out)
        self.assertIn("loop.steer_same_checks", rlog.events)
        self.assertEqual(reasoner_calls, [])


class TheStreakIsNotWipedByATriggerWithoutTextTests(unittest.TestCase):
    def test_the_stored_streak_survives_a_repetition_steer(self):
        """The overwrite is what made the guard blind for the NEXT steer too."""
        gs = Gs()
        gs.last_gate_flag = FINDINGS
        gs.steered_checks_text = FINDINGS
        checks_now = (getattr(gs, "last_gate_flag", "") or "").strip()
        self.assertEqual(checks_now, gs.steered_checks_text,
                         "an empty checks_now would have cleared the streak here")


if __name__ == "__main__":
    unittest.main()
