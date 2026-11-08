"""The tool cheat-sheet rides the harness's own system message in whatever shape it arrives, is never doubled, and names only tools that are callable."""
import pytest
from cria import toolmenu


def fn(name, **props): return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {k: {"type": "string"} for k in props}}}}

MENU = [fn("exec_command", cmd=1), fn("read_file", file_path=1), fn("list_dir", directory=1), fn("view_image", path=1), fn("web_search", query=1), fn("web_fetch", url=1),
        fn("update_plan", plan=1), fn("request_permissions", why=1), fn("write_stdin", chars=1)]
USER = {"role": "user", "content": "go"}


@pytest.mark.parametrize("system,expect", [
    (None, "inserted"), ("", "note only"), ("You are Codex.", "string + note"), ([{"type": "text", "text": "You are Codex."}], "parts + note"), (7, "note only")])
def test_the_cheatsheet_merges_into_the_leading_system_message_whatever_its_shape_and_strips_back_off(system, expect):
    """No system message gets one; a string or a parts list keeps its text and gains the note last; unusable content is replaced by the note; stripping restores the original."""
    body = {"tools": MENU, "messages": ([{"role": "system", "content": system}] if system is not None else []) + [USER]}
    toolmenu.add_cheatsheet(body)
    head = body["messages"][0]; assert head["role"] == "system" and body["messages"][-1] == USER
    note = toolmenu.cheatsheet(MENU)
    if expect == "inserted" or expect == "note only": assert head["content"] == note
    elif expect == "string + note": assert head["content"] == "You are Codex.\n\n" + note and toolmenu.without_cheatsheet(head["content"]) == "You are Codex."
    else: assert head["content"][-1] == {"type": "text", "text": note} and toolmenu.without_cheatsheet(head["content"]) == [{"type": "text", "text": "You are Codex."}]
    assert toolmenu.without_cheatsheet(note) == "" and toolmenu.without_cheatsheet("untouched") == "untouched" and toolmenu.without_cheatsheet([]) == []


def test_advertised_descriptions_own_tool_usage_and_composition_has_no_second_catalog():
    from cria import writeproxy
    body = {"tools": [fn("exec_command", cmd=1)], "messages": [USER]}
    writeproxy.advertise(body, brave_key="key")
    toolmenu.add_cheatsheet(body)
    descriptions = {t["function"]["name"]: t["function"]["description"] for t in body["tools"] if "description" in t["function"]}
    assert "User-Agent" in descriptions["web_fetch"]
    assert "old_string" in descriptions["edit_file"] and "inclusive" in descriptions["read_file"]
    assert "regular expression" in descriptions["grep"] and "glob" in descriptions["glob"]
    note = body["messages"][0]["content"]
    assert 'Args:' not in note and '- edit_file' not in note and '- web_fetch' not in note
    assert toolmenu.cheatsheet([]) is None
    empty = {"tools": [], "messages": [USER]}; toolmenu.add_cheatsheet(empty); assert empty["messages"] == [USER]


def test_native_descriptions_are_additive_idempotent_and_schema_qualified():
    import copy
    stdin = fn("write_stdin", session_id=1, chars=1)
    stdin["function"]["parameters"]["properties"]["session_id"]["type"] = "number"
    stdin["function"]["description"] = "Native session input."
    stdin["function"]["parameters"]["properties"]["chars"]["description"] = "Bytes to write to stdin. Defaults to empty, which polls without writing."
    stdin["function"]["parameters"]["properties"]["session_id"]["description"] = "Identifier of the running unified exec session."
    image = fn("view_image", path=1)
    image["function"]["parameters"]["properties"]["path"]["description"] = "Local filesystem path to an image file."
    permissions = fn("request_permissions", justification=1)
    edit = fn("edit_file", path=1, old_string=1, new_string=1)
    write = fn("create_file", path=1, content=1)
    shell = fn("run_shell_command", command=1)
    read = fn("read_file", path=1, start_line=1, end_line=1)
    read["function"]["parameters"]["properties"]["start_line"]["type"] = "integer"
    read["function"]["parameters"]["properties"]["end_line"]["type"] = "integer"
    unknown = fn("write_stdin", unrelated=1)
    body = {"tools": [stdin, image, permissions, edit, write, shell, read, unknown], "messages": [USER]}
    original = copy.deepcopy(body)
    toolmenu.add_cheatsheet(body)
    tools = body["tools"]
    assert tools[0]["function"]["description"].startswith("Native session input.")
    assert "empty" in tools[0]["function"]["description"] and "session" in tools[0]["function"]["description"]
    assert "local" in tools[1]["function"]["description"].lower()
    assert tools[2] == original["tools"][2]
    assert tools[3] == original["tools"][3]
    assert tools[4] == original["tools"][4]
    assert tools[5] == original["tools"][5]
    assert tools[6] == original["tools"][6]
    assert tools[7] == original["tools"][7]
    once = copy.deepcopy(body)
    toolmenu.add_cheatsheet(body)
    assert body == once


def test_legacy_catalog_is_removed_only_as_a_complete_terminal_block():
    old = ('Tools available this turn, listed in the order you should PREFER them — call these exact names with these argument shapes. Reach for a purpose-built tool below before a raw shell command.\n'
           '- read_file — Args: {"path": "<file>"}, or add "start_line"/"end_line" for a 1-based inclusive range\n'
           '- exec_command — LAST RESORT, for commands with no dedicated tool above (build, test, git, package installs, mkdir/rm). Per the tool\'s own argument schema. Do NOT use it to read, write, or list files when a focused tool exists.')
    assert toolmenu.without_cheatsheet("caller\n\n" + old) == "caller"
    assert toolmenu.without_cheatsheet("caller\n\n" + old + "\nDo not remove this caller text.") == "caller\n\n" + old + "\nDo not remove this caller text."
