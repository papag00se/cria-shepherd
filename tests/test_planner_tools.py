import contextlib
import json
import pathlib
import tempfile
import unittest
from unittest import mock

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
        # M6: a dotted CODE identifier is NOT a domain — the old shape check accepted ANY alphabetic final
        # label, so urllib.request / os.path passed and the repeat-search steer told the coder to fetch
        # `https://urllib.request`. The TLD allowlist rejects a code attr like `.request`.
        from cria.searchloop import _looks_like_domain
        for tok in ("urllib.request", "requests.get", "os.path", "asyncio.run", "self.config"):
            self.assertFalse(_looks_like_domain(tok), tok)
        for tok in ("api.handle.me", "example.com", "api.stripe.com", "example.co.uk"):
            self.assertTrue(_looks_like_domain(tok), tok)
        self.assertIsNone(pt.first_domain_in("use urllib.request to call the API"))  # no real domain


class SearchFormatTests(unittest.TestCase):
    def test_format_results(self):
        out = pt.format_results("q", [{"title": "T1", "url": "https://e.com/1", "description": "D1."}])
        self.assertIn("Search results for: q", out)
        self.assertIn("T1", out)
        self.assertIn("https://e.com/1", out)

    def test_no_key_web_search_is_graceful(self):
        # gate proceeds (records), then the missing key is reported — no network, no crash
        msg = pt.execute_tool("web_search", {"query": "x y z"}, ".", "", [], _Rlog()).text
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
    blind against docs it believed it had read. The seam moved when the planner stopped hand-rolling
    urllib and took the shared fetcher (which also owns the UA), so the patch follows it there —
    the invariant is unchanged: a real request goes out, carrying a real browser UA."""

    def test_web_fetch_sends_the_canonical_user_agent_and_does_not_nameerror(self):
        captured = {}

        class _Resp:
            status = 200

            headers = {"Content-Type": "application/json"}

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

        from cria import webfetch
        orig = webfetch.urllib.request.urlopen
        webfetch.urllib.request.urlopen = fake_urlopen
        try:
            out = pt._web_fetch({"url": "https://api.handle.me/openapi.json"}).text
        finally:
            webfetch.urllib.request.urlopen = orig

        self.assertNotIn("is not defined", out)        # the NameError no longer leaks into the result
        self.assertIn("HTTP 200", out)                 # the real response is surfaced
        from cria import webfetch
        self.assertEqual(captured["ua"], webfetch.USER_AGENT)  # a defined, canonical browser UA was sent


class ToolResultLearnedTests(unittest.TestCase):
    """Each gather tool STATES whether its call returned anything to learn from. The planner's
    research phase reads that flag; it must never have to infer it by reading the text back."""

    def test_a_command_that_prints_nothing_taught_nothing(self):
        # MEASURED (run 0727-090143): an empty workspace answered `ls -la` and `find` with nothing,
        # two calls counted as "it researched", and the planner drafted from memory and invented
        # `/resolve?handle={handle}` — which the coder then built and 404'd.
        import tempfile
        ws = tempfile.mkdtemp()
        self.assertFalse(pt.execute_tool("exec_command", {"cmd": "true"}, ws, "", [], _Rlog()).learned)
        self.assertTrue(pt.execute_tool("exec_command", {"cmd": "echo real output"}, ws, "", [],
                                        _Rlog()).learned)

    def test_errors_and_refusals_taught_nothing(self):
        import tempfile
        ws = tempfile.mkdtemp()
        self.assertFalse(pt.execute_tool("read_file", {"path": "nope.txt"}, ws, "", [], _Rlog()).learned)
        self.assertFalse(pt.execute_tool("web_fetch", {"url": ""}, ws, "", [], _Rlog()).learned)
        self.assertFalse(pt.execute_tool("web_search", {"query": "x"}, ws, "", [], _Rlog()).learned)
        self.assertFalse(pt.execute_tool("no_such_tool", {}, ws, "", [], _Rlog()).learned)

    def test_a_file_that_opened_taught_something(self):
        import os, tempfile
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "spec.txt"), "w") as fh:
            fh.write("GET /handles/{handle}\n")
        self.assertTrue(pt.execute_tool("read_file", {"path": "spec.txt"}, d, "", [], _Rlog()).learned)


class FreshWorkspaceTests(unittest.TestCase):
    """A workspace dir that doesn't exist (a fresh build) must not make exec_command die with
    'failed to launch' — it falls back to the scratchpad and tells the planner it's fresh."""

    def test_missing_workspace_falls_back_and_notes_fresh(self):
        import tempfile
        scratch = tempfile.mkdtemp()
        out = pt.execute_tool("exec_command", {"cmd": "echo hi"}, "/no/such/workspace", "", [],
                              _Rlog(), scratch=scratch).text
        self.assertNotIn("failed to launch", out)
        self.assertIn("does not exist yet", out)
        self.assertIn("FRESH build", out)

    def test_existing_workspace_runs_there(self):
        import tempfile, os
        ws = tempfile.mkdtemp()
        open(os.path.join(ws, "marker.txt"), "w").write("x")
        out = pt.execute_tool("exec_command", {"cmd": "ls"}, ws, "", [], _Rlog()).text
        self.assertIn("marker.txt", out)
        self.assertNotIn("does not exist yet", out)


