import unittest

from cria import planner_tools as pt


class SearchGate400Tests(unittest.TestCase):
    """The hard nudge: a repeated web_search is refused as an HTTP 400 so a small model
    can't burn the gather re-searching the same terms."""

    def test_first_proceeds_repeat_is_blocked_as_400(self):
        recent = []
        self.assertIsNone(pt.gate_search(recent, "api.handle.me get_handle endpoint"))  # runs
        blocked = pt.gate_search(recent, "get_handle endpoint on api.handle.me")        # reorder = same
        self.assertIsNotNone(blocked)
        self.assertIn("HTTP 400", blocked)
        self.assertIn("searched this before", blocked)

    def test_domain_repeat_steers_to_fetch_it_directly(self):
        recent = []
        pt.gate_search(recent, "api.handle.me handles response schema")
        blocked = pt.gate_search(recent, "handles response schema api.handle.me")
        self.assertIn("web_fetch https://api.handle.me", blocked)  # stop searching, go fetch

    def test_genuine_new_direction_proceeds(self):
        recent = []
        pt.gate_search(recent, "api.handle.me get_handle endpoint")
        self.assertIsNone(pt.gate_search(recent, "cardano staking rewards calculation"))

    def test_refinement_is_allowed(self):
        recent = []
        pt.gate_search(recent, "rust async trait")
        # longer, keeps the whole prior + adds specificity → a narrowing, not a re-hunt
        self.assertIsNone(pt.gate_search(recent, "rust async trait object safety dyn"))

    def test_anchor_dominated_reword_is_caught(self):
        recent = []
        pt.gate_search(recent, "api.handle.me handles/goose JSON response example")
        self.assertIsNotNone(pt.gate_search(recent, "api.handle.me handles/goose response"))


class ReadOnlyGuardTests(unittest.TestCase):
    def test_reads_allowed(self):
        for cmd in ("ls -la", "cat handler.py", "grep -r foo .", "git status", "git log --oneline",
                    "curl https://api.handle.me/v1/handles/goose", "find . -name '*.py'", "head -20 x.py",
                    "python3 -c \"import json; print(1)\"", "jq '.paths' /tmp/api.json"):
            self.assertTrue(pt.is_gather_safe_command(cmd, "/tmp/s")[0], cmd)

    def test_workspace_writes_refused(self):
        # relative or workspace-absolute writes still corrupt the user's code → refused
        for cmd in ("echo x > f", "sed -i s/a/b/ f", "git commit -m x", "curl -o out.json https://x",
                    "python setup.py build" if False else "mkdir d", "cat a | tee b", "touch handler.py",
                    "mv a.py b.py", "cp x /home/jesse/src/proj/y"):
            self.assertFalse(pt.is_gather_safe_command(cmd, "/tmp/s")[0], cmd)

    def test_scratchpad_writes_allowed(self):
        # the whole point: persist + process fetched data in /tmp or the scratch dir
        for cmd in ("curl https://api.handle.me/openapi.json > /tmp/api.json",
                    "echo '{}' > /tmp/x.json && grep foo /tmp/x.json",
                    "python3 -c \"import json,sys; json.dump({}, open('/tmp/o.json','w'))\"",
                    "cat /tmp/api.json | jq '.paths'", "curl -o /tmp/api.json https://x",
                    "mkdir -p /tmp/scr/sub", "tee /tmp/log.txt"):
            self.assertTrue(pt.is_gather_safe_command(cmd, "/tmp/s")[0], cmd)

    def test_scratch_dir_writes_allowed(self):
        s = "/tmp/cria-gather-abc"
        self.assertTrue(pt.is_gather_safe_command(f"echo hi > {s}/note.txt", s)[0])

    def test_workspace_under_tmp_is_still_off_limits(self):
        # the invariant is "scratchpad, never the workspace" — a workspace that lives under /tmp
        # (as in tests) must NOT be writable just because it's /tmp-rooted
        ws = "/tmp/ws-xyz"
        self.assertFalse(pt.is_gather_safe_command(f"echo pwned > {ws}/handler.py", "/tmp/s", ws)[0])
        self.assertFalse(pt.is_gather_safe_command(f"rm {ws}/f.py", "/tmp/s", ws)[0])
        # but a sibling /tmp path (not the workspace) is fine
        self.assertTrue(pt.is_gather_safe_command("echo x > /tmp/other.json", "/tmp/s", ws)[0])

    def test_catastrophic_refused_regardless_of_target(self):
        for cmd in ("rm -rf /", "rm -rf ~", "rm -rf .", "find . -delete", "find /tmp -delete",
                    "dd if=/dev/zero of=/dev/sda", ":(){ :|:& };:", "shred -u /tmp/x"):
            self.assertFalse(pt.is_gather_safe_command(cmd, "/tmp/s")[0], cmd)


