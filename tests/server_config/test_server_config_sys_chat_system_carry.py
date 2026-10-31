"""A Chat caller's system/developer text is CARRIED as caller instructions, exactly as Responses `instructions` are.

Incident (wave 9, agent L): on the Chat path `_proxy_body` and `assemble_base` kept only messages carrying
`bodykeys.CALLER_INSTRUCTIONS`, which only the Responses translation set, so a 100-token persona and a 60,000-token
rulebook were dropped identically while the same text sent as Responses `instructions` reached the model - and the
model was never told.
"""
import copy
import json

import pytest

from cria import bodykeys, responses, server
from cria.config import RoutingConfig

from test_server_config_http import BIG, Wire, chat_body, resp_body

TOOLS = [{"type": "function", "function": {"name": "write_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}}}]
RULES = "HOUSE RULE: every Python file starts with a module docstring."
TASK = "write hello.py"


def carried(messages):
    body = {"model": "m", "messages": copy.deepcopy(messages)}
    server.carry_chat_system(body)
    return body["messages"]


def test_every_system_and_developer_message_folds_into_one_marked_leading_message_with_the_first_system_as_persona():
    """Order kept; one leading system (a second breaks strict templates); only the first `system` text is the
    reducible persona, a `developer` message is configured authority; list content is read as text; empty ones add nothing."""
    out = carried([{"role": "system", "content": [{"type": "text", "text": "BASE PERSONA"}]},
                   {"role": "developer", "content": "never touch vendor/"},
                   {"role": "system", "content": "   "},
                   {"role": "user", "content": TASK}])
    assert out[0] == {"role": "system", "content": "BASE PERSONA\n\nnever touch vendor/",
                      bodykeys.CALLER_INSTRUCTIONS: True, bodykeys.CALLER_PERSONA: "BASE PERSONA",
                      bodykeys.CALLER_SPAN: {"start": 0, "text": "BASE PERSONA"}}
    assert out[1:] == [{"role": "system", "content": "   "}, {"role": "user", "content": TASK}]
    late = carried([{"role": "developer", "content": "rules"}, {"role": "system", "content": "PERSONA"}])[0]
    assert late["content"][late[bodykeys.CALLER_SPAN]["start"]:][:7] == "PERSONA"        # anchored at its offset
    dev_only = carried([{"role": "developer", "content": "rules"}, {"role": "user", "content": TASK}])
    assert bodykeys.CALLER_SPAN not in dev_only[0] and dev_only[0][bodykeys.CALLER_INSTRUCTIONS] is True


def test_a_body_with_no_caller_system_text_is_left_byte_for_byte_and_responses_is_never_remarked():
    """Chat with only user/assistant/tool turns and a Responses body (already marked) are untouched."""
    chat = [{"role": "user", "content": TASK}, {"role": "assistant", "content": "ok"}]
    assert carried(chat) == chat
    rbody = responses.to_chat_body({"model": "m", "instructions": "BASE", "input": [
        {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "cfg"}]},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": TASK}]}]})
    assert carried(rbody["messages"]) == rbody["messages"]
    body = {"model": "m"}
    server.carry_chat_system(body)
    assert body == {"model": "m"}


def wire_system(tmp_path, level, mode, role="system", tools=None):
    """The messages the model server received for a request carrying RULES in `mode`."""
    w = Wire(tmp_path, lambda url: RoutingConfig(engagement_level=level))
    try:
        if mode == "chat":
            body = chat_body(TASK, **({"tools": tools} if tools else {}))
            body["messages"].insert(0, {"role": role, "content": RULES})
            w.post("/v1/chat/completions", body)
        else:
            w.post("/v1/responses", resp_body(TASK, instructions=RULES, **({"tools": [
                {"type": "function", "name": "write_file", "parameters": {"type": "object"}}]} if tools else {})))
        return w.fake.chats[-1][1]["messages"]
    finally:
        w.close()


@pytest.mark.parametrize("level", [0, 3])
@pytest.mark.parametrize("role", ["system", "developer"])
def test_a_chat_callers_system_text_reaches_the_model_exactly_as_responses_instructions_do(tmp_path, level, role):
    """Same text, two wires, one wire body: the model receives the caller's rules (previously dropped on Chat)
    and no cria marker key is ever serialized."""
    chat = wire_system(tmp_path / "chat", level, "chat", role)
    resp = wire_system(tmp_path / "resp", level, "responses")
    assert chat == resp == [{"role": "system", "content": RULES}, {"role": "user", "content": TASK}]


def test_a_chat_request_with_no_system_message_ships_the_same_wire_body_as_before(tmp_path):
    """Byte-identical for callers who never sent a system message: the model sees exactly the user turn."""
    for level in (0, 3):
        w = Wire(tmp_path / f"l{level}", lambda url, level=level: RoutingConfig(engagement_level=level))
        try:
            w.post("/v1/chat/completions", chat_body(TASK))
            assert w.fake.chats[-1][1]["messages"] == [{"role": "user", "content": TASK}]
        finally:
            w.close()


def test_a_chat_system_message_far_over_the_window_is_reduced_with_its_label_never_dropped_silently(tmp_path):
    """The 60k-token case: the floor swaps the harness persona for its labelled stand-in and keeps the task;
    a `developer` message (configured constraints) is not reducible and survives whole."""
    w = Wire(tmp_path, lambda url: RoutingConfig(engagement_level=3))
    try:
        body = chat_body(TASK)
        body["messages"][:0] = [{"role": "system", "content": BIG}, {"role": "developer", "content": RULES}]
        w.post("/v1/chat/completions", body)
        sent = w.fake.chats[-1][1]["messages"]
    finally:
        w.close()
    assert sent[0]["role"] == "system" and BIG not in sent[0]["content"]
    assert "⟦ctx:reduced⟧" in sent[0]["content"] and RULES in sent[0]["content"]
    assert sent[-1] == {"role": "user", "content": TASK}
