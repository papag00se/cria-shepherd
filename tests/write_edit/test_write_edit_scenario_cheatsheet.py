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


def test_each_offered_tool_gets_its_hint_with_the_argument_name_that_tool_really_uses_and_no_tools_no_note():
    """Hints name the offered path argument (file_path, directory, path), cross-reference web_fetch only when it is callable, and an empty menu adds nothing."""
    note = toolmenu.cheatsheet(MENU)
    assert "file_path" in note and "directory" in note and "exec_command" in note
    assert "web_fetch" in toolmenu.cheatsheet([fn("web_search", query=1), fn("web_fetch", url=1)]) and toolmenu.cheatsheet([]) is None
    body = {"tools": [], "messages": [USER]}; toolmenu.add_cheatsheet(body); assert body["messages"] == [USER]
