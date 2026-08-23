"""The focus menu kept the shell by shape and the file tools by six literal names.

`toolmenu._FILE_OP_NAMES` is `{write_file, create_file, edit_file, str_replace, read_file,
list_dir}` under a comment calling them "FAMILIES". The shell beside them is matched by
`shelltool.is_shell_tool_name`, a real part-prefix rule, with a comment saying why: *"a name cria has
never met (Gemini's run_shell_command, Cline's execute_command) must not be dropped from the menu for
being unfamiliar."* The same argument was never applied to the file tools.

Simulated through the real gate (`needs_translation` → `advertise` → `focus_tools`):

    Gemini CLI  lost  replace, list_directory, glob, search_file_content
    Cline/Roo   lost  search_files, list_code_definition_names

Every one is a file operation the coder needs, and `shelltool.is_write_tool_name` — which already
matches `replace`, `write_to_file` and `replace_in_file` — was one import away.

The shape has to be bounded on the other side too: `create`, `list` and `read` are also how a harness
names its goal store, its MCP registry and its memory, and that firehose is exactly what the focus
menu exists to drop. So a name whose parts include `goal`, `mcp`, `resource`, `memory`, `plugin`,
`connector`, `todo`, `browser` or `notification` is not about the workspace, whatever verb it opens
with.

And `apply_patch` matches the file shape and must STILL be dropped: it is the lowering target, never
something the coder is asked to write.
"""

import unittest

from cria import shelltool
from cria.toolmenu import focus_tools

GEMINI = ["write_file", "read_file", "replace", "list_directory", "glob", "search_file_content",
          "google_web_search", "run_shell_command", "save_memory"]
CLINE = ["write_to_file", "replace_in_file", "read_file", "list_files", "search_files",
         "list_code_definition_names", "browser_action", "execute_command",
         "ask_followup_question"]
CODEX = ["write_file", "edit_file", "read_file", "list_dir", "view_image", "web_search",
         "web_fetch", "update_plan", "write_stdin", "exec_command", "apply_patch",
         "create_goal", "list_mcp_resources", "request_user_input"]


def _kept(names):
    body = {"tools": [{"type": "function", "function": {"name": n}} for n in names]}
    focus_tools(body)
    return {t["function"]["name"] for t in body["tools"]}


class AFileToolSurvivesWhateverItsHarnessCallsItTests(unittest.TestCase):
    def test_gemini_keeps_every_file_operation(self):
        kept = _kept(GEMINI)
        for n in ("write_file", "read_file", "replace", "list_directory", "glob",
                  "search_file_content"):
            with self.subTest(tool=n):
                self.assertIn(n, kept)

    def test_cline_keeps_every_file_operation(self):
        kept = _kept(CLINE)
        for n in ("write_to_file", "replace_in_file", "read_file", "list_files", "search_files",
                  "list_code_definition_names"):
            with self.subTest(tool=n):
                self.assertIn(n, kept)

    def test_the_shell_still_survives_on_both(self):
        self.assertIn("run_shell_command", _kept(GEMINI))
        self.assertIn("execute_command", _kept(CLINE))


class TheFirehoseIsStillDroppedTests(unittest.TestCase):
    def test_a_verb_on_something_that_is_not_the_workspace_is_not_a_file_tool(self):
        for n in ("create_goal", "get_goal", "update_goal", "list_mcp_resources",
                  "read_mcp_resource", "list_mcp_resource_templates", "save_memory",
                  "browser_action", "request_user_input"):
            with self.subTest(tool=n):
                self.assertFalse(shelltool.is_file_tool_name(n))

    def test_codex_menu_is_curated_exactly_as_before(self):
        kept = _kept(CODEX)
        self.assertNotIn("create_goal", kept)
        self.assertNotIn("list_mcp_resources", kept)
        self.assertNotIn("request_user_input", kept)

    def test_apply_patch_is_still_withheld(self):
        """It matches the file shape — a patch verb on the workspace — and is the LOWERING TARGET,
        never something the coder is asked to write."""
        self.assertTrue(shelltool.is_file_tool_name("apply_patch"))
        self.assertNotIn("apply_patch", _kept(CODEX))


if __name__ == "__main__":
    unittest.main()
