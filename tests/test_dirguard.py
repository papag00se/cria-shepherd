import unittest

from cria import dirguard
from cria.writeproxy import translate_outbound

WS = "/home/jesse/src/proj"


class IsExternalTests(unittest.TestCase):
    def test_internal_paths(self):
        for p in (".venv", "src/a.py", "./x", "../x/../proj/y", WS, WS + "/deep/f"):
            self.assertFalse(dirguard.is_external(p, WS), p)

    def test_external_paths(self):
        for p in ("/etc/passwd", "~/.ssh/id", "../sibling/x", "/home/jesse/other"):
            self.assertTrue(dirguard.is_external(p, WS), p)

    def test_dotdot_cannot_escape(self):
        self.assertTrue(dirguard.is_external("../../../etc/x", WS))   # normpath resolves the escape
        self.assertFalse(dirguard.is_external("sub/../a.py", WS))     # stays inside

    def test_no_workspace_treats_rooted_as_external(self):
        self.assertTrue(dirguard.is_external("/etc/x", None))
        self.assertTrue(dirguard.is_external("~/x", None))
        self.assertFalse(dirguard.is_external("rel/x", None))


class PathRefusalTests(unittest.TestCase):
    """Synthetic file tools — explicit path + operation, so enforcement is exact."""

    def test_none_blocks_all_external(self):
        self.assertTrue(dirguard.path_refusal("/etc/x", True, "none", WS))
        self.assertTrue(dirguard.path_refusal("/etc/x", False, "none", WS))

    def test_read_allows_external_read_blocks_external_write(self):
        self.assertIsNone(dirguard.path_refusal("/etc/x", False, "read", WS))   # external read OK
        self.assertTrue(dirguard.path_refusal("/etc/x", True, "read", WS))      # external write refused

    def test_write_unrestricted(self):
        self.assertIsNone(dirguard.path_refusal("/etc/x", True, "write", WS))

    def test_internal_always_allowed(self):
        for level in ("none", "read", "write"):
            self.assertIsNone(dirguard.path_refusal(".venv/x", True, level, WS))


class CommandRefusalTests(unittest.TestCase):
    """Raw shell — heuristic path/verb scan (best-effort backstop for a weak model)."""

    def test_none_refuses_any_external_path(self):
        self.assertTrue(dirguard.command_refusal("cat /etc/passwd", "none", WS))
        self.assertTrue(dirguard.command_refusal("echo hi > /tmp/x", "none", WS))

    def test_read_allows_external_read_blocks_external_write(self):
        self.assertIsNone(dirguard.command_refusal("cat /etc/passwd", "read", WS))       # read OK
        self.assertTrue(dirguard.command_refusal("rm -rf /home/jesse/other", "read", WS))  # write refused

    def test_workspace_and_relative_paths_pass(self):
        # the venv command: cd into the workspace + relative .venv + a flag (no EXPLICIT external path)
        cmd = f"cd {WS} && rm -rf .venv && python3 -m venv --system-site-packages .venv && .venv/bin/pip install -e ."
        self.assertIsNone(dirguard.command_refusal(cmd, "none", WS))

    def test_fd_redirect_is_not_a_write_path(self):
        self.assertIsNone(dirguard.command_refusal("pytest -q 2>&1 | grep -v Error", "none", WS))

    def test_write_level_never_refuses(self):
        self.assertIsNone(dirguard.command_refusal("rm -rf /etc/x", "write", WS))


class TranslateOutboundEnforcementTests(unittest.TestCase):
    """The guard fires at the writeproxy chokepoint: a violating call is replaced with a refusal
    the model reads; an allowed one is lowered/passed as normal."""

    SHELL = {"name": "shell", "parameters": {}}

    def _completion(self, name, args):
        return {"choices": [{"message": {"tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": name, "arguments": args}}]}}]}

    def _lowered_cmd(self, comp):
        import json
        tc = comp["choices"][0]["message"]["tool_calls"][0]
        cmd = json.loads(tc["function"]["arguments"]).get("command", "")
        return " ".join(cmd) if isinstance(cmd, list) else str(cmd)

    def test_external_write_file_refused_under_none(self):
        comp = self._completion("write_file", '{"path": "/etc/evil", "content": "x"}')
        translate_outbound(comp, self.SHELL, injected={"write_file"}, workspace_root=WS,
                           external_dir_permission="none")
        self.assertIn("outside the working directory", self._lowered_cmd(comp))  # a printf refusal

    def test_internal_write_file_lowered_normally(self):
        comp = self._completion("write_file", '{"path": "app.py", "content": "x=1"}')
        translate_outbound(comp, self.SHELL, injected={"write_file"}, workspace_root=WS,
                           external_dir_permission="none")
        self.assertNotIn("outside the working directory", self._lowered_cmd(comp))  # a real write

    def test_raw_shell_external_refused_under_none(self):
        comp = self._completion("shell", '{"command": ["bash", "-lc", "cat /etc/passwd"]}')
        translate_outbound(comp, self.SHELL, injected=set(), workspace_root=WS,
                           external_dir_permission="none")
        self.assertIn("outside the working directory", self._lowered_cmd(comp))

    def test_default_write_level_unrestricted(self):
        comp = self._completion("write_file", '{"path": "/etc/evil", "content": "x"}')
        translate_outbound(comp, self.SHELL, injected={"write_file"}, workspace_root=WS)  # default write
        self.assertNotIn("outside the working directory", self._lowered_cmd(comp))


if __name__ == "__main__":
    unittest.main()
