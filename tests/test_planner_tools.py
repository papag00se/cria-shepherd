import contextlib
import json
import pathlib
import tempfile
import os
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


class NoShellAtAllTests(unittest.TestCase):
    """The gather used to run `bash -lc` in the coder's workspace, from cria's own process.

    A read-only deny-list guarded it — no writes outside a scratchpad, no package managers, no
    `rm -rf /`. That guard was correct and it guarded the wrong thing: the workspace is on the
    HARNESS's filesystem. cria has no channel to the harness while a gather round is in flight (this
    loop runs inside one request), so there is no way to route the command — and off a shared box
    every one of those commands ran against whatever machine cria happened to be on.

    So the capability is gone rather than faked, and the questions it was used for — what is here,
    where is this defined, what does this file say — are answered by list_dir, grep_files and
    read_file, from the survey the harness runs. Deleting the executor deletes the whole class of
    problem the deny-list existed to hold back; these tests pin the deletion, because a
    re-introduced shell would silently pass every test that came after it."""

    def _exec(self, cmd, ws="/ws"):
        return pt.execute_tool("exec_command", {"cmd": cmd}, ws, "", [], _Rlog())

    def test_a_command_is_refused_and_the_refusal_names_the_tools_that_answer(self):
        out = self._exec("ls -la").text
        self.assertIn("no shell", out.lower())
        for tool in ("list_dir", "grep_files", "read_file"):
            self.assertIn(tool, out)

    def test_the_refusal_quotes_the_command_so_the_planner_can_re_aim_it(self):
        self.assertIn("grep -rn handle .", self._exec("grep -rn handle .").text)

    def test_a_refused_command_taught_nothing(self):
        self.assertFalse(self._exec("ls -la").learned)

    def test_every_shell_spelling_lands_on_the_same_refusal(self):
        for name in ("exec_command", "shell", "bash", "local_shell"):
            with self.subTest(name=name):
                out = pt.execute_tool(name, {"cmd": "rm -rf /"}, "/ws", "", [], _Rlog()).text
                self.assertIn("no shell", out.lower())

    def test_the_executor_and_its_deny_list_are_gone(self):
        """Behavioural: nothing here can spawn a process, so no guard has to hold one back."""
        self.assertFalse(hasattr(pt, "subprocess"))
        self.assertFalse(hasattr(pt, "_exec_command"))
        self.assertFalse(hasattr(pt, "is_gather_safe_command"))

    def test_no_shell_tool_is_advertised(self):
        names = {t["function"]["name"] for t in pt.PLANNER_TOOLS}
        self.assertEqual(names, {"list_dir", "grep_files", "read_file", "web_fetch", "web_search"})


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

    def test_a_listing_that_shows_nothing_taught_nothing(self):
        # MEASURED (run 0727-090143): an empty workspace answered `ls -la` and `find` with nothing,
        # two calls counted as "it researched", and the planner drafted from memory and invented
        # `/resolve?handle={handle}` — which the coder then built and 404'd.
        import tempfile
        ws = tempfile.mkdtemp()
        self.assertFalse(pt.execute_tool("list_dir", {"path": "."}, ws, "", [], _Rlog()).learned)
        open(os.path.join(ws, "real.py"), "w").write("x = 1\n")
        self.assertTrue(pt.execute_tool("list_dir", {"path": "."}, ws, "", [], _Rlog()).learned)

    def test_errors_and_refusals_taught_nothing(self):
        import tempfile
        ws = tempfile.mkdtemp()
        self.assertFalse(pt.execute_tool("read_file", {"path": "nope.txt"}, ws, "", [], _Rlog()).learned)
        self.assertFalse(pt.execute_tool("web_fetch", {"url": ""}, ws, "", [], _Rlog()).learned)
        self.assertFalse(pt.execute_tool("web_search", {"query": "x"}, ws, "", [], _Rlog()).learned)
        self.assertFalse(pt.execute_tool("no_such_tool", {}, ws, "", [], _Rlog()).learned)

    def test_a_file_that_opened_taught_something(self):
        import tempfile
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "spec.txt"), "w") as fh:
            fh.write("GET /handles/{handle}\n")
        self.assertTrue(pt.execute_tool("read_file", {"path": "spec.txt"}, d, "", [], _Rlog()).learned)

    def test_a_grep_that_matched_nothing_taught_nothing(self):
        import tempfile
        d = tempfile.mkdtemp()
        open(os.path.join(d, "a.py"), "w").write("x = 1\n")
        self.assertFalse(pt.execute_tool("grep_files", {"pattern": "handle"}, d, "", [], _Rlog()).learned)
        self.assertTrue(pt.execute_tool("grep_files", {"pattern": "x ="}, d, "", [], _Rlog()).learned)


class TheReplacementToolsAnswerTheSameQuestionsTests(unittest.TestCase):
    """What the shell was actually used for: what is here, where is it, what does it say."""

    def _ws(self):
        import tempfile
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "src"))
        open(os.path.join(d, "src", "app.py"), "w").write("def resolve_handle(h):\n    return h\n")
        open(os.path.join(d, "README.md"), "w").write("# proj\n")
        return d

    def test_list_dir_names_files_and_directories(self):
        out = pt.execute_tool("list_dir", {"path": "."}, self._ws(), "", [], _Rlog()).text
        self.assertIn("README.md", out)
        self.assertIn("src/", out)

    def test_grep_files_gives_the_file_the_line_number_and_the_line(self):
        out = pt.execute_tool("grep_files", {"pattern": "resolve_handle"},
                              self._ws(), "", [], _Rlog()).text
        self.assertIn("app.py:1:", out)
        self.assertIn("def resolve_handle", out)

    def test_a_search_that_could_not_read_everything_says_so(self):
        """A silent partial search reads exactly like an exhaustive one that found nothing, and the
        planner would draft against the difference (#5b)."""
        from cria import wsview
        view = wsview.View("/ws", "sess-grep")
        from wsfixture import survey
        wsview.apply_survey(view, survey("D\tsrc\nF\t0\t10\tsrc/app.py"))
        self.addCleanup(wsview.unbind, wsview.bind(view))
        out = pt.execute_tool("grep_files", {"pattern": "anything"}, "/ws", "", [], _Rlog()).text
        self.assertIn("not exhaustive", out)

    def test_a_file_nobody_has_read_is_not_reported_as_absent(self):
        from cria import wsview
        self.addCleanup(wsview.unbind, wsview.bind(wsview.View("/ws", "sess-read")))
        out = pt.execute_tool("read_file", {"path": "app.py"}, "/ws", "", [], _Rlog()).text
        self.assertNotIn("does not exist", out)
        self.assertIn("NOT evidence", out)


