"""The final-wire fit: the measured prompt (not an average) must fit window minus reply reserve; protected input is never silently deleted; unknown stays unknown."""
import io
import json
from copy import deepcopy
from unittest import mock

import pytest

from context_wire_b_helpers import Rlog, rows
from cria import assistruntime, bodykeys, selfcompact, tokenratio
from cria.upstream import Upstream

render = lambda payload: json.dumps(payload["messages"])

class Server:
    """A model server: renders with its template, counts tokens with `density(text)`, records generation POSTs."""

    def __init__(self, up, density):
        self.ops, self.posts, self.density = [], [], density
        up._ordinary_open, up._open = self.metadata, self.generate

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

@rows([(lambda text: len(text) // 3, False, False), ({"tokens": []}, False, False), ({"tokens": [True]}, False, False), ({"tokens": [-1]}, False, False), ({"tokens": ["42"]}, False, False), (2000, True, False),
       (lambda text: len(text) // 3, False, True), ({"tokens": []}, False, True), (2000, True, True)])
def test_only_replayed_handoff_text_is_cut_and_only_when_overflow_is_proven(tokens, no_render, handoff):
    """A person's oversized message is NEVER cut (principle 5): whatever the measurement says it is sent whole. A replayed handoff (typed provenance) loses its OLDEST part, labelled, only on a measured overflow; with no measurement (malformed answer, no rendered prompt) or a measured fit it is sent whole too. The caller's body is untouched."""
    up = upstream(4096)
    server, body = Server(up, lambda text: tokens(text) if callable(tokens) else tokens), native_request()
    if handoff:
        body["messages"][0][bodykeys.HARNESS_HANDOFF] = bodykeys.HarnessHandoff(True)
    if no_render:
        up._render_prompt = lambda body: None
    original = deepcopy(body)
    rlog = Rlog()
    up.chat(body, rlog)
    (sent,) = server.posts
    first = sent["messages"][0]["content"]
    measured_over = callable(tokens) and not no_render
    if handoff and measured_over:
        assert first.startswith("Keep this preceding constraint. ") and "⟦ctx:reduced⟧" in first and first.endswith("FINAL_CONSTRAINT_BYTE")
        assert rlog.first("context.overflow_reduced") is not None
    else:
        assert first == original["messages"][0]["content"] and rlog.first("context.overflow_reduced") is None
    assert sent["messages"][1:] == original["messages"][1:] and body == original and up._window == 4096

def test_typed_history_is_reduced_with_a_label_but_caller_messages_are_not():
    """Cria's own evidence turns may be compacted (labelled) under native overflow before any user message is touched."""
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


def test_producer_facts_do_not_turn_the_latest_tool_exchange_into_old_history():
    """Java 0131: trailing producer notes displaced a live check and the wire dropped its full result."""
    output = "check exit 0\n" + "".join(f"line {i:05d} data abcdefghijk\n" for i in range(1100))
    call = {"role": "assistant", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "exec_command", "arguments": '{"cmd":"make check"}'}}]}
    result = {"role": "tool", "tool_call_id": "c", "content": output}
    notes = [selfcompact.internal_evidence_message(t) for t in (
        "⟦ctx:current⟧ current file", "⟦ctx:files⟧ files", "⟦ctx:facts⟧ facts")]
    messages = [{"role": "system", "content": "system " * 1200}, {"role": "user", "content": "task"},
                {"role": "user", "content": "⟦ctx:continuation⟧ " + "past " * 1200},
                {"role": "user", "content": "⟦ctx:rollup⟧ " + "brief " * 1900}, call, result,
                {"role": "user", "content": "past guidance " * 1000,
                 bodykeys.ANNOTATION_SOURCE: bodykeys.AnnotationSource.GUIDANCE_HISTORY}, *notes]
    body = {"model": "m", bodykeys.OUTPUT_RESERVE: 16384, "messages": messages,
            "tools": [{"type": "function", "function": {"name": "exec_command", "description": "D" * 6400,
                                                        "parameters": {"type": "object", "properties": {}}}}]}
    raw, _, _ = Upstream("http://unused", context_window=40960)._prep(body, False, Rlog(), safety_override=1.42)
    sent = json.loads(raw)["messages"]
    assert next(m for m in sent if m.get("tool_call_id") == "c")["content"] == output
    assert any(tc.get("id") == "c" for m in sent for tc in m.get("tool_calls", []))
    assert any("⟦ctx:compacted⟧" in (m.get("content") or "") for m in sent)
    assert bodykeys.ANNOTATION_SOURCE not in raw.decode()
    assert all(any(m.get("content") == note["content"] for m in sent) for note in notes)
    untyped = deepcopy(body)
    for note in untyped["messages"][-len(notes):]:
        note.pop(bodykeys.ANNOTATION_SOURCE)
    old, _, _ = Upstream("http://unused", context_window=40960)._prep(untyped, False, Rlog(), safety_override=1.42)
    assert not any(m.get("tool_call_id") == "c" for m in json.loads(old)["messages"])

    # Identical user-authored text remains a real request; producer identity is not a text match.
    for note in notes:
        assert selfcompact.is_user_request({"role": "user", "content": note["content"]})
    followup = {"role": "user", "content": "Please review the result; this is a real follow-up."}
    body["messages"] = messages + [followup]
    later, _, _ = Upstream("http://unused", context_window=40960)._prep(body, False, Rlog(), safety_override=1.42)
    assert followup in json.loads(later)["messages"]


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
