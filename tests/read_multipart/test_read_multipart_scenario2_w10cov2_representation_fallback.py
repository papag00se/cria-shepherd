"""Scenario2 (w10 COV2): the paged read reaches the server intact but its model-facing representation cannot be bound to the protected read
(the canonical representation changed under it). The turn continues from the EXACT harness history: every carrier the harness returned is kept
verbatim and labelled unverified with no read credit, the model is told the exact read could not be established, the bridge withholds the read,
and the failure is logged - on both wire APIs, in the one request only."""
import json
import urllib.request

import pytest

from cria import bodykeys, denial
from cria.server import CriaHandler
from read_multipart_helpers import HEX, MENU, Backend, Wire, isolated_home  # noqa: F401


@pytest.mark.parametrize("api,stream", [("chat", False), ("responses", True)])
def test_a_read_whose_representation_cannot_bind_continues_from_the_harness_history_labelled_unverified(tmp_path, monkeypatch, api, stream):
    path = tmp_path / "f"
    path.write_text(HEX)
    backend = Backend(path)
    real = CriaHandler._bind_multipart_read_facts
    refused = []

    def cannot_bind(self, body, rlog):
        if getattr(self, "_multipart_facts", ()):
            refused.append(True)
            return False                                    # the very request that carries the finished read
        return real(self, body, rlog)
    monkeypatch.setattr(CriaHandler, "_bind_multipart_read_facts", cannot_bind)
    with Wire(tmp_path, backend, api, stream) as w:
        msg, carriers = w.drive()
        events = [json.loads(line) for line in open(w.log.path) if line.strip()]
    result = backend.tool_results()[0]
    last = backend.bodies[-1]
    assert "seen" in msg["content"] and refused and len(carriers) > 3
    assert result["content"].startswith(carriers[0]) and all(c in "".join(m["content"] for m in backend.tool_results()) for c in carriers[:2])
    assert HEX not in result["content"] and denial.read_payload(result) is None and not last.get(bodykeys.PROTECTED_READS)
    assert backend.tool_results()[-1]["content"].rstrip().endswith("do not assume a write did or did not run.") and "could not be verified" in backend.tool_results()[-1]["content"]
    assert [e["kind"] for e in events].count("multipart.representation_unavailable") == 1


def test_after_the_fallback_the_requests_next_read_is_a_plain_lowered_command_the_bridge_never_registers(tmp_path, monkeypatch):
    """The fallback disables multipart for the rest of that request: a read the model issues in the same turn must not be handed to the bridge
    (it would register a paged continuation whose state the request just declared unavailable)."""
    big, small = tmp_path / "f", tmp_path / "small.txt"
    big.write_text(HEX)
    small.write_text("tiny\n")

    class Second(Backend):
        def chat(self, body, rlog=None):
            if len(self.bodies) != 1:
                return super().chat(body, rlog)                 # first reply: the oversize read; every later one: "seen"
            self.bodies.append(body)                            # the fallback request itself: the model asks for another read
            call = {"id": "second", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": str(small)})}}
            return json.dumps({"id": "f", "object": "chat.completion", "created": 1, "model": "test-model", "choices": [{"index": 0, "finish_reason": "tool_calls",
                               "message": {"role": "assistant", "content": None, "tool_calls": [call]}}]})
    backend = Second(big)
    real = CriaHandler._bind_multipart_read_facts
    monkeypatch.setattr(CriaHandler, "_bind_multipart_read_facts",
                        lambda self, body, rlog: False if getattr(self, "_multipart_facts", ()) else real(self, body, rlog))
    with Wire(tmp_path, backend) as w:
        registered = []
        register = w.srv.multipart_bridge.register
        w.srv.multipart_bridge.register = lambda original, *a, **k: (registered.append(original), register(original, *a, **k))[1]
        msg, carriers = w.drive()
    assert msg["content"] == "seen" and "tiny" in carriers[-1]        # the second read still reached the harness and ran
    assert len(registered) == 1                                                 # only the first, pre-fallback read was ever registered


def test_the_private_continuation_calls_of_an_oversize_read_stream_over_chat_sse_and_the_file_still_arrives_exact(tmp_path):
    """A streaming chat harness: cria's own paging calls are streamed as a tool_calls SSE (finish tool_calls, [DONE]) and the finished read reaches the model exact."""
    path = tmp_path / "f"
    path.write_text(HEX)
    class Streaming(Backend):
        def stream_chat(self, body, rlog=None):
            self.bodies.append(body)
            frames = ([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "original", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": str(path)})}}]}}]}, {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]
                      if len(self.bodies) == 1 else [{"choices": [{"delta": {"content": "seen"}}]}, {"choices": [{"delta": {}, "finish_reason": "stop"}]}])
            for frame in frames:
                yield b"data: " + json.dumps(frame).encode() + b"\n\n"
            yield b"data: [DONE]\n\n"
    backend = Streaming(path)
    with Wire(tmp_path, backend) as w:
        def post():
            url = f"http://127.0.0.1:{w.srv.server_address[1]}/v1/chat/completions"
            req = urllib.request.Request(url, json.dumps({"model": "test-model", "stream": True, "tools": MENU, "messages": w.messages}).encode(),
                                         {"Content-Type": "application/json", "X-Cria-Session-Id": "sid"})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read().decode()
            assert raw.rstrip().endswith("data: [DONE]")
            calls, text = {}, ""
            for line in raw.splitlines():
                if line.startswith("data: {"):
                    frame = json.loads(line[6:])
                    if not frame.get("choices"):
                        continue
                    choice = frame["choices"][0]
                    text += choice["delta"].get("content") or ""
                    for c in choice["delta"].get("tool_calls") or []:
                        have = calls.setdefault(c["index"], {"id": c["id"], "type": "function", "function": {"name": "", "arguments": ""}})
                        have["function"]["name"] += c["function"].get("name", "")
                        have["function"]["arguments"] += c["function"].get("arguments", "")
            return {"role": "assistant", "content": text or None, "tool_calls": list(calls.values())}
        w.post = post
        msg, carriers = w.drive()
    assert msg["content"] == "seen" and len(carriers) > 3 and backend.tool_results()[0]["content"] == HEX