class FullContentTests(unittest.TestCase):
    """Model-read gather content is returned in FULL (no blind byte/char clip) — the section the
    planner needs may be past any fixed slice, and the context floor bounds the window downstream."""

    def test_read_file_returns_full_content_past_old_clip(self):
        import tempfile, os
        d = tempfile.mkdtemp()
        open(os.path.join(d, "big.py"), "w").write("A" * 20000 + "NEEDLE_AT_END")
        out = pt.execute_tool("read_file", {"path": "big.py"}, d, "", [], _Rlog()).text
        self.assertIn("NEEDLE_AT_END", out)          # the tail survives (was cut at 8000)
        self.assertNotIn("truncated at", out)         # no clip marker
        self.assertGreaterEqual(len(out), 20000)

    def test_exec_command_returns_full_output_past_old_clip(self):
        out = pt.execute_tool("exec_command",
                              {"cmd": "python3 -c \"print('X'*20000 + 'TAILMATCH')\""}, ".", "", [], _Rlog()).text
        self.assertIn("TAILMATCH", out)               # the last line survives (was cut at 8000)
        self.assertNotIn("truncated at", out)

    def test_web_fetch_returns_full_body_past_old_clip(self):
        """Under one page, the whole body still comes back inline — the old 6000/8000-char clip cut
        exactly the endpoint signatures the planner was fetching FOR. (One page is now the shared
        inline bound, content_reduce.INLINE_RESULT_MAX_BYTES — the body here sits past the old
        clips but under that bound.)"""
        big = ("B" * 8500) + "ENDPOINT_SIGNATURE"
        with self._urlopen(big):
            out = pt._web_fetch({"url": "https://x/api"}).text
        self.assertIn("ENDPOINT_SIGNATURE", out)      # the signature past 6000 survives
        self.assertNotIn("truncated at", out)

    def test_a_body_past_one_page_survives_in_full_in_the_spill(self):
        """Past one page it moves to a file rather than the context (a message larger than the window
        is unreducible and 400s the server) — but nothing is lost: the tail is in the file, and the
        result says where the file is."""
        import tempfile
        big = ("B" * 20000) + "ENDPOINT_SIGNATURE"
        with tempfile.TemporaryDirectory() as scratch, self._urlopen(big):
            out = pt._web_fetch({"url": "https://x/api"}, {}, scratch=scratch).text
            spilled = [q for q in pathlib.Path(scratch).rglob("*") if q.is_file()]
            self.assertEqual(len(spilled), 1)
            self.assertIn("ENDPOINT_SIGNATURE", spilled[0].read_text())
            self.assertIn(str(spilled[0]), out)
        self.assertNotIn("truncated at", out)

    @contextlib.contextmanager
    def _urlopen(self, body: str):
        class _Resp:
            status = 200
            headers = {"Content-Type": "text/plain"}

            def read(self, n=-1):
                return body.encode()

            def geturl(self):
                return "https://x/api"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        from cria import webfetch
        orig = webfetch.urllib.request.urlopen
        webfetch.urllib.request.urlopen = lambda req, timeout=None: _Resp()
        try:
            yield
        finally:
            webfetch.urllib.request.urlopen = orig


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
            out = pt.execute_tool("web_search", {"query": "some unique query terms"}, ".", "KEY", [], _Rlog()).text
        finally:
            pt.brave_search = orig
        self.assertEqual(captured["count"], 20)       # asked for the full set, not 5
        self.assertIn("(20 results)", out)            # and disclosed the count


