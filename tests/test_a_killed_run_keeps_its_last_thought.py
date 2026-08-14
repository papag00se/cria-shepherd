"""A killed process left no reasoning behind, and the last thought is the one worth having.

Operator, 2026-08-13: *"I want all streamed reasoning logged. Whether it finishes or not."* The fix
that followed covered a clean finish, a mid-stream transport error, and an exception in the read
loop — every path with a Python frame to run. It did not cover the process being terminated, and the
suite terminates a run at its milestone floor.

Measured, `rust-toml-cli x ternary-bonsai` in cycle 1: call 0043 has a prompt file and a request body
and **no** `.reasoning.txt`. The run was killed mid-call. What was lost is the reasoning of the last
turn before the kill — the one that says what the model was about to do next, which on the cell
before it ("It only looks at a single 'TOTAL' value instead of properly merging per-SKU totals") was
the whole answer, one edit away.

A SIGKILL cannot run a `finally`, so the only thing that survives it is a write that already
happened. Reasoning is now appended to a `.reasoning.partial.txt` as it streams and the partial is
removed once the real file lands, so the bound on what a kill can lose is one flush window instead
of a whole turn.
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
    """A stream that dies the way a killed process dies: no exception, no more lines, no aftermath."""

    def __init__(self, lines, die_after=None):
        self.lines, self.closed, self._die = lines, False, die_after

    def __iter__(self):
        for i, ln in enumerate(self.lines):
            if self._die is not None and i == self._die:
                raise KeyboardInterrupt("SIGINT/SIGTERM mid-stream")
            yield ln

    def close(self):
        self.closed = True

    def read(self):
        return b""


def partials(tmp):
    return sorted(pathlib.Path(tmp).rglob("*.reasoning.partial.txt"))


def finals(tmp):
    return sorted(pathlib.Path(tmp).rglob("*.reasoning.txt"))


class ThePartialSurvivesADeathWithNoAftermathTests(unittest.TestCase):
    def drive(self, lines, die_after=None):
        tmp = tempfile.mkdtemp()
        up = Upstream("http://x", context_window=8192, capture_dir=tmp, capture_rendered=False)
        resp = Resp(lines, die_after=die_after)
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            try:
                up.chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, Rlog())
            except BaseException:      # noqa: BLE001 — the kill itself is not what is under test
                pass
        return tmp

    def test_the_thinking_is_on_disk_before_the_stream_ends(self):
        """The whole point: bytes that reached the disk during the turn, not after it."""
        big = "the totals are merged per SKU, not under one TOTAL key. " * 60
        tmp = self.drive([sse({"reasoning_content": big}), sse({"reasoning_content": "x"})],
                         die_after=1)
        files = partials(tmp) or finals(tmp)
        self.assertTrue(files, "a killed turn left nothing behind at all")
        self.assertIn("merged per SKU", files[0].read_text())

    def test_a_clean_turn_leaves_only_the_real_file(self):
        """The partial is scaffolding; it must not survive a normal turn and be walked as evidence."""
        tmp = self.drive([sse({"reasoning_content": "a complete thought"}),
                          sse({"content": "answer"}, usage={"completion_tokens": 4}),
                          b"data: [DONE]\n"])
        self.assertEqual(partials(tmp), [])
        self.assertEqual(finals(tmp)[0].read_text(), "a complete thought")

    def test_a_turn_with_no_reasoning_writes_no_partial(self):
        tmp = self.drive([sse({"content": "hi"}, usage={"completion_tokens": 1}),
                          b"data: [DONE]\n"])
        self.assertEqual(partials(tmp), [])


if __name__ == "__main__":
    unittest.main()
