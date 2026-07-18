import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cria.events import EventLog, _console_line


class EventLogTests(unittest.TestCase):
    def _read(self, path: Path) -> list[dict]:
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def test_emit_writes_complete_jsonl_record(self):
        with TemporaryDirectory() as tmp:
            log = EventLog(level="info", dir=tmp, console=False, jsonl=True)
            log.emit("request.recv", session="s1", turn="t1", model="m", n_messages=3)
            log.close()
            recs = self._read(log.path)
            self.assertEqual(len(recs), 1)
            r = recs[0]
            self.assertEqual(r["kind"], "request.recv")
            self.assertEqual(r["session"], "s1")
            self.assertEqual(r["turn"], "t1")
            self.assertEqual(r["model"], "m")
            self.assertEqual(r["n_messages"], 3)
            self.assertIn("ts", r)
            self.assertIn("iso", r)

    def test_jsonl_is_never_level_filtered(self):
        # console level is 'error', but the JSONL must still capture a debug event.
        with TemporaryDirectory() as tmp:
            log = EventLog(level="error", dir=tmp, console=False, jsonl=True)
            log.emit("http.access", level="debug", line="GET /health")
            log.close()
            recs = self._read(log.path)
            self.assertEqual(recs[0]["level"], "debug")

    def test_decide_records_choice_and_reason(self):
        with TemporaryDirectory() as tmp:
            log = EventLog(dir=tmp, console=False)
            log.decide("engagement", "task", "prompt asks to write a handler + tests", turn="t9")
            log.close()
            r = self._read(log.path)[0]
            self.assertEqual(r["kind"], "decision")
            self.assertEqual(r["decision"], "engagement")
            self.assertEqual(r["choice"], "task")
            self.assertIn("write a handler", r["reason"])

    def test_bound_log_carries_ids(self):
        with TemporaryDirectory() as tmp:
            log = EventLog(dir=tmp, console=False)
            rlog = log.bind(session="sess", turn="turn")
            rlog.emit("upstream.request", url="http://x")
            rlog.decide("route", "local", "classifier said coding")
            log.close()
            recs = self._read(log.path)
            self.assertTrue(all(r.get("session") == "sess" and r.get("turn") == "turn" for r in recs))

    def test_console_line_is_readable_and_has_no_header_dupes(self):
        rec = {
            "ts": 1.0,
            "iso": "2026-07-06T22:00:00.500+00:00",
            "level": "info",
            "kind": "upstream.done",
            "turn": "abc123",
            "tokens": 42,
            "tok_per_s": 7.25,
        }
        line = _console_line(rec)
        self.assertIn("[abc123]", line)
        self.assertIn("upstream.done", line)
        self.assertIn("tokens=42", line)
        self.assertIn("tok_per_s=7.2", line)  # float trimmed to 1 dp
        self.assertNotIn("iso=", line)  # header fields not repeated in the tail

    def test_jsonl_disabled_writes_no_file(self):
        log = EventLog(dir=None, console=False, jsonl=False)
        log.emit("server.start")  # must not raise without a file sink
        self.assertIsNone(log.path)
        log.close()


class BoundLogTpsTests(unittest.TestCase):
    """The bound (per-turn) logger remembers the last model generation's tok/s so the
    response banner can show how fast the local model actually ran."""

    def _rlog(self):
        return EventLog(console=False, jsonl=False).bind(session="s", turn="t")

    def test_captures_last_tok_per_s_from_upstream_done(self):
        rlog = self._rlog()
        self.assertIsNone(rlog.last_tok_per_s)  # nothing generated yet
        rlog.emit("upstream.done", tokens=50, tok_per_s=42.3)
        self.assertEqual(rlog.last_tok_per_s, 42.3)

    def test_none_rate_does_not_clobber_a_real_one(self):
        rlog = self._rlog()
        rlog.emit("upstream.done", tokens=50, tok_per_s=42.3)
        rlog.emit("upstream.done", tokens=0, tok_per_s=None)  # a call with no usage
        self.assertEqual(rlog.last_tok_per_s, 42.3)

    def test_last_generation_wins(self):
        rlog = self._rlog()
        rlog.emit("upstream.done", tok_per_s=10.0)   # e.g. the planner call
        rlog.emit("upstream.done", tok_per_s=88.0)   # then the coder call
        self.assertEqual(rlog.last_tok_per_s, 88.0)

    def test_non_upstream_events_are_ignored(self):
        rlog = self._rlog()
        rlog.emit("loop.item", step=1, total=3)
        self.assertIsNone(rlog.last_tok_per_s)

    def test_generated_tokens_sum_across_calls_in_the_request(self):
        rlog = self._rlog()
        self.assertEqual(rlog.gen_tokens, 0)              # nothing generated yet
        rlog.emit("upstream.done", tokens=50, tok_per_s=42.3)    # e.g. a reasoner call
        rlog.emit("upstream.done", tokens=1200, tok_per_s=60.0)  # then the coder call
        self.assertEqual(rlog.gen_tokens, 1250)           # SUMMED, not last-wins (unlike the rate)
        rlog.emit("upstream.done", tokens=None, tok_per_s=None)  # a call with no usage → no-op on tokens
        self.assertEqual(rlog.gen_tokens, 1250)

    def test_model_calls_count_every_upstream_done(self):
        rlog = self._rlog()
        self.assertEqual(rlog.model_calls, 0)
        rlog.emit("upstream.done", tokens=50, tok_per_s=42.3)
        rlog.emit("upstream.done", tokens=None, tok_per_s=None)  # counts even with no usage/tokens
        self.assertEqual(rlog.model_calls, 2)                    # one per upstream.done — the real calls
        rlog.emit("loop.item", step=1)                           # a non-upstream event doesn't count
        self.assertEqual(rlog.model_calls, 2)


if __name__ == "__main__":
    unittest.main()
