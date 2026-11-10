"""The tool menu the coder sees: focused to the coding essentials, edit before rewrite, shell last, only what exists."""
import pytest

from cria import toolmenu


def tool(name, **props):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": props or {"path": {"type": "string"}}}}}


def names(tools):
    return [t["function"]["name"] for t in tools]


def focus(*tool_names):
    body = {"tools": [tool(n) for n in tool_names]}
    toolmenu.focus_tools(body)
    return names(body["tools"])


@pytest.mark.parametrize("given,kept", [
    # the create_goal incident menu: goal/MCP/connector catalog entries go, the coding essentials stay
    (["exec_command", "write_stdin", "list_mcp_resources", "read_mcp_resource", "update_plan", "view_image", "get_goal", "create_goal",
      "update_goal", "request_user_input", "write_file"], {"exec_command", "write_stdin", "update_plan", "view_image", "write_file"}),
    # a harness whose own write/edit tools are named create_file / str_replace must not lose them
    (["create_file", "str_replace", "exec_command", "create_goal"], {"create_file", "str_replace", "exec_command"}),
    (["read_file", "edit_file", "apply_patch", "list_dir", "web_fetch", "connector_gmail_send"], {"read_file", "edit_file", "list_dir", "web_fetch"}),
    # a plugin catalog tool (1,034 captured coder bodies carried list_available_plugins_to_install; 0 calls) is not a file
    # tool, and a function-typed deferred search (`tool_search`) is kept by shape: the coder keeps its route to other tools
    (["exec_command", "tool_search", "list_available_plugins_to_install", "request_plugin_install", "tool_suggest"], {"exec_command", "tool_search"}),
])
def test_focus_drops_everything_but_the_coding_essentials_by_family_not_by_one_harnesss_names(given, kept):
    """apply_patch is never model-facing (a 9B cannot produce diff context); the keep-set is derived from the file-op families."""
    assert set(focus(*given)) == kept


@pytest.mark.parametrize("shell", ["shell", "run_terminal_cmd", "run_shell_command"])
def test_any_shell_family_tool_survives_focus_and_trails_the_purpose_built_tools(shell):
    """The shell is matched by FAMILY (Gemini CLI advertises run_shell_command); purpose-built tools lead, the generic shell is last."""
    order = focus(shell, "create_file", "web_fetch", "write_file", "edit_file", "create_goal")      # create_file: kept, but unranked
    assert order[-1] == shell and "create_goal" not in order and order.index("write_file") < order.index("edit_file") < order.index("create_file")


def test_focus_never_leaves_the_coder_tool_less():
    """A menu of only non-essential tools is kept whole; an absent or empty menu is untouched."""
    assert focus("create_goal", "connector_x") == ["create_goal", "connector_x"]
    body = {"messages": []}
    toolmenu.focus_tools(body)
    assert "tools" not in body


FULL = [tool("write_file"), tool("edit_file"), tool("read_file"), tool("list_dir"), tool("exec_command", command={"type": "string"})]

