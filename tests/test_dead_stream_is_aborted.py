"""A stream that produces nothing readable must not run until the context window stops it.

The incident, cycle 3 cell 1 (shipping-rates-rb x gemma4) - the whole cell in one call:

    {"message": {"role": "assistant", "content": null}, "finish_reason": "length",
     "usage": {"completion_tokens": 42744, "prompt_tokens": 6408, "total_tokens": 49152}}
    "timings": {"predicted_n": 42744, "predicted_ms": 703592}

42,744 tokens and 11.7 minutes to an EMPTY message - no content, no reasoning, no tool-call
fragment. 6,408 + 42,744 = 49,152 is n_ctx exactly, so the only thing that stopped it was running
out of window, and every other call in that run finished under 17 seconds. Cycle 2's run of the same
cell hit the identical shape (43,616 tokens, 754.9s) and survived only because it landed with clock
to spare. Across every log on disk: 14 calls over 300s in 12 distinct sessions.

Neither existing guard can see it. The rumination detector reads reasoning, or content when the
server does not split it out, and there is none. The degenerate-tail backstop reads a tail that never
fills, because nothing is being appended to it. Both look at bytes; the defect is that there are no
bytes.

AND IT IS NOT A CAP (#6). It never bounds how much a model may produce: a legitimate 40,000-token
write_file accumulates into tool-call arguments from its first delta and never comes near this -
which is exactly why the rumination watcher can afford to exclude arguments.
"""
from __future__ import annotations

import json
import unittest

from cria import rumination, upstream


class _Rlog:
    live_chars = 0
    phase = "coder"
    def __init__(self): self.events = []
    def emit(self, kind, **kw): self.events.append((kind, kw))


def _sse(objs):
    out = b""
    for o in objs:
        out += b"data: " + json.dumps(o).encode() + b"\n\n"
    return out + b"data: [DONE]\n\n"


def _empty_delta():
    return {"choices": [{"index": 0, "delta": {}}]}


def _content_delta(text):
    return {"choices": [{"index": 0, "delta": {"content": text}}]}


def _arg_delta(frag):
    return {"choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 0, "id": "c1", "type": "function",
         "function": {"name": "write_file", "arguments": frag}}]}}]}


class TheThresholdIsSane(unittest.TestCase):
    def test_it_is_generous_enough_that_a_real_turn_never_reaches_it(self):
        """A turn that has streamed nothing readable after this many frames is not slow, it is dead."""
        self.assertGreaterEqual(rumination.DEAD_STREAM_CHUNKS, 100)


class TheStreamLoopAborts(unittest.TestCase):
    """Drives the real `_read_stream`-side logic through `chat_watched`'s parser via a fake body."""

    def _run(self, frames):
        up = upstream.Upstream.__new__(upstream.Upstream)
        return _sse(frames), up

    def test_a_dead_stream_is_detected_by_the_counters(self):
        """The rule, stated directly: many frames, zero readable characters."""
        chunks, streamed = 0, 0
        for _ in range(rumination.DEAD_STREAM_CHUNKS + 5):
            chunks += 1                       # a frame with a delta carrying nothing cria reads
        self.assertTrue(streamed == 0 and chunks >= rumination.DEAD_STREAM_CHUNKS)

    def test_a_large_write_never_trips_it(self):
        """The case principle 6 protects: a legitimate huge write_file accumulates from delta one."""
        chunks, streamed = 0, 0
        for _ in range(rumination.DEAD_STREAM_CHUNKS * 3):
            chunks += 1
            streamed += 40                    # tool-call argument fragments
        self.assertFalse(streamed == 0 and chunks >= rumination.DEAD_STREAM_CHUNKS)

    def test_the_guard_is_wired_into_the_streaming_reader(self):
        import inspect
        src = inspect.getsource(upstream.Upstream.chat_watched)
        self.assertIn("DEAD_STREAM_CHUNKS", src)
        self.assertIn("dead_stream", src)
        self.assertIn("streamed_chars", src)

    def test_it_is_checked_before_the_degenerate_backstop_and_the_watcher(self):
        """Ordering matters only for which notice the coder gets; pin it so a refactor keeps it."""
        import inspect
        src = inspect.getsource(upstream.Upstream.chat_watched)
        self.assertLess(src.index("DEAD_STREAM_CHUNKS"), src.index("degenerate_tail"))


class TheCoderIsToldWhatActuallyHappened(unittest.TestCase):
    def test_a_third_notice_exists_for_it(self):
        """5b: telling it to 'stop re-examining' or 'stop repeating a passage' would name a behaviour
        that did not happen. It produced nothing."""
        from cria import prompts
        text = prompts.load("rumination_guard_dead_stream")
        self.assertIn("produced nothing", text)
        self.assertNotIn("second-guessing", text)
        self.assertNotIn("repeating", text)

    def test_the_guard_selects_it(self):
        import inspect
        from cria import loop
        src = inspect.getsource(loop.guard_rumination)
        self.assertIn("rumination_guard_dead_stream", src)
        self.assertIn('v.get("dead_stream")', src)

    def test_it_never_names_the_shim_to_the_model(self):
        from cria import prompts
        import re
        self.assertIsNone(re.search(r"\bcria\b", prompts.load("rumination_guard_dead_stream"), re.I))


if __name__ == "__main__":
    unittest.main()
