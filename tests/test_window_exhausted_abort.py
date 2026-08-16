"""A generation that has used the whole window it will ever get is stopped and LABELLED.

Measured three times in cycle 3 alone - cell 1, its re-run, and cell 9 which had scored 100% in both
previous cycles - all identical:

    completion_tokens 44,058 | prompt_tokens 5,094 | total_tokens 49,152 = n_ctx EXACTLY
    finish_reason "length" | content empty | tool_calls empty | 720 seconds

The tokens go into write_file ARGUMENTS that never terminate, so nothing assembles and
guard_truncation discards the turn. Twelve minutes, nothing kept, and on a fifteen-minute floor that
is the whole cell.

Every other backstop misses it for a correct reason: the rumination watcher excludes tool-call
arguments on purpose (a real large write looks identical until it ends), the degenerate-tail check
needs a periodic tail, DEAD_STREAM_CHUNKS needs nothing readable to have arrived, and
timeout_seconds is 7200 here because a slow CPU model can take minutes.

NOT A CAP. Past `window - prompt` the server stops with finish_reason=length and the result is
discarded whatever happens, so aborting there keeps nothing from surviving that would have. What it
buys is a labelled turn with a notice the coder can act on instead of a silent discard.

AND IT IS OFF WHEN THE WINDOW IS A GUESS. _resolve_window returns a conservative fallback when
/props cannot be read; computing room from that would abort real generations on a model whose true
window is six times larger - the cap-output footgun arrived at by arithmetic instead of a constant.
"""
from __future__ import annotations

import unittest
from unittest import mock

from cria import rumination
from cria.upstream import Upstream


class TheFractionIsNotACap(unittest.TestCase):
    def test_it_fires_only_near_the_very_end_of_the_room(self):
        self.assertGreaterEqual(rumination.WINDOW_EXHAUSTED_FRACTION, 0.85)
        self.assertLess(rumination.WINDOW_EXHAUSTED_FRACTION, 1.0)

    def test_the_measured_case_would_trip_it(self):
        """44,058 generated against 44,058 of room."""
        room = 49152 - 5094
        self.assertGreaterEqual(44058, room * rumination.WINDOW_EXHAUSTED_FRACTION)

    def test_an_ordinary_large_write_does_not(self):
        """A 6,000-token file into a 49k window is nowhere near it."""
        room = 49152 - 5094
        self.assertLess(6000, room * rumination.WINDOW_EXHAUSTED_FRACTION)


class ItIsOffWhenTheWindowIsAGuess(unittest.TestCase):
    def test_a_configured_window_is_authoritative(self):
        up = Upstream("http://x", context_window=49152)
        self.assertTrue(up._window_final)

    def test_a_local_endpoint_starts_provisional(self):
        """No /props yet -> _window_final False -> the guard must not compute room from a fallback."""
        up = Upstream("http://x")
        self.assertFalse(up._window_final)

    def test_the_source_gates_on_it(self):
        import inspect
        src = inspect.getsource(Upstream.chat_watched)
        self.assertIn("_window_final", src)
        self.assertIn("window_room", src)
        self.assertIn("WINDOW_EXHAUSTED_FRACTION", src)


class TheCoderIsToldSomethingActionable(unittest.TestCase):
    def test_a_fourth_notice_exists(self):
        from cria import prompts
        t = prompts.load("rumination_guard_window")
        self.assertIn("write the file in pieces", t.lower())
        self.assertNotIn("second-guessing", t)

    def test_the_guard_selects_it_before_the_others(self):
        import inspect
        from cria import loop
        src = inspect.getsource(loop.guard_rumination)
        self.assertIn("rumination_guard_window", src)
        self.assertLess(src.index("window_exhausted"), src.index("dead_stream"))

    def test_it_never_names_the_shim_to_the_model(self):
        import re
        from cria import prompts
        self.assertIsNone(re.search(r"\bcria\b", prompts.load("rumination_guard_window"), re.I))


if __name__ == "__main__":
    unittest.main()
