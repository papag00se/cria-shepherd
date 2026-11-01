"""Malformed request bodies and headers at the HTTP edge (real server, real socket, fake upstream): every one is a typed
4xx naming the field (or deliberately handled), never a 500 traceback; the connection is closed or still serves the next request."""
import json

import pytest

import test_server_config_aud6_http_edge as E
from test_server_config_aud6_http_edge import exchange, w  # noqa: F401
from test_server_config_http import no_installed_opener  # noqa: F401

USER = {"type": "message", "role": "user", "content": "hi"}
CALL = {"type": "function_call", "call_id": "c1", "name": "shell", "arguments": "{}"}
OUT = {"type": "function_call_output", "call_id": "c1", "output": "ok"}


def resp(*items, **extra):
    return {"input": list(items), "stream": False, **extra}


def chat(*messages, **extra):
    return {"messages": list(messages), "stream": False, **extra}


def edit(item, **kw):
    return {**item, **kw}


def without(item, key):
    return {k: v for k, v in item.items() if k != key}


# (id, path, body, field the 400 must name)
REFUSED = [
    ("fc-name-null", "/v1/responses", resp(USER, edit(CALL, name=None)), "name"),
    ("fc-name-number", "/v1/responses", resp(USER, edit(CALL, name=5)), "name"),
    ("fc-name-object", "/v1/responses", resp(USER, edit(CALL, name={"a": 1})), "name"),
    ("fc-name-list", "/v1/responses", resp(USER, edit(CALL, name=["x"])), "name"),
    ("fc-name-missing", "/v1/responses", resp(USER, without(CALL, "name")), "name"),
    ("fc-name-empty", "/v1/responses", resp(USER, edit(CALL, name="")), "name"),
    ("fc-args-number", "/v1/responses", resp(USER, edit(CALL, arguments=5)), "arguments"),
    ("fc-args-list", "/v1/responses", resp(USER, edit(CALL, arguments=[1])), "arguments"),
    ("fc-args-bool", "/v1/responses", resp(USER, edit(CALL, arguments=True)), "arguments"),
    ("fc-callid-number", "/v1/responses", resp(USER, edit(CALL, call_id=7)), "call_id"),
    ("fc-callid-object", "/v1/responses", resp(USER, edit(CALL, call_id={"a": 1})), "call_id"),
    ("fco-callid-number", "/v1/responses", resp(USER, CALL, edit(OUT, call_id=7)), "call_id"),
    ("fco-callid-list", "/v1/responses", resp(USER, CALL, edit(OUT, call_id=["c1"])), "call_id"),
    ("fco-output-nontext-parts", "/v1/responses", resp(USER, CALL, edit(OUT, output=[{"type": "audio", "data": "x"}])), "output"),
    ("fco-output-part-not-object", "/v1/responses", resp(USER, CALL, edit(OUT, output=[1, 2])), "output"),
    ("custom-call-name-null", "/v1/responses", resp(USER, {"type": "custom_tool_call", "call_id": "c", "name": None, "input": "x"}), "name"),
    ("custom-call-input-object", "/v1/responses", resp(USER, {"type": "custom_tool_call", "call_id": "c", "name": "n", "input": {"a": 1}}), "input"),
    ("item-type-number", "/v1/responses", resp(USER, {"type": 5, "role": "user", "content": "x"}), "type"),
    ("item-type-null", "/v1/responses", resp(USER, {"type": None, "role": "user", "content": "x"}), "type"),
    ("item-role-number", "/v1/responses", resp({"type": "message", "role": 5, "content": "x"}), "role"),
    ("item-role-unknown", "/v1/responses", resp({"type": "message", "role": "wizard", "content": "x"}), "role"),
    ("item-role-missing", "/v1/responses", resp({"type": "message", "content": "x"}), "role"),
    ("item-role-list", "/v1/responses", resp({"type": "message", "role": ["user"], "content": "x"}), "role"),
    ("content-unknown-part", "/v1/responses", resp({"type": "message", "role": "user", "content": [{"type": "input_audio", "x": 1}]}), "content"),
    ("content-part-no-type", "/v1/responses", resp({"type": "message", "role": "user", "content": [{"text": "x"}]}), "content"),
    ("content-part-text-number", "/v1/responses", resp({"type": "message", "role": "user", "content": [{"type": "input_text", "text": 5}]}), "content"),
    ("content-part-text-missing", "/v1/responses", resp({"type": "message", "role": "user", "content": [{"type": "input_text"}]}), "content"),
    ("content-number", "/v1/responses", resp({"type": "message", "role": "user", "content": 5}), "content"),
    ("content-object", "/v1/responses", resp({"type": "message", "role": "user", "content": {"a": 1}}), "content"),
    ("input-items-not-objects", "/v1/responses", resp(1, "x", None), "input"),
    ("instructions-number", "/v1/responses", resp(USER, instructions=5), "instructions"),
    ("tools-not-list", "/v1/responses", resp(USER, tools="x"), "tools"),
    ("tool-name-number", "/v1/responses", resp(USER, tools=[{"type": "function", "name": 5}]), "name"),
    ("tool-custom-name-missing", "/v1/responses", resp(USER, tools=[{"type": "custom"}]), "name"),
    ("tool-params-string", "/v1/responses", resp(USER, tools=[{"type": "function", "name": "t", "parameters": "x"}]), "parameters"),
    ("tool-choice-number", "/v1/responses", resp(USER, tool_choice=5), "tool_choice"),
    ("tool-choice-flat-name-number", "/v1/responses", resp(USER, tool_choice={"type": "function", "name": 5}), "tool_choice"),
    ("reasoning-string", "/v1/responses", resp(USER, reasoning="high"), "reasoning"),
    ("stream-object", "/v1/responses", {"input": [USER], "stream": {"a": 1}}, "stream"),
    ("chat-message-role-missing", "/v1/chat/completions", chat({"content": "x"}), "role"),
    ("chat-message-role-number", "/v1/chat/completions", chat({"role": 5, "content": "x"}), "role"),
    ("chat-message-role-unknown", "/v1/chat/completions", chat({"role": "wizard", "content": "x"}), "role"),
    ("chat-content-part-not-object", "/v1/chat/completions", chat({"role": "user", "content": [1]}), "content"),
    ("chat-content-part-text-number", "/v1/chat/completions", chat({"role": "user", "content": [{"type": "text", "text": 5}]}), "content"),
    ("chat-toolcall-no-function", "/v1/chat/completions", chat({"role": "user", "content": "x"}, {"role": "assistant", "tool_calls": [{"id": "a", "type": "function"}]}), "function"),
    ("chat-toolcall-function-string", "/v1/chat/completions", chat({"role": "user", "content": "x"}, {"role": "assistant", "tool_calls": [{"id": "a", "type": "function", "function": "x"}]}), "function"),
    ("chat-toolcall-name-number", "/v1/chat/completions", chat({"role": "user", "content": "x"}, {"role": "assistant", "tool_calls": [{"id": "a", "type": "function", "function": {"name": 5, "arguments": "{}"}}]}), "name"),
    ("chat-toolcall-id-number", "/v1/chat/completions", chat({"role": "user", "content": "x"}, {"role": "assistant", "tool_calls": [{"id": 5, "type": "function", "function": {"name": "n", "arguments": "{}"}}]}), "id"),
    ("chat-tool-msg-id-number", "/v1/chat/completions", chat({"role": "user", "content": "x"}, {"role": "tool", "tool_call_id": 5, "content": "ok"}), "tool_call_id"),
    ("chat-tool-def-no-function", "/v1/chat/completions", chat({"role": "user", "content": "x"}, tools=[{"type": "function"}]), "function"),
    ("chat-tool-def-name-number", "/v1/chat/completions", chat({"role": "user", "content": "x"}, tools=[{"type": "function", "function": {"name": 5}}]), "name"),
    ("chat-stream-object", "/v1/chat/completions", chat({"role": "user", "content": "x"}, stream={"a": 1}), "stream"),
    ("chat-max-tokens-string", "/v1/chat/completions", chat({"role": "user", "content": "x"}, max_tokens="lots"), "max_tokens"),
    ("chat-temperature-string", "/v1/chat/completions", chat({"role": "user", "content": "x"}, temperature="hot"), "temperature"),
]

