"""Responses text is token-progressive where nothing can sit in front of or reorder the model's own
words (no decoration family, no loop/stream guard): real HTTP, a model that is gated mid-answer."""
import io
import json
import threading
import urllib.request

import pytest

import test_server_config_http as H
from cria.config import IndicatorsConfig
from test_server_config_http import OPEN, Wire, no_installed_opener, sse_events  # noqa: F401

FIRST = "The first sentence of a long answer, written out in full. "
SECOND = "And the rest of it only exists after the harness has already read the first. "
LEAK = '<tool_call>{"name": "shell", "arguments": {"command": ["ls"]}}</tool_call>'
TOOLS = [{"type": "function", "name": "shell", "description": "run", "parameters": {
    "type": "object", "properties": {"command": {"type": "array", "items": {"type": "string"}}}, "required": ["command"]}}]


def frame(delta=None, finish=None):
    choice = {"delta": {"content": delta} if delta is not None else {}, "finish_reason": finish}
    return b"data: " + json.dumps({"choices": [choice], **({"usage": {"completion_tokens": 5}} if finish else {})}).encode() + b"\n\n"


class Gated(H.FakeUpstream):
    """Streams the script in `server.script`: text pieces, a "WAIT" that blocks until the test saw the
    earlier text arrive at the HARNESS, "DROP" (die without a terminal status). stream=false answers the whole text."""

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.loads(raw or b"{}")
        script = getattr(self.server, "script", None)
        if not script or self.path.endswith(("tokenize", "apply-template")) or "REQUEST CLASSIFIER" in raw.decode():
            self.rfile = io.BytesIO(raw)  # replay the consumed body to the shared fake
            return super().do_POST()
        self.server.streamed = bool(body.get("stream"))
        text = "".join(p for p in script if isinstance(p, str) and p not in ("WAIT", "DROP", "RESET"))
        if not body.get("stream"):
            return self._reply({"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                                "usage": {"completion_tokens": 5}})
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n')
        for piece in script:
            if piece == "WAIT":
                self.server.gate.wait(10)
            elif piece == "DROP":
                return
            elif piece == "RESET":           # the model server dies: a TCP reset, not an orderly end
                import socket, struct
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                self.connection.close()
                return
            elif isinstance(piece, dict):    # a native tool call: {"name": ..., "arguments": "<json text>"}
                call = {"index": 0, "id": "call_9", "type": "function", "function": piece}
                self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"tool_calls": [call]}}]}).encode() + b"\n\n")
                self.wfile.flush()
            else:
                self.wfile.write(frame(piece))
                self.wfile.flush()
        last = "tool_calls" if any(isinstance(p, dict) for p in script) else "stop"
        self.wfile.write(frame(None, last) + b"data: [DONE]\n\n")


@pytest.fixture
def gated(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "FakeUpstream", Gated)
    made = []

    def build(*, indicators=False, level=3, routing=None):
        w = Wire(tmp_path, indicators=indicators)
        w.fake.gate = threading.Event()
        if indicators is True:  # default families on
            object.__setattr__(w.cria.cfg, "indicators", IndicatorsConfig(enabled=True))
        made.append(w)
        return w
    yield build
    for w in made:
        w.fake.gate.set()
        w.close()


