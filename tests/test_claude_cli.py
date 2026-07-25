import json
import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cria.claude_cli import ClaudeCliProvider, _openai_completion, _parse_claude_json
from cria.upstream import UpstreamError


class _Rlog:
    def __init__(self, session=None):
        self.session = session
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def _fake_claude(dirpath: str, arglog: str) -> str:
    """A stand-in `claude` binary: records its argv to arglog, prints canned JSON."""
    path = Path(dirpath) / "claude"
    path.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{arglog}"\n'
        "printf '%s' '{\"result\":\"did the thing\",\"session_id\":\"S1\","
        '"usage":{"input_tokens":10,"output_tokens":20},"model":"sonnet-4.6"}\x27\n'
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


class ParseTests(unittest.TestCase):
    def test_parses_result_session_and_usage(self):
        raw = '{"result":"hi","session_id":"abc","usage":{"input_tokens":3,"output_tokens":5},"model":"m"}'
        r = _parse_claude_json(raw, "fallback")
        self.assertEqual((r.content, r.session_id, r.output_tokens, r.model), ("hi", "abc", 5, "m"))

    def test_content_field_fallback(self):
        r = _parse_claude_json('{"content":"alt text"}', "fb")
        self.assertEqual(r.content, "alt text")
        self.assertEqual(r.model, "fb")

    def test_non_json_becomes_content(self):
        r = _parse_claude_json("just some text, not json", "fb")
        self.assertEqual(r.content, "just some text, not json")
        self.assertIsNone(r.session_id)

    def test_openai_completion_shape(self):
        r = _parse_claude_json('{"result":"x","usage":{"input_tokens":1,"output_tokens":2}}', "m")
        obj = json.loads(_openai_completion(r))
        self.assertEqual(obj["choices"][0]["message"]["content"], "x")
        self.assertEqual(obj["usage"]["total_tokens"], 3)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.arglog = os.path.join(self._tmp.name, "args.log")
        self.binary = _fake_claude(self._tmp.name, self.arglog)

    def _args_lines(self):
        return Path(self.arglog).read_text().splitlines() if os.path.exists(self.arglog) else []

    def test_chat_returns_completion_from_cli(self):
        p = ClaudeCliProvider(binary=self.binary)
        raw = p.chat({"model": "sonnet-4.6", "messages": [{"role": "user", "content": "do it"}]}, _Rlog())
        self.assertEqual(json.loads(raw)["choices"][0]["message"]["content"], "did the thing")

    def test_session_resume_on_second_call(self):
        p = ClaudeCliProvider(binary=self.binary)
        rlog = _Rlog(session="sess-A")
        body = {"model": "sonnet-4.6", "messages": [{"role": "user", "content": "step one"}]}
        p.chat(body, rlog)
        p.chat(body, rlog)  # same session → should --resume S1
        lines = self._args_lines()
        self.assertEqual(len(lines), 2)
        self.assertNotIn("--resume", lines[0])  # first call has no session yet
        self.assertIn("--resume S1", lines[1])  # second call resumes what the first returned

    def test_sessionless_calls_never_resume_across_conversations(self):
        # M15: without a real session id (rlog.session is None), the provider must NOT --resume — else
        # two UNRELATED sessionless conversations would fold onto a shared "main" key and bleed context (#23).
        p = ClaudeCliProvider(binary=self.binary)
        p.chat({"model": "m", "messages": [{"role": "user", "content": "task A"}]}, _Rlog(session=None))
        p.chat({"model": "m", "messages": [{"role": "user", "content": "task B"}]}, _Rlog(session=None))
        lines = self._args_lines()
        self.assertEqual(len(lines), 2)
        self.assertNotIn("--resume", lines[0])
        self.assertNotIn("--resume", lines[1])  # the 2nd sessionless call must NOT resume the 1st's session

    def test_streaming_fake_streams_the_result(self):
        p = ClaudeCliProvider(binary=self.binary)
        chunks = list(p.stream_chat({"model": "m", "messages": [{"role": "user", "content": "go"}]}, _Rlog()))
        blob = b"".join(chunks)
        self.assertIn(b"did the thing", blob)
        self.assertTrue(blob.endswith(b"data: [DONE]\n\n"))

    def test_missing_binary_raises(self):
        p = ClaudeCliProvider(binary="/no/such/claude/binary")
        with self.assertRaises(UpstreamError):
            p.chat({"model": "m", "messages": [{"role": "user", "content": "x"}]}, _Rlog())


if __name__ == "__main__":
    unittest.main()
