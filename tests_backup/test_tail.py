import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from cria.tail import latest_log, main, matches, render

_RECS = [
    {"iso": "2026-07-07T00:00:00.100+00:00", "level": "info", "kind": "request.recv", "turn": "t1", "session": "s1", "model": "m", "n_messages": 2},
    {"iso": "2026-07-07T00:00:00.200+00:00", "level": "info", "kind": "decision", "turn": "t1", "session": "s1", "decision": "engagement", "choice": "task", "reason": "write a handler", "task_type": "coding"},
    {"iso": "2026-07-07T00:00:00.300+00:00", "level": "warn", "kind": "route.skip", "turn": "t2", "role": "cloud.coder", "reason": "unresolvable"},
    {"iso": "2026-07-07T00:00:00.400+00:00", "level": "debug", "kind": "http.access", "turn": "t2", "line": "GET /health"},
]


class MatchTests(unittest.TestCase):
    def test_level_floor(self):
        self.assertFalse(matches(_RECS[3], min_level=20))  # debug < info
        self.assertTrue(matches(_RECS[2], min_level=20))  # warn >= info

    def test_turn_and_session(self):
        self.assertTrue(matches(_RECS[0], turn="t1"))
        self.assertFalse(matches(_RECS[0], turn="t2"))
        self.assertFalse(matches(_RECS[0], session="other"))

    def test_kind_substring(self):
        self.assertTrue(matches(_RECS[2], kind="route"))
        self.assertFalse(matches(_RECS[2], kind="upstream"))

    def test_decisions_only(self):
        self.assertTrue(matches(_RECS[1], decisions=True))
        self.assertFalse(matches(_RECS[0], decisions=True))


class RenderTests(unittest.TestCase):
    def test_decision_render_shows_choice_and_reason(self):
        line = render(_RECS[1], color=False)
        self.assertIn("DECIDE", line)
        self.assertIn("engagement", line)
        self.assertIn("task", line)
        self.assertIn("write a handler", line)
        self.assertIn("task_type=coding", line)  # extra field carried in the tail

    def test_normal_render_shows_kind_and_fields(self):
        line = render(_RECS[0], color=False)
        self.assertIn("request.recv", line)
        self.assertIn("n_messages=2", line)
        self.assertIn("INFO", line)


class LatestLogTests(unittest.TestCase):
    def test_picks_newest_by_name(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "cria-20260706.jsonl").write_text("")
            (Path(tmp) / "cria-20260707.jsonl").write_text("")
            self.assertTrue(latest_log(tmp).endswith("cria-20260707.jsonl"))

    def test_none_when_empty(self):
        with TemporaryDirectory() as tmp:
            self.assertIsNone(latest_log(tmp))


class MainTests(unittest.TestCase):
    def _write(self, tmp) -> str:
        p = Path(tmp) / "cria-20260707.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in _RECS) + "\n")
        return str(p)

    def _run(self, argv) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(argv)
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def test_decisions_filter(self):
        with TemporaryDirectory() as tmp:
            out = self._run([self._write(tmp), "--decisions"])
            self.assertIn("DECIDE", out)
            self.assertNotIn("request.recv", out)

    def test_turn_filter(self):
        with TemporaryDirectory() as tmp:
            out = self._run([self._write(tmp), "--turn", "t2"])
            self.assertIn("route.skip", out)
            self.assertNotIn("t1", out.replace("2026-07-07", ""))  # no t1 rows (ignore date)

    def test_raw_passthrough(self):
        with TemporaryDirectory() as tmp:
            out = self._run([self._write(tmp), "--kind", "decision", "--raw"])
            self.assertEqual(json.loads(out.strip())["decision"], "engagement")

    def test_last_n(self):
        with TemporaryDirectory() as tmp:
            out = self._run([self._write(tmp), "-n", "1"])
            self.assertEqual(len(out.strip().splitlines()), 1)
            self.assertIn("http.access", out)  # the last record

    def test_missing_file_returns_1(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["/no/such/log.jsonl"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
