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

    def test_read_allows_external_read_with_local_redirect(self):
        # L12: an external READ piped to a LOCAL write (`grep /etc/hosts > local.txt`) must PASS under
        # `read` — the old whole-command write-verb scan saw the `>` and false-refused it as "Writing"
        # the external file, which it never touched. Only the external token being a write TARGET refuses.
        self.assertIsNone(dirguard.command_refusal("grep pat /etc/hosts > local_results.txt", "read", WS))
        self.assertTrue(dirguard.command_refusal("grep pat local.txt > /etc/config", "read", WS))  # external WRITE refused

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

    def test_grep_pattern_with_a_slash_is_not_a_path(self):
        # A rooted path INSIDE a quoted grep/sed PATTERN is the SEARCH TERM, not a file — the guard must
        # not refuse it. Observed live: the coder ran `grep -n "GET /handles" ./tmp/read-only/spec.json`
        # (exactly what cria's spill outline told it to do) and the guard refused it, citing "/handles" —
        # a path it never touched — trapping the coder on the research step.
        for cmd in ('grep -n "GET /handles" ./tmp/read-only/api.handle.me_openapi.json',
                    "grep -n 'GET /handles' ./tmp/read-only/spec.json",
                    'grep -rn "/handles/{handle}" .',
                    'sed -n "s#/api/v1/resolve#X#p" ./local.txt'):
            for level in ("none", "read"):
                self.assertIsNone(dirguard.command_refusal(cmd, level, WS), (cmd, level))

    def test_external_file_still_caught_even_with_a_slash_pattern(self):
        # the quoted pattern is skipped, but a genuinely external FILE argument in the same command is NOT —
        # the fix narrows false positives, it doesn't blind the guard to real external access
        self.assertTrue(dirguard.command_refusal('grep "a/b/c" /etc/passwd', "none", WS))          # external read
        self.assertTrue(dirguard.command_refusal('grep "GET /x" /home/jesse/other/f > /etc/out', "none", WS))  # ext write

    def test_a_quoted_path_that_opens_the_quote_is_still_a_path(self):
        # a path the coder quoted because it has spaces is a REAL path (the quote opens with it) — caught
        self.assertTrue(dirguard.command_refusal('cat "/home/jesse/other/my secret"', "none", WS))

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


class GlobalInstallTests(unittest.TestCase):
    """An install writes OUTSIDE the workspace while naming no external path, so the path scan
    cannot see it. Measured 2026-08-01: a run's `pip install -e .` left an editable-install .pth in
    the user's real site-packages pointing at that run's /tmp workspace; two days later it still
    shadowed `import handle_resolver` for every Python process on the box."""

    WS = "/tmp/suite-ws"

    def refuse(self, cmd, level="none"):
        return dirguard.command_refusal(cmd, level, self.WS)

    def test_pip_install_is_refused_though_it_names_no_external_path(self):
        for cmd in ("pip install requests",
                    "pip3 install -e .",
                    "python3 -m pip install -e .",
                    "python -m pip install --upgrade build setuptools"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.refuse(cmd), cmd)

    def test_break_system_packages_is_refused(self):
        # The exact escape cria's own PEP-668 remedy used to recommend.
        self.assertIsNotNone(self.refuse("pip install --break-system-packages requests"))

    def test_other_shared_scope_managers(self):
        for cmd in ("npm install -g typescript", "yarn add --global foo",
                    "gem install rspec", "cargo install ripgrep",
                    "go install golang.org/x/tools/cmd/goimports@latest",
                    "composer global require phpunit/phpunit",
                    "apt-get install -y jq", "brew install jq"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.refuse(cmd), cmd)

    def test_project_local_installs_are_ordinary_work_and_pass(self):
        # These managers install INTO the project by default. Refusing them would block the
        # first fix — the class of intervention the doctrine forbids.
        for cmd in ("npm install", "npm install express", "npm ci",
                    "pnpm install", "yarn add left-pad",
                    "composer require guzzlehttp/guzzle", "bundle install",
                    "cargo add serde", "cargo build", "go get ./...", "go mod tidy",
                    "mvn -q test", "python3 -m pytest"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.refuse(cmd), cmd)

    def test_a_venv_inside_the_workspace_is_allowed(self):
        for cmd in ("python3 -m venv .venv && ./.venv/bin/pip install requests",
                    ".venv/bin/pip install requests",
                    "./venv/bin/pip install -e .",
                    "source .venv/bin/activate && pip install requests",
                    ". venv/bin/activate && pip install -r requirements.txt"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.refuse(cmd), cmd)

    def test_an_explicit_local_destination_is_allowed(self):
        for cmd in ("pip install --target ./deps requests",
                    "pip install --prefix=./out requests"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.refuse(cmd), cmd)

    def test_read_level_still_refuses_because_an_install_is_a_write(self):
        self.assertIsNotNone(self.refuse("pip install requests", level="read"))

    def test_write_level_never_refuses(self):
        self.assertIsNone(self.refuse("pip install requests", level="write"))

    def test_refusal_names_the_workspace_and_the_venv_route(self):
        msg = self.refuse("pip install requests")
        self.assertIn(self.WS, msg)
        self.assertIn(".venv", msg)

    def test_the_word_install_in_prose_or_another_verb_is_not_an_install(self):
        for cmd in ("grep -rn 'pip install' README.md",
                    "echo see README for install steps",
                    "python3 -m pip --version",
                    "pip list"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.refuse(cmd), cmd)


class CaseTypoNoteTests(unittest.TestCase):
    """A refusal for a LETTER-CASE typo of the workspace itself must say so.

    Walked on ada-handles_gemma4_codex_poff_1785869053: the coder wrote its own workspace with one
    capital letter (…-8Ibs7re8 for …-8ibs7re8) 106 times; the refusal printed both strings without
    naming the difference, and the model spiralled on an invented "absolute paths are forbidden"
    doctrine for ~300 calls."""

    def test_case_typo_of_workspace_is_called_out(self):
        r = dirguard.path_refusal("/home/jesse/src/Proj/x.py", True, "none", WS)
        self.assertIn("ONLY BY A TYPO", r)

    def test_case_typo_of_the_root_itself(self):
        r = dirguard.path_refusal("/home/jesse/SRC/proj", True, "none", WS)
        self.assertIn("ONLY BY A TYPO", r)


    def test_underscore_for_dash_typo_is_called_out(self):
        # ada-handles_mellum2_codex_poff_1785880114: suite-ada_handles for suite-ada-handles —
        # the same one-glyph loop the case fix missed.
        r = dirguard.path_refusal("/home/jesse/src_proj/x.py", True, "none", "/home/jesse/src-proj")
        self.assertIn("ONLY BY A TYPO", r)

    def test_dash_for_underscore_typo_is_called_out(self):
        r = dirguard.path_refusal("/home/jesse/src-proj/x.py", True, "none", "/home/jesse/src_proj")
        self.assertIn("ONLY BY A TYPO", r)

    def test_genuinely_external_path_gets_no_note(self):
        r = dirguard.path_refusal("/etc/passwd", True, "none", WS)
        self.assertNotIn("BY A TYPO", r)
        self.assertNotIn("{{CASENOTE}}", r)   # the token is always filled, never leaked

    def test_no_workspace_no_note(self):
        r = dirguard.path_refusal("/etc/passwd", True, "none", None)
        self.assertNotIn("BY A TYPO", r or "")
        self.assertNotIn("{{CASENOTE}}", r or "")


if __name__ == "__main__":
    unittest.main()
