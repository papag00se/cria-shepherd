import json
import unittest
from unittest import mock

from cria import rumination
from cria.upstream import Upstream, _accumulate_tool_deltas, _assemble_completion


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))
        return self


class _FakeResp:
    """A urlopen result: iterable over SSE byte lines, with a close() that records early aborts."""

    def __init__(self, lines):
        self._lines = list(lines)
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for ln in self._lines:
            self.consumed += 1
            yield ln

    def close(self):
        self.closed = True


def _sse(obj):
    return b"data: " + json.dumps(obj).encode() + b"\n"


def _delta(**d):
    return {"choices": [{"delta": d, "finish_reason": d.pop("_finish", None)}]}


class ToolAssemblyTests(unittest.TestCase):
    def test_accumulate_tool_deltas_by_index(self):
        acc = {}
        _accumulate_tool_deltas(acc, [{"index": 0, "id": "c1", "function": {"name": "write_file"}}])
        _accumulate_tool_deltas(acc, [{"index": 0, "function": {"arguments": '{"path":"a.py",'}}])
        _accumulate_tool_deltas(acc, [{"index": 0, "function": {"arguments": '"content":"x"}'}}])
        self.assertEqual(acc[0]["id"], "c1")
        self.assertEqual(acc[0]["name"], "write_file")
        self.assertEqual("".join(acc[0]["args"]), '{"path":"a.py","content":"x"}')

    def test_assemble_maps_finish_reason(self):
        acc = {0: {"id": "c1", "name": "write_file", "args": ['{"path":"a.py"}']}}
        c = _assemble_completion("m", [], [], acc, "stop", None, None)
        # a tool call present with a natural stop → normalized to tool_calls
        self.assertEqual(c["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(c["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "write_file")

    def test_assemble_rumination_sets_sentinel(self):
        c = _assemble_completion("m", ["thinking..."], ["reasoning"], {}, None, None, {"hits": 7, "reasoning_tokens": 5000})
        self.assertEqual(c["choices"][0]["finish_reason"], "rumination")
        self.assertEqual(c["cria_rumination"], {"hits": 7, "reasoning_tokens": 5000})


class ChatWatchedTests(unittest.TestCase):
    def _upstream(self):
        # context_window set → _resolve_window returns it without an HTTP /props call.
        return Upstream("http://x", context_window=8192, capture_dir=None)

    def test_assembles_tool_call_from_stream(self):
        lines = [
            _sse(_delta(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "write_file"}}])),
            _sse(_delta(tool_calls=[{"index": 0, "function": {"arguments": '{"path":"h.py","content":"print(1)"}'}}])),
            _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
            b"data: [DONE]\n",
        ]
        resp = _FakeResp(lines)
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            raw = self._upstream().chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, _Rlog())
        c = json.loads(raw)
        tc = c["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "write_file")
        self.assertEqual(json.loads(tc["function"]["arguments"])["path"], "h.py")
        self.assertEqual(c["choices"][0]["finish_reason"], "tool_calls")

    def test_saves_full_reasoning_untruncated_to_capture_sibling(self):
        import tempfile
        from pathlib import Path
        det = rumination.Detector(budget=10_000_000, threshold=999)  # never fires — capture a normal turn
        big = "I will resolve the handle then check the mock. " * 500  # ~23k chars; must NOT be clipped
        lines = [
            _sse(_delta(reasoning_content=big)),
            _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            b"data: [DONE]\n",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            up = Upstream("http://x", context_window=8192, capture_dir=tmp, capture_rendered=False)
            rlog = _Rlog()
            with mock.patch("cria.upstream.urllib.request.urlopen", return_value=_FakeResp(lines)):
                up.chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog, watch=det.check)
            files = list(Path(tmp).rglob("*.reasoning.txt"))
            self.assertEqual(len(files), 1)                       # one reasoning file per coder call
            self.assertEqual(files[0].read_text(), big)          # the WHOLE block, byte-for-byte, untruncated
            self.assertIn("coder.reasoning", [k for k, _ in rlog.events])

    def test_ruminating_reasoning_file_is_marked(self):
        import tempfile
        from pathlib import Path
        det = rumination.Detector(budget=1000, threshold=3)  # fires
        chunk = "actually wait hmm let me reconsider on second thought " * 10
        lines = [_sse(_delta(reasoning_content=chunk)) for _ in range(20)] + [b"data: [DONE]\n"]
        with tempfile.TemporaryDirectory() as tmp:
            up = Upstream("http://x", context_window=8192, capture_dir=tmp, capture_rendered=False)
            with mock.patch("cria.upstream.urllib.request.urlopen", return_value=_FakeResp(lines)):
                up.chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, _Rlog(), watch=det.check)
            saved = list(Path(tmp).rglob("*.reasoning.txt"))[0].read_text()
            self.assertIn("RUMINATION GUARD FIRED", saved)          # marked at the top
            self.assertIn("ABORTED HERE by the rumination guard", saved)  # and where it was cut
            self.assertIn("let me reconsider", saved)               # the full reasoning is still there

    def test_rumination_abort_cuts_stream_early(self):
        det = rumination.Detector(budget=1000, threshold=3)  # gate 500 tok; fires fast
        chunk = "actually wait hmm let me reconsider on second thought " * 10  # ~530 chars, many markers
        lines = [_sse(_delta(reasoning_content=chunk)) for _ in range(20)] + [b"data: [DONE]\n"]
        resp = _FakeResp(lines)
        rlog = _Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            raw = self._upstream().chat_watched(
                {"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog, watch=det.check)
        c = json.loads(raw)
        self.assertEqual(c["choices"][0]["finish_reason"], "rumination")
        self.assertIn("cria_rumination", c)
        self.assertTrue(resp.closed)
        self.assertLess(resp.consumed, len(lines))  # aborted BEFORE draining the whole stream
        self.assertIn("rumination.abort", [k for k, _ in rlog.events])


class MergeAssistantTests(unittest.TestCase):
    def test_adjacent_assistants_merged(self):
        from cria.upstream import _merge_consecutive_assistant
        msgs = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "let me do that"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]},
        ]
        out = _merge_consecutive_assistant(msgs)
        self.assertEqual([m["role"] for m in out], ["user", "assistant"])   # collapsed to one
        self.assertEqual(out[-1]["content"], "let me do that")
        self.assertEqual(len(out[-1]["tool_calls"]), 1)

    def test_non_adjacent_assistants_untouched(self):
        from cria.upstream import _merge_consecutive_assistant
        msgs = [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "a", "type": "function", "function": {"name": "s", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ]
        self.assertEqual([m["role"] for m in _merge_consecutive_assistant(msgs)], ["assistant", "tool", "assistant"])
