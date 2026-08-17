"""Four backstops abort a stream, and the capture header called all four the rumination guard.

The header rendered that ONE guard's two counters — `hits` and `reasoning_tokens` — which only it
ever sets. Measured live on cycle 4 cell 4, feed-pipeline-java x gemma4, where a WINDOW-EXHAUSTED
abort was filed as:

    ⟦RUMINATION GUARD FIRED⟧ None second-guessing markers · ~None reasoning tokens · aborted
    mid-stream and re-prompted to refocus

Two things wrong in one line. It names the wrong guard, and it prints `None` for numbers no guard
counted — which is the defect this same file already records fixing once, on the degenerate-tail
branch: "It used to report hits=0 and pass len(gen_tail) — a CHARACTER count — as reasoning_tokens,
and the notice built from that told the coder it 'hit 0 second-guessing phrases after ~2048
reasoning tokens'. A guard must not invent the numbers it fired on." That fix reached one of four.

The capture is the record a walk reads to answer "why did this turn stop", and 12 minutes of that
cell went into the stopped call. A header that misattributes it sends the next reader hunting a
second-guessing loop that never happened (#5b, #12).
"""

import unittest

from cria.upstream import _abort_footer, _abort_header

WINDOW = {"window_exhausted": True, "room": 44523, "frames": 40961}
DEAD = {"dead_stream": True, "chunks": 900}
DEGEN = {"degenerate": True, "chars": 2048}
RUMIN = {"hits": 10, "reasoning_tokens": 2048}


class EachGuardNamesItselfTests(unittest.TestCase):
    def test_the_measured_case_is_not_called_the_rumination_guard(self):
        h = _abort_header(WINDOW)
        self.assertIn("WINDOW-EXHAUSTED", h)
        self.assertNotIn("RUMINATION", h)
        self.assertNotIn("second-guessing", h)

    def test_every_guard_gets_its_own_name(self):
        for a, word in ((WINDOW, "WINDOW-EXHAUSTED"), (DEAD, "DEAD-STREAM"),
                        (DEGEN, "DEGENERATE-RUN"), (RUMIN, "RUMINATION")):
            with self.subTest(guard=word):
                self.assertIn(word, _abort_header(a))
                self.assertIn(word.lower().replace("-run", "-run").replace("-", "-"),
                              _abort_footer(a).lower())

    def test_the_footer_agrees_with_the_header(self):
        for a in (WINDOW, DEAD, DEGEN, RUMIN):
            with self.subTest(guard=sorted(a)[0]):
                self.assertIn("ABORTED HERE by the", _abort_footer(a))


class NoGuardPrintsAnotherGuardsNumbersTests(unittest.TestCase):
    def test_none_is_never_rendered(self):
        """The whole incident in one assertion."""
        for a in (WINDOW, DEAD, DEGEN, RUMIN):
            with self.subTest(guard=sorted(a)[0]):
                self.assertNotIn("None", _abort_header(a))

    def test_a_guard_prints_only_what_it_counted(self):
        self.assertIn("40961", _abort_header(WINDOW))
        self.assertIn("44523", _abort_header(WINDOW))
        self.assertNotIn("hits", _abort_header(WINDOW).lower())
        self.assertIn("900", _abort_header(DEAD))
        self.assertIn("2048", _abort_header(DEGEN))
        self.assertIn("10 second-guessing", _abort_header(RUMIN))

    def test_a_bare_abort_falls_to_the_rumination_wording(self):
        """Preserved: the rumination guard is the one that sets no distinguishing flag, so an abort
        with none of the three markers is still its own."""
        self.assertIn("RUMINATION", _abort_header({"hits": 3, "reasoning_tokens": 900}))


class TheHeaderSaysWhyStoppingWasFreeTests(unittest.TestCase):
    def test_the_window_wording_states_the_reason_it_is_not_a_cap(self):
        """#6 forbids capping output for latency. This backstop is allowed only because past
        `window - prompt` the server discards the result anyway, and the header has to say so or a
        reader will mistake it for a cap."""
        h = _abort_header(WINDOW)
        self.assertIn("discarded", h)
        self.assertIn("room", h)


if __name__ == "__main__":
    unittest.main()
