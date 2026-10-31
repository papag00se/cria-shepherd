"""Leaf-stage behavior; shared server/driver selection is not yet integrated."""
import copy
from dataclasses import replace

import pytest

from cria import toolmenu as menu
from cria.config import Config, ToolsConfig


def tool(name, path_arg="path"):
    return {"type": "function", "function": {
        "name": name, "description": "Literal native description\n<tool> 'quoted' \\n",
        "parameters": {"type": "object", "properties": {
            path_arg: {"type": "string", "description": "keep this schema byte-for-byte"}},
            "required": [path_arg], "additionalProperties": False}}}


class Log:
    def __init__(self):
        self.events = []

    def emit(self, name, **fields):
        self.events.append((name, fields))


def test_focus_preserves_native_bytes_and_stable_order():
    tools = [tool(n) for n in ["run_shell_command", "search_files", "write_file", "create_goal",
                               "replace", "edit_file", "apply_patch", "list_directory", "bash"]]
    original = copy.deepcopy(tools)
    log = Log()
    result = menu.FOCUS_DEFINITION.execute(menu.FocusInput(tools), log)
    assert [t["function"]["name"] for t in result.tools] == [
        "write_file", "edit_file", "search_files", "replace", "list_directory", "run_shell_command", "bash"]
    assert result.applied and tools == original
    assert all(any(t is native for native in tools) for t in result.tools)
    assert log.events == [("toolmenu.focused", {"kept": 7, "dropped": 2,
                                              "names": ["create_goal", "apply_patch"]})]


@pytest.mark.parametrize("tools", [None, [], [tool("connector_mail"), tool("create_goal")]])
def test_empty_or_no_survivors_leave_original_menu(tools):
    log = Log()
    result = menu.focus_menu(menu.FocusInput(tools), log)
    assert result.tools is tools and not result.applied
    assert log.events == []


@pytest.mark.parametrize("role", ["coder", "reasoner"])
@pytest.mark.parametrize("content", ["Original instructions\nverbatim", None, "",
                                      [{"type": "text", "text": "native"},
                                       {"type": "image_url", "image_url": {"url": "data:unchanged"}}]])
def test_instruction_body_parity(role, content):
    tools = [tool("read_file", "file_path"), tool("list_dir", "dir_path"), tool("shell")]
    messages = [{"role": "system", "content": content, "name": role},
                {"role": "developer", "content": "Keep this role"},
                {"role": "user", "content": "Work"}]
    original = copy.deepcopy(messages)
    note = menu.cheatsheet(tools)  # shared renderer, not a second policy
    result = menu.INSTRUCTION_DEFINITION.execute(menu.InstructionInput(tools, messages))
    assert result.applied and result.note == note
    if isinstance(content, list):
        expected = content + [{"type": "text", "text": note}]
    else:
        expected = content + "\n\n" + note if content else note
    assert result.messages == [{**messages[0], "content": expected}, *messages[1:]]
    assert result.messages[1] is messages[1]
    assert messages == original
    assert '"file_path"' in note and '"dir_path"' in note
    assert tools[0]["function"]["description"].startswith("Literal native")


def test_inserted_system_and_note_only_share_exact_rendered_bytes():
    tools = [tool("edit_file"), tool("write_file"), tool("shell")]
    messages = [{"role": "developer", "content": "permissions"}, {"role": "user", "content": "task"}]
    log = Log()
    embedded = menu.tool_instructions(menu.InstructionInput(tools), log)
    assert log.events == []  # direct coder hint previously emitted no event
    merged = menu.tool_instructions(menu.InstructionInput(tools, messages), log)
    assert merged.messages == [{"role": "system", "content": embedded.note}, *messages]
    assert log.events == [("toolmenu.cheatsheet", {})]
    assert embedded.messages is None and embedded.applied
    assert embedded.note == menu.cheatsheet(tools)
    assert embedded.note.index("edit_file") < embedded.note.index("write_file")


