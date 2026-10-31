"""The tool menu policies (cria.toolmenu) follow the bound assist selection and the two config switches independently: what is not selected or
configured leaves the body object-identical (nothing detected, rendered or copied), what is selected acts on the tools it was handed."""
import pytest

from cria import assistruntime as ar, toolmenu
from write_edit_helpers import write_edit_workspace_view  # noqa: F401


def tool(name):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}


def fresh():
    return {"tools": [tool("shell"), tool("create_goal"), tool("write_file")], "messages": [{"role": "system", "content": "native"}]}


@pytest.mark.parametrize("kwargs,focused,noted", [
    (dict(level=2), True, True), (dict(level=1), False, False), (dict(level=0), False, False),
    (dict(level=5, disabled=("focused-tool-menu",)), False, True), (dict(level=5, disabled=("tool-menu-instructions",)), True, False),
    (dict(level=5, disabled=("focused-tool-menu", "tool-menu-instructions")), False, False)])
def test_the_bound_selection_decides_independently_whether_the_menu_is_focused_and_the_cheatsheet_added(kwargs, focused, noted):
    """Focus drops create_goal and puts the shell last; the sheet lands in the system message and never names a goal tool. Unselected = identity."""
    body = fresh()
    tools, messages = body["tools"], body["messages"]
    with ar.bound(ar.AssistRuntime.select(**kwargs)):
        toolmenu.focus_tools(body)
        toolmenu.add_cheatsheet(body)
    assert (body["tools"] is not tools) is focused and (body["messages"] is not messages) is noted
    if focused:
        assert [t["function"]["name"] for t in body["tools"]] == ["write_file", "shell"]
    if noted:
        sheet = body["messages"][0]["content"]
        assert sheet.startswith("native\n\n") and "write_file" in sheet and "create_goal" not in sheet
    else:
        assert body["messages"] == messages


@pytest.mark.parametrize("off", ["focus-config", "cheatsheet-config", "focus-unselected", "cheatsheet-unselected"])
def test_a_configured_or_unselected_off_switch_leaves_its_half_alone_and_the_other_half_working(off):
    """tools.focus / tools.cheatsheet (config) and the two assist selections are independent gates: off means the very same objects come back."""
    tools = fresh()["tools"]
    messages = [{"role": "system", "content": "native"}]
    field, gate = off.split("-")
    flag = {"configured": False} if gate == "config" else {"selected": False}
    focus = toolmenu.focus_menu(toolmenu.FocusInput(tools, **(flag if field == "focus" else {})))
    note = toolmenu.tool_instructions(toolmenu.InstructionInput(tools, messages, **(flag if field == "cheatsheet" else {})))
    assert (focus.tools is tools) is (field == "focus") and (note.messages is messages) is (field == "cheatsheet")
    assert (focus.applied, bool(note.applied)) == (field != "focus", field != "cheatsheet") and (note.note is None) is (field == "cheatsheet")
