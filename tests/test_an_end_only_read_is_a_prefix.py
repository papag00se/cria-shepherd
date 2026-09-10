"""An end bound must not silently turn a prefix read into a whole-file read."""
import json
import pathlib
import subprocess
import tempfile
import unittest

from cria import writeproxy, wsview
from cria.writeproxy import _read_command


class EndOnlyReadContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="end-only-contract-")
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name) / "fixture.txt"

    def run_read(self, **bounds):
        command = _read_command({"path": str(self.path), **bounds})
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr

    def test_end_only_large_file_matches_explicit_prefix(self):
        self.path.write_text("".join(f"row {n}\n" for n in range(9001)))
        expected = self.run_read(start_line=1, end_line=20)
        self.assertIn("20: row 19\n", expected[1])
        self.assertNotIn("denied", expected[1])
        self.assertEqual(self.run_read(end_line=20), expected)

    def test_end_only_small_file_does_not_return_unrequested_tail(self):
        self.path.write_text("one\ntwo\nthree\n")
        self.assertEqual(self.run_read(end_line=2), self.run_read(start_line=1, end_line=2))

    def test_whole_read_keeps_eof_bytes(self):
        self.path.write_text("\none\n\n")
        self.assertEqual(self.run_read()[1], "\none\n\n")

    def test_start_only_keeps_existing_numbered_suffix(self):
        self.path.write_text("one\ntwo\nthree\n")
        self.assertEqual(self.run_read(start_line=2)[1], "2: two\n3: three\n")

    def test_inverted_range_is_still_refused(self):
        self.path.write_text("one\ntwo\nthree\n")
        self.assertIn("denied", self.run_read(start_line=3, end_line=1)[1])

    def test_oversized_requested_prefix_is_still_refused(self):
        self.path.write_text("x" * 20000 + "\n")
        self.assertIn("denied", self.run_read(end_line=1)[1])

    def test_end_beyond_eof_matches_explicit_range(self):
        self.path.write_text("one\ntwo\n")
        self.assertEqual(self.run_read(end_line=200), self.run_read(start_line=1, end_line=200))

    def test_roundtrip_keeps_original_arguments_and_whole_file_authority(self):
        payload = "one\ntwo\nthree\n"
        self.path.write_text(payload)
        args = {"path": "fixture.txt", "end_line": 2}
        comp = {"choices": [{"message": {"tool_calls": [{
            "id": "prefix", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps(args)}}]}}]}
        shell = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
        view = wsview.View(self.tmp.name)
        view.note_written("fixture.txt", payload)
        token = wsview.bind(view)
        try:
            writeproxy.translate_outbound(comp, shell, injected={"read_file"})
            call = comp["choices"][0]["message"]["tool_calls"][0]
            command = json.loads(call["function"]["arguments"])["cmd"]
            result = subprocess.run(["bash", "-c", command], cwd=self.tmp.name,
                                    capture_output=True, text=True, check=True)
            represented = writeproxy.represent_inbound([
                {"role": "assistant", "tool_calls": [call]},
                {"role": "tool", "tool_call_id": "prefix", "content": result.stdout}])
            restored = represented[0]["tool_calls"][0]["function"]
            self.assertEqual(restored["name"], "read_file")
            self.assertEqual(json.loads(restored["arguments"]), args)
            self.assertEqual(represented[-1]["content"], "1: one\n2: two\n")
            self.assertEqual(view.read_bytes(str(self.path)), payload.encode())
        finally:
            wsview.unbind(token)

    def test_missing_file_still_reports_the_read_failure(self):
        self.assertEqual(self.run_read(end_line=20), self.run_read(start_line=1, end_line=20))
        self.assertIn("denied", self.run_read(end_line=20)[1])