def open_stream(w, tools=None):
    body = H.resp_body("explain it at length", stream=True, **({"tools": tools} if tools else {}))
    req = urllib.request.Request(f"http://127.0.0.1:{w.cria.server_address[1]}/v1/responses",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return OPEN(req, timeout=20)


def read_until(r, needle):
    seen = b""
    while needle not in seen:
        line = r.readline()
        assert line, f"stream ended before {needle!r} arrived; saw {seen[-300:]!r}"
        seen += line
    return seen


def test_text_reaches_the_harness_while_the_model_is_still_answering(gated):
    """The first sentence is read at the harness BEFORE the model has produced the rest (the upstream is
    gated on that), and the finished stream is the same item the buffered Responses path builds."""
    w = gated()
    w.fake.script = [FIRST, "WAIT", SECOND]
    with open_stream(w) as r:
        first = read_until(r, b"first sentence")           # blocks forever if the text is buffered
        assert not w.fake.gate.is_set() and b"response.completed" not in first
        w.fake.gate.set()
        rest = r.read()
    events = sse_events((first + rest).decode())
    types = [e["type"] for e in events]
    deltas = [e["delta"] for e in events if e["type"] == "response.output_text.delta"]
    assert len(deltas) >= 2 and "".join(deltas) == FIRST + SECOND
    assert types[0] == "response.created" and types[-1] == "response.completed"
    done = next(e for e in events if e["type"] == "response.output_item.done")["item"]
    assert done["content"][0]["text"] == FIRST + SECOND
    completed = events[-1]["response"]
    assert completed["output"] == [done] and completed["usage"]["output_tokens"] > 0
    buffered = json.loads(w.post("/v1/responses", H.resp_body("explain it at length"))[1])
    assert buffered["output"][0]["content"][0]["text"] == done["content"][0]["text"]


def test_a_leaked_call_is_never_shown_and_is_recovered_as_a_call(gated):
    """The dialect the model leaked into its text is cut before delivery; the call arrives as a function_call
    item (the same recovery the buffered path applies) and the shown text is a prefix of the final text."""
    w = gated()
    w.fake.script = [FIRST, "Let me list the files.\n", LEAK]
    raw = open_stream(w, TOOLS).read().decode()
    events = sse_events(raw)
    shown = "".join(e["delta"] for e in events if e["type"] == "response.output_text.delta")
    assert "<tool_call" not in raw.split("response.completed")[0] and shown.startswith(FIRST)
    final = events[-1]["response"]["output"]
    assert [i["type"] for i in final] == ["message", "function_call"] and final[1]["name"] == "shell"
    # the recovery trims the newline that preceded the call; the item carries the authoritative text
    assert final[0]["content"][0]["text"] == shown.rstrip() and shown.endswith("files.\n")


def test_the_connection_dying_mid_answer_still_ends_in_a_valid_terminal_event(gated):
    """Text already delivered, then the model's stream ends without a terminal status: the harness gets
    response.failed (retryable), never a hang or a bare EOF."""
    w = gated()
    w.fake.script = [FIRST, "DROP"]
    events = sse_events(open_stream(w).read().decode())
    types = [e["type"] for e in events]
    assert "response.output_text.delta" in types and types[-1] == "response.failed"
    assert "response.completed" not in types and events[-1]["response"]["error"]["message"]


def test_a_dying_connection_before_any_text_is_re_asked_through_the_buffered_call(gated):
    """Nothing shown yet, so the transient-retry owner (the buffered call) answers the turn."""
    w = gated()
    w.fake.script = ["DROP", FIRST]
    events = sse_events(open_stream(w).read().decode())
    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["output"][0]["content"][0]["text"] == FIRST
    assert "response.progressive_reask" in [e["kind"] for e in w.events()]


def test_a_final_text_the_postprocessing_rewrote_ends_the_stream_instead_of_showing_two_answers(gated):
    """Content ⟦cria⟧ note lines are stripped from the finished completion; text already shown that carried one can
    no longer be a prefix, so the stream fails retryably (and logs it) rather than contradict itself."""
    w = gated()
    w.fake.script = [FIRST * 2, "\n⟦cria⟧ a note line\n", SECOND * 2]
    events = sse_events(open_stream(w).read().decode())
    assert events[-1]["type"] == "response.failed"
    assert "response.progressive_diverged" in [e["kind"] for e in w.events()]


def test_decorated_turns_keep_the_whole_answer_first_path(gated):
    """With indicators on (status ticker, banner...) the model's text is one delta after the completion exists,
    and the upstream is never asked for a stream."""
    w = gated(indicators=True)
    w.fake.script = [FIRST, SECOND]
    events = sse_events(open_stream(w).read().decode())
    answer = [e["delta"] for e in events if e["type"] == "response.output_text.delta" and "first sentence" in e["delta"]]
    assert len(answer) == 1 and SECOND.strip() in answer[0]
    assert events[-1]["type"] == "response.completed"


NO_MARKER_CALLS = {
    "json envelope": '{"commands": [{"name": "shell", "arguments": {"command": ["ls", "-la", "/some/long/directory"]}}]}',
    "call syntax": 'shell({"command": ["ls", "-la", "/some/long/directory/path/here"]})',
    "fenced envelope": 'I will list the files in that directory now.\n```json\n'
                       '{"name": "shell", "arguments": {"command": ["ls", "-la"]}}\n```',
}


@pytest.mark.parametrize("written", NO_MARKER_CALLS.values(), ids=NO_MARKER_CALLS.keys())
def test_a_call_written_as_text_without_a_leak_marker_is_still_a_call_never_a_failed_stream(gated, written):
    """The buffered path recovers a call the model wrote as JSON data / call syntax / a fenced envelope and
    drops that text; the streamed path must end in the same function_call, not in a retryable failure the model
    reproduces on every retry (the text had already left before the recovery could read it whole)."""
    w = gated()
    w.fake.script = [written[:40], written[40:]]
    buffered = json.loads(w.post("/v1/responses", H.resp_body("explain it at length", tools=TOOLS))[1])
    assert [i["type"] for i in buffered["output"]][-1] == "function_call", buffered["output"]
    events = sse_events(open_stream(w, TOOLS).read().decode())
    assert [e["type"] for e in events].count("response.completed") == 1 and events[-1]["type"] == "response.completed", \
        [e["type"] for e in events][-3:]
    final = events[-1]["response"]["output"]
    assert [i["type"] for i in final][-1] == "function_call"
    assert final[-1]["arguments"] == buffered["output"][-1]["arguments"]
    said = lambda items: "".join(c["text"] for i in items if i["type"] == "message" for c in i["content"])
    assert said(final) == said(buffered["output"])          # the transcript the harness stores is the buffered one


FREEFORM = [{"type": "custom", "name": "freeform", "description": "run", "format": {"type": "text"}}]


def test_a_call_the_harness_cannot_be_given_still_ends_the_stream_with_one_terminal_event(gated):
    """A custom (freeform) tool call whose arguments are not one string input cannot become an item. The
    harness gets a retryable response.failed - not a bare EOF in the middle of an open message item."""
    w = gated()
    w.fake.script = [FIRST, {"name": "freeform", "arguments": '{"cmd": "ls"}'}]
    events = sse_events(open_stream(w, FREEFORM).read().decode())
    terminal = [e["type"] for e in events if e["type"] in ("response.completed", "response.failed", "response.incomplete")]
    assert terminal == ["response.failed"], [e["type"] for e in events]
    assert events[-1]["type"] == "response.failed" and events[-1]["response"]["error"]["message"]


def test_the_harness_hanging_up_mid_answer_is_a_client_gone_not_an_error(gated):
    """Text now leaves while the model writes, so a user interrupt lands inside the model call: it is logged as
    the client leaving (and the model's stream is dropped), never as a cria internal error."""
    import time
    w = gated()
    w.fake.script = [FIRST, "WAIT"] + [SECOND] * 40
    r = open_stream(w)
    read_until(r, b"first sentence")
    r.close()
    w.fake.gate.set()
    for _ in range(100):
        kinds = [e["kind"] for e in w.events()]
        if "response.client_gone" in kinds or "response.error" in kinds:
            break
        time.sleep(0.05)
    assert "response.client_gone" in kinds and "response.error" not in kinds, kinds[-6:]


@pytest.mark.parametrize("make", [
    lambda: __import__("cria.upstream", fromlist=["x"]).UpstreamProtocolError("bad", {"type": "invalid_model_output_error", "message": "bad"}),
    lambda: __import__("cria.upstream", fromlist=["x"]).ReadFitUnknown("unmeasured"),
    lambda: __import__("cria.upstream", fromlist=["x"]).InputOverflow("too big", 9, 5, 1, True, 0),
], ids=["protocol error", "read fit unknown", "input overflow"])
def test_an_error_the_buffered_call_treats_as_terminal_is_not_asked_again_before_any_text(make):
    """A typed outcome (malformed generation, refit/overflow) reaches the caller as it does from the buffered call:
    no second model request that would repeat the doomed one or replace the evidence with a fresh answer."""
    from cria import responses
    from cria.server import CriaHandler
    asked = []

    class Provider:
        def chat_watched(self, body, rlog, on_content=None):
            raise make()

        def chat(self, body, rlog):
            asked.append(body)
            return b"{}"

    class Rlog:
        def emit(self, *a, **k):
            pass

    progressive = responses.ProgressiveMessage(lambda b: None, lambda t: -1, 32, 0)
    with pytest.raises(Exception) as caught:
        CriaHandler._chat_progressive(None, Provider(), {}, progressive, Rlog())
    assert type(caught.value).__name__ in ("UpstreamProtocolError", "ReadFitUnknown", "InputOverflow") and asked == []


def test_the_model_server_resetting_mid_answer_ends_in_response_failed_not_in_client_gone(gated):
    """A TCP reset from the MODEL's side is the same exception type as the harness hanging up. It must still
    end the harness's stream with its one retryable terminal event, never a silent EOF logged as a departed client."""
    w = gated()
    w.fake.script = [FIRST, "WAIT", "RESET"]   # reset only after the harness has read the first text
    with open_stream(w) as r:
        first = read_until(r, b"first sentence")
        w.fake.gate.set()
        events = sse_events((first + r.read()).decode())
    assert [e["type"] for e in events][-1] == "response.failed", [e["type"] for e in events]
    assert "response.client_gone" not in [e["kind"] for e in w.events()]
