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
from unittest import mock

from cria import bodykeys, loop, prompts, rumination, upstream


class _Rlog:
    live_chars = 0
    phase = "coder"
    def __init__(self): self.events = []
    def emit(self, kind, **kw): self.events.append((kind, kw))
    def first(self, kind): return next((kw for k, kw in self.events if k == kind), None)


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


class _SSEResp:
    """A urllib response double good for one read: iterating its lines, then closeable."""

    def __init__(self, frames):
        self._lines = _sse(frames).splitlines(keepends=True)

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass


def _watched(frames, *, context_window=1_000_000):
    """Drive the REAL streaming reader (`Upstream.chat_watched`) over a fake SSE response and
    return ``(assembled completion dict, rlog)``."""
    up = upstream.Upstream("http://x", context_window=context_window)
    rlog = _Rlog()
    with mock.patch("urllib.request.urlopen", return_value=_SSEResp(frames)):
        out = up.chat_watched({"messages": [{"role": "user", "content": "hi"}], "model": "m"}, rlog)
    return json.loads(out), rlog


class TheThresholdIsSane(unittest.TestCase):
    def test_it_is_generous_enough_that_a_real_turn_never_reaches_it(self):
        """A turn that has streamed nothing readable after this many frames is not slow, it is dead."""
        self.assertGreaterEqual(rumination.DEAD_STREAM_CHUNKS, 100)


class TheStreamLoopAborts(unittest.TestCase):
    """Drives the real streaming reader (`Upstream.chat_watched`) over a fake SSE response —
    the rule stated directly ('many frames, zero readable characters') is only proven by making
    the real counters count."""

    def test_a_dead_stream_is_detected_and_aborted(self):
        comp, rlog = _watched([_empty_delta()] * (rumination.DEAD_STREAM_CHUNKS + 5))
        abort = rlog.first("rumination.abort")
        self.assertIsNotNone(abort, "many empty frames must trip the guard")
        self.assertTrue(abort["dead_stream"])
        self.assertEqual(comp["choices"][0]["finish_reason"], "rumination")
        self.assertEqual(comp["cria_rumination"]["dead_stream"], True)

    def test_a_large_write_never_trips_it(self):
        """The case principle 6 protects: a legitimate huge write_file accumulates from delta one
        and must stream to completion untouched, however many frames it takes."""
        frags = [_arg_delta(f"line{i} = compute_value({i})\n") for i in range(rumination.DEAD_STREAM_CHUNKS * 3)]
        comp, rlog = _watched(frags)
        self.assertIsNone(rlog.first("rumination.abort"))
        self.assertEqual(comp["choices"][0]["finish_reason"], "tool_calls")
        args = comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        self.assertIn("line0 = compute_value(0)", args)
        self.assertIn(f"line{len(frags) - 1} = compute_value({len(frags) - 1})", args)

    def test_it_is_checked_before_the_degenerate_backstop_and_the_watcher(self):
        """STRUCTURAL, deliberately not a behaviour test: `gen_tail`/`streamed_chars` update
        together on every readable fragment (upstream.py, the frag loop right above these checks),
        so `streamed_chars == 0` (dead-stream's own trigger) and a non-empty periodic tail
        (degenerate-tail's trigger) can never both hold at the same evaluation — no fixture can
        make the checks fire in the "wrong" order because the two conditions are mutually
        exclusive by construction. What this guards is the source staying in the narrative order
        the surrounding comments describe, which only `inspect.getsource` + position can see."""
        import inspect
        src = inspect.getsource(upstream.Upstream.chat_watched)
        self.assertLess(src.index("DEAD_STREAM_CHUNKS"), src.index("degenerate_tail"))


class TheCoderIsToldWhatActuallyHappened(unittest.TestCase):
    def test_a_third_notice_exists_for_it(self):
        """5b: telling it to 'stop re-examining' or 'stop repeating a passage' would name a behaviour
        that did not happen. It produced nothing."""
        text = prompts.load("rumination_guard_dead_stream")
        self.assertIn("produced nothing", text)
        self.assertNotIn("second-guessing", text)
        self.assertNotIn("repeating", text)

    def test_the_guard_selects_it(self):
        """Drive the real selection: a dead-stream-aborted completion must retry with THIS
        prompt's text, not the generic rumination/window/degenerate notices."""
        comp = {"choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "rumination"}],
               bodykeys.RUMINATION: {"dead_stream": True, "chunks": 400}}
        sent = []

        def chat(body, rlog):
            sent.append(list(body.get("messages") or []))
            return json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"},
                                            "finish_reason": "stop"}]}).encode()

        loop.guard_rumination(comp, {"messages": [{"role": "user", "content": "task"}], "tools": []},
                              chat, _Rlog())
        self.assertEqual(sent[0][-1]["content"], prompts.load("rumination_guard_dead_stream"))

    def test_it_never_names_the_shim_to_the_model(self):
        import re
        self.assertIsNone(re.search(r"\bcria\b", prompts.load("rumination_guard_dead_stream"), re.I))


if __name__ == "__main__":
    unittest.main()
