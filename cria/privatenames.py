"""The model's view of a replayed history: no private lowered command, no private marker name, whatever release made it.

A harness keeps the history it was given, so a conversation outlives the release that wrote it. Calls lowered by an
earlier release carry (a) the private marker and directory names that release used and (b) a leading declaration without
the receipt later releases require before they re-present a lowered call as the tool the model made
(`toolwire._declaration`: an unreceipted header is honoured for `read_file` only, because a command a coder wrote itself
may quote one). Replayed through the current release, those calls reached the model as what they are: a heredoc program
with the product's name in it, a survey the model never ran, a frame of base64 in a result. Measured by replaying real
harness requests of 2026-10-22/23 through a fresh session.

Two steps, both stateless (the evidence is the history itself, so a restart or a resumed session behaves the same):

* :func:`upgrade_names` - applied where history enters (`server._strip_and_reframe_inbound`) and again at the wire - renames
  the earlier shapes to the current ones, but only inside commands cria composed (the first line is a declaration or a
  survey header) and the results of exactly those calls. Text the model or the workspace wrote is never touched: a file
  that quotes a marker keeps it, because the model must be able to edit what it read.
* :func:`restore_wire` - applied at the wire only, after every consumer has had the history - shows the model the call
  it made. A header-declared lowering of an earlier release is re-presented as the declared tool, its result loses the
  survey frame riding on it, and a survey cria composed itself (nobody's tool call) leaves with its result.

The earlier names are assembled here from parts so that no source line, prompt or log of the present release spells them.
"""
from __future__ import annotations

import json
import re

from . import earliernames, toolwire, wsview

LEGACY = earliernames.LEGACY
_EARLIER = re.compile("|".join(re.escape(old) for old, _ in LEGACY))
_SURVEY_HEADERS = tuple({wsview.SURVEY_CMD_OPEN, "# " + LEGACY[0][0] + "SURVEY_CMD___"})


def _rename(text: str) -> str:
    for old, new in LEGACY:
        text = text.replace(old, new)
    return text


def _is_tool_result(message) -> bool:
    return isinstance(message, dict) and (message.get("role") == "tool" or message.get("type") == "function_call_output")


def _call_command(call) -> str:
    """The command text of one assistant shell call ("" when its arguments are not a command)."""
    function = call.get("function") if isinstance(call, dict) else None
    try:
        return toolwire._command_of((function or {}).get("arguments"))
    except Exception:  # noqa: BLE001 - arguments of any other shape are not a lowered command
        return ""


def _first_line(command: str) -> str:
    return command.split("\n", 1)[0].strip()


def _composed_by_cria(command: str) -> bool:
    """By position, as everywhere else: the declaration (tool, gate) or the survey header is the FIRST line."""
    head = _first_line(command)
    return (head.startswith("# " + toolwire._SENTINEL) or head.startswith("# " + toolwire.GATE_SENTINEL)
            or head in _SURVEY_HEADERS)


def _text_parts(message: dict):
    content = message.get("content", message.get("output"))
    if isinstance(content, str):
        yield content
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                yield part["text"]


def _map_text(message: dict, fn) -> dict:
    """The message with ``fn`` applied to its text (string, or the text parts of a list), identity when nothing changes."""
    key = "content" if "content" in message else "output"
    content = message.get(key)
    if isinstance(content, str):
        new = fn(content)
        return message if new == content else {**message, key: new}
    if isinstance(content, list):
        parts = [{**p, "text": fn(p["text"])} if isinstance(p, dict) and isinstance(p.get("text"), str) else p for p in content]
        return message if parts == content else {**message, key: parts}
    return message


def _mentions_earlier(message) -> bool:
    """Cheap precheck over the only text this module rewrites (call arguments, result text); never serializes a message, because
    a message may carry private objects that are not JSON (`bodykeys` hints)."""
    if not isinstance(message, dict):
        return False
    if message.get("role") == "assistant":
        return any(isinstance(raw, str) and _EARLIER.search(raw) for raw in
                   (((call.get("function") or {}).get("arguments")) for call in message.get("tool_calls") or [] if isinstance(call, dict)))
    return _is_tool_result(message) and any(_EARLIER.search(text) for text in _text_parts(message))


def _carrier_ids(messages: list) -> set[str]:
    """Ids of the assistant calls whose command cria composed (a stored header at its first line)."""
    return {call["id"] for m in messages if isinstance(m, dict) and m.get("role") == "assistant"
            for call in (m.get("tool_calls") or []) if isinstance(call, dict) and call.get("id") and _composed_by_cria(_call_command(call))}


def upgrade_names(messages: list) -> list:
    """``messages`` with the earlier release's private names renamed inside cria-composed commands and their results.
    Identity when there is nothing to rename (a current history is returned as given)."""
    if not isinstance(messages, list) or not any(_mentions_earlier(m) for m in messages):
        return messages
    carriers = _carrier_ids(messages)
    out = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls"):
            calls = []
            for call in m["tool_calls"]:
                function = call.get("function") if isinstance(call, dict) else None
                raw = (function or {}).get("arguments")
                if call.get("id") in carriers and isinstance(raw, str) and _EARLIER.search(raw):
                    call = {**call, "function": {**function, "arguments": _rename(raw)}}
                calls.append(call)
            m = {**m, "tool_calls": calls}
        elif _is_tool_result(m) and (m.get("tool_call_id") or m.get("call_id")) in carriers:
            m = _map_text(m, _rename)
        out.append(m)
    return out


def _declared_call(command: str):
    """``(name, arguments)`` of the tool an UNRECEIPTED declaration names, else None. A declaration that carries a receipt is
    the current release's own, already re-presented (or rejected, because the header was copied) by `represent_inbound`."""
    declaration = toolwire._decode_sentinel(command)
    if declaration is None or declaration.get("rcpt") or declaration["name"] == "read_file":
        return None
    return declaration["name"], declaration.get("arguments") or "{}"


def restore_wire(messages: list) -> list:
    """The history as the model should read it: see the module docstring. Identity when there is nothing private left."""
    messages = upgrade_names(messages)
    if not isinstance(messages, list):
        return messages
    restored: set[str] = set()      # calls re-presented as the declared tool: their result drops the survey riding on it
    private: set[str] = set()       # a survey cria composed on its own: the call and its result leave
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "assistant":
            for call in m.get("tool_calls") or []:
                command = _call_command(call) if isinstance(call, dict) and call.get("id") else ""
                if not command:
                    continue
                if _first_line(command) in _SURVEY_HEADERS:
                    private.add(call["id"])
                elif _declared_call(command) is not None:
                    restored.add(call["id"])
    if not restored and not private:
        return messages
    out = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls"):
            calls = []
            for call in m["tool_calls"]:
                if call.get("id") in private:
                    continue
                if call.get("id") in restored:
                    name, arguments = _declared_call(_call_command(call))
                    call = {**call, "function": {"name": name, "arguments": arguments}}
                calls.append(call)
            if not calls and not any(t.strip() for t in _text_parts(m)):
                continue                  # nothing of the turn is left once the private survey is gone
            m = {**m, "tool_calls": calls} if calls else {k: v for k, v in m.items() if k != "tool_calls"}
        elif _is_tool_result(m):
            call_id = m.get("tool_call_id") or m.get("call_id")
            if call_id in private:
                continue
            if call_id in restored:
                m = _map_text(m, lambda text: wsview.strip_survey(text)[0])
        out.append(m)
    return out
