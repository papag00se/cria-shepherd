"""The live status ticker (operator: "for the first 7 mins there was no feedback" + "a file wrote
to the project, but there was no indicator"). Curated rlog kinds → one-line ⟦cria⟧ status, streamed
as they happen, deduped, never able to break the request; per-ACTION lines narrate what the
harness renders as an opaque lowered blob. Stripped inbound like the banner."""

import unittest

from cria import statusline
from cria.indicators import MARKER


class LineForTests(unittest.TestCase):
    def test_curated_kinds_map(self):
        self.assertEqual(statusline.line_for("plan.submitted", None, {"steps": 6}),
                         f"{MARKER}plan ready · 6 steps")
        self.assertEqual(statusline.line_for("loop.item", None, {"step": 2, "total": 5}),
                         f"{MARKER}step 2/5")

    def test_actions_narrate_the_lowered_call(self):
        self.assertEqual(
            statusline.line_for("writeproxy.lowered", None, {"tool": "write_file", "target": "resolve.py"}),
            f"{MARKER}writing resolve.py")
        self.assertEqual(
            statusline.line_for("writeproxy.lowered", None, {"tool": "web_search", "detail": "ada handles api"}),
            f"{MARKER}searching · ada handles api")

    def test_phase_fallback_announces_slow_internal_calls(self):
        self.assertEqual(statusline.line_for("upstream.request", "self-compact", {}),
                         f"{MARKER}compacting history")
        self.assertEqual(statusline.line_for("upstream.request", "critic-confirm", {}),
                         f"{MARKER}confirming the pass")

    def test_uncurated_kinds_and_broken_templates_stay_silent(self):
        self.assertIsNone(statusline.line_for("ctx.estimate", None, {}))
        self.assertIsNone(statusline.line_for("plan.submitted", None, {}))  # field missing → silence


class StatusWriterTests(unittest.TestCase):
    def test_dedupes_consecutive_and_survives_a_broken_wire(self):
        wrote = []
        w = statusline.StatusWriter(wrote.append)
        for _ in range(3):
            w.on_event("upstream.request", "planner", {})
        w.on_event("plan.drafted", None, {})
        self.assertEqual(len(wrote), 2)                       # planner ticked once, then drafted

        def boom(_):
            raise BrokenPipeError()
        w2 = statusline.StatusWriter(boom)
        w2.on_event("plan.drafted", None, {})                 # must not raise
        self.assertEqual(w2.lines, 0)


class StripTests(unittest.TestCase):
    def test_status_lines_are_stripped_from_inbound_history(self):
        from cria.indicators import strip_history
        msgs = [{"role": "assistant",
                 "content": f"{MARKER}research · web_fetch\n{MARKER}writing resolve.py\nreal answer"}]
        out, n = strip_history(msgs)
        self.assertEqual(out[0]["content"].strip(), "real answer")
        self.assertEqual(n, 2)


if __name__ == "__main__":
    unittest.main()


class LiveRateTests(unittest.TestCase):
    """tok/s on the in-between tick — ONLY for the streamed call (the coder). Internal judge and
    compactor calls are non-streamed: nothing arrives until they finish, so no rate is invented."""

    def test_rate_appears_when_streaming_counters_exist(self):
        self.assertIn("~7.8 tok/s", statusline.still_working_line("coder-s2", 125.0, 7.83))

    def test_no_rate_for_non_streamed_calls(self):
        line = statusline.still_working_line("critic", 95.0, None)
        self.assertNotIn("tok/s", line)

    def test_chat_watched_maintains_and_clears_the_counters(self):
        import json as j
        from unittest import mock
        from cria.upstream import Upstream
        from tests.test_upstream import _FakeResp, _Rlog, _delta, _sse
        lines = [
            _sse(_delta(content="hello world, streaming tokens")),
            _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            b"data: [DONE]\n",
        ]
        rlog = _Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=_FakeResp(lines)):
            Upstream("http://x", context_window=8192, capture_dir=None).chat_watched(
                {"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog)
        self.assertEqual(rlog.live_chars, len("hello world, streaming tokens"))
        self.assertIsNone(rlog.live_t0)                       # cleared: no stale rate after the call
