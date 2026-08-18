"""cria told its own steer author an action had been repeated three times. It had been taken once.

`shipping-rates-rb × ternary-bonsai`, 2026-08-17. `guard_track_repetition` has two trigger routes —
the same action seen N times in the window, and cria REFUSING N calls — and both fell into one
reporting site that emitted a hardcoded `REPEAT_FINGERPRINT_N` and set `repeat_action` to whatever
call happened to be in flight. So the refusal route fired and cria wrote:

    WHAT TRIPPED THE DETECTOR:
    It keeps repeating the SAME action 3× without the outcome changing:
    exec_command {"cmd":"which bundler 2>/dev/null; which bundle3.2 ..."}

Counted from the run's own response captures, the coder issued that command **once**, at call 0031.
The three were cria's refusals, of three DIFFERENT commands.

The steer author read it literally and wrote it back as settled — *"you've already confirmed they're
unavailable (three failed attempts)"* — and on that premise authored:

    implement EU membership as a hardcoded constant map of two-letter country codes
    (e.g., { "DE" => true, "FR" => true }) inside the module instead. That satisfies the
    task requirement without needing an external gem that can't be installed here.

The task says, in those words: **"Do not hardcode EU membership."** The author's own system prompt
carries the guard against exactly this — *"Do not choose the IMPLEMENTATION… Measured: directives
that picked the approach cost nine checks — one told the coder to hand-roll a list the task had
explicitly forbidden hand-rolling"* — and it was ignored, because a false count made the premise
look settled. The coder obeyed, read the steer as the user speaking, wrote an EU list missing HR and
PL with eleven duplicate entries, and spent six calls arguing itself back out.

**#12, exactly: a metric surfaced from the trigger instead of from the event.** cria had both real
numbers in hand at that line — `matches + 1` for the action route, `blocked` for the refusal route —
and reported the constant. The fix is not to soften the sentence; it is to say what was counted.

"in a row" went too. The action route is windowed, not consecutive, so it was never true there
either.
"""

import unittest

from cria import loop, prompts


def _gs(kind, count, action="exec_command {\"cmd\":\"which bundler\"}"):
    gs = loop.GuardState()
    gs.repeat_kind, gs.repeat_count, gs.repeat_action = kind, count, action
    return gs


class TheSentenceDescribesTheTriggerThatFiredTests(unittest.TestCase):
    def test_a_refusal_is_reported_as_a_refusal(self):
        said = loop._STEER_TRIGGER["repetition"](_gs("refusal", 3), 1)
        self.assertIn("REFUSED 3", said)
        self.assertNotIn("repeating the SAME action", said)

    def test_a_real_repetition_is_still_reported_as_one(self):
        said = loop._STEER_TRIGGER["repetition"](_gs("repetition", 3), 1)
        self.assertIn("SAME action 3", said)
        self.assertNotIn("REFUSED", said)

    def test_the_number_is_the_one_measured_not_the_threshold(self):
        """The walked failure in one line: five refusals must not be reported as three."""
        self.assertIn("5", loop._STEER_TRIGGER["repetition"](_gs("refusal", 5), 1))
        self.assertIn("7", loop._STEER_TRIGGER["repetition"](_gs("repetition", 7), 1))

    def test_the_measured_action_is_still_named(self):
        for kind in ("refusal", "repetition"):
            with self.subTest(kind=kind):
                self.assertIn("which bundler", loop._STEER_TRIGGER["repetition"](_gs(kind, 3), 1))


class TheCodersRedirectSaysTheSameThingTests(unittest.TestCase):
    """Both seats read one observation, so they cannot describe the same fire differently."""

    def _canned(self, gs):
        return prompts.render("redirect_canned", ground_truth="", **loop._repeat_observation(gs))

    def test_a_refusal_says_the_calls_did_not_run(self):
        said = self._canned(_gs("refusal", 3))
        self.assertIn("refused", said.lower())
        self.assertIn("did not run", said.lower().replace("none of them ran", "did not run"))

    def test_a_repetition_says_the_action_was_taken_again(self):
        self.assertIn("same action 3 times", self._canned(_gs("repetition", 3)).lower())

    def test_it_no_longer_claims_the_actions_were_consecutive(self):
        """The action route is WINDOWED. "in a row" was false on both routes."""
        for gs in (_gs("refusal", 3), _gs("repetition", 3)):
            self.assertNotIn("in a row", self._canned(gs))

    def test_an_unset_route_states_no_number_at_all(self):
        """Saying less is allowed; saying a number cria did not count is not (#5b)."""
        said = self._canned(_gs("", 0))
        self.assertNotIn("3", said)
        self.assertIn("not getting a new outcome", said)

    def test_every_render_site_goes_through_the_one_owner(self):
        """Two seats render this template. Neither may build the tokens itself — that is how the
        two routes came to share one sentence in the first place."""
        import inspect
        src = inspect.getsource(loop)
        sites = src.count('"redirect_canned"')
        self.assertEqual(src.count("**_repeat_observation(gs)"), sites)
        self.assertNotIn('"redirect_canned", repeat_action=', src)


class TheCountComesFromTheEventTests(unittest.TestCase):
    def test_the_fire_site_records_what_it_observed(self):
        """`matches + 1` and `blocked` are both in hand at that line; the constant was not."""
        import inspect
        src = inspect.getsource(loop.guard_track_repetition)
        self.assertIn("gs.repeat_count = blocked if blocked_fires else matches + 1", src)
        self.assertNotIn("count=REPEAT_FINGERPRINT_N", src)

    def test_the_emitted_event_carries_the_route(self):
        import inspect
        self.assertIn("trigger=gs.repeat_kind", inspect.getsource(loop.guard_track_repetition))


if __name__ == "__main__":
    unittest.main()
