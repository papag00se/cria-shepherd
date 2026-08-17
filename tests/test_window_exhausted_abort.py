"""A generation that has used the whole window it will ever get is stopped and LABELLED.

Measured repeatedly, always the same shape:

    completion_tokens 44,058 | prompt_tokens 5,094 | total_tokens 49,152 = n_ctx EXACTLY
    finish_reason "length" | content empty | tool_calls empty | 720 seconds

The tokens go into write_file ARGUMENTS that never terminate, so nothing assembles and
guard_truncation discards the turn. Twelve minutes, nothing kept, and on a fifteen-minute floor that
is the whole cell. 14 such calls are in the captures; the four largest are 44,549 / 44,510 / 44,058 /
43,873 completion tokens, every one of them totalling exactly 49,152.

Every other backstop misses it for a correct reason: the rumination watcher excludes tool-call
arguments on purpose (a real large write looks identical until it ends), the degenerate-tail check
needs a periodic tail, DEAD_STREAM_CHUNKS needs nothing readable to have arrived, and
timeout_seconds is 7200 here because a slow CPU model can take minutes.

NOT A CAP. Past `window - prompt` the server stops with finish_reason=length and the result is
discarded whatever happens, so aborting there keeps nothing from surviving that would have. What it
buys is a labelled turn with a notice the coder can act on instead of a silent discard.

WHAT THIS MODULE USED TO BE. Eight tests, not one of which streamed a single frame: they read the
guard's source with `inspect.getsource`, asserted the constant's value, and did the guard's
arithmetic themselves on literals. All eight passed while `rumination.abort` had never once carried
`window_exhausted` in any log cria has kept — and four of those 14 runaway calls happened AFTER the
guard shipped. A test that re-states the rule cannot tell you the rule never runs. These drive
`chat_watched` with a real SSE stream and read what came out.

AND THE GATE WAS WRONG. The guard was off unless `_window_final`, which answers "stop probing", not
"is this number real". A window learned from a prompt the server ACCEPTED is measured but not final,
so the guard stayed off in exactly the sessions where /props was unreachable — the ones where a
runaway was least likely to be noticed. It now gates on `_window_guessed`: off only when cria
invented the number.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from cria import rumination
from cria.upstream import _FALLBACK_WINDOW, Upstream


class _Rlog:
    phase = "coder"

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]

    def first(self, kind):
        return next((kw for k, kw in self.events if k == kind), None)


def _sse(frames: int, *, shape: str = "args"):
    """`frames` SSE frames of NON-repeating content, so only the window guard can fire.

    The fragment used to be `word{i % 997}`, which is not non-repeating at all — it is a 997-fragment
    cycle, and once the wide degenerate check could see a repeating unit larger than 682 characters it
    fired here at three cycles, correctly. A stream that really does say the same ~10 KB three times
    over is the thing that check exists for; this fixture's premise is that it does not."""
    lines = []
    for i in range(frames):
        frag = f" word{i} "
        delta = ({"tool_calls": [{"index": 0, "function": {"arguments": frag}}]}
                 if shape == "args" else {"content": frag})
        lines.append(b"data: " + json.dumps({"choices": [{"delta": delta}]}).encode() + b"\n")
    lines.append(b"data: [DONE]\n")

    class _Resp:
        def __iter__(self):
            return iter(lines)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def close(self):
            pass

    return _Resp()


def stream(up: Upstream, frames: int, *, shape: str = "args"):
    rlog = _Rlog()
    with mock.patch("urllib.request.urlopen", return_value=_sse(frames, shape=shape)):
        out = up.chat_watched({"messages": [{"role": "user", "content": "hi"}], "model": "m"}, rlog)
    return out, rlog


class ItActuallyStopsTheStreamTests(unittest.TestCase):
    """Driven, not asserted about."""

    def test_a_runaway_is_aborted_near_the_end_of_the_room(self):
        up = Upstream("http://x", context_window=5200)
        _, rlog = stream(up, 5000)
        abort = rlog.first("rumination.abort")
        self.assertIsNotNone(abort, "the guard did not fire on a stream that used the whole window")
        self.assertTrue(abort["window_exhausted"])
        self.assertLess(abort["frames"], 5000, "it must stop the stream, not observe it ending")
        self.assertGreaterEqual(abort["frames"],
                                abort["room"] * rumination.WINDOW_EXHAUSTED_FRACTION)

    def test_it_fires_on_tool_arguments_which_is_the_measured_shape(self):
        """The runaway went into write_file arguments — the one shape the rumination watcher skips
        on purpose, because a real large write looks identical until it ends."""
        _, rlog = stream(Upstream("http://x", context_window=5200), 5000, shape="args")
        self.assertTrue(rlog.first("rumination.abort")["window_exhausted"])

    def test_it_fires_on_plain_content_too(self):
        _, rlog = stream(Upstream("http://x", context_window=5200), 5000, shape="content")
        self.assertTrue(rlog.first("rumination.abort")["window_exhausted"])

    def test_an_ordinary_generation_streams_to_the_end_untouched(self):
        """A 400-frame answer into the same window: no abort, and the text survives whole."""
        out, rlog = stream(Upstream("http://x", context_window=5200), 400, shape="content")
        self.assertIsNone(rlog.first("rumination.abort"))
        self.assertIn("word399", json.loads(out)["choices"][0]["message"]["content"])

    def test_a_big_window_leaves_the_same_stream_alone(self):
        """The guard is arithmetic against the real room, not a length limit: the identical 5,000
        frames pass untouched when the window can hold them."""
        _, rlog = stream(Upstream("http://x", context_window=49152), 5000)
        self.assertIsNone(rlog.first("rumination.abort"))