class DomainDetectTests(unittest.TestCase):
    def test_domains_not_filenames(self):
        self.assertEqual(pt.first_domain_in("api.handle.me handles endpoint"), "api.handle.me")
        self.assertEqual(pt.first_domain_in("docs on example.com"), "example.com")
        self.assertIsNone(pt.first_domain_in("read handler.py and config.json"))
        self.assertIsNone(pt.first_domain_in("cardano staking rewards"))

    def test_code_identifiers_are_not_domains(self):
        # M6: a dotted CODE identifier is NOT an API domain — the old shape check accepted ANY alphabetic
        # final label, so urllib.request / os.path passed and burned the live search-escape fetching
        # https://urllib.request/openapi.json. The TLD allowlist rejects a code attr like `.request`.
        from cria.searchloop import _looks_like_domain, task_api_domain
        for tok in ("urllib.request", "requests.get", "os.path", "asyncio.run", "self.config"):
            self.assertFalse(_looks_like_domain(tok), tok)
        for tok in ("api.handle.me", "example.com", "api.stripe.com", "example.co.uk"):
            self.assertTrue(_looks_like_domain(tok), tok)
        self.assertFalse(task_api_domain("use urllib.request to call the Stripe API"))  # no real domain


class SearchFormatTests(unittest.TestCase):
    def test_format_results(self):
        out = pt.format_results("q", [{"title": "T1", "url": "https://e.com/1", "description": "D1."}])
        self.assertIn("Search results for: q", out)
        self.assertIn("T1", out)
        self.assertIn("https://e.com/1", out)

    def test_no_key_web_search_is_graceful(self):
        # gate proceeds (records), then the missing key is reported — no network, no crash
        msg = pt.execute_tool("web_search", {"query": "x y z"}, ".", "", [], _Rlog())
        self.assertIn("no search API key", msg)


class _Rlog:
    def emit(self, *a, **k):
        pass


if __name__ == "__main__":
    unittest.main()


class WebFetchUserAgentTests(unittest.TestCase):
    """Invariant: the planner's web_fetch actually ISSUES a request with a defined browser
    User-Agent. Regression guard for the `_USER_AGENT` NameError (undefined symbol) that made
    every gather-loop fetch fail — swallowed by the broad `except`, so the reasoner planned
    blind against docs it believed it had read."""

    def test_web_fetch_sends_the_canonical_user_agent_and_does_not_nameerror(self):
        captured = {}

        class _Resp:
            status = 200

            def read(self, n=-1):
                return b'{"ok": true}'

            def geturl(self):
                return "https://api.handle.me/openapi.json"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            captured["ua"] = next((v for k, v in req.header_items() if k.lower() == "user-agent"), None)
            return _Resp()

        orig = pt.urllib.request.urlopen
        pt.urllib.request.urlopen = fake_urlopen
        try:
            out = pt._web_fetch({"url": "https://api.handle.me/openapi.json"})
        finally:
            pt.urllib.request.urlopen = orig

        self.assertNotIn("is not defined", out)        # the NameError no longer leaks into the result
        self.assertIn("HTTP 200", out)                 # the real response is surfaced
        self.assertEqual(captured["ua"], pt.brave.USER_AGENT)  # a defined, canonical browser UA was sent