VALID = {"/v1/chat/completions": {"messages": [{"role": "user", "content": "hi"}], "stream": False},
         "/v1/responses": {"input": "hi", "stream": False}}


def post_then_valid(w, path, body):
    """POST the malformed body, then a valid request on the SAME connection: the connection is either answered cleanly or closed."""
    raw = json.dumps(body).encode()
    ok = json.dumps(VALID[path]).encode()
    req = lambda b: (b"POST " + path.encode() + b" HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: "
                     + str(len(b)).encode() + b"\r\n\r\n" + b)
    return exchange(w, req(raw), then=req(ok))


@pytest.mark.parametrize("name, path, body, field", REFUSED, ids=[r[0] for r in REFUSED])
def test_a_malformed_body_is_a_400_naming_the_field_never_a_500(w, name, path, body, field):
    head, rest = post_then_valid(w, path, body)
    assert head.startswith(b"HTTP/1.1 400"), (head, rest)
    reply, _, follow = rest.partition(b"|")
    assert field in json.loads(reply)["error"], reply
    # the connection is either closed or still a clean HTTP stream that serves the next request; only that valid request may reach upstream
    assert follow == b"" or follow.startswith(b"HTTP/1.1 200"), follow
    assert [b["messages"] for _h, b in w.fake.chats] == ([VALID[path].get("messages") or [{"role": "user", "content": "hi"}]] if follow else []), "a refused body must never travel upstream"
    # and the server as a whole keeps serving
    head2, _ = E.post(w, json.dumps(VALID[path]).encode(), path)
    assert head2.startswith(b"HTTP/1.1 200")


