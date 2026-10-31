"""The final-wire fit: the measured prompt (not an average) must fit window minus reply reserve; protected input is never silently deleted; unknown stays unknown."""
import io
import json
from copy import deepcopy
from unittest import mock

import pytest

from context_wire_b_helpers import Rlog, rows
from cria import assistruntime, bodykeys, selfcompact, tokenratio
from cria.upstream import Upstream, UpstreamError

render = lambda payload: json.dumps(payload["messages"])

class Server:
    """A model server: renders with its template, counts tokens with `density(text)`, records generation POSTs."""

    def __init__(self, up, density):
        self.ops, self.posts, self.density = [], [], density
        up._ordinary_open, up._receive_open = self.metadata, self.generate

    def metadata(self, packet, **kwargs):
        data = json.loads(packet.data)
        if packet.full_url.endswith("/apply-template"):
            self.ops.append("render")
            return io.BytesIO(json.dumps({"prompt": render(data)}).encode())
        assert packet.full_url.endswith("/tokenize") and data["add_special"] is False
        self.ops.append("count")
        n = self.density(data["content"])
        return io.BytesIO(json.dumps({"tokens": [7] * n if isinstance(n, int) else n}).encode())

    def generate(self, packet, **kwargs):
        self.posts.append(json.loads(packet.data))
        return io.BytesIO(b'{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"ok"}}]}')

def upstream(window, props={"chat_template": "served"}, **kw):
    up = Upstream("http://inprocess.invalid", context_window=window, capture_dir=None, capture_rendered=False, **kw)
    up._props, up._props_seen = props, props is not None
    return up

def evidence(n, text):
    return [selfcompact.internal_evidence_message(text(i)) for i in range(n)]

def test_dense_briefing_is_measured_and_refitted_so_no_oversized_post_is_made():
    """Numeric output is denser than chars/4; only the server's own count of the FINAL prompt settles fit. The count, not the estimate, decides; the caller's body is not mutated."""
    up, body = upstream(16000), {"model": "small", "messages": [
        {"role": "system", "content": "Write a factual briefing."}, *evidence(6, lambda n: f"tool {n}: " + "00001: 4326.28\n" * 500),
        selfcompact.internal_evidence_message("A check exited 1: blank quantity."), {"role": "user", "content": "Write the briefing now."}]}
    count = lambda text: 100 + text.count("4326.28") * 8
    server, original = Server(up, count), deepcopy(body)
    assert count(render(body)) > 16000
    up.chat(body, Rlog())
    (sent,) = server.posts
    assert count(render(sent)) <= 16000 and sent["messages"][-1]["content"] == "Write the briefing now." and "max_tokens" not in sent
    assert "blank quantity" in render(sent) and "ctx:compacted" in render(sent) and body == original

@pytest.fixture(autouse=True)
def _fresh_density():
    tokenratio.reset()
    yield
    tokenratio.reset()


def test_a_measured_prompt_must_leave_the_reply_reserve_free():
    """Ornith/Java run 1792480002 call 0051: a summary prompt measured 48,192 of a 49,152 window was accepted against the window alone; the briefing got 959 tokens and was cut off."""
    up = upstream(8000)
    count = lambda text: len(text) * 3 // 8
    for _ in range(20):
        tokenratio.record("m#summary", 10000, 10000)    # the learned density lags: the floor believes ~1.0 while this prompt measures ~1.5
    server = Server(up, count)
    body = {"model": "m", "max_tokens": 4000, bodykeys.DENSITY_KIND: "summary", "messages": [
        {"role": "system", "content": "Write a briefing."}, *evidence(24, lambda i: f"turn {i}: " + "word " * 120), {"role": "user", "content": "Write the briefing now."}]}
    assert 4000 < count(render(body)) < 8000
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        up.chat(body, Rlog())
    (sent,) = server.posts
    assert count(render(sent)) <= 4000 and sent["messages"][-1]["content"] == "Write the briefing now." and bodykeys.DENSITY_KIND not in sent

def native_request():
    return {"model": "native-fit", bodykeys.PINNED_TASK: "Perform the original task.", bodykeys.OUTPUT_RESERVE: 64, "messages": [
        {"role": "user", "content": "Keep this preceding constraint. " + "documentation " * 1600 + " FINAL_CONSTRAINT_BYTE"},
        {"role": "user", "content": "Perform the original task."},
        {"role": "assistant", "content": "⟦ctx:briefing⟧ Original evidence\r\nwith its role and β bytes intact."},
        {"role": "user", "content": "A later amendment: preserve preceding instructions."}]}

