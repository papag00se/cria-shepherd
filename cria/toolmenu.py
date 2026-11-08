"""Tool-menu curation + cheat-sheet — the one Context-shaping move that is cria's
job (the rest — compaction, trim, window — is delegated to the harness).

Two curation moves, both on the OUTBOUND request to the model:

1. FOCUS the menu (``focus_tools``) — a weak model loses attention on a big tool
   list, so cria drops everything that isn't a coding essential and keeps ~10 tools
   (ports codex-local's ``ToolSubset::Focused`` / ``LIGHT_CODER_TOOL_NAMES``). The
   full Codex menu is ~120 (its default Apps/Connectors catalog); a 9B does far
   better with the shell/exec + file + read + web tools and none of the goal /
   MCP-discovery / connector firehose.
2. INSTRUCTIONS (``add_cheatsheet``) — preserve general workflow in the system frame
   and put recognized native tool clarifications into their actual descriptions.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Protocol

from . import prompts
from .assistcontract import ExecutableDefinition, Policy, Reference
from .shelltool import find_shell_tool, is_file_tool_name, is_shell_tool_name
from .filecommands import _EDIT_NAMES, _LIST_NAMES, _READ_NAMES, _WRITE_NAMES

# The file-op tool FAMILIES cria recognizes (write/edit/read/list, incl. aliases like create_file /
# str_replace), sourced from filecommands so the focus menu never DROPS a differently-named essential a
# harness advertises natively — the keep-set must match what needs_translation treats as first-class.
# …AND BY SHAPE, like the shell beside it. This was a six-name literal set under a comment calling
# them FAMILIES. Simulated through the real gate (`needs_translation` → `advertise` → `focus_tools`):
# Gemini CLI's menu lost `replace`, `list_directory`, `glob` and `search_file_content`; Cline's lost
# `search_files` and `list_code_definition_names`. Every one is a file operation the coder needs, and
# `shelltool.is_write_tool_name` — a real shape rule that already matches `replace`, `write_to_file`
# and `replace_in_file` — was sitting unused one import away (#20).
#
# The literal set is kept as well, because it is what `needs_translation` treats as first-class and
# the keep-set must not be narrower than that.
_FILE_OP_NAMES = _WRITE_NAMES | _EDIT_NAMES | _READ_NAMES | _LIST_NAMES

# The curated coder menu — the coding essentials a small local model actually needs
# (ports codex-local LIGHT_CODER_TOOL_NAMES + its synthetic read/write/edit tools). The
# shell/exec tool is matched by FAMILY (shelltool.is_shell_tool_name) so this stays
# harness-agnostic — a name cria has never met (Gemini's run_shell_command, Cline's
# execute_command) must not be dropped from the menu for being unfamiliar.
# Everything NOT here is dropped: goal management (create_goal/get_goal/update_goal), MCP
# discovery (list_mcp_resources/…), ask-the-user (request_user_input), connector/app tools,
# and Codex's tool_suggest / request_plugin_install. Measured 2026-11 (decision-log, "Elision roots"): a FUNCTION-typed
# `tool_search` is KEPT by the file-tool shape rule below (its verb reads as a search), and the Responses-typed
# native tools never reach this function: `responses._to_chat_tools` skips `namespace`/`web_search` and rejects any
# other type (a `tool_search` tool is a 400 there).
FOCUS_TOOL_NAMES = frozenset({
    "write_stdin",                                    # exec_command's PTY companion
    "write_file", "edit_file", "read_file",
    "list_dir", "grep", "glob", "view_image", "update_plan",
    "web_search", "local_web_search", "web_fetch",
    "request_permissions",
})
# Tools cria withholds from the model even though they ARE file operations. The shape rule above
# matches `apply_patch` (a "patch" verb on the workspace) and it must still be dropped — see the
# note below: it is the LOWERING TARGET, not something the coder is asked to write.
_NEVER_ADVERTISED = frozenset({"apply_patch"})

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
    "read_file", "list_dir", "grep", "glob", "view_image",  # reading / inspection
    "web_search", "local_web_search", "web_fetch",    # the web tools
    "update_plan", "request_permissions",
    "write_stdin",                                     # shell-adjacent (paired with exec_command)
)


def _tool_name(t) -> str | None:
    return (((t.get("function") or t) if isinstance(t, dict) else {}) or {}).get("name")


def _order_key(name) -> tuple:
    """Sort key for the focused menu: purpose-built tools first (in _FOCUS_ORDER), the shell/exec
    family LAST, everything else stable in the middle."""
    if is_shell_tool_name(name):
        return (2, 0)                                 # shell/exec — last resort, listed last
    if name in _FOCUS_ORDER:
        return (0, _FOCUS_ORDER.index(name))          # cria's tools first, in preferred order
    return (1, 0)                                     # unranked focus tool — keep in the middle


@dataclass(frozen=True)
class FocusInput:
    tools: list[dict] | None
    selected: bool = True
    configured: bool = True


@dataclass(frozen=True)
class FocusResult:
    tools: list[dict] | None
    # Whether the caller should install the projection, not a count of drops.
    applied: bool = False


class Log(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


def focus_menu(request: FocusInput, rlog: Log | None = None) -> FocusResult:
    """Select and order a menu without rewriting native tool objects or schemas.

    Selection and the existing tools.focus configuration are independent gates.
    No detector or event runs when either is off. Never curate to empty.
    """
    tools = request.tools
    if not request.selected or not request.configured or not tools:
        return FocusResult(tools)
    kept, dropped = [], []
    for t in tools:
        nm = _tool_name(t)
        if nm in _NEVER_ADVERTISED:
            dropped.append(nm)
            continue
        if (nm in FOCUS_TOOL_NAMES or is_shell_tool_name(nm)
                or nm in _FILE_OP_NAMES or is_file_tool_name(nm)):
            kept.append(t)
        else:
            dropped.append(nm)
    if not kept:  # nothing coding-essential survives — leaving zero tools would break the model
        return FocusResult(tools)
    # Reorder to lead with cria's tools even when nothing was dropped (the harness may already send
    # only focused tools); prune too when the firehose brought extras.
    kept.sort(key=lambda t: _order_key(_tool_name(t)))  # specific tools first, shell last
    if rlog is not None and dropped:
        rlog.emit("toolmenu.focused", kept=len(kept), dropped=len(dropped), names=dropped)
    return FocusResult(kept, applied=True)


def focus_tools(body: dict, rlog=None) -> None:
    """In-place compatibility: honor a bound root; unbound keeps old defaults."""
    result = current_policies().focus(FocusInput(body.get("tools")), rlog)
    if result.applied:
        body["tools"] = result.tools


def cheatsheet(tools) -> str | None:
    """General cross-tool workflow only; individual usage belongs to the live schemas."""
    if not tools:
        return None
    return prompts.load_map("cheatsheet")["header"] + "\n" + prompts.load_map("native_tool_descs")["workflow"]


def enrich_descriptions(tools):
    """Add guidance only for recognized native names with their expected argument shapes.

    Preserve all caller fields and descriptions; do not infer a contract for unfamiliar schemas.
    """
    fragments = prompts.load_map("native_tool_descs")
    result = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            result.append(tool)
            continue
        fn = tool.get("function") or tool
        if not isinstance(fn, dict):
            result.append(tool)
            continue
        name = fn.get("name")
        params = fn.get("parameters") or {}
        props = params.get("properties") or {} if isinstance(params, dict) else {}
        def typed(key, kinds):
            return isinstance(props, dict) and isinstance(props.get(key), dict) and props[key].get("type") in kinds
        key = None
        # Names and JSON types do not establish a tool's semantics. These native contracts
        # are enriched only where the harness's own property descriptions establish them.
        if (name == "write_stdin" and typed("session_id", ("number", "integer")) and typed("chars", ("string",))
                and props["chars"].get("description") == "Bytes to write to stdin. Defaults to empty, which polls without writing."
                and props["session_id"].get("description") == "Identifier of the running unified exec session."):
            key = "write_stdin"
        elif (name == "view_image" and typed("path", ("string",))
              and props["path"].get("description") == "Local filesystem path to an image file."):
            key = "view_image"
        if key is None:
            result.append(tool)
            continue
        old = fn.get("description")
        extra = fragments[key]
        if old is not None and not isinstance(old, str):
            result.append(tool)
            continue
        if extra in (old or ""):
            result.append(tool)
            continue
        new_fn = {**fn, "description": ((old + " ") if old else "") + extra}
        result.append({**tool, "function": new_fn} if "function" in tool else new_fn)
    return result


@dataclass(frozen=True)
class InstructionInput:
    tools: list[dict] | None
    # None requests the note for embedding in an owned coder system frame.
    # A list (including []) requests the historical first-system merge.
    messages: list[dict] | None = None
    selected: bool = True
    configured: bool = True


@dataclass(frozen=True)
class InstructionResult:
    note: str | None
    messages: list[dict] | None
    applied: bool = False


def tool_instructions(request: InstructionInput, rlog: Log | None = None) -> InstructionResult:
    """One instruction policy, with note-only and first-system projections.

    Both consume the resolved menu, not the pre-focus menu. The shared renderer
    is support, not a selectable helper. No rendering or message copying occurs
    when selection or configuration is off. Note-only delivery keeps the coder's
    existing placement and emits no event (matching its former direct renderer).
    """
    if not request.selected or not request.configured:
        return InstructionResult(None, request.messages)
    note = cheatsheet(request.tools)
    if note is None:
        return InstructionResult(None, request.messages)
    if request.messages is None:
        return InstructionResult(note, None, applied=True)
    messages = list(request.messages)
    if messages and messages[0].get("role") == "system":
        head = dict(messages[0])
        head["content"] = _merge_system(head.get("content"), note)
        messages[0] = head
    else:
        messages.insert(0, {"role": "system", "content": note})
    if rlog is not None:
        rlog.emit("toolmenu.cheatsheet")
    return InstructionResult(note, messages, applied=True)


def add_cheatsheet(body: dict, rlog=None) -> None:
    """Root-aware compatibility with the original first-system merge and event."""
    result = current_policies().instructions(
        InstructionInput(body.get("tools"), body.get("messages") or []), rlog)
    if result.applied:
        body["messages"] = result.messages
        body["tools"] = enrich_descriptions(body.get("tools"))


def _legacy_cheatsheet(text: str, frag: dict[str, str]) -> bool:
    """Recognize a complete old generated block, not a header embedded in caller prose."""
    legacy_header = ("Tools available this turn, listed in the order you should PREFER them — "
                     "call these exact names with these argument shapes. Reach for a purpose-built tool below before a raw shell command.")
    lines = text.splitlines()
    if len(lines) < 2 or lines[0] not in (legacy_header, frag["header"]):
        return False
    keys = ("lead_write", "edit_file", "write_file", "read_file", "list_dir", "grep", "glob",
            "view_image", "web_search", "web_fetch", "update_plan", "request_permissions", "write_stdin", "shell", "read_via_shell")
    patterns = []
    for key in keys:
        template = frag[key]
        if key == "web_search":
            for suffix in ("", frag["web_search_fetch_hint"]):
                patterns.append(re.escape(prompts.fill(template, fetch_hint=suffix)))
            continue
        pattern = re.escape(template)
        for token in ("TOOLS", "ARG", "SHELL"):
            pattern = pattern.replace(re.escape("{{" + token + "}}"), r"[^\n]+?")
        patterns.append(pattern)
        if key == "shell":
            patterns.append(pattern.split(re.escape(" A focused tool cannot open an archive"))[0])
        if key == "write_stdin":
            patterns.append(re.escape("- write_stdin — send input to a shell session started by ")
                            + r"[^\n]+?" + re.escape(" (e.g. answer an interactive prompt). Per the tool's own argument schema."))
    return all(any(re.fullmatch(pattern, line) for pattern in patterns) for line in lines[1:])


def without_cheatsheet(content):
    """Remove only a complete generated note at the end of caller content.

    Historical per-tool blocks are recognized against their known line templates; unrecognized
    trailing caller text prevents removal. New workflow notes must match exactly.
    """
    frag = prompts.load_map("cheatsheet")
    note = frag["header"] + "\n" + prompts.load_map("native_tool_descs")["workflow"]
    def owned_note(text):
        return text == note or _legacy_cheatsheet(text, frag)
    if isinstance(content, str):
        if owned_note(content):
            return ""
        for match in re.finditer(r"\n\n", content):
            if owned_note(content[match.end():]):
                return content[:match.start()]
    if isinstance(content, list) and content:
        last = content[-1]
        if isinstance(last, dict) and isinstance(last.get("text"), str) and owned_note(last["text"]):
            return content[:-1]
    return content


def _merge_system(existing, note: str):
    """Append the note to an existing system message's content, preserving whether it
    was a plain string or a list of content parts."""
    if existing is None or existing == "":
        return note
    if isinstance(existing, str):
        return existing if existing == note or existing.endswith("\n\n" + note) else existing + "\n\n" + note
    if isinstance(existing, list):  # multimodal content parts
        if existing and existing[-1] == {"type": "text", "text": note}:
            return existing
        return list(existing) + [{"type": "text", "text": note}]
    return note


class FocusStage(Protocol):
    def __call__(self, request: FocusInput, rlog: Log | None = None) -> FocusResult: ...


class InstructionStage(Protocol):
    def __call__(self, request: InstructionInput, rlog: Log | None = None) -> InstructionResult: ...


@dataclass(frozen=True)
class FocusDefinition:
    policy: Policy
    execute: FocusStage


@dataclass(frozen=True)
class InstructionDefinition:
    policy: Policy
    execute: InstructionStage


# Integration handoff: server._setup_translation must resolve both selections
# after advertise, at its existing SIMPLE_TOOLS admission, using cfg.tools.focus
# and cfg.tools.cheatsheet independently. Apply focus before instructions.
# loop._frame_for_item must replace its direct cheatsheet(tools) with the same
# INSTRUCTION_DEFINITION note-only projection at the existing embedding position.
# That path historically ignores cfg.tools.cheatsheet; do not silently change
# existing config behavior while installing selection. without_cheatsheet remains
# shared support for removing the upstream copy before the coder re-embeds it.
# Neither role names nor tool schemas are changed here. No reasoner/provider is
# consulted: a reasoner receives instructions only if its caller requests them.
# Compatibility wrappers project the bound canonical root (standalone calls keep
# defaults). Required coder-base assembly projects the same selected note-only
# adapter; migrated=False remains conservative until broader migration acceptance.
FOCUS_DEFINITION = FocusDefinition(
    Policy("focused-tool-menu", "tool-menu-focus", 2, family_id="F10",
           state="none; request-local menu projection",
           services=("resolved tool menu", "tools.focus configuration"),
           hooks=(Reference("cria/server.py", "CriaHandler._setup_translation"),),
           regressions=(Reference("tests/write_edit/test_write_edit_menu.py", "test_any_shell_family_tool_survives_focus_and_trails_the_purpose_built_tools"),
                        Reference("tests-before-reset-20261031:tests/test_toolmenu_root_projection.py", "test_bound_absence_prevents_all_detection_render_mutation_and_events"),
                        Reference("tests-before-reset-20261031:tests/test_toolmenu_root_projection.py", "test_bound_exact_replacements_and_nested_empty_restore_through_public_aliases")),
           migrated=False),
    focus_menu,
)
INSTRUCTION_DEFINITION = InstructionDefinition(
    Policy("tool-menu-instructions", "tool-menu-instructions", 2, family_id="F10",
           prompts=("cheatsheet", "native_tool_descs"), state="none; request-local note/system projection",
           services=("resolved tool menu", "tools.cheatsheet configuration", "system content"),
           hooks=(Reference("cria/server.py", "CriaHandler._setup_translation"),
                  Reference("cria/loop.py", "_required_coder_base"),
                  Reference("cria/loop.py", "_frame_for_item")),
           regressions=(Reference("tests/write_edit/test_write_edit_scenario_cheatsheet.py", "test_the_cheatsheet_merges_into_the_leading_system_message_whatever_its_shape_and_strips_back_off"),
                        Reference("tests-before-reset-20261031:tests/test_toolmenu_source_policies.py", "test_instruction_body_parity"),
                        Reference("tests-before-reset-20261031:tests/test_toolmenu_source_policies.py", "test_disabled_never_detects_renders_copies_or_emits"),
                        Reference("tests/loop_guards/test_loop_guards_step_preparation.py", "test_an_explicit_tool_menu_choice_is_honoured_and_absence_never_falls_back_to_the_default")),
           migrated=False),
    tool_instructions,
)
DEFINITIONS = (FOCUS_DEFINITION, INSTRUCTION_DEFINITION)


@dataclass(frozen=True)
class MenuPolicies:
    """Typed projection of one canonical selection, including explicit absence.

    These methods enforce applicability BEFORE invoking even a replacement.
    There is no absent-definition fallback and no second context-local registry.
    Projection results are installed by the body owner only when applied=True.
    """
    focus_definition: FocusDefinition | None = None
    instruction_definition: InstructionDefinition | None = None

    def __post_init__(self):
        for definition, expected, kind in (
                (self.focus_definition, FOCUS_DEFINITION, FocusDefinition),
                (self.instruction_definition, INSTRUCTION_DEFINITION, InstructionDefinition)):
            if definition is not None and (not isinstance(definition, kind)
                    or definition.policy != expected.policy or not callable(definition.execute)):
                raise ValueError("Tool menu replacement must preserve its typed policy contract")

    def focus(self, source: FocusInput, rlog: Log | None = None) -> FocusResult:
        if self.focus_definition is None or not source.selected or not source.configured:
            return FocusResult(source.tools)
        result = self.focus_definition.execute(source, rlog)
        if not isinstance(result, FocusResult):
            raise ValueError("Tool menu focus replacement must return FocusResult")
        return result

    def instructions(self, source: InstructionInput, rlog: Log | None = None) -> InstructionResult:
        if self.instruction_definition is None or not source.selected or not source.configured:
            return InstructionResult(None, source.messages)
        result = self.instruction_definition.execute(source, rlog)
        if not isinstance(result, InstructionResult):
            raise ValueError("Tool instruction replacement must return InstructionResult")
        return result


def selected_policies(definitions: Iterable[ExecutableDefinition]) -> MenuPolicies:
    """Project exact selected definitions; unrelated policies are not defaults.

    Primary integration: after advertise, call focus(FocusInput(...,
    configured=cfg.tools.focus)), install only an applied result, then call
    instructions(InstructionInput(resolved_tools, messages,
    configured=cfg.tools.cheatsheet)). The coder uses instructions with
    messages=None and configured=True at its existing note slot: historically
    that path ignores cfg.tools.cheatsheet. Both policies retain minimum L2;
    canonical root selection owns engagement filtering, not this projection.
    """
    chosen = {}
    ids = (FOCUS_DEFINITION.policy.id, INSTRUCTION_DEFINITION.policy.id)
    for definition in definitions:
        identity = definition.policy.id
        if identity in ids:
            if identity in chosen:
                raise ValueError("Duplicate tool menu policy selection: " + identity)
            chosen[identity] = definition
    return MenuPolicies(chosen.get(ids[0]), chosen.get(ids[1]))


def current_policies() -> MenuPolicies:
    """Public compatibility: exact stored selection wins; only UNBOUND defaults.

    Storage owns no catalog or dispatcher. Explicit hooks may instead use
    selected_policies(selection.definitions); neither path creates a shadow
    binding, invents defaults for a bound selection, or catches selection errors.
    """
    from . import assistbinding
    selection = assistbinding.current()
    if selection is assistbinding.UNBOUND:
        return MenuPolicies(FOCUS_DEFINITION, INSTRUCTION_DEFINITION)
    return selected_policies(selection.definitions)