@pytest.mark.parametrize("selected,configured", [(False, True), (True, False), (False, False)])
def test_disabled_never_detects_renders_copies_or_emits(monkeypatch, selected, configured):
    def forbidden(*args, **kw):
        raise AssertionError("disabled stage accessed policy support")
    for name in ("_tool_name", "_order_key", "cheatsheet", "_merge_system"):
        monkeypatch.setattr(menu, name, forbidden)
    tools, messages = [tool("shell")], [{"role": "system", "content": "raw"}]
    log = Log()
    focused = menu.focus_menu(menu.FocusInput(tools, selected, configured), log)
    instructions = menu.tool_instructions(menu.InstructionInput(tools, messages, selected, configured), log)
    embedded = menu.tool_instructions(menu.InstructionInput(tools, selected=selected, configured=configured), log)
    assert focused.tools is tools and not focused.applied
    assert instructions.messages is messages and not instructions.applied and instructions.note is None
    assert embedded.note is None and not embedded.applied
    assert log.events == []


@pytest.mark.parametrize("tools", [None, [], [tool("connector_mail")]])
def test_no_instruction_preserves_messages_and_emits_nothing(tools):
    messages = [{"role": "user", "content": "unchanged"}]
    log = Log()
    result = menu.tool_instructions(menu.InstructionInput(tools, messages), log)
    assert result.messages is messages and not result.applied and result.note is None
    assert log.events == []


def test_independent_switches_and_default_configuration():
    assert ToolsConfig().focus and ToolsConfig().cheatsheet
    assert Config().tools == ToolsConfig()
    tools = [tool("shell"), tool("create_goal"), tool("write_file")]
    focused = menu.focus_menu(menu.FocusInput(tools, configured=True))
    note_off = menu.tool_instructions(menu.InstructionInput(focused.tools, configured=False))
    assert len(focused.tools) == 2 and note_off.note is None
    focus_off = menu.focus_menu(menu.FocusInput(tools, configured=False))
    note_on = menu.tool_instructions(menu.InstructionInput(focus_off.tools))
    assert focus_off.tools is tools and note_on.note == menu.cheatsheet(tools)


def test_compatibility_entries_preserve_body_fields_and_original_no_config_behavior():
    body = {"model": "native", "tools": [tool("shell"), tool("write_file"), tool("create_goal")],
            "messages": [{"role": "user", "content": "task"}], "temperature": 0.25,
            "tool_choice": "auto", "stream": True}
    original = copy.deepcopy(body)
    menu.focus_tools(body)
    menu.add_cheatsheet(body)
    assert body == {**original, "tools": [original["tools"][1], original["tools"][0]],
                    "messages": [{"role": "system", "content": menu.cheatsheet(body["tools"])},
                                 *original["messages"]]}
    empty = {"model": "native"}
    menu.focus_tools(empty)
    menu.add_cheatsheet(empty)
    assert empty == {"model": "native"}


def test_semantic_replacements_are_used_by_actual_leaf_entries(monkeypatch):
    tools = [tool("shell"), tool("write_file"), tool("edit_file")]
    # Replace curation with a menu preserving only the harness shell, rather than
    # calling the old focus implementation or mutating its result afterwards.
    replacement_focus = replace(menu.FOCUS_DEFINITION,
                                execute=lambda request, rlog=None: menu.FocusResult([request.tools[0]], True))
    monkeypatch.setattr(menu, "FOCUS_DEFINITION", replacement_focus)
    body = {"tools": tools, "messages": [{"role": "user", "content": "task"}]}
    menu.focus_tools(body)
    assert body["tools"] == [tools[0]]
    assert body["tools"][0] is tools[0]

    def replacement_instruction(request, rlog=None):
        # A legitimate alternate instruction policy withholds all instructions.
        return menu.InstructionResult(None, request.messages)
    monkeypatch.setattr(menu, "INSTRUCTION_DEFINITION",
                        replace(menu.INSTRUCTION_DEFINITION, execute=replacement_instruction))
    before = copy.deepcopy(body)
    menu.add_cheatsheet(body)
    assert body == before and body["messages"][0]["role"] == "user"
    embedded = menu.INSTRUCTION_DEFINITION.execute(menu.InstructionInput(tools))
    assert embedded.note is None  # the driver's future hook uses this same API
    assert all(d.policy.family_id == "F10" and not d.policy.migrated for d in menu.DEFINITIONS)
