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
    "write_file", "edit_file", "read_file",
    "list_dir", "view_image", "update_plan",
    "web_search", "local_web_search", "web_fetch",
    "request_permissions",
})
# apply_patch is deliberately NOT model-facing (ported from codex-local): a 9B can't produce
# matching diff context, so it's replaced by content-based write_file/edit_file. It stays only as
# the LOWERING TARGET (massage.lower_edit_file rewrites edit_file → apply_patch), executed by the
# harness even though it's not in the advertised menu.

# Preferred PRESENTATION order (ports codex-local present_local_tools + the LIGHT_CODER order):
# cria's purpose-built tools come FIRST so a weak model reaches for write_file/edit_file/read_file/
# web_* before falling back to a raw command; the shell/exec family is pushed LAST. The schema order
# the model sees is a real preference signal — the same lever codex-local used to curb shell-reflex.
_FOCUS_ORDER = (
    "write_file", "edit_file",                        # writing — the default change path
    "read_file", "list_dir", "view_image",            # reading / inspection
    "web_search", "local_web_search", "web_fetch",    # the web tools
    "update_plan", "request_permissions",
    "write_stdin",                                     # shell-adjacent (paired with exec_command)
)


def _tool_name(t) -> str | None:
    return (((t.get("function") or t) if isinstance(t, dict) else {}) or {}).get("name")


def _order_key(name) -> tuple:
    """Sort key for the focused menu: purpose-built tools first (in _FOCUS_ORDER), the shell/exec
    family LAST, everything else stable in the middle."""
    if name in SHELL_TOOL_NAMES:
        return (2, 0)                                 # shell/exec — last resort, listed last
    if name in _FOCUS_ORDER:
        return (0, _FOCUS_ORDER.index(name))          # cria's tools first, in preferred order
    return (1, 0)                                     # unranked focus tool — keep in the middle


def focus_tools(body: dict, rlog=None) -> None:
    """Curate the model's tool menu to the coding essentials AND order it by preference — in place.

    Ports codex-local's ``ToolSubset::Focused`` + ``present_local_tools``: keep the shell/exec tool
    (by family, so it's harness-agnostic) plus FOCUS_TOOL_NAMES; drop goal/MCP/connector/ask-the-user
    tools that only distract a small model (and let it wander off — e.g. spawning a rogue
    ``create_goal``); then REORDER the survivors so cria's purpose-built tools lead and the generic
    shell trails (the schema order nudges the model to prefer the specific tools). No-op when there
    are no tools. NEVER curates to empty: if nothing coding-essential survives (a degenerate harness),
    the original menu is left untouched rather than leaving the model tool-less."""
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
    if not kept:  # nothing coding-essential survives — leaving zero tools would break the model
        return
    # Reorder to lead with cria's tools even when nothing was dropped (the harness may already send
    # only focused tools); prune too when the firehose brought extras.
    kept.sort(key=lambda t: _order_key(_tool_name(t)))  # specific tools first, shell last
    body["tools"] = kept
    if rlog is not None and dropped:
        rlog.emit("toolmenu.focused", kept=len(kept), dropped=len(dropped), names=dropped)


def cheatsheet(tools) -> str | None:
    """The menu-derived tool hint (ports codex-local ``build_tool_hint``): a terse per-tool note
    with argument shapes, generated FROM this turn's resolved menu — so the guidance names ONLY
    tools the model can actually call and the prompt can never disagree with the menu. None when
    there's nothing worth saying. The wording lives in cria/prompts/cheatsheet.txt."""
    by_name = {n: t for t in tools or [] if (n := (((t.get("function") or t) if isinstance(t, dict) else {}).get("name")))}
    names = set(by_name)
    shell = find_shell_tool(tools)
    frag = prompts.load_map("cheatsheet")
    lines = []
    # Call the file tools out up front — naming ONLY the write tools actually in the menu (parity).
    write_tools = []
    if "write_file" in names:
        write_tools.append("write_file (a new or fully overwritten file)")
    if "edit_file" in names:
        write_tools.append("edit_file (replace one snippet)")
    if write_tools:
        lines.append(prompts.fill(frag["lead_write"], tools=" or ".join(write_tools)))
    # Same preferred order as the schema (_FOCUS_ORDER): writing tools first, then reading/
    # inspection, then web, with the shell last — so the hint mirrors the menu. apply_patch is
    # intentionally absent (not model-facing). Arg NAMES for read_file/list_dir are read from the
    # resolved schema, so the hint can't disagree with a harness-native tool (path vs dir_path).
    if "write_file" in names:
        lines.append(frag["write_file"])
    if "edit_file" in names:
        lines.append(frag["edit_file"])
    if "read_file" in names:
        lines.append(prompts.fill(frag["read_file"], arg=_path_arg(by_name["read_file"])))
    elif shell is not None:
        lines.append(prompts.fill(frag["read_via_shell"], shell=shell["name"]))
    if "list_dir" in names:
        lines.append(prompts.fill(frag["list_dir"], arg=_path_arg(by_name["list_dir"])))
    if "view_image" in names:
        lines.append(frag["view_image"])
    if "web_search" in names or "local_web_search" in names:
        # The web_fetch cross-reference is included ONLY when web_fetch is actually callable.
        fetch_hint = frag["web_search_fetch_hint"] if "web_fetch" in names else ""
        lines.append(prompts.fill(frag["web_search"], fetch_hint=fetch_hint))
    if "web_fetch" in names:  # the find/cursor navigation hint — a weak model re-fetches otherwise
        lines.append(frag["web_fetch"])
    if "update_plan" in names:
        lines.append(frag["update_plan"])
    if "request_permissions" in names:
        lines.append(frag["request_permissions"])
    if "write_stdin" in names and shell is not None:
        lines.append(prompts.fill(frag["write_stdin"], shell=shell["name"]))
    if shell is not None:
        lines.append(prompts.fill(frag["shell"], shell=shell["name"]))
    if not lines:
        return None
    body = frag["header"] + "\n" + "\n".join(lines)
    if shell is not None and (names & {"write_file", "read_file", "list_dir", "web_search", "web_fetch"}):
        body += "\n" + prompts.fill(frag["footer"], shell=shell["name"])  # worth saying only when a focused tool exists to prefer
    return body


def _path_arg(tool, default: str = "path") -> str:
    """The property name a read/list tool uses for its path (path / dir_path / file_path / …),
    read from the RESOLVED schema so the hint matches a harness-native tool instead of assuming
    cria's synthetic `path`. Falls back to the first required/declared property, then `default`."""
    params = (((tool or {}).get("function") or tool or {}) if isinstance(tool, dict) else {}).get("parameters") or {}
    props = params.get("properties") or {}
    for cand in ("path", "dir_path", "file_path", "filename", "dir", "directory"):
        if cand in props:
            return cand
    req = params.get("required") or []
    return req[0] if req else next(iter(props), default)


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