def test_two_different_content_lengths_are_refused_with_400_and_the_connection_closes(w):
    """RFC 9110 §8.6: conflicting Content-Length values are a framing error; reading the first one would let the rest be parsed as the next request."""
    smuggled = b"GET /smuggled HTTP/1.1\r\nHost: x\r\n\r\n"
    body = b'{"messages": [{"role": "user", "content": "hi"}]}'
    head, reply = exchange(w, b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Length: " + str(len(body)).encode()
                           + b"\r\nContent-Length: " + str(len(body) + len(smuggled)).encode() + b"\r\n\r\n" + body + smuggled)
    assert head.startswith(b"HTTP/1.1 400") and b"Connection: close" in head and "Content-Length" in json.loads(reply)["error"]
    assert w.fake.chats == []


def test_identical_duplicate_content_lengths_are_accepted_as_one(w):
    body = b'{"messages": [{"role": "user", "content": "hi"}], "stream": false}'
    n = str(len(body)).encode()
    head, _ = exchange(w, b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Length: " + n + b"\r\nContent-Length: " + n + b"\r\n\r\n" + body)
    assert head.startswith(b"HTTP/1.1 200")


# Handled deliberately (not refused): (id, path, body, text that must reach the model unchanged)
HANDLED = [
    ("fco-output-object-without-text", "/v1/responses", resp(USER, CALL, edit(OUT, output={"output": {"a": 1}})), '{\\"output\\": {\\"a\\": 1}}'),
    ("chat-unknown-content-part-type-is-the-upstreams-to-judge", "/v1/chat/completions",
     chat({"role": "user", "content": [{"type": "audio_marker", "id": "zebra"}]}), "zebra"),
    ("chat-historical-tool-call-arguments-are-carried-not-judged", "/v1/chat/completions",
     chat({"role": "user", "content": "x"}, {"role": "assistant", "tool_calls": [{"id": "a", "type": "function", "function": {"name": "n", "arguments": 12345}}]}), "n"),
    ("item-type-absent-is-a-message", "/v1/responses", {"input": [{"role": "user", "content": "zebra"}], "stream": False}, "zebra"),
    ("unknown-item-type-is-dropped-like-reasoning", "/v1/responses", resp(USER, {"type": "reasoning", "summary": []}), "hi"),
    ("function-call-without-ids-gets-one", "/v1/responses", resp(USER, without(CALL, "call_id")), "hi"),
    ("function-call-output-without-id-is-dropped", "/v1/responses", resp(USER, without(OUT, "call_id")), "hi"),
    ("null-content-is-empty", "/v1/responses", resp(USER, {"type": "message", "role": "assistant", "content": None}), "hi"),
]


@pytest.mark.parametrize("name, path, body, reaches", HANDLED, ids=[h[0] for h in HANDLED])
def test_a_deliberately_handled_shape_is_answered_200_and_its_content_reaches_the_model(w, name, path, body, reaches):
    head, rest = post_then_valid(w, path, body)
    assert head.startswith(b"HTTP/1.1 200"), (head, rest)
    assert reaches in json.dumps(w.fake.chats[0][1]["messages"]), w.fake.chats[0][1]["messages"]
    assert rest.partition(b"|")[2].startswith(b"HTTP/1.1 200")   # the keep-alive connection serves the next request
