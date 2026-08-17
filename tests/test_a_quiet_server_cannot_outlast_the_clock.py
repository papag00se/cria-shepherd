"""Twelve and a half minutes, 43,442 tokens, an empty message, and not one guard fired.

`shipping-rates-rb × gemma4`, cycle 4 call 0070 — the SECOND occurrence on the same cell and model,
one cycle after `rumination.DEAD_STREAM_CHUNKS` was written for the first:

    usage:   completion_tokens 43,442   prompt_tokens 5,710   total 49,152   (= n_ctx exactly)
    timings: predicted_ms 755,470   source "cria-measured"    (so it WAS streamed)
    message: {"role": "assistant", "content": null}
    upstream.done: aborted False

Zero `rumination.abort` events in the whole session. Two explanations were ruled out from the record:
it was not the buffered re-ask (no `upstream.stream_error`, and the timings are cria-measured, which
only a streamed call gets), and the window guard was not gated off by a bad estimate (cria estimated
5,523 tokens sent against a real 5,710, so `window_room` was ≈43,600).

WHAT WAS LEFT IS PROVABLE FROM THE ABSENCE OF THE EVENTS. `tok_per_s` is 43442/755.47 = 57.5 exactly,
so `t_first` was never set and fell back to `t0` — meaning no frame ever carried content or
reasoning, so `streamed_chars` was 0. The window guard not firing puts `chunks_seen` under
43,629 × 0.92 = 40,139. The dead-stream guard not firing, with `streamed_chars == 0`, puts it under
400. **cria received fewer than 400 readable frames while the server generated 43,442 tokens.**

THE COMMON ROOT: every abort condition in the stream loop thresholds on what ARRIVES — frames for the
window and dead-stream guards, characters for both degenerate checks. A server that goes quiet while
generating is below all four for the entire call, and cria is blind by construction.

The clock is the one signal a quiet server cannot suppress. Time to the first readable byte, generous
enough that prompt processing on a large context is not mistaken for death — the measured runs reach
their first token in seconds, and three minutes still returns nine and a half of the twelve.

Also fixed here: `upstream.done` now records `frames` and `read_chars` on every call. Nothing did,
which is why the frame count above had to be deduced rather than read (#12).
"""

import json
import unittest
from unittest import mock

from cria import rumination
from cria.upstream import Upstream


class _Rlog:
    phase = "coder-s1"
    live_t0 = None
    live_chars = 0

    def __init__(self):
        self.events = []

    def emit(self, name, **k):
        self.events.append((name, k))

    def first(self, name):
        return next((k for n, k in self.events if n == name), None)


def _sse(frames, *, readable, clock):
    """`frames` SSE frames. ``readable`` decides whether any delta carries text cria can read;
    ``clock`` is advanced by the fixture so elapsed time is deterministic."""
    lines = []
    for i in range(frames):
        delta = {"content": f" w{i} "} if readable else {}
        lines.append(b"data: " + json.dumps({"choices": [{"delta": delta}]}).encode() + b"\n")
    lines.append(b'data: {"usage": {"completion_tokens": 43442}}\n')
    lines.append(b"data: [DONE]\n")

    class _Resp:
        def __iter__(self):
            for ln in lines:
                clock.tick()
                yield ln

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def close(self):
            pass

    return _Resp()


class _Clock:
    """monotonic() that advances a fixed amount per streamed frame."""

    def __init__(self, per_frame):
        self.t = 1000.0
        self.per_frame = per_frame

    def tick(self):
        self.t += self.per_frame

    def __call__(self):
        return self.t


def run(*, frames, readable, seconds_total):
    clock = _Clock(seconds_total / max(frames, 1))
    rlog = _Rlog()
    up = Upstream("http://x", context_window=49152)
    with mock.patch("time.monotonic", clock), \
         mock.patch("urllib.request.urlopen", return_value=_sse(frames, readable=readable, clock=clock)):
        up.chat_watched({"messages": [{"role": "user", "content": "hi"}], "model": "m"}, rlog)
    return rlog


class TheMeasuredCallIsCaughtTests(unittest.TestCase):
    def test_a_quiet_server_is_stopped_on_the_clock(self):
        """The shape of call 0070: far fewer than 400 frames, nothing readable, minutes of it."""
        rlog = run(frames=300, readable=False, seconds_total=755.0)
        abort = rlog.first("rumination.abort")
        self.assertIsNotNone(abort, "twelve minutes of nothing and no guard fired")
        self.assertTrue(abort["dead_stream"])
        self.assertGreaterEqual(abort["seconds"], rumination.DEAD_STREAM_SECONDS)

    def test_it_stops_near_the_threshold_not_at_the_end(self):
        """The point is the minutes returned to the model, so it must fire early, not on the last
        frame. 180 s of a 755 s call leaves nine and a half minutes."""
        rlog = run(frames=300, readable=False, seconds_total=755.0)
        self.assertLess(rlog.first("rumination.abort")["seconds"], 300)

    def test_the_frame_guard_alone_could_never_have_fired(self):
        """Why the clock was needed: under 400 frames, the counting guard is below threshold for the
        whole call however long it runs."""
        self.assertLess(300, rumination.DEAD_STREAM_CHUNKS)


class RealWorkIsNotStoppedTests(unittest.TestCase):
    def test_a_stream_that_produces_text_is_left_alone(self):
        """The condition is `nothing readable`, not `slow`. A model streaming real output for twenty
        minutes is working, and the other guards own the runaway case."""
        rlog = run(frames=2000, readable=True, seconds_total=1200.0)
        self.assertIsNone(rlog.first("rumination.abort"))

    def test_a_slow_first_token_inside_the_budget_is_fine(self):
        """Prompt processing on a large context is the one honest reason for a long quiet head."""
        rlog = run(frames=50, readable=False, seconds_total=rumination.DEAD_STREAM_SECONDS - 30)
        self.assertIsNone(rlog.first("rumination.abort"))

    def test_the_budget_is_generous(self):
        self.assertGreaterEqual(rumination.DEAD_STREAM_SECONDS, 120)


class TheNumbersAreRecordedNowTests(unittest.TestCase):
    def test_every_call_reports_frames_and_readable_chars(self):
        """The frame count for call 0070 had to be DEDUCED from which guards did not fire, because
        nothing recorded it (#12)."""
        rlog = run(frames=20, readable=True, seconds_total=2.0)
        done = rlog.first("upstream.done")
        self.assertIsNotNone(done)
        self.assertIn("frames", done)
        self.assertIn("read_chars", done)
        self.assertGreater(done["frames"], 0)

    def test_the_abort_names_the_frames_it_had_seen(self):
        """And it stops PART WAY: 180 s into a 755 s stream is roughly a quarter of the frames, which
        is the nine and a half minutes handed back to the model."""
        rlog = run(frames=300, readable=False, seconds_total=755.0)
        seen = rlog.first("rumination.abort")["chunks"]
        self.assertGreater(seen, 0)
        self.assertLess(seen, 300, "it consumed the whole stream instead of cutting it short")


if __name__ == "__main__":
    unittest.main()
