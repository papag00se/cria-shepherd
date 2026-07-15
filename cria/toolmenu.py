"""Tool-menu curation + cheat-sheet — the one Context-shaping move that is cria's
job (the rest — compaction, trim, window — is delegated to the harness).

Two curation moves, both on the OUTBOUND request to the model:

1. FOCUS the menu (``focus_tools``) — a weak model loses attention on a big tool
   list, so cria drops everything that isn't a coding essential and keeps ~10 tools
   (ports codex-local's ``ToolSubset::Focused`` / ``LIGHT_CODER_TOOL_NAMES``). The
   full Codex menu is ~120 (its default Apps/Connectors catalog); a 9B does far
   better with the shell/exec + file + read + web tools and none of the goal /
   MCP-discovery / connector firehose.
2. CHEAT-SHEET (``add_cheatsheet``) — name the kept tools up front with terse usage;
   it's a system message, not part of the harness conversation, so it doesn't
   accumulate and cria re-adds it each turn.
"""

from __future__ import annotations

from . import prompts
from .shelltool import SHELL_TOOL_NAMES, find_shell_tool

# The curated coder menu — the coding essentials a small local model actually needs
# (ports codex-local LIGHT_CODER_TOOL_NAMES + its synthetic read/write/edit tools). The
# shell/exec tool is matched by FAMILY (SHELL_TOOL_NAMES) so this stays harness-agnostic.
# Everything NOT here is dropped: goal management (create_goal/get_goal/update_goal), MCP
# discovery (list_mcp_resources/…), ask-the-user (request_user_input), connector/app tools,
# and Codex's deferred-tool search (tool_search/tool_suggest).
FOCUS_TOOL_NAMES = frozenset({
    "write_stdin",                                    # exec_command's PTY companion
    "apply_patch", "write_file", "edit_file", "read_file",
    "list_dir", "view_image", "update_plan",
    "web_search", "local_web_search", "web_fetch",
    "request_permissions",
})


def _tool_name(t) -> str | None:
    return (((t.get("function") or t) if isinstance(t, dict) else {}) or {}).get("name")


def focus_tools(body: dict, rlog=None) -> None:
    """Curate the model's tool menu to the coding essentials, dropping the rest — in place.

    Ports codex-local's ``ToolSubset::Focused``: keep the shell/exec tool (by family, so it's
    harness-agnostic) plus FOCUS_TOOL_NAMES; drop goal/MCP/connector/ask-the-user tools that
    only distract a small model (and let it wander off — e.g. spawning a rogue ``create_goal``).
    No-op when there are no tools. NEVER curates to empty: if nothing coding-essential survives
    (a degenerate harness), the original menu is left untouched rather than leaving the model
    tool-less."""
    tools = body.get("tools")
    if not tools:
        return
    kept, dropped = [], []
    for t in tools:
        nm = _tool_name(t)
        if nm in FOCUS_TOOL_NAMES or nm in SHELL_TOOL_NAMES:
            kept.append(t)
        else:
            dropped.append(nm)
    if dropped and kept:  # leaving zero tools would break the model — keep the firehose instead
        body["tools"] = kept
        if rlog is not None:
            rlog.emit("toolmenu.focused", kept=len(kept), dropped=len(dropped), names=dropped)


def cheatsheet(tools) -> str | None:
    """The menu-derived tool hint (ports codex-local ``build_tool_hint``): a terse per-tool note
    with argument shapes, generated FROM this turn's resolved menu — so the guidance names ONLY
    tools the model can actually call and the prompt can never disagree with the menu. None when
    there's nothing worth saying. The wording lives in cria/prompts/cheatsheet.txt."""
    names = {(((t.get("function") or t) if isinstance(t, dict) else {}).get("name")) for t in tools or []}
    shell = find_shell_tool(tools)
    frag = prompts.load_map("cheatsheet")
    lines = []
    if "write_file" in names:
        lines.append(frag["write_file"])
    if "read_file" in names:
        lines.append(frag["read_file"])
    elif shell is not None:
        lines.append(prompts.fill(frag["read_via_shell"], shell=shell["name"]))
    if "list_dir" in names:
        lines.append(frag["list_dir"])
    if "edit_file" in names:
        lines.append(frag["edit_file"])
    if "apply_patch" in names:
        lines.append(frag["apply_patch"])
    if "web_search" in names or "local_web_search" in names:
        lines.append(frag["web_search"])
    if "web_fetch" in names:  # the find/cursor navigation hint — a weak model re-fetches otherwise
        lines.append(frag["web_fetch"])
    if shell is not None:
        lines.append(prompts.fill(frag["shell"], shell=shell["name"]))
    if not lines:
        return None
    body = frag["header"] + "\n" + "\n".join(lines)
    if shell is not None and (names & {"write_file", "read_file", "list_dir"}):
        body += "\n" + frag["footer"]  # only worth saying when there IS a focused tool to prefer
    return body


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
