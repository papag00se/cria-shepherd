"""Every streamed reasoning block is written to disk, whether the stream finished or not.

Operator, 2026-08-13: *"I want all streamed reasoning logged. Whether it finishes or not."*

THREE HOLES, all found by trying to answer a question about 91 apparently-dead streams and being
unable to, because the evidence had never been kept.

  1. THE PROXY PATH LOGGED NOTHING. `stream_chat` forwards raw SSE and counted only content deltas.
     It already received a capture_path from the opener and threw it away. 34 of the 47 long turns
     in one sweep took this path and not one had a reasoning file.

  2. A STREAM ERROR DISCARDED THE THINKING. `chat_watched` re-asks the request buffered when the
     transport breaks — returning from before the save, so everything the model had already thought
     went with it. Those are the turns whose reasoning is worth MOST, because the answer is gone.

  3. AN EXCEPTION IN THE READ LOOP DISCARDED IT TOO. The `finally` closed the socket and saved
     nothing.

AND A REASONING DELTA IS A FIRST TOKEN. `upstream.first_token` fired only on CONTENT, so a turn that
thought for four minutes and then errored looked, in the log, like a stream that never spoke. That
is the measurement error that made 47 healthy calls read as dead ones.

A partial file is LABELLED at both ends. A truncated trace read as a complete one is the same lie as
a truncated file (#5b), and the label is what makes keeping it worth more than dropping it.
"""

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from cria.upstream import Upstream


class Rlog:
    def __init__(self):
        self.events = []
        self.live_t0 = None
        self.phase = "coder"

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def sse(delta=None, usage=None):
    payload = {"choices": [{"delta": delta or {}}]}
    if usage:
        payload["usage"] = usage
    return b"data: " + json.dumps(payload).encode() + b"\n"


class Resp:
    def __init__(self, lines, raise_at=None):
        self.lines, self.closed, self._raise_at = lines, False, raise_at

    def __iter__(self):
        for i, ln in enumerate(self.lines):
            if self._raise_at is not None and i == self._raise_at:
                raise OSError("connection reset by peer")
            yield ln

    def close(self):
        self.closed = True

    def read(self):
        return b""


def files(tmp):
    return sorted(pathlib.Path(tmp).rglob("*.reasoning.txt"))


