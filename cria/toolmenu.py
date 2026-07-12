"""Tool-menu curation + cheat-sheet — the one Context-shaping move that is cria's
job (the rest — compaction, trim, window — is delegated to the harness).

A weak model does better when the reliable tools are named up front with terse
usage. cria injects a short cheat-sheet as a system message on the OUTBOUND request
to the model — it is not part of the harness's conversation, so it doesn't
accumulate and needs no stripping; cria re-adds it each turn. Only tools the harness
actually advertises (plus write_file, which cria advertises) are described.
"""

from __future__ import annotations

from . import prompts
from .shelltool import find_shell_tool


def cheatsheet(tools) -> str | None:
    """A terse per-tool usage note for the tools present, or None if there's nothing
    worth saying. The wording lives in cria/prompts/cheatsheet.txt (edit it there)."""
    names = {(((t.get("function") or t) if isinstance(t, dict) else {}).get("name")) for t in tools or []}
    shell = find_shell_tool(tools)
    frag = prompts.load_map("cheatsheet")
    lines = []
    if "write_file" in names:
        lines.append(frag["write_file"])
    if shell is not None:
        lines.append(prompts.fill(frag["shell"], shell=shell["name"]))
    if "apply_patch" in names:
        lines.append(frag["apply_patch"])
    if "read_file" in names:
        lines.append(frag["read_file"])
    elif shell is not None:
        lines.append(prompts.fill(frag["read_via_shell"], shell=shell["name"]))
    if not lines:
        return None
    return frag["header"] + "\n" + "\n".join(lines)


def add_cheatsheet(body: dict, rlog=None) -> None:
    """Fold the cheat-sheet into the model's system prompt on the OUTBOUND request.

    It MERGES into the existing first system message rather than adding a second one:
    some chat templates (e.g. Qwythos, Ornith) raise "System message must be at the
    beginning" — i.e. they permit exactly one system message, at index 0 — and a
    second system message 500s the model server. Merging keeps exactly one system
    message and is compatible with both strict and lenient templates. If there is no
    system message, one is inserted at the front."""
    note = cheatsheet(body.get("tools"))
    if note is None:
        return
    messages = list(body.get("messages") or [])
    if messages and messages[0].get("role") == "system":
        head = dict(messages[0])
        head["content"] = _merge_system(head.get("content"), note)
        messages[0] = head
    else:
        messages.insert(0, {"role": "system", "content": note})
    body["messages"] = messages
    if rlog is not None:
        rlog.emit("toolmenu.cheatsheet")


def _merge_system(existing, note: str):
    """Append the note to an existing system message's content, preserving whether it
    was a plain string or a list of content parts."""
    if existing is None or existing == "":
        return note
    if isinstance(existing, str):
        return existing + "\n\n" + note
    if isinstance(existing, list):  # multimodal content parts
        return list(existing) + [{"type": "text", "text": note}]
    return note
