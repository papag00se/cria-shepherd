"""cria trimmed the prompt against a window it had invented.

When `/props` cannot be read, `_resolve_window` returns `_FALLBACK_WINDOW = 8192` and sets
`_window_guessed`. The floor then ran against that number. cria's own measurement of the cost is in
`_window_at_least`:

    52 floor runs against the 8,192 fallback, over_budget on 52 of 52, 934 PROTECTED messages
    destroyed across 6 sessions — while the model's real window was 49,152, six times larger.

The trigger is as ordinary as cria restarting while llama.cpp is still loading its model.

The asymmetry is what makes it a defect rather than a trade: the mid-stream abort already refuses to
act on the same guess — `if (_win and not self._window_guessed)` — on the stated grounds that acting
on a guess would cut a real generation. The destructive direction had no such check.

An overflow is recoverable and a deletion is not. A 400 carries the server's own `n_ctx`, which
`_overflow_refit` treats as FINAL, so the cost of not guessing is one round trip after which the
window is measured for the rest of the process.
"""

import unittest

from cria import upstream


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    phase = ""


class _Up(upstream.Upstream):
    """A real Upstream pointed at nothing — only `_prep`'s floor decision is under test, and
    `_resolve_window` is overridden so no /props probe is attempted."""

    def __init__(self, guessed: bool):
        super().__init__("http://127.0.0.1:1", capture_dir=None, capture_rendered=False)
        self._window = upstream._FALLBACK_WINDOW if guessed else 49152
        self._window_guessed = guessed
        self._window_final = not guessed

    def _resolve_window(self, rlog):
        return self._window


def _fat_body():
    """A body far over the 8,192 fallback and comfortably inside a real 49,152 window."""
    return {"model": "m", "messages":
            [{"role": "system", "content": "frame"}]
            + [{"role": "user", "content": "x" * 4000} for _ in range(12)]}


class AGuessMayNotTrimTests(unittest.TestCase):
    def test_the_floor_is_skipped_when_the_window_is_invented(self):
        rlog = _Rlog()
        _Up(guessed=True)._prep(_fat_body(), False, rlog)
        kinds = [k for k, _ in rlog.events]
        self.assertIn("context.floor_skipped", kinds)
        self.assertNotIn("context.floor", kinds, "cria trimmed against a number it made up")

    def test_it_says_why_rather_than_dropping_silently(self):
        rlog = _Rlog()
        _Up(guessed=True)._prep(_fat_body(), False, rlog)
        why = next(kw for k, kw in rlog.events if k == "context.floor_skipped")
        self.assertEqual(why.get("why"), "window is a guess")
        self.assertEqual(why.get("guess"), upstream._FALLBACK_WINDOW)

    def test_nothing_is_dropped_from_the_body(self):
        body = _fat_body()
        data, _sent, _cap = _Up(guessed=True)._prep(body, False, _Rlog())
        import json
        self.assertEqual(len(json.loads(data)["messages"]), len(body["messages"]))

    def test_a_measured_window_still_trims(self):
        """The floor is not disabled — only the guess is refused."""
        rlog = _Rlog()
        _Up(guessed=False)._prep(_fat_body(), False, rlog)
        self.assertNotIn("context.floor_skipped", [k for k, _ in rlog.events])


class TheAsymmetryIsGoneTests(unittest.TestCase):
    def test_the_abort_guard_and_the_floor_now_agree(self):
        """Both directions refuse the same guess. The abort guard has always read
        `not self._window_guessed`; the floor now does too."""
        import inspect
        src = inspect.getsource(upstream.Upstream._prep)
        self.assertIn("_window_guessed", src)


if __name__ == "__main__":
    unittest.main()