class PlannerFetchOversizeTests(unittest.TestCase):
    """The planner's `web_fetch` returned the WHOLE decoded body inline, on the belief — written in
    its own comment — that "the context floor reduces it if it's large for the window". The floor
    cannot: doctrine forbids truncating model-read content, and a single tool message larger than the
    window has no lossless reduction available. Measured in run 0727-123534: a 340,951-char GitHub
    page arrived as one message, the floor logged `msg_before=108954 msg_after=108954` against a
    49,152 window, llama.cpp answered **400 Bad Request**, and the planner burned all three retries
    and produced NO PLAN — the whole run then coded unplanned.

    The coder path already solved this: a doc bigger than one page is written IN FULL to a file and
    the model gets a pointer plus an outline. The planner writes to its own scratchpad (never the
    workspace) and can grep it back with the tools it already has."""

    def _big_page(self, n=340_000):
        return "line of documentation\n" * (n // 22)

    def _fetch_stub(self, body, ct="text/html"):
        from cria import webfetch

        def _stub(url, user_agent=None):
            return webfetch.FetchResult(200, url, ct, body, False)
        return _stub

    def test_an_oversized_page_does_not_ride_inline_into_the_planner_context(self):
        from cria import planner_tools, webfetch
        body = self._big_page()
        with tempfile.TemporaryDirectory() as scratch, \
                mock.patch.object(webfetch, "fetch", self._fetch_stub(body)):
            res = planner_tools._web_fetch({"url": "https://example.com/huge"}, {}, scratch=scratch)
        self.assertLess(len(res.text), webfetch.OVERSIZE_CHARS,
                        "the planner was handed the whole document inline")

    def test_the_full_document_is_kept_losslessly_and_pointed_at(self):
        from cria import planner_tools, webfetch
        body = self._big_page()
        with tempfile.TemporaryDirectory() as scratch, \
                mock.patch.object(webfetch, "fetch", self._fetch_stub(body)):
            res = planner_tools._web_fetch({"url": "https://example.com/huge"}, {}, scratch=scratch)
            spilled = [p for p in pathlib.Path(scratch).rglob("*") if p.is_file()]
            self.assertEqual(len(spilled), 1, "the document was not written anywhere")
            # rstrip: the MIME-aware reduce normalizes trailing whitespace. Every line survives,
            # which is the property that matters — a truncation would drop the tail.
            self.assertEqual(spilled[0].read_text().rstrip("\n"), body.rstrip("\n"),
                             "the spilled copy is not the whole document")
            self.assertIn(str(spilled[0]), res.text, "the planner was not told where the document is")
        self.assertTrue(res.learned)

    def test_a_normal_page_is_still_returned_inline(self):
        from cria import planner_tools, webfetch
        with tempfile.TemporaryDirectory() as scratch, \
                mock.patch.object(webfetch, "fetch", self._fetch_stub("GET /handles/{handle}\n")):
            res = planner_tools._web_fetch({"url": "https://api.example.com/spec"}, {}, scratch=scratch)
        self.assertIn("/handles/{handle}", res.text)
        self.assertEqual([], list(pathlib.Path(scratch).rglob("*")))


class GatherEnvironmentMutationTests(unittest.TestCase):
    """The gather's contract is READ anything, WRITE only to the scratchpad — never the workspace,
    never the user's machine. The guard enforced that with a list of FILESYSTEM mutators (rm, mv, cp,
    mkdir, tee) and redirect targets, so it could not see a package manager: `pip install x` names no
    path, and `python3 -m venv venv` has `python3` as its base.

    MEASURED (run 0727-125508): during planning, cria ran `pip install requests responses
    koios-mesh-sdk` against the user's SYSTEM python, then `python3 -m venv venv` inside the user's
    workspace, then pip install again — 3 of 12 gather rounds, in a gather that hit its cap. The
    install failed only because this machine is PEP 668 externally-managed; on a machine without that
    it would have written to the user's site-packages. And pip's refusal is what TAUGHT the model to
    create the venv, which the guard then also allowed.

    Every ecosystem, not just Python: the goal is language-agnostic and so is the category."""

    WS, SCRATCH = "/home/jesse/src/ws", "/tmp/scratch"

    def _ok(self, cmd):
        return pt.is_gather_safe_command(cmd, scratch=self.SCRATCH, workspace=self.WS)[0]

    def test_python_installers_and_virtualenvs_are_refused(self):
        for cmd in ("pip install requests", "pip3 install -r requirements.txt",
                    "python3 -m venv venv", "python -m pip install responses",
                    "virtualenv env", "uv pip install httpx", "poetry add requests",
                    "conda install numpy"):
            self.assertFalse(self._ok(cmd), f"allowed: {cmd}")

    def test_other_ecosystems_are_refused_the_same_way(self):
        for cmd in ("npm install express", "yarn add lodash", "pnpm install",
                    "cargo install ripgrep", "go get github.com/x/y", "gem install rails",
                    "bundle install", "composer require x", "apt-get install python3-dev",
                    "brew install jq"):
            self.assertFalse(self._ok(cmd), f"allowed: {cmd}")

    def test_the_read_subcommands_of_those_same_tools_still_work(self):
        # Research legitimately inspects a project's dependency state; only MUTATION is refused.
        for cmd in ("pip list", "pip show requests", "npm ls", "cargo tree",
                    "go list ./...", "bundle exec rspec --dry-run"):
            self.assertTrue(self._ok(cmd), f"refused: {cmd}")

    def test_ordinary_research_commands_are_untouched(self):
        for cmd in ("ls -la", "grep -rn handle .", "find . -name '*.py'", "git log --oneline -5",
                    "python3 -c \"import json; print(1)\"", "cat README.md"):
            self.assertTrue(self._ok(cmd), f"refused: {cmd}")

    def test_the_refusal_says_which_rule_was_broken(self):
        ok, why = pt.is_gather_safe_command("pip install requests", scratch=self.SCRATCH, workspace=self.WS)
        self.assertFalse(ok)
        self.assertIn("install", why.lower())

    def test_the_install_refusal_does_not_hand_out_impossible_advice(self):
        """The generic refusal says "write it to /tmp instead", which is right for a redirect and
        meaningless for `pip install` — and a refusal that suggests an impossible next move sends the
        model somewhere worse than the one it was stopped from (`pip install --target /tmp/...`)."""
        out = pt.execute_tool("exec_command", {"cmd": "pip install requests"}, self.WS, "", [],
                              _Rlog(), scratch=self.SCRATCH).text
        self.assertIn("Nothing needs installing to research", out)
        self.assertNotIn("/tmp/api.json", out)


class LedgerShapeFormatTests(unittest.TestCase):
    """Two producers fill the SAME ledger field — the coder-side `_extract_fetches` (via `_shape_block`)
    and the planner's gather (`_record_fetch`) — and they merge into one ⟦ctx:facts⟧ anchor. They must
    agree on how entries are separated, because the reader's contract is line-based: `_shape_block`'s
    own docstring says "entry lines are the ones carrying →".

    MEASURED (run 0727-134912): the planner joined five endpoint shapes with "; ", so the coder was
    handed 1,534 characters on ONE unbroken line — `/handles/{handle}`, `/holders/{address}`, `/stats`,
    `/mpt-root`, `/health` all run together — under a heading that says "use these EXACT names and
    nesting". Every fact was present and correct; only the shape of it was wrong. This is a legibility
    fix, not a claim about what the model then does with it."""

    def test_both_producers_separate_endpoint_shapes_the_same_way(self):
        from cria import loop
        rendered = ('HTTP 200 OK · https://api.example.com/openapi.json\n'
                    '[response shape — the fields each endpoint RETURNS:\n'
                    'GET /handles/{handle} → holder, resolved_addresses{ada}\n'
                    'GET /holders/{address} → total_handles, address]\n')
        coder_side = loop._shape_block(rendered, 0)
        self.assertEqual(len(coder_side.splitlines()), 3)     # header + 2 entries, one per line

        facts = {}
        pt._record_fetch(facts, "https://api.example.com/openapi.json", 200,
                         json.dumps({"paths": {
                             "/handles/{handle}": {"get": {"responses": {"200": {"content": {
                                 "application/json": {"schema": {"properties": {
                                     "holder": {"type": "string"},
                                     "resolved_addresses": {"type": "object", "properties": {"ada": {}}}}}}}}}}},
                             "/holders/{address}": {"get": {"responses": {"200": {"content": {
                                 "application/json": {"schema": {"properties": {
                                     "total_handles": {"type": "integer"},
                                     "address": {"type": "string"}}}}}}}}}}}),
                         "application/json")
        shapes = facts["https://api.example.com/openapi.json"][2]
        self.assertIn("/holders/{address}", shapes)
        # ONE UNINDENTED LINE PER ENDPOINT. A nested group now gets its own INDENTED continuation
        # line (see webfetch._lay_out_fields — the flat run was burying resolved_addresses 74% into
        # a 1,486-char line and every maple run read `name` as the address instead). The invariant
        # the original assertion was protecting — the planner must not smash all endpoints onto one
        # line — is unchanged and now stated directly, rather than as a raw line count that also
        # forbade an endpoint's own shape from wrapping.
        heads = [ln for ln in shapes.splitlines() if not ln.startswith(" ")]
        self.assertEqual(len(heads), 2, "each endpoint starts its own unindented line")
        self.assertTrue(all(ln.lstrip().startswith(("GET ", "POST ", "PUT ", "DELETE ", "PATCH "))
                            for ln in heads), heads)
        self.assertTrue(any(ln.startswith(" ") and '"ada"' in ln
                            for ln in shapes.splitlines()),
                        "a nested group is broken out where the coder can see it")


class PlannerLearnsAPageDefinedNothingTests(unittest.TestCase):
    """`b862402` tells the CODER when a fetched page yielded no endpoints — "that status is a fact
    about the REQUEST, not about what the API returns; the source that DEFINES them is still unread".
    The PLANNER, which is the one still looking for the spec, was never told: 0 of 16 planner prompts
    in run 0727-163703 carried it.

    MEASURED, three runs (0727-142536, -153326, -163703): the gather fetched a swagger UI SHELL — an
    HTML page with no spec in it — got a 200 and readable text back, and drafted a plan presupposing
    "the resolve endpoint" / "the resolve-handle endpoint". Downstream, a hardener turned that phrase
    into a concrete route: once the step critic (`POST /handles/resolve`), once the coder
    (`preprod.api.handle.me/resolve-handle/{handle}`, which 404s).

    Purely ADDITIVE — a true sentence appended to the fetch result, never an action taken for it, and
    self-limiting: it appears only while cria knows NO routes at all, which is exactly the state that
    produces a presupposed endpoint. Once any spec has been read, it goes quiet."""

    def _fetch(self, body, facts, ct="text/html"):
        from cria import webfetch, planner_tools

        def _stub(url, user_agent=None):
            return webfetch.FetchResult(200, url, ct, body, False)
        with mock.patch.object(webfetch, "fetch", _stub):
            return planner_tools._web_fetch({"url": "https://api.handle.me/swagger/"}, facts).text

    def test_a_page_with_no_endpoints_says_so(self):
        out = self._fetch("<html><body>Swagger UI</body></html>", {})
        self.assertIn("no endpoints", out.lower())

    def test_it_goes_quiet_once_a_spec_has_been_read(self):
        facts = {"https://api.handle.me/openapi.json":
                 ("HTTP 200", "/handles/{handle}, /holders/{address}", "GET /handles/{handle} → holder")}
        out = self._fetch("<html><body>Swagger UI</body></html>", facts)
        self.assertNotIn("no endpoints", out.lower())

    def test_a_page_that_DOES_define_endpoints_gets_no_note(self):
        # TWO routes: `_endpoint_routes` deliberately needs >=2 route-like keys before it calls a doc
        # a spec, so one `/`-key is not mistaken for one.
        spec = json.dumps({"paths": {"/handles/{handle}": {"get": {"summary": "x"}},
                                     "/holders/{address}": {"get": {"summary": "y"}}}})
        out = self._fetch(spec, {}, ct="application/json")
        self.assertNotIn("no endpoints", out.lower())
        self.assertIn("/handles/{handle}", out)


class SearchNoStructureNoteTests(unittest.TestCase):
    """THE NO-ROUTES DISCLOSURE RIDES SEARCH RESULTS TOO (run 0728-m11): a gather whose ONLY tool was
    one web_search never saw the 147e224 note — it was attached to fetch results alone — so the
    planner drafted invented `/api/v1/addresses/by-ada-handle/{handle}` from snippets and the coder
    built a live 404. Same condition, same silence rule: the note appears exactly while cria knows no
    routes and goes quiet the moment any fetched entry carries endpoints."""

    def _search(self, facts):
        from unittest import mock
        from cria import planner_tools
        with mock.patch.object(planner_tools, "brave_search",
                               return_value=[{"title": "t", "url": "https://x", "description": "d"}]):
            return planner_tools.execute_tool("web_search", {"query": "ada handles api"}, ".",
                                              "key", [], _Rlog(), facts=facts)

    def test_search_with_no_known_routes_carries_the_disclosure(self):
        r = self._search(facts={})
        self.assertTrue(r.learned)
        self.assertIn("POINTERS, not the source", r.text)
        self.assertIn("web_fetch the document", r.text)

    def test_search_goes_quiet_once_any_spec_was_read(self):
        r = self._search(facts={"https://api.x/openapi.json": (200, "/handles/{handle}", "fields")})
        self.assertNotIn("POINTERS", r.text)
