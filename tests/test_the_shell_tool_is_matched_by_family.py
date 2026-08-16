"""A closed list of six names was doing the job of "match tools by family".

The shell is the ONE primitive cria assumes every harness has. It is the writeproxy's lowering
target, the plan loop's precondition, and the tool the coder falls back to for everything cria does
not model. Recognising it went through:

    SHELL_TOOL_NAMES = {"shell", "bash", "exec_command", "local_shell",
                        "run_terminal_cmd", "shell_command"}

which is a literal-name rule wearing the word "family" (#18 forbids exactly this). Gemini CLI
advertises `run_shell_command`; Cline advertises `execute_command`. On either one cria answered
"this harness has no shell", and three things follow from that answer:

    find_shell_tool → None      the plan loop declines every turn (loop.no_shell_tool)
    the writeproxy              has no lowering target, so write_file cannot be lowered
    focus_tools                 DELETES the tool — a tool in none of its three sets is dropped

The last is the worst: cria would take the coder's shell away for having an unfamiliar name.

THE RULE IS NOW THE SHAPE OF THE NAME. Split on `_`, `-`, `.` and space; any part beginning
`shell`, `bash`, `exec` or `terminal` is the family. Checked against every tool name in the
captures — read_file, list_dir, write_file, edit_file, view_image, web_search, web_fetch,
update_plan, write_stdin, exec_command, task_complete, verdict — only exec_command matches. The old
literal set is kept as a fast path, not as the rule.

`container.exec` no longer needs its hand-added special case in loop: the split reads `exec`.
"""

import unittest

from cria import shelltool, toolmenu


def tool(name, props=None):
    return {"type": "function",
            "function": {"name": name,
                         "parameters": {"type": "object",
                                        "properties": props or {"command": {"type": "string"}}}}}


class TheFamilyIsRecognisedByShapeTests(unittest.TestCase):
    HARNESS_SHELLS = ["shell", "bash", "Bash", "exec_command", "local_shell", "run_terminal_cmd",
                      "shell_command", "run_shell_command", "execute_command", "container.exec"]

    def test_every_harness_shell_is_the_family(self):
        for n in self.HARNESS_SHELLS:
            with self.subTest(name=n):
                self.assertTrue(shelltool.is_shell_tool_name(n))

    def test_the_two_that_used_to_be_missed(self):
        """Gemini CLI and Cline. Neither name had ever been met, which was the whole problem."""
        self.assertTrue(shelltool.is_shell_tool_name("run_shell_command"))
        self.assertTrue(shelltool.is_shell_tool_name("execute_command"))

    def test_it_finds_them_in_a_menu(self):
        for n in ("run_shell_command", "execute_command"):
            with self.subTest(name=n):
                found = shelltool.find_shell_tool([tool("read_file"), tool(n)])
                self.assertIsNotNone(found)
                self.assertEqual(found["name"], n)

    def test_container_exec_needs_no_special_case(self):
        import inspect

        from cria import loop
        self.assertNotIn('| {"container.exec"}', inspect.getsource(loop))


class NothingElseIsSweptInTests(unittest.TestCase):
    """Every tool name that appears in cria's captures, plus the ones it drops on purpose."""

    NOT_SHELLS = ["read_file", "list_dir", "write_file", "edit_file", "view_image", "web_search",
                  "web_fetch", "update_plan", "write_stdin", "task_complete", "verdict",
                  "apply_patch", "create_goal", "request_user_input", "tool_search",
                  "list_mcp_resources", "str_replace_editor", "request_permissions"]

    def test_none_of_them_are_the_shell(self):
        for n in self.NOT_SHELLS:
            with self.subTest(name=n):
                self.assertFalse(shelltool.is_shell_tool_name(n))

    def test_empty_and_none(self):
        self.assertFalse(shelltool.is_shell_tool_name(""))
        self.assertFalse(shelltool.is_shell_tool_name(None))

    def test_a_partial_word_does_not_match(self):
        """`exec` must begin a part, not appear anywhere in one: a hypothetical `codexec_helper`
        is not a shell."""
        self.assertFalse(shelltool.is_shell_tool_name("codexec_helper"))


class TheMenuKeepsItTests(unittest.TestCase):
    def test_an_unfamiliar_shell_survives_the_focus(self):
        """THE REGRESSION. focus_tools drops any tool in none of its three sets, so an unrecognised
        shell was deleted from the coder's menu."""
        for n in ("run_shell_command", "execute_command"):
            with self.subTest(name=n):
                body = {"tools": [tool("read_file"), tool(n), tool("create_goal")]}
                toolmenu.focus_tools(body)
                names = [t["function"]["name"] for t in body["tools"]]
                self.assertIn(n, names)
                self.assertNotIn("create_goal", names)

    def test_it_is_still_ordered_last(self):
        """The shell trails the purpose-built tools — the schema order is a preference signal, and
        an unfamiliar shell must get the same treatment as a familiar one."""
        body = {"tools": [tool("run_shell_command"), tool("write_file"), tool("read_file")]}
        toolmenu.focus_tools(body)
        self.assertEqual([t["function"]["name"] for t in body["tools"]][-1], "run_shell_command")

    def test_the_known_shell_is_unchanged(self):
        body = {"tools": [tool("exec_command"), tool("write_file")]}
        toolmenu.focus_tools(body)
        self.assertEqual([t["function"]["name"] for t in body["tools"]],
                         ["write_file", "exec_command"])


class OneOwnerTests(unittest.TestCase):
    def test_no_module_keeps_its_own_name_set(self):
        import inspect

        from cria import loop, toolmenu as tm, writeproxy
        for mod in (loop, tm, writeproxy):
            with self.subTest(module=mod.__name__):
                self.assertNotIn("in SHELL_TOOL_NAMES", inspect.getsource(mod))

    def test_the_literal_set_is_only_a_fast_path(self):
        """Kept because the names are cheap and certain — but everything in it must also pass the
        shape rule, or the two would be able to disagree."""
        for n in shelltool.SHELL_TOOL_NAMES:
            with self.subTest(name=n):
                self.assertTrue(shelltool.is_shell_tool_name(n))


if __name__ == "__main__":
    unittest.main()