class TheProxyPathLogsItsReasoningTests(unittest.TestCase):
    def drive(self, lines):
        tmp = tempfile.mkdtemp()
        up = Upstream("http://x", context_window=8192, capture_dir=tmp, capture_rendered=False)
        rlog = Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=Resp(lines)):
            list(up.stream_chat({"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog))
        return tmp, rlog

    def test_the_thinking_lands_on_disk(self):
        tmp, _ = self.drive([sse({"reasoning_content": "step one. "}),
                             sse({"reasoning_content": "step two."}),
                             sse({"content": "done"}, usage={"completion_tokens": 9}),
                             b"data: [DONE]\n"])
        self.assertIn("step one. step two.", files(tmp)[0].read_text())

    def test_the_event_points_at_it(self):
        _, rlog = self.drive([sse({"reasoning_content": "thinking"}),
                              sse({"content": "x"}, usage={"completion_tokens": 2}),
                              b"data: [DONE]\n"])
        self.assertIn("coder.reasoning", [k for k, _ in rlog.events])

    def test_a_reasoning_delta_counts_as_the_first_token(self):
        """Counting only CONTENT is what made a thinking turn look like a silent one."""
        _, rlog = self.drive([sse({"reasoning_content": "thinking hard"}),
                              sse({"content": "x"}, usage={"completion_tokens": 2}),
                              b"data: [DONE]\n"])
        ft = [kw for k, kw in rlog.events if k == "upstream.first_token"]
        self.assertTrue(ft)
        self.assertEqual(ft[0].get("channel"), "reasoning")

    def test_a_turn_with_no_reasoning_writes_nothing(self):
        tmp, _ = self.drive([sse({"content": "hi"}, usage={"completion_tokens": 1}),
                             b"data: [DONE]\n"])
        self.assertEqual(files(tmp), [])


class AnUnfinishedStreamIsStillLoggedTests(unittest.TestCase):
    def drive_watched(self, lines, raise_at=None):
        tmp = tempfile.mkdtemp()
        up = Upstream("http://x", context_window=8192, capture_dir=tmp, capture_rendered=False)
        rlog = Rlog()
        resp = Resp(lines, raise_at=raise_at)
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            try:
                up.chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog)
            except Exception:
                pass
        return tmp, rlog

    def test_an_exception_mid_read_still_saves_what_was_thought(self):
        tmp, _ = self.drive_watched(
            [sse({"reasoning_content": "I have worked out that the gem is ISO3166"}),
             sse({"reasoning_content": " and the call should be codes.include?"}),
             b"data: [DONE]\n"], raise_at=2)
        body = files(tmp)[0].read_text()
        self.assertIn("ISO3166", body)
        self.assertIn("codes.include?", body)

    def test_and_says_it_is_incomplete_at_both_ends(self):
        tmp, _ = self.drive_watched([sse({"reasoning_content": "half a thought"}),
                                     b"data: [DONE]\n"], raise_at=1)
        body = files(tmp)[0].read_text()
        self.assertIn("INCOMPLETE REASONING", body)
        self.assertIn("stream ENDED HERE", body)
        self.assertIn("connection reset by peer", body)

    def test_the_event_marks_it_incomplete(self):
        _, rlog = self.drive_watched([sse({"reasoning_content": "half"}), b"data: [DONE]\n"],
                                     raise_at=1)
        kw = next(kw for k, kw in rlog.events if k == "coder.reasoning")
        self.assertTrue(kw.get("incomplete"))
        self.assertIn("connection reset", kw.get("ending"))

    def test_a_clean_stream_is_written_pure(self):
        """Unchanged: a complete block stays greppable and diffable with no header."""
        tmp, _ = self.drive_watched([sse({"reasoning_content": "a complete thought"}),
                                     sse({"content": "answer"}, usage={"completion_tokens": 4}),
                                     b"data: [DONE]\n"])
        self.assertEqual(files(tmp)[0].read_text(), "a complete thought")

    def test_it_is_written_exactly_once(self):
        tmp, rlog = self.drive_watched([sse({"reasoning_content": "one thought"}),
                                        sse({"content": "x"}, usage={"completion_tokens": 2}),
                                        b"data: [DONE]\n"])
        self.assertEqual(len(files(tmp)), 1)
        self.assertEqual(len([k for k, _ in rlog.events if k == "coder.reasoning"]), 1)


class TheAbortMarkerIsUnchangedTests(unittest.TestCase):
    def test_a_guard_abort_still_gets_its_own_loud_header(self):
        from cria import rumination
        tmp = tempfile.mkdtemp()
        det = rumination.Detector(budget=1000, rate_per_1k=3)
        chunk = "actually wait hmm let me reconsider on second thought " * 10
        lines = [sse({"reasoning_content": chunk}) for _ in range(20)] + [b"data: [DONE]\n"]
        up = Upstream("http://x", context_window=8192, capture_dir=tmp, capture_rendered=False)
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=Resp(lines)):
            up.chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]},
                            Rlog(), watch=det.check)
        body = files(tmp)[0].read_text()
        # THE GUARD THAT ACTUALLY FIRED. This fixture repeats one sentence, so the DEGENERATE-RUN
        # backstop reaches it before the rumination watcher's marker gate does — and the header used
        # to name the rumination guard regardless, rendering its counters as `None`. The assertion
        # tracked the misattribution rather than the behaviour.
        self.assertIn("DEGENERATE-RUN ABORT", body)
        self.assertIn("ABORTED HERE by the degenerate-run backstop", body)
        self.assertNotIn("None", body.splitlines()[0])   # no other guard's counters
        self.assertNotIn("INCOMPLETE REASONING", body)   # the abort has its own, more specific label


class TheDeadStreamClockIsGoneTests(unittest.TestCase):
    """Removed at the operator's instruction. It was measured against a population that was half
    artifact: 47 of the 91 "dead" streams were long BUFFERED or proxy calls that never emit a
    first-token event, and 26 of the 34 whose captures could be opened had produced real output. The
    real half — 44 qwen35 classifier turns, every one at exactly 16,384 tokens — was already fixed at
    its source by not making the call."""

    def test_no_wall_clock_bounds_a_model_call_here(self):
        from cria import upstream
        self.assertFalse(hasattr(upstream, "DEAD_STREAM_SECONDS"))

    def test_the_operators_own_timeout_is_still_the_backstop(self):
        """principle 6 names timeout_seconds as one of the three; it is the operator's to set. The
        real field, not a source-text search that a comment or an unrelated string could also
        satisfy."""
        import dataclasses

        from cria import config
        self.assertIn("timeout_seconds",
                      [f.name for f in dataclasses.fields(config.UpstreamConfig)])


if __name__ == "__main__":
    unittest.main()
