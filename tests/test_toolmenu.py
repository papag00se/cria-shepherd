import unittest

from cria.toolmenu import add_cheatsheet, cheatsheet, focus_tools

_SHELL = {"type": "function", "function": {"name": "shell"}}
_WRITE = {"type": "function", "function": {"name": "write_file"}}
_PATCH = {"type": "function", "function": {"name": "apply_patch"}}


def _t(name):
    return {"type": "function", "function": {"name": name}}


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class FocusToolsTests(unittest.TestCase):
    """Ports codex-local ToolSubset::Focused: curate the harness's menu (up to ~120 with the
    Apps/Connectors catalog) down to the coding essentials, dropping the rest."""

    def test_drops_goal_and_mcp_tools_keeps_essentials(self):
        # the exact 12-tool menu from the create_goal incident session
        body = {"tools": [_t(n) for n in [
            "exec_command", "write_stdin", "list_mcp_resources", "list_mcp_resource_templates",
            "read_mcp_resource", "update_plan", "request_user_input", "view_image",
            "get_goal", "create_goal", "update_goal", "write_file"]]}
        rlog = _Rlog()
        focus_tools(body, rlog)
        kept = {m["function"]["name"] for m in body["tools"]}
        self.assertEqual(kept, {"exec_command", "write_stdin", "update_plan", "view_image", "write_file"})
        for gone in ("create_goal", "get_goal", "update_goal", "list_mcp_resources", "request_user_input"):
            self.assertNotIn(gone, kept)
        ev = dict(rlog.events)["toolmenu.focused"]
        self.assertEqual(ev["kept"], 5)
        self.assertIn("create_goal", ev["names"])

    def test_shell_family_kept_harness_agnostic(self):
        # the shell/exec tool is matched by FAMILY, not a hardcoded name
        for shell_name in ("shell", "bash", "local_shell", "run_terminal_cmd", "shell_command"):
            body = {"tools": [_t(shell_name), _t("create_goal")]}
            focus_tools(body)
            self.assertEqual([m["function"]["name"] for m in body["tools"]], [shell_name], shell_name)

    def test_keeps_web_and_read_and_edit_tools(self):
        body = {"tools": [_t(n) for n in [
            "read_file", "edit_file", "apply_patch", "list_dir",
            "web_search", "local_web_search", "web_fetch", "request_permissions", "connector_gmail_send"]]}
        focus_tools(body)
        kept = {m["function"]["name"] for m in body["tools"]}
        self.assertNotIn("connector_gmail_send", kept)
        self.assertIn("web_fetch", kept)
        self.assertIn("edit_file", kept)

    def test_never_curates_to_empty(self):
        # a degenerate harness with ONLY non-essential tools: keep the firehose rather than
        # leave the model tool-less
        body = {"tools": [_t("create_goal"), _t("connector_x")]}
        focus_tools(body)
        self.assertEqual(len(body["tools"]), 2)  # untouched

    def test_noop_without_tools(self):
        body = {"messages": []}
        focus_tools(body)
        self.assertNotIn("tools", body)
        body2 = {"tools": []}
        focus_tools(body2)
        self.assertEqual(body2["tools"], [])


class CheatsheetTests(unittest.TestCase):
    def test_describes_present_tools(self):
        note = cheatsheet([_WRITE, _SHELL, _PATCH])
        self.assertIn("write_file", note)
        self.assertIn('"content"', note)   # the menu-derived hint carries argument shapes
        self.assertIn("shell", note)
        self.assertIn("apply_patch", note)

    def test_none_without_tools(self):
        self.assertIsNone(cheatsheet([]))
        self.assertIsNone(cheatsheet(None))

    def test_shell_read_hint_when_no_read_file(self):
        self.assertIn("cat <path>", cheatsheet([_SHELL]))

    def test_names_only_tools_in_the_menu(self):
        # prompt<->menu consistency: read_file + list_dir present → named with arg shapes;
        # edit_file absent → NEVER mentioned (the mismatch the coder prompt used to have)
        note = cheatsheet([_WRITE, _SHELL, _t("read_file"), _t("list_dir")])
        self.assertIn("read_file", note)
        self.assertIn("list_dir", note)
        self.assertIn("start_line", note)     # read_file's argument shape is spelled out
        self.assertNotIn("edit_file", note)   # not in the menu → the hint must not name it
        # …and when edit_file IS in the menu, it gets described
        note2 = cheatsheet([_WRITE, _t("edit_file")])
        self.assertIn("edit_file", note2)
        self.assertIn("old_string", note2)


class AddCheatsheetTests(unittest.TestCase):
    def test_merges_into_system_prompt(self):
        # A SECOND system message 500s strict templates ("system must be at the
        # beginning"), so the cheat-sheet folds into the existing one.
        body = {
            "tools": [_WRITE, _SHELL],
            "messages": [
                {"role": "system", "content": "You are a coder."},
                {"role": "user", "content": "build it"},
            ],
        }
        add_cheatsheet(body)
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["system", "user"])  # still exactly one system message
        self.assertIn("You are a coder.", body["messages"][0]["content"])  # original preserved
        self.assertIn("write_file", body["messages"][0]["content"])  # cheat-sheet merged in

    def test_creates_system_when_none(self):
        body = {"tools": [_SHELL], "messages": [{"role": "user", "content": "build it"}]}
        add_cheatsheet(body)
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["system", "user"])
        self.assertIn("run a shell command", body["messages"][0]["content"])

    def test_merges_into_multimodal_system(self):
        body = {
            "tools": [_SHELL],
            "messages": [
                {"role": "system", "content": [{"type": "text", "text": "sys"}]},
                {"role": "user", "content": "hi"},
            ],
        }
        add_cheatsheet(body)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        parts = body["messages"][0]["content"]
        self.assertTrue(any("run a shell command" in p.get("text", "") for p in parts))

    def test_noop_without_tools(self):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        add_cheatsheet(body)
        self.assertEqual(len(body["messages"]), 1)


if __name__ == "__main__":
    unittest.main()
