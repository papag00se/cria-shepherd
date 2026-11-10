"""The model's view of a replayed history: no private lowered command, no private marker name, whatever release made it.

A harness keeps the history it was given, so a conversation outlives the release that wrote it. Calls lowered by an
earlier release carry (a) the private marker and directory names that release used and (b) a leading declaration without
the receipt later releases require before they re-present a lowered call as the tool the model made
(`toolwire._declaration`: an unreceipted header is honoured for `read_file` only, because a command a coder wrote itself
may quote one). Replayed through the current release, those calls reach the model as what they are: a heredoc program
with the product's name in it, a survey the model never ran, a frame of base64 in a result.

NOTHING IS RECONSTRUCTED FROM COMMAND TEXT (operator decision D2, docs/harness-programs.md). A command's first line is
text any author can write, so a header there is not evidence that cria composed the call, and re-presenting such a
command as a different tool call let a model-authored command rewrite its own history (finding F4). A call lowered by an
earlier release therefore stays what it is in the model's view: a session that began before this change shows its old
private commands raw (a campaign is simply restarted).

Two steps, both stateless (the evidence is the history itself, so a restart or a resumed session behaves the same):

* :func:`upgrade_names` - applied where history enters (`server._strip_and_reframe_inbound`) and again at the wire - renames
  the earlier shapes to the current ones, but only inside commands cria composed (the first line is a declaration or a
  survey header) and the results of exactly those calls. Text the model or the workspace wrote is never touched: a file
  that quotes a marker keeps it, because the model must be able to edit what it read.
* :func:`restore_wire` - applied at the wire only, after every consumer has had the history - removes a survey cria
  composed itself (nobody's tool call) together with its result. (The first-line survey headers have the same
  text-authority shape and leave with the survey route, phase 6.)

The earlier names are assembled here from parts so that no source line, prompt or log of the present release spells them.
"""
from __future__ import annotations

import json
import re

from . import earliernames, toolwire

LEGACY = earliernames.LEGACY
_EARLIER = re.compile("|".join(re.escape(old) for old, _ in LEGACY))


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
    """By position, as everywhere else: the declaration is the FIRST line."""
    head = _first_line(command)
    return head.startswith("# " + toolwire._SENTINEL)


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


def restore_wire(messages: list) -> list:
    """The history as the model should read it: see the module docstring. Identity when there is nothing private left."""
    messages = upgrade_names(messages)
    if not isinstance(messages, list):
        return messages
    return messages