class ItIsOffOnlyWhenTheNumberIsInventedTests(unittest.TestCase):
    def test_a_committed_fallback_disables_it(self):
        """The cap-output footgun this exists to avoid: a legitimate long generation must not be
        killed against a window cria guessed. /props unreachable → the guard is simply off."""
        up = Upstream("http://x")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            up._resolve_window(_Rlog())
        self.assertTrue(up._window_guessed)
        self.assertEqual(up._window, _FALLBACK_WINDOW)
        with mock.patch.object(up, "_resolve_window", return_value=_FALLBACK_WINDOW):
            _, rlog = stream(up, 9000)
        self.assertIsNone(rlog.first("rumination.abort"))

    def test_a_window_learned_from_an_accepted_prompt_enables_it(self):
        """THE REGRESSION. `_window_final` answers "stop probing"; the guard needs "is it real".
        A prompt the server ACCEPTED is measurement, and the guard used to stay off for it.

        The measured shape exactly: /props unreachable, the 8,192 fallback committed, and the server
        then answers a call reporting a prompt bigger than the whole assumed window — proof in cria's
        hand that its number is wrong."""
        up = Upstream("http://x")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            up._resolve_window(_Rlog())
        self.assertTrue(up._window_guessed)
        up._window_at_least(12000, _Rlog())          # the server accepted 12,000 prompt tokens
        self.assertEqual(up._window, 12000)
        self.assertFalse(up._window_guessed)
        self.assertFalse(up._window_final, "a lower bound must not stop /props probing")
        with mock.patch.object(up, "_resolve_window", return_value=12000):
            _, rlog = stream(up, 11800)
        self.assertTrue(rlog.first("rumination.abort")["window_exhausted"])

    def test_an_accepted_prompt_smaller_than_the_guess_proves_nothing(self):
        """It only ever RAISES. A 5,000-token prompt says nothing about whether the window is 8,192
        or 49,152, so the guess stands and the guard stays off."""
        up = Upstream("http://x")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            up._resolve_window(_Rlog())
        up._window_at_least(5000, _Rlog())
        self.assertEqual(up._window, _FALLBACK_WINDOW)
        self.assertTrue(up._window_guessed)

    def test_a_discovered_window_is_never_overwritten_by_a_lower_bound(self):
        up = Upstream("http://x", context_window=49152)
        up._window_at_least(99999, _Rlog())
        self.assertEqual(up._window, 49152)


class TheBoundIsTotalTokensNotPromptTokensTests(unittest.TestCase):
    """The floor budgets `window - output_reserve`. Setting the window to the PROMPT size alone
    leaves a 20k prompt with 3.6k of budget and trims harder than the 8,192 guess it replaced. The
    server held prompt AND completion at once, so total_tokens is the bound it actually proved."""

    def _fallen_back(self):
        up = Upstream("http://x")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            up._resolve_window(_Rlog())
        return up

    def test_the_completion_counts_toward_the_bound(self):
        up = self._fallen_back()
        up._calibrate("m", {"prompt_tokens": 6000, "completion_tokens": 30000,
                            "total_tokens": 36000}, 5800, _Rlog())
        self.assertEqual(up._window, 36000)

    def test_it_adds_them_when_total_is_absent(self):
        up = self._fallen_back()
        up._calibrate("m", {"prompt_tokens": 6000, "completion_tokens": 30000}, 5800, _Rlog())
        self.assertEqual(up._window, 36000)

    def test_no_usage_changes_nothing(self):
        up = self._fallen_back()
        up._calibrate("m", None, 5800, _Rlog())
        self.assertEqual(up._window, _FALLBACK_WINDOW)
        self.assertTrue(up._window_guessed)

    def test_the_density_calibration_still_reads_the_prompt_count(self):
        """Density is real prompt ÷ estimated prompt. Feeding it the total would poison the ratio
        the floor budgets with."""
        import inspect
        src = inspect.getsource(Upstream._calibrate)
        self.assertIn("tokenratio.record(model, prompt_tokens, estimate)", src)

    def test_a_configured_window_is_authoritative(self):
        up = Upstream("http://x", context_window=49152)
        self.assertTrue(up._window_final)
        self.assertFalse(up._window_guessed)


class TheFractionIsNotACapTests(unittest.TestCase):
    def test_it_fires_only_near_the_very_end_of_the_room(self):
        self.assertGreaterEqual(rumination.WINDOW_EXHAUSTED_FRACTION, 0.85)
        self.assertLess(rumination.WINDOW_EXHAUSTED_FRACTION, 1.0)

    def test_the_measured_cases_would_trip_it(self):
        for room, frames in ((49152 - 5094, 44058), (49152 - 5279, 43873)):
            with self.subTest(room=room):
                self.assertGreaterEqual(frames, room * rumination.WINDOW_EXHAUSTED_FRACTION)

    def test_an_ordinary_large_write_does_not(self):
        room = 49152 - 5094
        self.assertLess(6000, room * rumination.WINDOW_EXHAUSTED_FRACTION)


class TheCoderIsToldSomethingActionableTests(unittest.TestCase):
    def test_a_fourth_notice_exists(self):
        """It used to pin "write the file in pieces", which is the sentence that had to go: the
        notice was asserting WHICH call overran when cria had the tool name and it was an `edit_file`
        whose payload had already finished (cycle 4 cell 4). What it must still do is be its own
        notice with its own actionable step — see test_the_guard_selects_it_before_the_others and
        tests/test_a_whole_file_repeating_is_seen.py."""
        from cria import prompts
        t = prompts.load("rumination_guard_window")
        self.assertIn("single tool call", t.lower())
        self.assertNotIn("second-guessing", t)
        self.assertNotIn("almost always means", t)

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
