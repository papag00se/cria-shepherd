"""An oversized Responses `instructions` on a turn cria PROXIES is reduced with its label, not refused.

Incident (wave 9 SYS, open-threads "Chat system carry"): `responses.to_chat_body` marked CALLER_PERSONA but not
CALLER_SPAN, so on the relay path (no coder frame to anchor a span in `assemble_base`) the context floor had no
boundary to reduce and a persona over the window was refused whole as `input-not-delivered`.
"""
import json

from cria import bodykeys, responses
from cria.config import RoutingConfig

from test_server_config_http import BIG, Wire, resp_body

TASK = "write hello.py"
RULES = "HOUSE RULE: every Python file starts with a module docstring."


def sent_messages(tmp_path, instructions, level=0, **kw):
    w = Wire(tmp_path, lambda url: RoutingConfig(engagement_level=level))
    try:
        status, raw = w.post("/v1/responses", resp_body(TASK, instructions=instructions, **kw))
        return status, raw, w.fake.chats[-1][1]["messages"]
    finally:
        w.close()


def test_to_chat_body_anchors_the_persona_span_at_the_head_of_the_folded_system_message():
    out = responses.to_chat_body({"model": "m", "instructions": "BASE PERSONA", "input": [
        {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "cfg"}]},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": TASK}]}]})
    system = out["messages"][0]
    assert system["content"] == "BASE PERSONA\n\ncfg" and system[bodykeys.CALLER_PERSONA] == "BASE PERSONA"
    assert system[bodykeys.CALLER_SPAN] == {"start": 0, "text": "BASE PERSONA"}
    developer_only = responses.to_chat_body({"model": "m", "input": [
        {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "cfg"}]}]})
    assert bodykeys.CALLER_SPAN not in developer_only["messages"][0]     # no persona, nothing reducible


def test_a_persona_over_the_window_on_a_proxied_turn_is_reduced_with_its_label_and_the_turn_is_answered(tmp_path):
    status, raw, sent = sent_messages(tmp_path, BIG, level=0)
    assert status == 200 and "input-not-delivered" not in raw and json.loads(raw)["output"]
    assert BIG not in sent[0]["content"] and sent[0]["content"].startswith("⟦ctx:reduced⟧")
    assert sent[-1] == {"role": "user", "content": TASK}
    assert not any(k.startswith("cria_") for m in sent for k in m)         # no marker key reaches the model


def test_only_the_persona_is_reduced_a_developer_constraint_survives_whole(tmp_path):
    dev = {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": RULES}]}
    w = Wire(tmp_path, lambda url: RoutingConfig(engagement_level=0))
    try:
        body = resp_body(TASK, instructions=BIG)
        body["input"].insert(0, dev)
        w.post("/v1/responses", body)
        sent = w.fake.chats[-1][1]["messages"]
    finally:
        w.close()
    assert "⟦ctx:reduced⟧" in sent[0]["content"] and sent[0]["content"].endswith(RULES) and BIG not in sent[0]["content"]


def test_a_persona_that_fits_ships_the_same_wire_body_as_before(tmp_path):
    """Byte-identical where nothing was over the window: the span is stripped at the wire and nothing is reduced."""
    persona = "You are a coding agent. " * 40
    _, _, sent = sent_messages(tmp_path, persona, level=0)
    assert sent == [{"role": "system", "content": persona}, {"role": "user", "content": TASK}]
