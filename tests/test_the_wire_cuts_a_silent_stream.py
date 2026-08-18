"""The dead-stream guard's own comment says a quiet server cannot suppress the clock. One did.

`shipping-rates-rb × gemma4`, 2026-08-17, call 0017:

    "finish_reason": "rumination"
    "cria_rumination": {"dead_stream": true, "chunks": 2, "seconds": 743.4}

`DEAD_STREAM_SECONDS` is 180. It fired at 743.4 because the elapsed test sits INSIDE
`for raw in resp:` — it can only be evaluated when a frame arrives, and that stream delivered two
frames in twelve and a half minutes. **743 of the run's 949 seconds, 78%.** The coder needed 72
seconds of generation across every other call in the run. The guard's unit test drives 300 frames
over 755 simulated seconds, so the near-zero-frame case it exists for was never exercised.

And `stream_chat` — the buffered proxy's passthrough — had no dead-stream check at all, no
degenerate check, no window check. `server.py` routes every non-loop request through it, which is
the entire assists-off arm of the matrix. Measured across 24 baseline runs: the longest single call
is **525 seconds of nothing**, unguarded.

**#24: an invariant that must hold on the wire belongs at the wire.** `urlopen`'s timeout is a
per-READ socket deadline, so a stream that keeps delivering may run for hours under it and one that
goes silent raises. Neither reader owns it and neither can suppress it.

**SIZED FROM MEASUREMENT, NOT FROM THE GAP THRESHOLD.** The first read of a stream covers prompt
processing, during which a healthy server is silent by design. Over 1,313 captured calls carrying
timing blocks: median 0.6 s, p99 125 s, real maximum **309.4 s** on a deep-context proxy turn. Using
180 at the wire would have killed working calls. 420 sits above the observed ceiling with headroom
and still cuts both walked stalls — 743 s and 525 s — well before either costs a run.

The in-loop 180 s check stays. It works once frames are flowing, which is the regime it can see.
"""

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


class TheDeadlineIsSizedFromMeasurementTests(unittest.TestCase):
    def test_it_clears_the_worst_real_prompt_processing(self):
        """309.4 s was measured on a real deep-context turn. A deadline under it cuts working calls."""
        self.assertGreater(rumination.WIRE_SILENCE_SECONDS, 309.4)

    def test_it_still_cuts_both_walked_stalls(self):
        for seconds, where in ((743.4, "shipping-rates-rb x gemma4"), (525.0, "the baseline arm")):
            with self.subTest(where=where):
                self.assertLess(rumination.WIRE_SILENCE_SECONDS, seconds)

    def test_it_is_not_the_gap_threshold(self):
        """Two different questions: silence at the socket, and a gap between frames that arrive."""
        self.assertNotEqual(rumination.WIRE_SILENCE_SECONDS, rumination.DEAD_STREAM_SECONDS)
        self.assertGreater(rumination.WIRE_SILENCE_SECONDS, rumination.DEAD_STREAM_SECONDS)


class BothReadersGetItWithoutOwningItTests(unittest.TestCase):
    def _opened(self, stream):
        seen = {}

        class _Resp:
            def __iter__(self):
                return iter([b"data: [DONE]\n"])

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def close(self):
                pass

            def read(self):
                return b'{"choices":[{"message":{"content":"x"}}]}'

        def _urlopen(req, timeout=None):
            seen["timeout"] = timeout
            return _Resp()

        up = Upstream("http://x", context_window=49152)
        with mock.patch("urllib.request.urlopen", _urlopen):
            up._open_with_refit({"messages": [{"role": "user", "content": "hi"}], "model": "m"},
                                stream, _Rlog())
        return seen["timeout"]

    def test_a_streaming_open_carries_the_wire_deadline(self):
        self.assertEqual(self._opened(True), rumination.WIRE_SILENCE_SECONDS)

    def test_a_buffered_post_keeps_the_long_timeout(self):
        """Its whole generation arrives as ONE read, so a short deadline there cuts a working call."""
        self.assertGreater(self._opened(False), rumination.WIRE_SILENCE_SECONDS)

    def test_neither_reader_spells_the_deadline_itself(self):
        """One owner. The passthrough had no check at all precisely because each reader owned its
        own guards, and one of them was written without any."""
        import inspect

        from cria import upstream
        for fn in (upstream.Upstream.chat_watched, upstream.Upstream.stream_chat):
            with self.subTest(fn=fn.__name__):
                self.assertNotIn("WIRE_SILENCE_SECONDS", inspect.getsource(fn))


class ASilentWireEndsAsARePromptableTurnTests(unittest.TestCase):
    def test_a_timeout_becomes_a_dead_stream_abort_not_an_exception(self):
        """A 502 hands the harness a blind retry of the body that just stalled. A rumination
        completion is something the caller re-prompts from (#13)."""
        rlog = _Rlog()

        class _Silent:
            def __iter__(self):
                raise TimeoutError("timed out")

            def close(self):
                pass

        up = Upstream("http://x", context_window=49152)
        with mock.patch("urllib.request.urlopen", return_value=_Silent()):
            out = up.chat_watched({"messages": [{"role": "user", "content": "hi"}], "model": "m"}, rlog)
        abort = rlog.first("rumination.abort")
        self.assertIsNotNone(abort, "the wire went silent and nothing said so")
        self.assertTrue(abort["dead_stream"])
        self.assertTrue(abort["wire"])
        self.assertIn(b"rumination", out)


if __name__ == "__main__":
    unittest.main()
