"""Full-fidelity per-call capture: exactly what the model sees, one file per call."""
import json
import tempfile
import unittest
from pathlib import Path

from cria import callcapture


class _FakeLog:
    def __init__(self, session="sess-1", turn="turn-9", phase=None):
        self._session = session
        self._turn = turn
        self.phase = phase
        self.events = []

    @property
    def session(self):
        return self._session

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class TestCapture(unittest.TestCase):
    def test_writes_exact_body_and_emits_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            rlog = _FakeLog(phase="coder-s2")
            body = {
                "model": "qwopus", "stream": False, "temperature": 0.6,
                "chat_template_kwargs": {"enable_thinking": True},
                "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}],
                "tools": [{"type": "function", "function": {"name": "exec_command"}}],
            }
            path = callcapture.capture(body, rlog, calls_dir=tmp, phase=rlog.phase, url="http://x/v1/chat/completions")
            self.assertIsNotNone(path)
            rec = json.loads(Path(path).read_text())
            # the captured body is byte-for-byte the input body (exact fidelity)
            self.assertEqual(rec["body"], body)
            self.assertEqual(rec["phase"], "coder-s2")
            self.assertEqual(rec["session"], "sess-1")
            self.assertEqual(rec["turn"], "turn-9")
            self.assertEqual(rec["stats"]["n_messages"], 2)
            self.assertEqual(rec["stats"]["n_tools"], 1)
            self.assertGreater(rec["stats"]["est_total"], 0)
            # a pointer event was emitted for correlation
            kinds = [k for k, _ in rlog.events]
            self.assertIn("upstream.dump", kinds)
            dump = dict(rlog.events[0][1])
            self.assertEqual(dump["path"], path)
            self.assertEqual(dump["phase"], "coder-s2")

    def test_filename_labeled_by_seq_and_phase_and_ordered(self):
        with tempfile.TemporaryDirectory() as tmp:
            rlog = _FakeLog(session="sess-2")
            p1 = callcapture.capture({"messages": []}, rlog, calls_dir=tmp, phase="planner")
            p2 = callcapture.capture({"messages": []}, rlog, calls_dir=tmp, phase="coder-s1")
            self.assertRegex(Path(p1).name, r"^\d{4}-planner\.json$")
            self.assertRegex(Path(p2).name, r"^\d{4}-coder-s1\.json$")
            self.assertLess(Path(p1).name, Path(p2).name)  # sequence increments → sorts in call order
            # both land under the session subdir
            self.assertEqual(Path(p1).parent.name, "sess-2")

    def test_no_phase_falls_back_to_call_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = callcapture.capture({"messages": []}, _FakeLog(session="s3"), calls_dir=tmp, phase=None)
            self.assertRegex(Path(path).name, r"^\d{4}-call\.json$")

    def test_missing_session_uses_nosession_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = callcapture.capture({"messages": []}, _FakeLog(session=None), calls_dir=tmp, phase="proxy")
            self.assertEqual(Path(path).parent.name, "nosession")

    def test_rendered_prompt_written_as_sibling_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            rlog = _FakeLog(session="s4")
            rendered = "<|im_start|>user\nhi<|im_end|>\n<|im_start|>assistant\n<think>\n"
            path = callcapture.capture({"messages": [{"role": "user", "content": "hi"}]}, rlog,
                                       calls_dir=tmp, phase="coder-s1", rendered=rendered)
            rec = json.loads(Path(path).read_text())
            txt = Path(path).parent / rec["rendered_prompt_file"]
            self.assertTrue(txt.exists())
            self.assertEqual(txt.read_text(), rendered)  # the literal string the model tokenizes
            self.assertEqual(rec["stats"]["rendered_chars"], len(rendered))
            self.assertTrue(dict(rlog.events[0][1])["rendered"])


class SessionDirnameTests(unittest.TestCase):
    """The per-run folder is named <timestamp>-<session> so the newest run sorts last and the
    time reads at a glance — the timestamp decoded from the (UUIDv7) session id."""

    def test_uuid7_id_gets_a_sortable_timestamp_prefix(self):
        sid = "019f5818-c99f-7911-a78e-79bbdb49625f"
        name = callcapture.session_dirname(sid)
        self.assertTrue(name.startswith("20260712T"), name)   # decoded from the id's own ms clock
        self.assertTrue(name.endswith(sid))
        self.assertRegex(name, r"^\d{8}T\d{6}-")

    def test_deterministic_and_stable(self):
        sid = "019f5818-c99f-7911-a78e-79bbdb49625f"
        self.assertEqual(callcapture.session_dirname(sid), callcapture.session_dirname(sid))

    def test_chronological_sort_matches_creation_order(self):
        older = "019f5818-0000-7000-8000-000000000000"
        newer = "019f5900-0000-7000-8000-000000000000"
        self.assertLess(callcapture.session_dirname(older), callcapture.session_dirname(newer))

    def test_non_uuid7_falls_back_to_bare_id(self):
        # a v4 UUID (not v7) and an arbitrary key get NO invented prefix (no unstable now())
        self.assertEqual(callcapture.session_dirname("550e8400-e29b-41d4-a716-446655440000"),
                         "550e8400-e29b-41d4-a716-446655440000")
        self.assertEqual(callcapture.session_dirname("my-key"), "my-key")
        self.assertEqual(callcapture.session_dirname(None), "nosession")

    def test_capture_lands_in_the_timestamped_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid = "019f5818-c99f-7911-a78e-79bbdb49625f"
            rlog = _FakeLog(session=sid)
            path = callcapture.capture({"messages": [{"role": "user", "content": "hi"}]}, rlog,
                                       calls_dir=tmp, phase="coder-s1")
            self.assertEqual(Path(path).parent.name, callcapture.session_dirname(sid))


if __name__ == "__main__":
    unittest.main()