class TheGatherStillReadsItsOwnScratchpadTests(unittest.TestCase):
    """cria spills a fetched spec into its OWN directory so a 57K doc does not ride in the prompt.
    The planner is the only reader of it, and it runs on cria's machine — so that read is not
    workstation access and must keep working."""

    def test_a_spilled_doc_can_be_read_back(self):
        import tempfile
        scratch = tempfile.mkdtemp()
        target = os.path.join(scratch, "spec.txt")
        open(target, "w").write("GET /handles/{handle}\n")
        out = pt.execute_tool("read_file", {"path": target}, "/ws", "", [], _Rlog(),
                              scratch=scratch).text
        self.assertIn("/handles/{handle}", out)

    def test_a_spilled_doc_can_be_grepped(self):
        import tempfile
        scratch = tempfile.mkdtemp()
        open(os.path.join(scratch, "spec.txt"), "w").write("GET /handles/{handle}\n")
        out = pt.execute_tool("grep_files", {"pattern": "handles", "path": scratch}, "/ws", "", [],
                              _Rlog(), scratch=scratch).text
        self.assertIn("spec.txt:1:", out)

    def test_the_scratchpad_route_cannot_reach_anything_else(self):
        import tempfile
        scratch = tempfile.mkdtemp()
        other = tempfile.mkdtemp()
        open(os.path.join(other, "secret.txt"), "w").write("nope\n")
        from cria import wsview
        self.addCleanup(wsview.unbind, wsview.bind(wsview.View("/ws", "s")))
        out = pt.execute_tool("read_file", {"path": os.path.join(other, "secret.txt")},
                              "/ws", "", [], _Rlog(), scratch=scratch).text
        self.assertNotIn("nope", out)


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


class NoPackageManagerCanRunFromAGatherTests(unittest.TestCase):
    """MEASURED (run 0727-125508): during PLANNING, cria ran `pip install requests responses
    koios-mesh-sdk` against the user's SYSTEM python, then `python3 -m venv venv` inside the user's
    workspace, then pip install again — 3 of 12 gather rounds, in a gather that hit its cap. The
    install failed only because that machine is PEP 668 externally-managed; on a machine without
    that it would have written to the user's site-packages.

    A deny-list held this back afterwards. The list is gone because the executor is gone, which is
    the stronger repair: there is no command a gather can run at all. This pins the OUTCOME the
    deny-list was protecting, independent of how it is achieved."""

    WS, SCRATCH = "/home/jesse/src/ws", "/tmp/scratch"

    def _out(self, cmd):
        return pt.execute_tool("exec_command", {"cmd": cmd}, self.WS, "", [], _Rlog(),
                               scratch=self.SCRATCH).text

    def test_no_installer_of_any_ecosystem_can_run(self):
        for cmd in ("pip install requests", "python3 -m venv venv", "npm install express",
                    "cargo install ripgrep", "gem install rails", "bundle install",
                    "composer require x", "apt-get install python3-dev", "brew install jq"):
            with self.subTest(cmd=cmd):
                self.assertIn("no shell", self._out(cmd).lower())

    def test_nothing_destructive_can_run_either(self):
        for cmd in ("rm -rf /", "find . -delete", "dd if=/dev/zero of=/dev/sda", "shred -u /tmp/x"):
            with self.subTest(cmd=cmd):
                self.assertIn("no shell", self._out(cmd).lower())

    def test_the_refusal_does_not_hand_out_impossible_advice(self):
        """The old generic refusal said "write it to /tmp instead", which is right for a redirect and
        meaningless for `pip install` — a refusal that suggests an impossible next move sends the
        model somewhere worse than the one it was stopped from (`pip install --target /tmp/...`)."""
        self.assertNotIn("/tmp", self._out("pip install requests"))


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
        # line (see webfetch._schema_json_shape — the flat run was burying resolved_addresses 74% into
        # a 1,486-char line and every maple run read `name` as the address instead). The invariant
        # the original assertion was protecting — the planner must not smash all endpoints onto one
        # line — is unchanged and now stated directly, rather than as a raw line count that also
        # forbade an endpoint's own shape from wrapping.
        heads = [ln for ln in shapes.splitlines() if ln.lstrip().startswith(("GET ", "POST "))]
        self.assertEqual(len(heads), 2, "one endpoint header per endpoint")
        self.assertEqual(shapes.count("```ts"), 2, "each shape is its own fenced ts block")
        self.assertEqual(shapes.count("```"), 4, "every fence is closed")
        # the fixture declares no type for `ada`, so it renders "?" — the nesting is the point
        self.assertTrue(any('ada?:' in ln for ln in shapes.splitlines()),
                        "the nested field is visible as real JSON nesting")
        self.assertIn('resolved_addresses?: {', shapes)


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


if __name__ == "__main__":
    unittest.main()
