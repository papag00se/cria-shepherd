"""cria told its own steer author an action had been repeated three times. It had been taken once.

`shipping-rates-rb × ternary-bonsai`, 2026-08-17. `guard_track_repetition` had two trigger routes —
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

**The action route was removed on 2026-08-19** (measured in
`docs/audits/base-vs-cria-footgun-patterns.md`: BASE runs containing three or more identical
consecutive calls averaged 51%, the CRIA runs this steer fired in averaged 48%). One route reaches
the redirect now, so the two can no longer share a sentence. What is still tested here is that the
surviving route says what it counted, and counts what it says.
"""

import unittest

from cria import loop, prompts


def _gs(count, action="exec_command {\"cmd\":\"which bundler\"}"):
    gs = loop.GuardState()
    gs.repeat_count, gs.repeat_action = count, action
    return gs


class TheSentenceDescribesTheTriggerThatFiredTests(unittest.TestCase):
    def test_a_refusal_is_reported_as_a_refusal(self):
        said = loop._STEER_TRIGGER["refusal"](_gs(3), 1)
        self.assertIn("3 of its recent calls were refused", said)
        self.assertNotIn("repeating the SAME action", said)

    def test_the_supervisor_is_never_named_to_the_model(self):
        """#17. This sentence said "cria REFUSED …" and was the last live occurrence of the token in
        model-facing text — 47 in the post-fix capture window, still firing on 2026-08-23. The steer
        author reads it as established fact and writes the steer the coder then reads."""
        for cond, gs in (("refusal", _gs(3)), ("wheel_spin", loop.GuardState()),
                         ("thrash", loop.GuardState())):
            with self.subTest(condition=cond):
                self.assertNotIn("cria", loop._STEER_TRIGGER[cond](gs, 1).lower())

    def test_the_sentences_live_in_a_prompt_file(self):
        """#22 — and all three were inline f-strings carrying measured incidents in their comments."""
        keys = prompts.load_map("steer_triggers")
        self.assertEqual(set(keys), {"refusal", "wheel_spin", "thrash"})

    def test_the_number_is_the_one_measured_not_the_threshold(self):
        """The walked failure in one line: five refusals must not be reported as three."""
        self.assertIn("5", loop._STEER_TRIGGER["refusal"](_gs(5), 1))

    def test_the_measured_action_is_still_named(self):
        self.assertIn("which bundler", loop._STEER_TRIGGER["refusal"](_gs(3), 1))

    def test_the_action_route_is_gone_from_the_sentence(self):
        """No input may produce the retired route's wording — there is no route behind it."""
        for n in (0, 1, 3, 9):
            with self.subTest(n=n):
                self.assertNotIn("SAME action", loop._STEER_TRIGGER["refusal"](_gs(n), 1))


class TheCodersRedirectSaysTheSameThingTests(unittest.TestCase):
    """Both seats read one observation, so they cannot describe the same fire differently."""

    def _canned(self, gs):
        return prompts.render("redirect_canned", ground_truth="", **loop._repeat_observation(gs))

    def test_a_refusal_says_the_calls_did_not_run(self):
        said = self._canned(_gs(3))
        self.assertIn("refused", said.lower())
        self.assertIn("none of them ran", said.lower())

    def test_it_no_longer_claims_the_actions_were_consecutive(self):
        """The refusal window is WINDOWED. "in a row" was never true."""
        self.assertNotIn("in a row", self._canned(_gs(3)))

    def test_an_unfired_trigger_states_no_number_at_all(self):
        """Saying less is allowed; saying a number cria did not count is not (#5b)."""
        said = self._canned(_gs(0))
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
        """`blocked` is in hand at that line; the constant was not."""
        import inspect
        src = inspect.getsource(loop.guard_track_refusals)
        self.assertIn("gs.repeat_count = blocked", src)
        self.assertNotIn("count=REPEAT_FINGERPRINT_N", src)

    def test_the_quoted_call_is_one_that_was_actually_refused(self):
        """The steer names "the most recent" refused call. It used to name whatever call was in
        flight when the counter tripped — a call cria had not refused at all."""
        import inspect
        src = inspect.getsource(loop.guard_track_refusals)
        self.assertIn("gs.repeat_action = last_refused", src)


if __name__ == "__main__":
    unittest.main()