class FreshWorkspaceTests(unittest.TestCase):
    """A workspace dir that doesn't exist (a fresh build) must not make exec_command die with
    'failed to launch' — it falls back to the scratchpad and tells the planner it's fresh."""

    def test_missing_workspace_falls_back_and_notes_fresh(self):
        import tempfile
        scratch = tempfile.mkdtemp()
        out = pt.execute_tool("exec_command", {"cmd": "echo hi"}, "/no/such/workspace", "", [],
                              _Rlog(), scratch=scratch)
        self.assertNotIn("failed to launch", out)
        self.assertIn("does not exist yet", out)
        self.assertIn("FRESH build", out)

    def test_existing_workspace_runs_there(self):
        import tempfile, os
        ws = tempfile.mkdtemp()
        open(os.path.join(ws, "marker.txt"), "w").write("x")
        out = pt.execute_tool("exec_command", {"cmd": "ls"}, ws, "", [], _Rlog())
        self.assertIn("marker.txt", out)
        self.assertNotIn("does not exist yet", out)


class FullContentTests(unittest.TestCase):
    """Model-read gather content is returned in FULL (no blind byte/char clip) — the section the
    planner needs may be past any fixed slice, and the context floor bounds the window downstream."""

    def test_read_file_returns_full_content_past_old_clip(self):
        import tempfile, os
        d = tempfile.mkdtemp()
        open(os.path.join(d, "big.py"), "w").write("A" * 20000 + "NEEDLE_AT_END")
        out = pt.execute_tool("read_file", {"path": "big.py"}, d, "", [], _Rlog())
        self.assertIn("NEEDLE_AT_END", out)          # the tail survives (was cut at 8000)
        self.assertNotIn("truncated at", out)         # no clip marker
        self.assertGreaterEqual(len(out), 20000)

    def test_exec_command_returns_full_output_past_old_clip(self):
        out = pt.execute_tool("exec_command",
                              {"cmd": "python3 -c \"print('X'*20000 + 'TAILMATCH')\""}, ".", "", [], _Rlog())
        self.assertIn("TAILMATCH", out)               # the last line survives (was cut at 8000)
        self.assertNotIn("truncated at", out)

    def test_web_fetch_returns_full_body_past_old_clip(self):
        big = ("B" * 20000) + "ENDPOINT_SIGNATURE"

        class _Resp:
            status = 200

            def read(self, n=-1):
                return big.encode()

            def geturl(self):
                return "https://x/api"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        orig = pt.urllib.request.urlopen
        pt.urllib.request.urlopen = lambda req, timeout=None: _Resp()
        try:
            out = pt._web_fetch({"url": "https://x/api"})
        finally:
            pt.urllib.request.urlopen = orig
        self.assertIn("ENDPOINT_SIGNATURE", out)      # the signature past 6000 survives
        self.assertNotIn("truncated at", out)


class SearchCountTests(unittest.TestCase):
    """web_search asks Brave for its full result set (clamped to 20 in the API layer) and discloses
    how many landed, so the planner isn't blind to an arbitrary 5-result slice."""

    def test_requests_full_count_and_discloses_it(self):
        captured = {}

        def fake_brave(key, query, count=None):
            captured["count"] = count
            return [{"title": f"T{i}", "url": f"https://e/{i}", "description": "d"} for i in range(20)]

        orig = pt.brave_search
        pt.brave_search = fake_brave
        try:
            out = pt.execute_tool("web_search", {"query": "some unique query terms"}, ".", "KEY", [], _Rlog())
        finally:
            pt.brave_search = orig
        self.assertEqual(captured["count"], 20)       # asked for the full set, not 5
        self.assertIn("(20 results)", out)            # and disclosed the count
