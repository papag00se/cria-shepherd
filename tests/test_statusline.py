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
