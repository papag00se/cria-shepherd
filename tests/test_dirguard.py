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

    def test_urls_are_not_treated_as_external_paths(self):
        # the guard governs the FILESYSTEM, never the network — a curl/wget to a URL must pass
        for cmd in ("curl -s https://api.handle.me/handles/goose",
                    "wget http://example.com/x",
                    "curl https://x.com/a | jq .",
                    "python3 -c 'import requests; requests.get(\"https://x/y\")'"):
            self.assertIsNone(dirguard.command_refusal(cmd, "none", WS), cmd)

    def test_url_path_fragment_built_across_a_variable_is_not_a_file_path(self):
        # THE recurring footgun: the URL path is concatenated to a variable, so the regex sees a bare
        # `/handles/goose` after the `}` and read it as an external FILE path — refusing an HTTP request.
        for cmd in (
            "python3 -c \"import requests; BASE='https://api.handle.me'; requests.get(f'{BASE}/handles/goose')\"",
            "python3 -c \"import urllib.request as u; u.urlopen(f'https://api.handle.me/holders/{addr}')\"",
            "cd " + WS + " && curl -s \"https://api.handle.me/handles/${h}\""):
            self.assertIsNone(dirguard.command_refusal(cmd, "none", WS), cmd)
        # ...but an explicit external write TARGET in the same network command is STILL caught
        self.assertTrue(dirguard.command_refusal("curl https://x/a > /tmp/out.json", "none", WS))
        self.assertTrue(dirguard.command_refusal("curl https://x/a -o /home/jesse/other/x", "none", WS))
        # and a non-network external read is unaffected
        self.assertTrue(dirguard.command_refusal("cat /home/jesse/other/secret", "none", WS))

    def test_a_download_TARGET_outside_the_workspace_is_still_caught(self):
        # the URL is fine, but writing the download to an external path is a real external write
        self.assertTrue(dirguard.command_refusal("curl https://x.com/a -o /etc/evil", "none", WS))

    def test_device_files_and_plumbing_are_exempt(self):
        # /dev/null redirection & friends are I/O plumbing, NOT external data — must never be refused
        for cmd in ("grep -n x resolve.py 2>/dev/null",
                    "echo hi > /dev/stderr",
                    "python3 test.py > /dev/null 2>&1",
                    "cat /proc/cpuinfo",
                    "curl -s https://api.handle.me/x 2>/dev/null"):
            self.assertIsNone(dirguard.command_refusal(cmd, "none", WS), cmd)
        self.assertIsNone(dirguard.path_refusal("/dev/null", True, "none", WS))     # synthetic path too
        self.assertTrue(dirguard.path_refusal("/etc/passwd", False, "none", WS))    # real external read still blocked


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
