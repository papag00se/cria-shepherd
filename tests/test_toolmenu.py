import unittest

from cria.toolmenu import add_cheatsheet, cheatsheet

_SHELL = {"type": "function", "function": {"name": "shell"}}
_WRITE = {"type": "function", "function": {"name": "write_file"}}
_PATCH = {"type": "function", "function": {"name": "apply_patch"}}


class CheatsheetTests(unittest.TestCase):
    def test_describes_present_tools(self):
        note = cheatsheet([_WRITE, _SHELL, _PATCH])
        self.assertIn("write_file(path, content)", note)
        self.assertIn("shell(command)", note)
        self.assertIn("apply_patch", note)

    def test_none_without_tools(self):
        self.assertIsNone(cheatsheet([]))
        self.assertIsNone(cheatsheet(None))

    def test_shell_read_hint_when_no_read_file(self):
        self.assertIn("cat <path>", cheatsheet([_SHELL]))


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
        self.assertIn("shell(command)", body["messages"][0]["content"])

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
        self.assertTrue(any("shell(command)" in p.get("text", "") for p in parts))

    def test_noop_without_tools(self):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        add_cheatsheet(body)
        self.assertEqual(len(body["messages"]), 1)


if __name__ == "__main__":
    unittest.main()
