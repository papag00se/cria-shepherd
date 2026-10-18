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

from dataclasses import dataclass
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
# and Codex's deferred-tool search (tool_search/tool_suggest).
FOCUS_TOOL_NAMES = frozenset({
    "write_stdin",                                    # exec_command's PTY companion
    "write_file", "edit_file", "read_file",
    "list_dir", "view_image", "update_plan",
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
    # EDIT FIRST, and the reason is measured. This list is introduced to the model as "the order you
    # should PREFER them", and it led with `write_file — {"content": "<full file text>"}`. On the
    # targeted re-run of `rust-toml-cli x ternary-bonsai` the coder used write_file SEVEN times and
    # edit_file ZERO — rewriting a 6.6 KB main.rs whole, five times, each version 99.1-99.9%
    # identical to the last, and not one of the five versions compiles — verified by building them. The
    # SAME model on the SAME task with the harness's own menu wrote the file once and made three
    # ~285-byte edit_file patches: 20 calls, 4 of 4.
    #
    # It did what it was told. Changing part of a file that exists is what edit_file is for, and a
    # whole-file rewrite is the expensive way to change one line — it regenerates every line that was
    # already right, and each regeneration is a fresh chance to break one.
    #
    # THIS DOES NOT UNDO THE TWO DECISIONS AROUND IT, and both were checked before it landed.
    #
    # `87563ae` set this ordering, and its lesson is FILE TOOLS FIRST, SHELL LAST — the shell-reflex
    # lever. That is untouched: the file tools still lead and the shell still trails. Which of the two
    # file tools came first was incidental to it ("writing tools grouped first").
    #
    # `editrecovery`'s monotonic policy is the one that really bears on this: it escalates to a
    # whole-file rewrite after repeated edit failures because that "commits to the action a weak model
    # can actually complete, rather than pin an old_string it keeps mis-copying". Measured over every
    # captured call before changing anything (#15) — 20,056 successful edits against 1,551 failures:
    #
    #     gemma4              272 edits,   0 failures     0%
    #     qwen35            2,132 edits,  24 failures     1%
    #     ternary-bonsai      153 edits,  22 failures    13%
    #     nemotron-elastic    135 edits,  79 failures    37%
    #     ALL              20,056 edits, 1,551 failures   7.2%   (write_file fails 3.9%)
    #
    # So the escalation's premise holds for ONE model and is false for the others, and 93% of edits
    # land. The escalation is a RECOVERY, keyed on that file's own failure history, and this change
    # leaves it exactly where it is: a model that mis-pins `old_string` three times still gets
    # committed to a grounded whole-file rewrite. What changes is only that cria no longer starts
    # every model, on every file, at the escalated state.
    write_tools = []
    if "edit_file" in names:
        write_tools.append("edit_file (change part of a file that already exists — PREFER this)")
    if "write_file" in names:
        write_tools.append("write_file (create a file, or replace one wholesale)")
    if write_tools:
        lines.append(prompts.fill(frag["lead_write"], tools=" or ".join(write_tools)))
    # Same preferred order as the schema (_FOCUS_ORDER): file tools first — EDIT before WRITE, see
    # above — then reading/
    # inspection, then web, with the shell last — so the hint mirrors the menu. apply_patch is
    # intentionally absent (not model-facing). Arg NAMES for read_file/list_dir are read from the
    # resolved schema, so the hint can't disagree with a harness-native tool (path vs dir_path).
    if "edit_file" in names:
        lines.append(frag["edit_file"])
    if "write_file" in names:
        lines.append(frag["write_file"])
    if "read_file" in names:
        lines.append(prompts.fill(frag["read_file"], arg=_path_arg(by_name["read_file"])))
    elif shell is not None:
        lines.append(prompts.fill(frag["read_via_shell"], shell=shell["name"]))
    if "list_dir" in names:
        lines.append(prompts.fill(frag["list_dir"], arg=_path_arg(by_name["list_dir"])))
    if "view_image" in names:
        lines.append(frag["view_image"])
    if "web_search" in names:  # advertise() renames a harness local_web_search → web_search BEFORE this,
        # so keying on the callable name keeps the hint from ever naming an uncallable local_web_search.
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
    # No footer recap: the header ("prefer a purpose-built tool before a raw shell command") and the
    # shell entry ("LAST RESORT … don't use it to read/write/list when a focused tool exists") already
    # carry the prefer-tool rule — a third restatement was the same rule a 5th way to a small model.
    return frag["header"] + "\n" + "\n".join(lines)


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


def without_cheatsheet(content):
    """``content`` with the cheat-sheet :func:`add_cheatsheet` folded onto its end removed again.

    The fold is the harness-system-message path (`add_cheatsheet` merges into whatever system message
    leads the request). A caller-instruction system message is KEPT by the coder frame — and the frame
    renders the same menu hint itself, so the kept copy carried it TWICE (phi4 / feed-pipeline-java A2:
    the `Tools available this turn` block in the coder system message at 23,858 and again at 25,744, on
    top of the template's own tool JSON). The note is always the LAST thing `_merge_system` appends and
    always opens with the fragment header, so it is found by that structure, never by guessing."""
    header = prompts.load_map("cheatsheet")["header"]
    if isinstance(content, str):
        i = content.rfind("\n\n" + header)
        if i >= 0:
            return content[:i]
        return "" if content.startswith(header) else content
    if isinstance(content, list) and content:
        last = content[-1]
        if isinstance(last, dict) and str(last.get("text") or "").startswith(header):
            return content[:-1]
    return content


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
           regressions=(Reference("tests/test_toolmenu_source_policies.py", "test_focus_preserves_native_bytes_and_stable_order"),
                        Reference("tests/test_toolmenu_root_projection.py", "test_bound_absence_prevents_all_detection_render_mutation_and_events"),
                        Reference("tests/test_toolmenu_root_projection.py", "test_bound_exact_replacements_and_nested_empty_restore_through_public_aliases")),
           migrated=False),
    focus_menu,
)
INSTRUCTION_DEFINITION = InstructionDefinition(
    Policy("tool-menu-instructions", "tool-menu-instructions", 2, family_id="F10",
           prompts=("cheatsheet",), state="none; request-local note/system projection",
           services=("resolved tool menu", "tools.cheatsheet configuration", "system content"),
           hooks=(Reference("cria/server.py", "CriaHandler._setup_translation"),
                  Reference("cria/loop.py", "_required_coder_base"),
                  Reference("cria/loop.py", "_frame_for_item")),
           regressions=(Reference("tests/test_toolmenu_source_policies.py", "test_instruction_body_parity"),
                        Reference("tests/test_toolmenu_source_policies.py", "test_disabled_never_detects_renders_copies_or_emits"),
                        Reference("tests/test_toolmenu_root_projection.py", "test_projection_coder_note_uses_exact_selected_replacement_and_rejects_wrong_results")),
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