@rows([(None,), ({},), ({"chat_template": "known"},)])
def test_a_body_that_fits_natively_keeps_all_caller_input_and_strips_private_hints(props):
    """The exact measurement of preserved caller input (not its deletion) authorizes the send, whatever /props state is cached."""
    up = upstream(4096, props)
    server, body = Server(up, lambda text: 2000), native_request()
    original = deepcopy(body)
    up.chat(body, Rlog())
    (sent,) = server.posts
    assert all(m in sent["messages"] for m in original["messages"]) and server.ops == ["render", "count"]
    assert bodykeys.PINNED_TASK not in sent and body == original

@rows([(5000, False), ({"tokens": []}, False), ({"tokens": [True]}, False), ({"tokens": [-1]}, False), ({"tokens": ["42"]}, False), (2000, True)])
def test_caller_input_is_refused_not_deleted_when_it_cannot_be_proven_to_fit(tokens, no_render):
    """A true overflow, or a missing/malformed measurement (or no rendered prompt), refuses before any generation POST and leaves the body intact: unknown stays unknown."""
    up = upstream(4096)
    server, body = Server(up, lambda text: tokens), native_request()
    if no_render:
        up._render_prompt = lambda body: None
    original = deepcopy(body)
    with pytest.raises(UpstreamError, match="without losing protected input"):
        up.chat(body, Rlog())
    assert server.posts == [] and body == original and up._window == 4096

def test_typed_history_is_reduced_with_a_label_but_caller_messages_are_not():
    """Cria's own evidence turns may be compacted (labelled) under native overflow; genuine user turns never are."""
    up = upstream(4096, {})
    server = Server(up, lambda text: 9000 if "Old observation" in text else 2000)
    body = {"model": "typed", bodykeys.PINNED_TASK: "Original task", bodykeys.OUTPUT_RESERVE: 64, "messages": [
        {"role": "user", "content": "Original constraint"}, {"role": "user", "content": "Original task"},
        selfcompact.internal_evidence_message("Old observation " * 4000), {"role": "user", "content": "Current amendment"}]}
    up.chat(body, Rlog())
    (sent,) = server.posts
    users = [m for m in sent["messages"] if m["role"] == "user" and "⟦ctx:compacted⟧" not in m["content"]]
    assert users == [body["messages"][i] for i in (0, 1, 3)] and "Old observation" not in json.dumps(sent) and "⟦ctx:compacted⟧" in json.dumps(sent, ensure_ascii=False)

@rows([(0, 2000), (1, 2000), (2, 2000), (3, None)])
def test_lower_levels_and_a_guessed_window_never_authorize_reduction(level, window):
    """The floor activates only at its own rung and only on a measured window: /props unreachable leaves the 8,192 fallback, an invented number that once destroyed 934 protected messages."""
    messages = [{"role": "user", "content": "oversized task " * 4000}]
    with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=OSError("down")):
        wire, _, _ = Upstream("http://synthetic.invalid", context_window=window, engagement_level=level)._prep({"model": "s", "messages": messages}, False, Rlog())
    assert json.loads(wire)["messages"] == messages


def test_the_wire_reduces_the_authored_caller_span_under_pressure_and_never_serializes_the_hints():
    """The caller-span boundary rides the body to the wire, is acted on there (persona reduced, labelled, permissions kept) and is stripped from the bytes the model receives."""
    persona = "Harness persona sentence. " * 800
    system = {"role": "system", "content": "RULES\n" + persona + "\nPERMISSIONS", bodykeys.CALLER_SPAN: {"start": 6, "text": persona}}
    body = {"model": "m", bodykeys.PINNED_TASK: "the task", bodykeys.OUTPUT_RESERVE: 1000, "messages": [system, {"role": "user", "content": "the task"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c", "content": "FILE TEXT\n" * 50}]}
    raw, _, _ = Upstream("http://unused", context_window=4000)._prep(body, False, Rlog(), safety_override=1.0)
    sent = json.loads(raw)["messages"][0]["content"]
    assert bodykeys.CALLER_SPAN not in raw.decode() and bodykeys.PINNED_TASK not in raw.decode()
    assert persona not in sent and "⟦ctx:reduced⟧" in sent and "PERMISSIONS" in sent and "FILE TEXT" in raw.decode()
