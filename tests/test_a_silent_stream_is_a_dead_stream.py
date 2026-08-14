"""A stream said nothing for twelve minutes and nothing could stop it.

    gemma4/ruby call 0009: upstream.done {"total_ms": 730418.5, "tokens": 44510, "aborted": false},
    with no preceding upstream.first_token. `content`, `reasoning_content` and `tool_calls` all
    null. The server buffered an unterminated tool call and sent zero deltas.

Both existing backstops read an accumulated string, so both read "" and neither could fire. Of
principle 6's three runaway guards only n_ctx was live — the timeout is 7200s — and n_ctx by
construction burns the entire remaining window first. 91 such streams across the corpus, 372
minutes of wall clock.

THE BOUND IS MEASURED. Across 12,394 recorded first tokens the slowest legitimate one is 456s; p99.9
is 184s and p99 is 32s. 480s aborts none of them and recovers 37 of the 372 minutes.

AND IT IS DELIBERATELY THE CONSERVATIVE END. Most dead streams sit BELOW the slowest real first
token — dead median is 197s — so no safe bound catches them, and a cold 27B has already been
mistaken for a dead model once (cc8e8c7). Tightening this needs more first-token data, not a
sharper guess.
"""

import json
import time
import unittest
from unittest import mock

from cria import upstream
from cria.upstream import Upstream


class Rlog:
    def __init__(self):
        self.events = []
        self.live_t0 = None

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def sse(payload):
    return b"data: " + json.dumps(payload).encode() + b"\n"


class FakeResp:
    """A stream whose frames arrive but carry no delta cria can parse — the measured shape."""

    def __init__(self, lines, clock):
        self.lines, self.closed, self.consumed, self._clock = lines, False, 0, clock

    def __iter__(self):
        for ln in self.lines:
            self.consumed += 1
            self._clock[0] += 60.0        # each frame advances the clock a minute
            yield ln

    def close(self):
        self.closed = True

    def read(self):
        return b""


class ADeadStreamIsAbortedTests(unittest.TestCase):
    def run_stream(self, lines, seconds_per_frame=60.0):
        clock = [0.0]
        resp = FakeResp(lines, clock)
        rlog = Rlog()
        with mock.patch.object(upstream.time, "monotonic", lambda: clock[0]), \
             mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            raw = Upstream("http://x", context_window=8192).chat_watched(
                {"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog)
        return json.loads(raw), rlog, resp

    def keepalive(self, n):
        """Frames that parse but carry nothing — no content, no reasoning, no tool_calls."""
        return [sse({"choices": [{"delta": {}}]}) for _ in range(n)] + [b"data: [DONE]\n"]

    def test_a_stream_with_no_delta_is_cut(self):
        comp, rlog, resp = self.run_stream(self.keepalive(20))
        self.assertIn("rumination.abort", [k for k, _ in rlog.events])
        self.assertTrue(resp.closed)

    def test_it_stops_before_draining_the_whole_stream(self):
        _, _, resp = self.run_stream(self.keepalive(40))
        self.assertLess(resp.consumed, 41)

    def test_the_event_says_what_fired_and_for_how_long(self):
        _, rlog, _ = self.run_stream(self.keepalive(20))
        kw = next(kw for k, kw in rlog.events if k == "rumination.abort")
        self.assertTrue(kw.get("dead_stream"))
        self.assertGreaterEqual(kw.get("seconds"), upstream.DEAD_STREAM_SECONDS)

    def test_the_abort_is_recorded_on_the_completion(self):
        comp, _, _ = self.run_stream(self.keepalive(20))
        self.assertEqual(comp["choices"][0].get("finish_reason"), "rumination")


class ALiveStreamIsNeverCutTests(unittest.TestCase):
    def test_a_slow_first_token_well_past_the_bound_survives(self):
        """The whole risk. A cold model that finally speaks must not be killed for being slow."""
        clock = [0.0]
        lines = ([sse({"choices": [{"delta": {}}]}) for _ in range(6)]      # 6 min of silence
                 + [sse({"choices": [{"delta": {"content": "hello"}}]})]     # …then it speaks
                 + [sse({"choices": [{"delta": {"content": " world"}}]}), b"data: [DONE]\n"])
        resp = FakeResp(lines, clock)
        rlog = Rlog()
        with mock.patch.object(upstream.time, "monotonic", lambda: clock[0]), \
             mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            comp = json.loads(Upstream("http://x", context_window=8192).chat_watched(
                {"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog))
        self.assertNotIn("rumination.abort", [k for k, _ in rlog.events])
        self.assertIn("hello world", json.dumps(comp))

    def test_a_fast_stream_is_untouched(self):
        clock = [0.0]
        lines = [sse({"choices": [{"delta": {"content": "hi"}}]}), b"data: [DONE]\n"]
        resp = FakeResp(lines, clock)
        rlog = Rlog()
        with mock.patch.object(upstream.time, "monotonic", lambda: clock[0]), \
             mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            Upstream("http://x", context_window=8192).chat_watched(
                {"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog)
        self.assertNotIn("rumination.abort", [k for k, _ in rlog.events])


class TheBoundIsAboveEveryMeasuredFirstTokenTests(unittest.TestCase):
    def test_it_clears_the_slowest_legitimate_sample(self):
        """456s is the slowest of 12,394 recorded first tokens on this box."""
        self.assertGreater(upstream.DEAD_STREAM_SECONDS, 456)

    def test_it_is_far_under_the_request_timeout(self):
        """The timeout is 7200s, which is why this was the only live backstop's job to take."""
        self.assertLess(upstream.DEAD_STREAM_SECONDS, 7200)


if __name__ == "__main__":
    unittest.main()
