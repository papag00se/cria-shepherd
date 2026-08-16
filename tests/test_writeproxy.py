import base64
import json
import subprocess
import pathlib
import tempfile
import unittest
from unittest import mock

from cria import webfetch
from cria import writeproxy

from cria.config import CRIA_HOME
from cria.writeproxy import (
    advertise,
    native_search_name,
    needs_translation,
    represent_inbound,
    translate_outbound,
    _repair_double_escaped,
)

_ARR_SHELL = {"name": "shell", "schema": {"properties": {"command": {"type": "array"}}}}
_CMD_SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}


def _t(name, **params):
    return {"type": "function", "function": {"name": name, "parameters": params or {"type": "object"}}}


def _call(name, args, cid="c1"):
    return {"choices": [{"message": {"tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def _lowered_cmd(comp):
    """The shell command string of the (single) lowered tool call in a translated completion."""
    tc = comp["choices"][0]["message"]["tool_calls"][0]
    args = json.loads(tc["function"]["arguments"])
    v = args.get("cmd") or args.get("command")
    return v[-1] if isinstance(v, list) else v


def _history_from(comp):
    """The lowered completion's tool calls, shaped as an assistant history message for inbound."""
    return [{"role": "assistant", "tool_calls": comp["choices"][0]["message"]["tool_calls"]}]


class DetectTests(unittest.TestCase):
    def test_translate_when_shell_but_no_write(self):
        self.assertIsNotNone(needs_translation([_t("shell")]))

    def test_passthrough_when_harness_has_write_file(self):
        self.assertIsNone(needs_translation([_t("shell"), _t("write_file")]))

    def test_none_when_no_shell(self):
        self.assertIsNone(needs_translation([_t("read_file")]))


class AdvertiseTests(unittest.TestCase):
    def test_injects_the_lean_set_including_edit_file(self):
        body = {"tools": [_t("shell")]}
        injected = advertise(body)
        names = {(t.get("function") or t)["name"] for t in body["tools"]}
        self.assertLessEqual({"write_file", "edit_file", "read_file", "list_dir", "web_fetch"}, names)
        self.assertIn("edit_file", injected)   # the surgical-edit path is now advertised

    def test_does_not_inject_a_harness_native_tool(self):
        body = {"tools": [_t("shell"), _t("read_file"), _t("edit_file")]}
        injected = advertise(body)
        self.assertNotIn("read_file", injected)
        self.assertNotIn("edit_file", injected)

    def test_local_web_search_presented_as_web_search(self):
        body = {"tools": [_t("shell"), _t("local_web_search")]}
        advertise(body)
        names = {(t.get("function") or t)["name"] for t in body["tools"]}
        self.assertIn("web_search", names)          # presented to the model as web_search
        self.assertNotIn("local_web_search", names)  # the raw Brave name is hidden

    def test_web_search_synthesized_only_with_a_brave_key(self):
        no_key = {"tools": [_t("shell")]}
        advertise(no_key, brave_key=None)
        self.assertNotIn("web_search", {(t.get("function") or t)["name"] for t in no_key["tools"]})
        with_key = {"tools": [_t("shell")]}
        injected = advertise(with_key, brave_key="sk-brave")
        self.assertIn("web_search", injected)


class TranslateWriteTests(unittest.TestCase):
    def test_write_lowers_to_one_atomic_command_no_chunking(self):
        big = "x" * 500_000  # far over any old chunk size — must still be ONE call (heredoc stdin)
        comp = _call("write_file", {"path": "a/b.py", "content": big})
        translate_outbound(comp, _ARR_SHELL, injected={"write_file"})
        calls = comp["choices"][0]["message"]["tool_calls"]
        self.assertEqual(len(calls), 1)            # no chunking
        cmd = _lowered_cmd(comp)
        self.assertIn("write_bytes", cmd)
        self.assertIn("os.replace", cmd)           # atomic: temp then replace
        self.assertIn("def _v(", cmd)              # validate-before-write is composed in
        self.assertIn("⟦ctx:tool⟧", cmd)          # the stateless sentinel

    def test_write_round_trip_is_byte_exact_and_stateless(self):
        content = "line1\n\ttabbed 'quotes' \"dq\" $VAR `bt`\nend\n"
        comp = _call("write_file", {"path": "x.py", "content": content})
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"})
        # NO store handed back — re-presentation reads the sentinel from the command itself
        out = represent_inbound(_history_from(comp))
        tc = out[0]["tool_calls"][0]["function"]
        self.assertEqual(tc["name"], "write_file")
        self.assertEqual(json.loads(tc["arguments"])["content"], content)

    def test_write_result_reframed_only_on_the_success_token(self):
        from cria.writeproxy import _WROTE
        comp = _call("write_file", {"path": "x.py", "content": "y"}, cid="c9")
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"})
        # SUCCESS: the result carries the positive token → clean confirmation (token hidden)
        ok = _history_from(comp) + [{"role": "tool", "tool_call_id": "c9", "content": _WROTE}]
        self.assertIn("x.py", str(represent_inbound(ok)[-1]["content"]))
        self.assertNotIn(_WROTE, str(represent_inbound(ok)[-1]["content"]))
        # FAILURE: no token (error on stderr, or blank) → left UNTOUCHED, the model sees the failure
        for failed in ("permission denied", "  ", ""):
            hist = _history_from(comp) + [{"role": "tool", "tool_call_id": "c9", "content": failed}]
            self.assertEqual(represent_inbound(hist)[-1]["content"], failed)   # never fabricated success
        # M11: a harness that ECHOES the command carries the token only INSIDE print('…'), NOT as a
        # standalone stdout line — a FAILED write must not be reframed as "Wrote" just because the echoed
        # heredoc source contains the token. Line-anchoring (== the token) distinguishes them.
        echoed = f"os.replace failed\nprint('{_WROTE}')\nPermissionError: denied"
        hist = _history_from(comp) + [{"role": "tool", "tool_call_id": "c9", "content": echoed}]
        self.assertEqual(represent_inbound(hist)[-1]["content"], echoed)   # untouched — the failure is shown


class WriteWithNoContentTests(unittest.TestCase):
    """`content` is a REQUIRED argument of write_file, and `args.get("content") or ""` turned its
    absence — and its explicit `null` — into an empty string, which the byte-exact write then put on
    disk. A working file truncated to zero bytes, reported back to the coder as a successful write,
    and validate-before-lower cannot object because an empty file parses.

    The same lesson as `new_string` on the edit path: a MISSING required argument is not an empty
    one. Only absent/null is refused; an intentional empty string still writes."""

    def _cmd(self, args):
        comp = _call("write_file", args)
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"})
        return _lowered_cmd(comp)

    def test_an_absent_content_is_refused_not_written_as_empty(self):
        cmd = self._cmd({"path": "keep.py"})
        self.assertIn("content", cmd)
        self.assertIn("cut off", cmd)
        self.assertNotIn("write_bytes", cmd)      # nothing was lowered to disk

    def test_a_null_content_is_refused_not_written_as_empty(self):
        cmd = self._cmd({"path": "keep.py", "content": None})
        self.assertIn("cut off", cmd)
        self.assertNotIn("write_bytes", cmd)

    def test_an_intentional_empty_string_still_writes(self):
        cmd = self._cmd({"path": "keep.py", "content": ""})
        self.assertIn("write_bytes", cmd)
        self.assertNotIn("cut off", cmd)

    def test_a_falsy_but_real_content_is_not_discarded(self):
        """`content or contents or ""` also threw away a legitimate `0` — silently, as an empty
        file. The lowered command carries the bytes base64-encoded, so assert on those."""
        self.assertIn(base64.b64encode(b"0").decode(), self._cmd({"path": "n.txt", "content": 0}))

    def test_the_contents_spelling_still_works(self):
        cmd = self._cmd({"path": "a.py", "contents": "body"})
        self.assertIn(base64.b64encode(b"body").decode(), cmd)

    def test_the_refusal_is_traced(self):
        events = []

        class Rec:
            def emit(self, kind, **fields):
                events.append((kind, fields))

        comp = _call("write_file", {"path": "keep.py"})
        translate_outbound(comp, _CMD_SHELL, Rec(), injected={"write_file"})
        self.assertIn("writeproxy.write_missing_arg", [k for k, _f in events])


class MalformedFusedCallTests(unittest.TestCase):
    """A weak model fuses two calls into one turn, leaking tool-call marker tokens into the shell
    command (gemma live: `["bash","-lc","pytest"]}<tool_call|><|tool_call>call:write_file{…`). It can't
    be reconstructed and dies in bash as a cryptic EOF — refuse it with guidance instead of running it."""

    def test_fused_call_debris_is_refused_with_guidance(self):
        comp = _call("shell", {"command": ["bash", "-lc", 'pytest"]}<tool_call|><|tool_call>call:write_file{content:']})
        translate_outbound(comp, _CMD_SHELL, injected=set())
        cmd = _lowered_cmd(comp)
        self.assertIn("malformed", cmd.lower())
        self.assertIn("ONE clean tool call", cmd)
        self.assertNotIn("<|tool_call>", cmd)          # the debris is gone — the refusal replaced the call

    def test_clean_shell_call_is_untouched(self):
        comp = _call("shell", {"command": ["bash", "-lc", "pytest test_lambda.py"]})
        translate_outbound(comp, _CMD_SHELL, injected=set())
        cmd = _lowered_cmd(comp)
        self.assertIn("pytest test_lambda.py", cmd)
        self.assertNotIn("malformed", cmd.lower())


class TranslateEditReadTests(unittest.TestCase):
    def test_edit_file_lowers_to_python_replace_and_round_trips(self):
        comp = _call("edit_file", {"path": "m.py", "old_string": 'x, "id"}', "new_string": 'x, "id": id}'})
        translate_outbound(comp, _CMD_SHELL, injected={"edit_file"})
        cmd = _lowered_cmd(comp)
        self.assertIn("python3", cmd)
        self.assertIn("editfail", cmd)   # fail-closed on a miss → a structured ⟦ctx:editfail⟧ fact-report
        back = represent_inbound(_history_from(comp))[0]["tool_calls"][0]["function"]
        self.assertEqual(back["name"], "edit_file")
        self.assertEqual(json.loads(back["arguments"])["new_string"], 'x, "id": id}')

    def test_read_file_range_and_start_only(self):
        both = _call("read_file", {"path": "f.py", "start_line": 10, "end_line": 20})
        translate_outbound(both, _CMD_SHELL, injected={"read_file"})
        self.assertIn("sed -n '10,20p'", _lowered_cmd(both))
        start = _call("read_file", {"path": "f.py", "start_line": 10})   # was silently ignored before
        translate_outbound(start, _CMD_SHELL, injected={"read_file"})
        self.assertIn("sed -n '10,$p'", _lowered_cmd(start))
        whole = _call("read_file", {"path": "f.py"})
        translate_outbound(whole, _CMD_SHELL, injected={"read_file"})
        self.assertIn("cat ", _lowered_cmd(whole))

    def test_read_and_list_are_re_presented_inbound(self):
        comp = _call("read_file", {"path": "f.py"}, cid="r1")
        translate_outbound(comp, _CMD_SHELL, injected={"read_file"})
        back = represent_inbound(_history_from(comp))[0]["tool_calls"][0]["function"]
        self.assertEqual(back["name"], "read_file")   # model sees read_file, not the raw shell cat

    def test_not_lowered_when_not_injected(self):
        comp = _call("read_file", {"path": "f.py"})
        translate_outbound(comp, _CMD_SHELL, injected=set())
        self.assertEqual(comp["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "read_file")


class WebTests(unittest.TestCase):
    def test_web_fetch_fetches_in_process_and_lowers_to_printf(self):
        # cria fetches + reduces in-process (stateful server) and lowers to a printf of the
        # already-reduced result — no raw curl the harness would truncate mid-line.
        from cria import webfetch
        webfetch.clear_cache()
        body = json.dumps({"openapi": "3.0.3", "paths": {"/holders": {"get": {"summary": "list holders"}}}})
        orig = webfetch.fetch
        webfetch.fetch = lambda u, ua=None: webfetch.FetchResult(200, u, "application/json", body, False)
        try:
            plain = _call("web_fetch", {"url": "https://x/openapi.json"})
            translate_outbound(plain, _CMD_SHELL, injected={"web_fetch"})
            cmd = _lowered_cmd(plain)
            self.assertIn("printf", cmd)               # in-process fetch, not a raw curl
            self.assertNotIn("curl -sL", cmd)
            self.assertIn("HTTP 200", cmd)             # the reduced result is embedded verbatim
            self.assertIn("openapi", cmd)
            find = _call("web_fetch", {"url": "https://x/openapi.json", "find": "holders"})
            translate_outbound(find, _CMD_SHELL, injected={"web_fetch"})
            self.assertIn("list holders", _lowered_cmd(find))  # structural find, served from cache
        finally:
            webfetch.fetch = orig

    def test_raw_plus_find_reaches_fetch_nav_at_the_REAL_boundary(self):
        # webfetch honors `find` under `raw`, but THIS is the only caller from the model path and it
        # used to null `find` first — so the fix was unreachable in production while its own test
        # (which drives fetch_nav directly) stayed green. Nulling find also forced the oversized-spill
        # branch below, reproducing the "saved N chars, go grep it" reply the fix set out to kill.
        from cria import webfetch
        webfetch.clear_cache()
        body = json.dumps({"openapi": "3.0.3",
                           "components": {"schemas": {"Handle": {"properties": {
                               "resolved_addresses": {"type": "object"}}}}},
                           "paths": {f"/pad{i}": {"get": {"summary": "s" * 90}} for i in range(400)}})
        orig = webfetch.fetch
        webfetch.fetch = lambda u, ua=None: webfetch.FetchResult(200, u, "application/json", body, False)
        try:
            c = _call("web_fetch", {"url": "https://x/openapi.json", "find": "resolved", "raw": True})
            translate_outbound(c, _CMD_SHELL, injected={"web_fetch"})
            cmd = _lowered_cmd(c)
            self.assertIn("resolved_addresses", cmd)          # the find RAN...
            self.assertNotIn("too large for the context", cmd)  # ...instead of the whole-doc spill
        finally:
            webfetch.fetch = orig

    def test_large_fetch_spills_to_a_tmp_file_with_a_pointer(self):
        # A plain fetch of an oversized doc lowers to: write the FULL doc to ./tmp, then print a short
        # grep/find pointer — instead of a low-signal page-1 the weak model can't navigate.
        from cria import webfetch
        webfetch.clear_cache()
        body = json.dumps({"openapi": "3.0.3", "info": {"title": "X"},
                           "paths": {f"/p{i}": {"get": {"summary": "s" * 80}} for i in range(500)}},
                          separators=(",", ":"))
        orig = webfetch.fetch
        webfetch.fetch = lambda u, ua=None: webfetch.FetchResult(200, u, "application/json", body, False)
        try:
            comp = _call("web_fetch", {"url": "https://x/openapi.json"})
            translate_outbound(comp, _CMD_SHELL, injected={"web_fetch"})
            cmd = _lowered_cmd(comp)
            self.assertIn("mkdir -p", cmd)
            # the doc is STAGED in cria's dir + cp'd in — NOT embedded as base64 in the argv (a big spec's
            # base64 overflows the harness exec arg cap: "Argument list too long"). The command stays tiny.
            self.assertIn("cp ", cmd)
            self.assertNotIn("base64 -d", cmd)
            self.assertLess(len(cmd), len(body), "lowered spill command must not carry the doc bytes")
            self.assertIn("./tmp/read-only/", cmd)  # dedicated read-only scratch dir (the target)
            self.assertNotIn("chmod 444", cmd)      # NOT FS-read-only: a re-spill must overwrite; dirguard protects
            self.assertNotIn("rm -f", cmd)          # the Codex sandbox rejects `rm -f`
            self.assertIn("grep", cmd)              # pointer message tells the model how to read it
        finally:
            webfetch.fetch = orig

    def test_whole_read_of_a_big_file_is_size_guarded(self):
        # A whole read_file lowers to a size-check: cat a small file, but hand a grep/range pointer for a
        # big one (a raw cat is truncated head+tail by the harness). A ranged read is a plain sed.
        from cria.writeproxy import _read_command, READ_INLINE_MAX
        whole = _read_command({"path": "big.json"})
        self.assertIn("wc -c", whole)          # size-checked
        self.assertIn("cat big.json", whole)   # small-file path still cats
        self.assertIn("grep", whole)           # big-file path steers to grep
        ranged = _read_command({"path": "f.py", "start_line": 2, "end_line": 9})
        self.assertIn("sed -n '2,9p' f.py", ranged)
        self.assertIn("past the end of the file", ranged)   # a past-EOF read isn't a silent empty
        self.assertIn("END{print NR}", ranged)              # accurate line count (awk NR, not wc -l)
        self.assertIn("too large to return", ranged)        # an over-cap RANGE steers, never truncates
        self.assertIn(str(READ_INLINE_MAX), ranged)

    def test_web_search_spills_results_to_read_only(self):
        comp = _call("web_search", {"query": "ada handle resolve endpoint"})
        translate_outbound(comp, _CMD_SHELL, injected={"web_search"}, brave_key="k")
        cmd = _lowered_cmd(comp)
        self.assertIn("curl -sL", cmd)                    # still the Brave curl
        self.assertIn("./tmp/read-only/search-", cmd)     # saved to the read-only spill dir
        # NO rm -f (the Codex sandbox HARD-rejects it → every web_search failed → model hallucinated an
        # endpoint) and NO chmod 444 (so `>` can overwrite on the next search); the dirguard protects the dir
        self.assertNotIn("rm -f", cmd)
        self.assertNotIn("chmod 444", cmd)
        self.assertIn("grep", cmd)                        # pointer tells the model to grep/line-read
        # M12: on a rate-limited/HTML/empty body the parse (json.load) raises → without a fallback the raw
        # Python TRACEBACK becomes the model's web_search result. The `|| printf <clean message>` hands it
        # a model-facing "unparseable/transient — retry" line instead of the traceback.
        self.assertIn("|| printf", cmd)
        self.assertNotIn("Traceback", cmd)

    def test_spill_dir_is_read_only_no_edit_or_whole_read(self):
        # A spilled reference doc must not be edited (it tried identical no-op edits, poisoning the
        # reasoner) and a whole read is steered to grep (a raw cat of a big file gets truncated).
        p = "./tmp/read-only/api.handle.me_openapi.json"
        edit = _call("edit_file", {"path": p, "old_string": "a", "new_string": "b"})
        translate_outbound(edit, _CMD_SHELL, injected={"edit_file"})
        self.assertIn("READ-ONLY reference", _lowered_cmd(edit))
        wholeread = _call("read_file", {"path": p})
        translate_outbound(wholeread, _CMD_SHELL, injected={"read_file"})
        self.assertIn("grep", _lowered_cmd(wholeread))
        # a RANGED read is legitimate → normal sed handler, not the steer
        ranged = _call("read_file", {"path": p, "start_line": 1, "end_line": 40})
        translate_outbound(ranged, _CMD_SHELL, injected={"read_file"})
        self.assertIn("sed -n", _lowered_cmd(ranged))
        # a NORMAL workspace file is untouched by the guard
        normal = _call("edit_file", {"path": "resolver.py", "old_string": "a", "new_string": "b"})
        translate_outbound(normal, _CMD_SHELL, injected={"edit_file"})
        self.assertNotIn("READ-ONLY reference", _lowered_cmd(normal))

    def test_whole_read_of_a_spilled_doc_is_steered_WITH_the_documents_outline(self):
        # The SIBLING of the web_fetch spill refusal, and the other half of the closed loop that held
        # ada-handles_fabliq_codex_pon_1785721353 on step 1 for 267 calls: the re-fetch says "read the
        # file", the whole read of that file says "grep it for what you need", and neither ever names
        # what is IN it. Measured across the 123 captured sessions: 1,931 coder calls carried this
        # steer, 500 of them (26%) with no outline anywhere in the prompt. cria holds the doc parsed,
        # so the steer says what to grep FOR.
        import json as _json
        from cria import webfetch as wf
        url = "https://api.handle.me/swagger/swagger.yml"
        body = _json.dumps({"openapi": "3.0.0", "info": {"description": "x" * (wf.OVERSIZE_CHARS + 500)},
                            "paths": {"/handles/{handle}": {}, "/holders/{address}": {}}})
        wf._cache_put(url, 200, "application/json",
                      *wf.reduce_for_cache(body, "application/json", url), False)
        try:
            whole = _call("read_file", {"path": wf._spill_name(url)})
            translate_outbound(whole, _CMD_SHELL, injected={"read_file"})
            cmd = _lowered_cmd(whole)
            self.assertIn("API endpoints (2)", cmd)
            self.assertIn("/holders/{address}", cmd)
            self.assertNotIn("<keyword>", cmd)      # a real route list replaces the placeholder
            self.assertNotIn("{{", cmd)             # every token filled — no raw placeholder shipped
            # an UNCACHED spill file invents nothing — the steer still stands on its own (rule 5b)
            other = _call("read_file", {"path": "./tmp/read-only/some-other-doc.txt"})
            translate_outbound(other, _CMD_SHELL, injected={"read_file"})
            ocmd = _lowered_cmd(other)
            self.assertNotIn("API endpoints", ocmd)
            self.assertIn("grep", ocmd)
        finally:
            wf.clear_cache()

    def test_malformed_fused_call_caught_on_any_shell_name(self):
        # the debris guard keyed on the literal name "shell" — inert for the LIVE Codex shell
        # (exec_command) and any harness whose shell is named differently. Now it's SHELL_TOOL_NAMES.
        for shell_name in ("exec_command", "run_terminal_cmd", "local_shell"):
            comp = _call(shell_name, {"cmd": "ls"})
            # inject tool-call sentinel debris into the raw arguments (a fused/corrupt call)
            comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = '{"cmd":"ls"}<|tool_call_start|>'
            translate_outbound(comp, {"name": shell_name, "schema": {"properties": {"cmd": {}}}}, injected=set())
            self.assertIn("ONE clean", _lowered_cmd(comp), shell_name)   # the malformed_call_refusal fired

    def test_list_dir_is_size_guarded(self):
        # A huge directory (node_modules, a data dir) would be silently truncated by the harness
        # output cap. It used to be capped-and-disclosed; since the 2026-08-12 ruling it is REFUSED
        # — a clipped listing is still a partial view the model reasons over as the directory, and
        # naming the size of a clip does not make it actionable. No elision on any read path.
        from cria.writeproxy import _list_command, READ_INLINE_MAX
        cmd = _list_command({"path": "somedir"})
        self.assertIn("ls -la", cmd)
        self.assertIn("too many to list", cmd)
        self.assertIn(str(READ_INLINE_MAX), cmd)
        self.assertNotIn("head -c", cmd)          # nothing is clipped
        self.assertNotIn("exit 1", cmd)           # and nothing claims the directory is missing

    def test_lowered_commands_avoid_sandbox_rejected_primitives(self):
        # cria's OWN lowered commands must never use a destructive primitive a harness sandbox rejects
        # (Codex hard-rejects `rm -f`), else EVERY use of that tool fails in the real harness while
        # live_exec — which has NO sandbox — masks it. Regression guard for the web_search rm -f outage:
        # a lowered command a harness runs must be built from safe primitives, harness-agnostically.
        from cria.writeproxy import _search_command, _spill_command, _list_command
        HOSTILE = ("rm -f", "rm -rf", "chmod ", " dd ", "mkfs", " mv ")
        cmds = {
            "web_search": _search_command({"query": "x"}, "KEY"),
            "web_fetch spill": _spill_command("./tmp/read-only/x.json", "content", "msg"),
            "list_dir": _list_command({"path": "some/dir"}),
        }
        for name, cmd in cmds.items():
            for tok in HOSTILE:
                self.assertNotIn(tok, cmd, f"{name}'s lowered command must not contain {tok!r} (sandbox-rejected)")

    def test_spill_relpath_redirects_only_the_root_absolute_form(self):
        from cria.writeproxy import _spill_relpath
        self.assertEqual(_spill_relpath("/tmp/read-only/api.json"), "./tmp/read-only/api.json")
        self.assertEqual(_spill_relpath("/tmp/read-only"), "./tmp/read-only")
        self.assertIsNone(_spill_relpath("./tmp/read-only/api.json"))       # already relative — fine
        self.assertIsNone(_spill_relpath("tmp/read-only/api.json"))         # relative — fine
        self.assertIsNone(_spill_relpath("/home/u/proj/tmp/read-only/x"))   # nested elsewhere — leave alone
        self.assertIsNone(_spill_relpath("/etc/passwd"))

    def test_dropped_dot_slash_spill_read_is_redirected_not_dirguard_blocked(self):
        # The live footgun: the model reads the fetched spec via '/tmp/read-only/x' (dropped the './'),
        # the dirguard blocks it as external, and the spec sits unreadable. A RANGED read must be
        # redirected to the real workspace file, NOT refused.
        ranged = _call("read_file", {"path": "/tmp/read-only/api.handle.me_openapi.json",
                                     "start_line": 1, "end_line": 100})
        translate_outbound(ranged, _CMD_SHELL, injected={"read_file"},
                           workspace_root="/home/jesse/src/proj", external_dir_permission="none")
        cmd = _lowered_cmd(ranged)
        self.assertNotIn("outside the working directory", cmd)                   # NOT the dirguard refusal
        self.assertIn("./tmp/read-only/api.handle.me_openapi.json", cmd)         # hits the real file
        self.assertIn("sed -n '1,100p'", cmd)
        # a WHOLE read of the dropped-'./' spill is still steered to grep (with the corrected path)
        whole = _call("read_file", {"path": "/tmp/read-only/api.handle.me_openapi.json"})
        translate_outbound(whole, _CMD_SHELL, injected={"read_file"},
                           workspace_root="/home/jesse/src/proj", external_dir_permission="none")
        wcmd = _lowered_cmd(whole)
        self.assertNotIn("outside the working directory", wcmd)
        self.assertIn("grep", wcmd)
        self.assertIn("./tmp/read-only/api.handle.me_openapi.json", wcmd)

    def test_dropped_dot_slash_spill_COMMAND_is_redirected_not_dirguard_blocked(self):
        # The command-string half of the same footgun: read_file on '/tmp/read-only/x' was silently
        # redirected while a grep/cp naming the SAME string was dirguard-refused — the model, shown
        # both, learned "the sandbox blocks this file" and burned ~130 calls (run 0729-gemma4 pon2).
        comp = _call("exec_command", {"command": "grep -n 'holder' /tmp/read-only/api.json"})
        translate_outbound(comp, _CMD_SHELL, injected=set(),
                           workspace_root="/home/jesse/src/proj", external_dir_permission="none")
        tc = comp["choices"][0]["message"]["tool_calls"][0]
        args = json.loads(tc["function"]["arguments"])
        self.assertEqual(args["command"], "grep -n 'holder' ./tmp/read-only/api.json")
        self.assertNotIn("outside the working directory", json.dumps(comp))     # no refusal fired

    def test_a_genuinely_external_command_refusal_names_the_real_workspace(self):
        # The anonymous "the project directory" left a blocked model inventing roots (/tmp/src,
        # /tmp/project) for whole runs — the refusal must state the one true root.
        comp = _call("exec_command", {"command": "cat /etc/passwd"})
        translate_outbound(comp, _CMD_SHELL, injected=set(),
                           workspace_root="/home/jesse/src/proj", external_dir_permission="none")
        self.assertIn("(/home/jesse/src/proj)", _lowered_cmd(comp))

    def test_web_search_routes_to_native_when_present(self):
        comp = _call("web_search", {"query": "ada handle"})
        translate_outbound(comp, _CMD_SHELL, injected=set(), native_search="local_web_search")
        self.assertEqual(comp["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "local_web_search")

    def test_web_search_lowers_to_brave_when_synthesized(self):
        comp = _call("web_search", {"query": "ada handle"})
        translate_outbound(comp, _CMD_SHELL, injected={"web_search"}, brave_key="sk-brave")
        cmd = _lowered_cmd(comp)
        self.assertIn("brave", cmd)
        self.assertIn("curl", cmd)

    def test_local_web_search_history_represented_as_web_search(self):
        hist = [{"role": "assistant", "tool_calls": [
            {"id": "s1", "type": "function", "function": {"name": "local_web_search", "arguments": '{"query":"x"}'}}]}]
        out = represent_inbound(hist)
        self.assertEqual(out[0]["tool_calls"][0]["function"]["name"], "web_search")


class BlindPipeNoteTests(unittest.TestCase):
    """`pytest … | grep -E 'passed|failed'` on a collection error prints NOTHING (grep exits 1 on no
    match) — a weak model re-ran that blind for eleven turns (run 0729-gemma4 B3) while the real
    traceback existed. When the model's OWN command has a filter pipe, exits nonzero, and printed
    nothing, the result gains a note stating those three facts; anything less stays silent."""

    @staticmethod
    def _msgs(command, exit_code=1, output=""):
        content = (f"Chunk ID: 805c35\nWall time: 0.1 seconds\nProcess exited with code {exit_code}\n"
                   f"Original token count: 0\nOutput:\n{output}")
        return [{"role": "assistant", "tool_calls": [{"id": "c1", "type": "function",
                 "function": {"name": "exec_command", "arguments": json.dumps({"command": command})}}]},
                {"role": "tool", "tool_call_id": "c1", "content": content}]

    def test_filtered_empty_failure_gains_the_note(self):
        out = represent_inbound(self._msgs("python3 -m pytest -q 2>&1 | grep -E 'passed|failed'"))
        self.assertIn("filter", out[1]["content"])
        self.assertIn("WITHOUT the pipe", out[1]["content"])

    def test_no_pipe_no_note(self):
        out = represent_inbound(self._msgs("grep -E 'passed' log.txt"))       # grep IS the command
        self.assertNotIn("WITHOUT the pipe", out[1]["content"])

    def test_output_present_no_note(self):
        out = represent_inbound(self._msgs("pytest | grep failed", output="3 failed\n"))
        self.assertNotIn("WITHOUT the pipe", out[1]["content"])

    def test_exit_zero_no_note(self):
        out = represent_inbound(self._msgs("pytest | grep passed", exit_code=0))
        self.assertNotIn("WITHOUT the pipe", out[1]["content"])


class WebFetchEnvelopeTests(unittest.TestCase):
    """A synthetic web_fetch is lowered to a shell exec, so the harness wraps its result in the Codex
    exec envelope (Chunk ID / Process exited / Output: / truncation advisories). Left in a re-presented
    web_fetch value it reads as a disk-caching shell command — the model then greps a phantom cache path
    and re-fetches the whole page. The envelope must be stripped back to the tool's own payload."""

    _ENVELOPE = (
        "Chunk ID: 805c35\n"
        "Wall time: 0.0000 seconds\n"
        "Process exited with code 0\n"
        "Original token count: 4106\n"
        "Output:\n"
        "Warning: truncated output (original token count: 4106)\n"
        "Total output lines: 8\n"
        "\n"
        "HTTP 200 OK · https://api.handle.me/openapi.json\n"
        "Content-Type: application/json\n"
        "--- (chars 0-16000 of 57548) ---\n"
        '{"openapi":"3.0.3"}\n'
        '⚠ More remains (41548 of 57548 chars left). Continue with cursor="c16000".'
    )

    def test_strip_removes_envelope_keeps_payload_and_real_footer(self):
        from cria.writeproxy import _strip_exec_envelope
        out = _strip_exec_envelope(self._ENVELOPE)
        self.assertTrue(out.startswith("HTTP 200 OK"))          # the payload leads
        for noise in ("Chunk ID", "Process exited", "Wall time", "Original token count",
                      "Warning: truncated output", "Total output lines"):
            self.assertNotIn(noise, out)                         # no shell/cache/truncation signal
        self.assertIn("⚠ More remains", out)                    # webfetch's OWN accurate footer survives
        self.assertIn('cursor="c16000"', out)

    def test_strip_is_a_no_op_without_the_envelope(self):
        from cria.writeproxy import _strip_exec_envelope
        clean = 'HTTP 200 OK · https://x\n{"a":1}'
        self.assertEqual(_strip_exec_envelope(clean), clean)     # already clean → untouched
        self.assertEqual(_strip_exec_envelope(""), "")

    def test_web_fetch_result_stripped_end_to_end(self):
        comp = _call("web_fetch", {"url": "https://api.handle.me/openapi.json"}, cid="c7")
        translate_outbound(comp, _CMD_SHELL, injected={"web_fetch"})
        hist = _history_from(comp) + [{"role": "tool", "tool_call_id": "c7", "content": self._ENVELOPE}]
        out = represent_inbound(hist)
        self.assertEqual(out[0]["tool_calls"][0]["function"]["name"], "web_fetch")   # name restored
        content = str(out[-1]["content"])
        self.assertNotIn("Chunk ID", content)                    # envelope stripped from the result
        self.assertNotIn("Process exited", content)
        self.assertTrue(content.startswith("HTTP 200 OK"))
        self.assertIn("⚠ More remains", content)

    def test_gate_result_is_not_stripped_no_fetch_sentinel(self):
        # A gate/exec result whose call carries NO fetch sentinel is left untouched — the gate path
        # (probegate) needs its envelope + ___CRIA_GATE_ sections; this must never be collateral damage.
        gate = ("Chunk ID: ab\nProcess exited with code 0\nOutput:\n"
                "___CRIA_GATE_probe-1___\nEXIT:0")
        hist = [{"role": "assistant", "tool_calls": [
                    {"id": "g1", "type": "function",
                     "function": {"name": "exec_command", "arguments": '{"cmd":"git status"}'}}]},
                {"role": "tool", "tool_call_id": "g1", "content": gate}]
        out = represent_inbound(hist)
        self.assertEqual(out[-1]["content"], gate)               # untouched: not a re-presented fetch

    def test_read_file_and_list_dir_results_are_also_stripped(self):
        # read_file (254×/session) and list_dir leak the SAME envelope — they must read as a file
        # read / dir listing, not a shell command that cached a chunk to disk.
        for tool, args, cid, payload in (
            ("read_file", {"path": "m.py"}, "r1", "def resolve(handle):\n    return handle"),
            ("list_dir", {"path": "src"}, "l1", "m.py\ntests/\nREADME.md"),
        ):
            comp = _call(tool, args, cid=cid)
            translate_outbound(comp, _CMD_SHELL, injected={tool})
            enveloped = f"Chunk ID: 77\nProcess exited with code 0\nOutput:\n{payload}"
            hist = _history_from(comp) + [{"role": "tool", "tool_call_id": cid, "content": enveloped}]
            out = represent_inbound(hist)
            self.assertEqual(out[0]["tool_calls"][0]["function"]["name"], tool)   # name restored
            self.assertEqual(str(out[-1]["content"]), payload)                    # envelope gone, payload exact

    def test_write_failure_strips_envelope_but_keeps_the_error(self):
        from cria.writeproxy import _WROTE
        comp = _call("write_file", {"path": "x.py", "content": "y"}, cid="w9")
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"})
        enveloped = "Chunk ID: 5\nProcess exited with code 1\nOutput:\nsed: cannot write: Permission denied"
        hist = _history_from(comp) + [{"role": "tool", "tool_call_id": "w9", "content": enveloped}]
        out = represent_inbound(hist)
        content = str(out[-1]["content"])
        self.assertNotIn("Chunk ID", content)                    # envelope noise gone
        self.assertNotIn(_WROTE, content)                        # never fabricates success on a failure
        self.assertIn("Permission denied", content)              # the REAL error survives


class MiscTests(unittest.TestCase):
    def test_inbound_leaves_unrelated_calls_alone(self):
        hist = [{"role": "assistant", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "shell", "arguments": '{"cmd":"ls"}'}}]}]
        self.assertEqual(represent_inbound(hist), hist)   # no sentinel → untouched

    def test_redact_secrets_strips_the_key_from_every_leak_shape(self):
        # The Brave key leaked via a tool RESULT (the harness echoes the curl command), assistant content,
        # and tool-call args. Redaction scrubs all of them so cria's credential never reaches the model.
        from cria.writeproxy import redact_secrets
        KEY = "BSAnwLmCmt454A0U3WnT7fzIVFRAKM2"
        msgs = [
            {"role": "tool", "content": f"curl -H 'X-Subscription-Token: {KEY}' …\n5 results"},          # result echo
            {"role": "assistant", "content": f"I'll pass api-key {KEY}",
             "tool_calls": [{"id": "c", "type": "function",
                             "function": {"name": "exec_command", "arguments": f'{{"cmd":"curl -H api-key:{KEY}"}}'}}]},
            {"role": "user", "content": [{"type": "text", "text": f"token {KEY}"}]},                       # Codex blocks
        ]
        out = redact_secrets(msgs, [KEY])
        self.assertNotIn(KEY, json.dumps(out))
        self.assertIn("***", out[0]["content"])
        self.assertEqual(redact_secrets(msgs, [""]), msgs)      # no secret → untouched (len<8 ignored)

    def test_native_search_name(self):
        self.assertEqual(native_search_name([_t("local_web_search")]), "local_web_search")
        self.assertEqual(native_search_name([_t("web_search")]), "web_search")
        self.assertIsNone(native_search_name([_t("shell")]))

    def test_literal_newlines_decoded_real_left_alone(self):
        self.assertEqual(_repair_double_escaped("a\\nb\\nc"), "a\nb\nc")
        self.assertEqual(_repair_double_escaped("a\nb"), "a\nb")


class ValidateBeforeLowerTests(unittest.TestCase):
    """A syntactically-broken write/edit never reaches disk — but ONLY as a regression guard: it
    refuses to break a file that currently parses, and NEVER blocks a model from fixing a broken one."""

    def _exec(self, cmd):
        import subprocess
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        return (r.stdout + r.stderr)

    def _tmp(self, name, content=None):
        import os, tempfile
        p = os.path.join(tempfile.mkdtemp(), name)
        if content is not None:
            open(p, "w").write(content)
        return p

    def test_write_refuses_to_break_a_currently_valid_file(self):
        from cria.writeproxy import _write_command, _WROTE
        p = self._tmp("a.py", "def f():\n    return 1\n")            # currently valid
        out = self._exec(_write_command(p, "def f(:\n"))            # broken replacement
        self.assertIn("REFUSED", out)
        self.assertNotIn(_WROTE, out)
        self.assertEqual(open(p).read(), "def f():\n    return 1\n")  # untouched

    def test_write_allows_a_new_or_already_broken_file(self):
        from cria.writeproxy import _write_command, _WROTE
        new = self._tmp("new.py")                                   # does not exist yet
        self.assertIn(_WROTE, self._exec(_write_command(new, "def g(:\n")))   # regression-only → allowed
        broken = self._tmp("b.py", "def h(:\n")                     # already broken on disk
        self.assertIn(_WROTE, self._exec(_write_command(broken, "def h(:\n  pass\n")))

    def test_write_validates_toml_and_json_too(self):
        from cria.writeproxy import _write_command, _WROTE
        t = self._tmp("c.toml", "[a]\nx = 1\n")
        self.assertIn("REFUSED", self._exec(_write_command(t, "[a]\nx = = 1\n")))
        j = self._tmp("d.json", '{"a": 1}')
        self.assertIn("REFUSED", self._exec(_write_command(j, '{"a": }')))
        md = self._tmp("e.md", "# ok")                              # non-code → not validated
        self.assertIn(_WROTE, self._exec(_write_command(md, "# hi (unbalanced")))

    def test_edit_refuses_a_regression_but_allows_fixing_a_broken_file(self):
        import base64, json
        from cria.writeproxy import _edit_command, _WROTE
        from cria import editrecovery
        valid = self._tmp("f.py", "x = 1\ny = 2\n")
        out = self._exec(_edit_command(valid, "y = 2", "y = (2"))                       # would break a valid file
        fail = json.loads(base64.b64decode(out.split(editrecovery.EDITFAIL, 1)[1].strip()).decode())
        self.assertEqual(fail["mode"], "would_break")                                   # reported, not applied
        self.assertEqual(open(valid).read(), "x = 1\ny = 2\n")                          # untouched
        broken = self._tmp("g.py", "def h(:\n    pass\n")                               # already broken
        self.assertIn(_WROTE, self._exec(_edit_command(broken, "def h(:", "def h():")))  # fixing → allowed
        self.assertIn("def h():", open(broken).read())


class EditCommandTests(unittest.TestCase):
    """The edit EXECUTOR: exact match, whitespace-flexible fallback (indent/blank-line drift), and — on a
    miss — a STRUCTURED ⟦ctx:editfail⟧ fact-report (mode + real bytes + near anchor). Prose/policy is no
    longer composed here; cria.editrecovery turns the facts into the one directive (see EditRecoveryTests)."""

    def _run(self, content, old, new):
        import base64, json, os, subprocess, sys, tempfile
        from cria.writeproxy import _EDIT_PY, _VALIDATE_FN, _WROTE
        from cria import editrecovery
        fd, path = tempfile.mkstemp(suffix=".py")
        os.write(fd, content.encode()); os.close(fd)
        b = lambda x: base64.b64encode(x.encode()).decode()
        from cria import content_reduce
        script = (_VALIDATE_FN + _EDIT_PY).format(path=b(path), old=b(old), new=b(new),
                                                  wrote=_WROTE, editfail=editrecovery.EDITFAIL,
                                                  cap=content_reduce.INLINE_RESULT_MAX_BYTES)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        out = open(path).read(); os.unlink(path)
        msg = (r.stdout + r.stderr).strip()
        fail = None
        if msg.startswith(editrecovery.EDITFAIL):
            fail = json.loads(base64.b64decode(msg[len(editrecovery.EDITFAIL):]).decode())
        return r.returncode, msg, out, fail

    def test_exact_match_replaces(self):
        rc, msg, out, _ = self._run("foo\nbar\n", "foo", "FOO")
        self.assertEqual(rc, 0); self.assertIn("⟦ctx:wrote⟧", msg); self.assertEqual(out, "FOO\nbar\n")

    def test_blank_line_drift_still_matches(self):
        # old has an EXTRA blank line vs the file — byte-exact would fail; whitespace-flexible matches.
        rc, msg, out, _ = self._run("a = 1\n\nb = 2\n", "a = 1\n\n\nb = 2", "a = 1\n\nc = 3")
        self.assertEqual(rc, 0); self.assertIn("⟦ctx:wrote⟧", msg); self.assertIn("c = 3", out)

    def test_indentation_drift_still_matches(self):
        rc, msg, out, _ = self._run("    x = 1\n", "x = 1", "x = 2")
        self.assertEqual(rc, 0); self.assertEqual(out, "    x = 2\n")   # file's indent preserved

    def test_indented_old_string_does_not_double_the_indent(self):
        """THE 91-ESCALATION ROOT (mellum2 1786196176, walked 2026-08-08). The coder's old_string
        carried the block's real 12-space indent and differed from disk only by a whitespace-only
        line — which the flexible match forgives. But the token match starts at the first
        non-whitespace char, so the file's indent stayed in the prefix and new_string's own indent
        landed after it: 24 spaces, "unexpected indent", and a would_break report telling the coder
        to fix a new_string that was correct (call 0190). The identical fix with a one-line
        old_string applied verbatim at call 0215 — 120 calls later."""
        content = ("        with patch('requests.get') as mock_get:\n"
                   "            mock_get.return_value = mock_handle_resp\n"
                   "            \n"
                   "            # Mock /holders response\n"
                   "            mock_get.return_value = mock_holder_resp\n")
        old = ("            mock_get.return_value = mock_handle_resp\n"
               "            # Mock /holders response\n"
               "            mock_get.return_value = mock_holder_resp")
        new = "            mock_get.side_effect = [mock_handle_resp, mock_holder_resp]"
        rc, msg, out, fail = self._run(content, old, new)
        self.assertIsNone(fail, msg)                                    # applied, not would_break
        self.assertIn("\n            mock_get.side_effect", out)        # exactly 12 spaces…
        self.assertNotIn("                        mock_get", out)        # …never 24

    def test_bare_old_string_still_inherits_the_file_indent(self):
        # the complementary case the fix must NOT break: coder gave flush-left statements
        rc, msg, out, _ = self._run("    if a:\n        x = 1\n", "x = 1", "x = 2")
        self.assertEqual(rc, 0); self.assertEqual(out, "    if a:\n        x = 2\n")

    def test_flexible_match_midline_is_untouched(self):
        # a match that starts mid-line (non-space before it on the same line) must not eat the line
        rc, msg, out, _ = self._run("v = alpha +  beta\n", "alpha  +  beta", "gamma")
        self.assertEqual(rc, 0); self.assertEqual(out, "v = gamma\n")

    def test_ambiguous_reports_multi(self):
        rc, msg, out, fail = self._run("x\nx\n", "x", "y")
        self.assertNotEqual(rc, 0); self.assertEqual(fail["mode"], "multi"); self.assertEqual(fail["n"], 2)
        self.assertEqual(out, "x\nx\n")

    def test_miss_reports_anchor_with_real_bytes(self):
        rc, msg, out, fail = self._run("def resolve(handle):\n    y = 2\n", "def resolve(handle):\n    x = 1", "z")
        self.assertNotEqual(rc, 0)
        self.assertEqual(fail["mode"], "anchor")
        self.assertIn("y = 2", fail["anchor"])       # the file's ACTUAL text near the target
        self.assertIn("y = 2", fail["current"])      # AND the whole current file for the escalation path
        self.assertEqual(out, "def resolve(handle):\n    y = 2\n")   # unchanged

    def test_identical_reports_identical_with_full_current(self):
        rc, msg, out, fail = self._run("    x = 1\n    y = 2\n", "    x = 1", "    x = 1")
        self.assertNotEqual(rc, 0)
        self.assertEqual(fail["mode"], "identical")
        self.assertIn("y = 2", fail["current"])      # the real bytes ride along; cria decides what to show
        self.assertEqual(out, "    x = 1\n    y = 2\n")  # file untouched

    def test_no_anchor_reports_no_anchor(self):
        rc, msg, out, fail = self._run("[project]\nname = \"x\"\n", "[tool.setuptools]\npackage-dir = 1", "z")
        self.assertNotEqual(rc, 0)
        self.assertEqual(fail["mode"], "no_anchor")
        self.assertIn('name = "x"', fail["current"])   # current bytes present regardless of file size

    def test_phantom_reports_phantom(self):
        # the model re-fixes an already-correct line: old misremembers (base_user), new is what the file
        # already reads (base_url) → mode=phantom; the directive tells it the change is DONE.
        rc, msg, out, fail = self._run(
            '    x = get(f"{base_url}/h")\n',
            '    x = get(f"{base_user}/h")', '    x = get(f"{base_url}/h")')
        self.assertNotEqual(rc, 0)
        self.assertEqual(fail["mode"], "phantom")
        self.assertIn("base_url", fail["anchor"])

    def test_near_miss_reports_close(self):
        rc, msg, out, fail = self._run("    timeout = 30\n", "    timeoutt = 30", "    timeout = 60")
        self.assertNotEqual(rc, 0)
        self.assertEqual(fail["mode"], "close")
        self.assertIn("timeout = 30", fail["anchor"])   # the closest real line


class EditRecoveryTests(unittest.TestCase):
    """The ONE edit-recovery owner: turns the heredoc's fact-report into a single MONOTONIC directive,
    keyed on the file's failure history — surgical first, then a committed whole-file-rewrite escalation.
    Replaces the old per-branch, history-blind rewrite/don't-rewrite prose that whipsawed the model."""

    def _fail(self, mode, **kw):
        kw.setdefault("path", "resolve_handle.py"); kw.setdefault("current", "a = 1\nb = 2\n")
        return {"mode": mode, **kw}

    def test_surgical_then_escalates_to_whole_rewrite(self):
        from cria import editrecovery
        fail = self._fail("anchor", anchor="a = 1")
        early = editrecovery.compose(fail, prior=0)
        # Surgical: it hands over the file's REAL text at the point of difference and tells the model
        # to use exactly that. Pinned on substance, not wording — the anchor body was reworded on
        # 2026-08-05 when the window moved from the head of old_string to the first diverging line.
        self.assertIn("a = 1", early)
        self.assertRegex(early, r"(?i)verbatim")
        self.assertNotIn("FULL file", early)
        late = editrecovery.compose(fail, prior=editrecovery.ESCALATE_AFTER - 1)
        self.assertIn("produce the corrected FULL file", late)        # committed rewrite
        self.assertIn("a = 1\nb = 2", late)                           # grounded in the real current bytes

    def test_a_successful_write_restarts_the_escalation_clock(self):
        # g18 (gemma4, ada-handles), calls 153-182: 4 edit steers on test_resolve.py with SEVEN
        # successful writes interleaved. The clock counted lifetime misses, so the file stayed in
        # forced-whole-rewrite mode — and one of those ~2,000-character retypes silently reverted the
        # `handler` -> `handle` fix the model had already landed. It chased that NameError for the rest
        # of the run. A landed write proves the model can pin this file; the clock starts over.
        from cria import editrecovery, prompts
        tag = editrecovery.EDIT_MARK + " app.py — "
        steer = {"role": "user", "content": tag + "copy this VERBATIM"}
        ok = {"role": "tool", "content": prompts.render("write_confirm", path="/work/app.py")}
        self.assertEqual(editrecovery._prior_edit_steers([steer, steer, steer], "/work/app.py"), 3)
        self.assertEqual(editrecovery._prior_edit_steers([steer, steer, steer, ok], "/work/app.py"), 0)
        self.assertEqual(editrecovery._prior_edit_steers([steer, steer, ok, steer], "/work/app.py"), 1)

    def test_the_clock_is_per_file_and_path_form_agnostic(self):
        from cria import editrecovery, prompts
        mine = {"role": "user", "content": editrecovery.EDIT_MARK + " app.py — miss"}
        other = {"role": "tool", "content": prompts.render("write_confirm", path="other.py")}
        rel = {"role": "tool", "content": prompts.render("write_confirm", path="app.py")}
        self.assertEqual(editrecovery._prior_edit_steers([mine, other], "/work/app.py"), 1)  # not my file
        self.assertEqual(editrecovery._prior_edit_steers([mine, rel], "/work/app.py"), 0)    # same file

    def test_summarize_collapses_the_base64_report_for_a_reasoner(self):
        # The raw ⟦ctx:editfail⟧<base64> embeds the file's WHOLE current bytes — 96K-token poison in a
        # reasoner prompt. summarize() collapses it to a one-line fact (the model still gets recover()).
        import base64, json
        from cria import editrecovery
        report = {"mode": "identical", "path": "api.handle.me_openapi.json", "current": "{" + "x" * 90000 + "}"}
        raw = "  -> " + editrecovery.EDITFAIL + base64.b64encode(json.dumps(report).encode()).decode()
        out = editrecovery.summarize(raw)
        self.assertLess(len(out), 200)                       # the base64 wall is gone
        self.assertIn("api.handle.me_openapi.json", out)
        self.assertIn("identical", out)
        self.assertNotIn("xxxx", out)                        # the file bytes are NOT in it
        self.assertEqual(editrecovery.summarize("a normal tool result"), "a normal tool result")

    def test_phantom_and_would_break_are_history_independent(self):
        from cria import editrecovery
        ph = editrecovery.compose(self._fail("phantom", anchor="x = get(base_url)"), prior=9)
        self.assertIn("DONE", ph); self.assertNotIn("FULL file", ph)   # never escalates to a rewrite
        wb = editrecovery.compose(self._fail("would_break", err="SyntaxError: bad"), prior=9)
        self.assertIn("SyntaxError", wb); self.assertIn("stays valid", wb)

    def test_recover_counts_history_and_escalates(self):
        import base64, json
        from cria import editrecovery
        raw = editrecovery.EDITFAIL + base64.b64encode(
            json.dumps(self._fail("no_anchor")).encode()).decode()
        # no prior steers → surgical; ESCALATE_AFTER prior steers for this file → committed rewrite
        self.assertNotIn("FULL file", editrecovery.recover(raw, []))
        hist = [{"role": "tool", "content": f"{editrecovery.EDIT_MARK} resolve_handle.py — x"}
                for _ in range(editrecovery.ESCALATE_AFTER)]
        self.assertIn("FULL file", editrecovery.recover(raw, hist))

    def test_non_editfail_passes_through(self):
        from cria import editrecovery
        self.assertEqual(editrecovery.recover("a real error, not a marker", []), "a real error, not a marker")

    def test_rewrite_sanctioned_detects_escalation(self):
        from cria import editrecovery
        esc = [{"role": "tool", "content": f"{editrecovery.EDIT_MARK} h.py — … produce the corrected FULL file …"}]
        self.assertTrue(editrecovery.rewrite_sanctioned(esc, "h.py"))
        self.assertFalse(editrecovery.rewrite_sanctioned(esc, "other.py"))
        self.assertFalse(editrecovery.rewrite_sanctioned([], "h.py"))


class CriaHomeGuardTests(unittest.TestCase):
    """The driven model must never read or write inside cria's OWN private dir (~/.cria): no leaking
    cria's .env credentials, no corrupting cria.toml / loopstate with a stray write. Dual of the
    no-workspace-pollution rule. A confused small model really did write a `~/.cria/chat-<id>.txt`
    'message to the user' there — this refuses it at the same chokepoint that lowers the tools."""

    def _lowered(self, name, args):
        comp = _call(name, args)
        translate_outbound(comp, _ARR_SHELL, injected={name})
        return _lowered_cmd(comp)

    def test_write_into_cria_home_is_refused(self):
        cmd = self._lowered("write_file", {"path": str(CRIA_HOME / "chat-123.txt"), "content": "hi"})
        self.assertIn("off-limits", cmd)
        self.assertNotIn("os.replace", cmd)          # the real write was never composed

    def test_read_of_cria_env_secret_is_refused(self):
        cmd = self._lowered("read_file", {"path": str(CRIA_HOME / ".env")})
        self.assertIn("off-limits", cmd)
        self.assertNotIn("cat ", cmd)               # never cats cria's secrets to the model

    def test_tilde_cria_path_is_refused(self):
        self.assertIn("off-limits", self._lowered("write_file", {"path": "~/.cria/cria.toml", "content": "x"}))

    def test_dotdot_escape_into_cria_home_is_refused(self):
        p = str(CRIA_HOME / "sub" / ".." / "loopstate.json")   # normpath collapses to ~/.cria/loopstate.json
        self.assertIn("off-limits", self._lowered("write_file", {"path": p, "content": "x"}))

    def test_edit_and_list_into_cria_home_are_refused(self):
        self.assertIn("off-limits", self._lowered("edit_file", {"path": str(CRIA_HOME / "cria.toml"),
                                                                 "old_string": "a", "new_string": "b"}))
        self.assertIn("off-limits", self._lowered("list_dir", {"path": str(CRIA_HOME)}))

    def test_workspace_relative_write_is_allowed(self):
        cmd = self._lowered("write_file", {"path": "src/app.py", "content": "x"})
        self.assertIn("os.replace", cmd)             # normal lowering, not refused
        self.assertNotIn("off-limits", cmd)

    def test_absolute_path_outside_cria_home_is_allowed(self):
        cmd = self._lowered("write_file", {"path": "/tmp/scratch/app.py", "content": "x"})
        self.assertIn("os.replace", cmd)
        self.assertNotIn("off-limits", cmd)



class SpillLedgerAcrossWorkspacesTests(unittest.TestCase):
    """cria refuses a re-fetch of a spilled doc with "it was saved to <path> — read THAT file". That
    claim is a MEMORY (`_FETCH_SPILLED`), and the file it names lives in the WORKSPACE. When the
    harness sends no session id, `session_key` falls back to `task:<hash of the first user message>`
    — so two runs of the same prompt share one key, and the second inherits the first's ledger while
    working in a different directory.

    MEASURED (run 0727-131647): the coder's VERY FIRST web_fetch was refused with "You already
    fetched … saved to ./tmp/read-only/api.handle.me_openapi.json". That directory did not exist in
    its workspace — the file was in the previous run's. The coder then looped: fetch → refused →
    read_file → "large document, grep it" → fetch → refused, never once seeing the spec.

    The filesystem is the ground truth for "cria wrote this file". Ask it."""

    PAGE = {"paths": {"/handles/{handle}": {"get": {"summary": "x" * 40}}},
            "components": {"schemas": {"H": {"properties": {"holder": {"type": "string"}}}}},
            "filler": ["y" * 200 for _ in range(200)]}

    def setUp(self):
        webfetch.clear_cache()
        webfetch._FETCH_SPILLED.clear()

    def _lower(self, workspace):
        comp = {"choices": [{"message": {"tool_calls": [{"id": "1", "type": "function", "function": {
            "name": "web_fetch", "arguments": json.dumps({"url": "https://api.example.com/openapi.json"})}}]}}]}
        out = translate_outbound(comp, _ARR_SHELL, None, injected={"web_fetch"},
                                 session="task:same-prompt", workspace_root=workspace)
        return (out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])

    def test_a_spill_from_another_workspace_does_not_refuse_a_first_fetch(self):
        body = json.dumps(self.PAGE)

        def _stub(url, user_agent=None):
            return webfetch.FetchResult(200, url, "application/json", body, False)

        with tempfile.TemporaryDirectory() as ws1, tempfile.TemporaryDirectory() as ws2, \
                mock.patch.object(webfetch, "fetch", _stub):
            first = self._lower(ws1)
            self.assertIn("read-only", first)          # run 1 spills the doc into ITS workspace
            self._run_the_cp(first, ws1)
            second = self._lower(ws2)                  # run 2: same session key, different workspace
        self.assertNotIn("You already fetched", second,
                         "cria refused a first fetch by pointing at another run's file")

    def _run_the_cp(self, lowered, ws):
        """cria EMITS the spill as a `cp` command; the HARNESS runs it. Existence is only a fact once
        it has — which is why the check is worth making: a sandbox-rejected cp now re-spills instead
        of pointing the model at a file that was never written."""
        # Derived, not spelled out: the spill NAME is webfetch's to choose (it gained a mandatory
        # `.txt` when a fetched `…decimal.go` got compiled by `go build ./...`), and a hard-coded
        # copy of it here silently stops writing the file the guard looks for.
        target = pathlib.Path(ws) / webfetch._spill_name("https://api.example.com/openapi.json").lstrip("./")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("the spilled document")

    def test_the_same_workspace_is_still_refused_a_whole_re_fetch(self):
        """The guard this fix works around is real and must survive: a doc cria DID write into THIS
        workspace is not copied over itself on every re-fetch (measured: 19 times in one run)."""
        body = json.dumps(self.PAGE)

        def _stub(url, user_agent=None):
            return webfetch.FetchResult(200, url, "application/json", body, False)

        with tempfile.TemporaryDirectory() as ws, mock.patch.object(webfetch, "fetch", _stub):
            first = self._lower(ws)
            self._run_the_cp(first, ws)
            again = self._lower(ws)
            self.assertIn("You already fetched", again)

    def test_a_spilled_file_the_model_deleted_is_not_claimed_to_exist(self):
        body = json.dumps(self.PAGE)

        def _stub(url, user_agent=None):
            return webfetch.FetchResult(200, url, "application/json", body, False)

        with tempfile.TemporaryDirectory() as ws, mock.patch.object(webfetch, "fetch", _stub):
            first = self._lower(ws)
            self._run_the_cp(first, ws)
            for f in pathlib.Path(ws).rglob("*"):
                if f.is_file():
                    f.unlink()
            again = self._lower(ws)
        self.assertNotIn("You already fetched", again)


class WriteTempEscapesWorkspaceTests(unittest.TestCase):
    """cria's atomic write is `tmp = str(p) + SUFFIX` then `os.replace(tmp, p)`. When the model aims a
    write at a DIRECTORY — measured (run 0727-161325), the plan step read "Write resolve_handle.py in
    /home/jesse/src/ada-goal-run-0727-161500/." and the coder took the trailing `/.` as the target —
    `Path('<ws>/.')` normalizes to `<ws>`, so the temp path lands ONE LEVEL UP, outside the workspace.

    That really happened: 1,089 bytes of the model's resolver were written to
    `/home/jesse/src/ada-goal-run-0727-161500.cria-tmp`, a sibling of the workspace in the user's
    ~/src. The dirguard had checked the MODEL's path (`<ws>/.`, legitimately inside); the temp path
    cria derived from it afterwards was never re-checked. `os.replace` onto a directory then fails,
    so the escaped file is also left behind — a second leftover was still sitting in another run's
    workspace hours later.

    A directory target is refused outright, and any temp is removed on failure."""

    def _run_write(self, path: str, content: str = "print(1)\n"):
        """Execute the REAL generated write program — the same python cria lowers to the harness."""
        import re, subprocess
        from cria.writeproxy import _write_command
        cmd = _write_command(path, content)
        m = re.search(r"python3 - <<'__CRIA_PY_EOF__'\n(.*?)\n__CRIA_PY_EOF__", cmd, re.S)
        self.assertIsNotNone(m, "could not extract the write program")
        return subprocess.run(["python3", "-c", m.group(1)], capture_output=True, text=True)

    def test_a_write_aimed_at_a_directory_creates_nothing_outside_it(self):
        with tempfile.TemporaryDirectory() as root:
            ws = pathlib.Path(root) / "workspace"
            ws.mkdir()
            self._run_write(str(ws) + "/.")
            strays = [p.name for p in pathlib.Path(root).iterdir() if p.name != "workspace"]
            self.assertEqual(strays, [], f"cria wrote outside the workspace: {strays}")

    def test_a_write_aimed_at_a_directory_leaves_no_temp_inside_either(self):
        with tempfile.TemporaryDirectory() as root:
            ws = pathlib.Path(root) / "workspace"
            ws.mkdir()
            self._run_write(str(ws))
            self.assertEqual([p.name for p in ws.iterdir()], [])

    def test_an_ordinary_write_still_works(self):
        with tempfile.TemporaryDirectory() as root:
            target = pathlib.Path(root) / "x.py"
            self._run_write(str(target), "print('hi')\n")
            self.assertEqual(target.read_text(), "print('hi')\n")
            self.assertEqual([p.name for p in pathlib.Path(root).iterdir()], ["x.py"])


class BinaryBlobTests(unittest.TestCase):
    """Operator ruling (07-30): binary blobs have NO place in any model-facing prompt — a stated
    fact replaces them, everywhere. Text that merely LOOKS exotic (CJK, base64, a hexdump the model
    asked for) is text and passes untouched."""

    def test_detector_matches_soup_never_text(self):
        from cria.content_reduce import looks_binary
        self.assertTrue(looks_binary("�" * 100))
        self.assertTrue(looks_binary("PNG\x00\x01\x02\x03" * 50))
        self.assertFalse(looks_binary("完全なユニコードテキスト。" * 200))          # CJK is text
        self.assertFalse(looks_binary("aGVsbG8gd29ybGQ=" * 500))                  # base64 is text
        self.assertFalse(looks_binary("00000000: 8950 4e47 0d0a 1a0a  .PNG....\n" * 100))  # hexdump is text

    def test_coder_history_soup_replaced_envelope_kept(self):
        from cria.writeproxy import represent_inbound
        soup = ("Chunk ID: x\nWall time: 0.1 seconds\nProcess exited with code 0\n"
                "Original token count: 900\nOutput:\n" + "�\x00\x01" * 400)
        out = represent_inbound([{"role": "tool", "tool_call_id": "c9", "content": soup}])
        c = out[0]["content"]
        self.assertIn("Process exited with code 0", c)     # the envelope is the true record — kept
        self.assertIn("binary content", c)                 # the payload became a fact
        self.assertNotIn("�", c)

    def test_judge_read_of_a_png_becomes_a_fact_line(self):
        import os
        import tempfile

        from cria.verifytools import execute
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "chart.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 30)
        out = execute("read_file", {"path": "chart.png"}, d)
        self.assertIn("PNG image", out)
        self.assertIn("binary content", out)
        self.assertNotIn("�", out)

    def test_gather_exec_of_binary_stdout_is_a_fact_not_a_crash(self):
        import os
        import tempfile

        from cria import planner_tools
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "blob.bin"), "wb") as f:
            f.write(bytes(range(256)) * 40)
        r = planner_tools._exec_command({"command": "cat blob.bin"}, cwd=d, scratch=d)
        self.assertIn("binary content", r.text)            # not soup, not an exception
        self.assertNotIn("�", r.text)


class MissingPathRefusalTests(unittest.TestCase):
    """A synthetic write/edit whose PATH never arrived (the arguments came out malformed — gemma4
    re-measure run 1785893473 calls 0007/0059/0184 fused path and old_string into new_string) used
    to fall through UN-LOWERED to the harness, whose reply — "unsupported call: edit_file" — the
    coder read as 'edits are unsupported'. cria advertised the tool; cria owns the refusal."""

    def _cmd(self, name, args):
        comp = _call(name, args)
        translate_outbound(comp, _CMD_SHELL, injected={name})
        return _lowered_cmd(comp)

    def test_edit_with_no_path_is_refused_not_forwarded_raw(self):
        # the run's real malformed shape: everything fused into new_string
        cmd = self._cmd("edit_file", {"new_string": "    assert x\\n',old_string:"})
        self.assertIn("malformed", cmd)
        self.assertIn("path", cmd)

    def test_edit_with_path_but_absent_old_string_is_refused(self):
        cmd = self._cmd("edit_file", {"path": "a.py", "new_string": "x"})
        self.assertIn("malformed", cmd)

    def test_write_with_no_path_is_refused_not_forwarded_raw(self):
        cmd = self._cmd("write_file", {"content": "body text", "result_type": "file_created"})
        self.assertIn("malformed", cmd)
        self.assertIn("path", cmd)

    def test_intact_calls_still_lower(self):
        self.assertIn("write_bytes", self._cmd("write_file", {"path": "a.py", "content": "x"}))
        edit = self._cmd("edit_file", {"path": "a.py", "old_string": "x", "new_string": "y"})
        self.assertNotIn("malformed", edit)


class InvertedRangeTests(unittest.TestCase):
    """Run 1785893473 call 0018: the coder sent start_line=1041, end_line=358. cria silently
    dropped the end_line (the `end >= start` guard fails, so the start-only branch read 1041→EOF)
    and then refused THAT as "too large — narrow your window", about a request the coder believed
    was already narrow. The refusal must name the real defect: the range is inverted."""

    def test_an_inverted_range_is_refused_with_the_true_cause(self):
        cmd = writeproxy._read_command(
            {"path": "spec.json", "start_line": 1041, "end_line": 358})
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(r.returncode, writeproxy.REFUSED_EXIT_CODE)
        self.assertIn("1041", r.stdout)
        self.assertIn("358", r.stdout)
        self.assertIn("inverted", r.stdout.lower())

    def test_a_sane_range_still_reads(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("a\nb\nc\nd\n")
        try:
            cmd = writeproxy._read_command({"path": f.name, "start_line": 2, "end_line": 3})
            r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            self.assertIn("2: b", r.stdout)
            self.assertIn("3: c", r.stdout)
        finally:
            os.unlink(f.name)

    def test_equal_start_and_end_is_a_one_line_read_not_an_inversion(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("a\nb\nc\n")
        try:
            cmd = writeproxy._read_command({"path": f.name, "start_line": 2, "end_line": 2})
            r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            self.assertIn("2: b", r.stdout)
        finally:
            os.unlink(f.name)


class ParentIsAFileTests(unittest.TestCase):
    """Walked on ada-handles_nemotron-elastic_codex_poff_1785946072 (scored 2/4): a mis-split fused
    call wrote a junk FILE named `tests`, and every later write to tests/*.py then died in cria's
    own lowering with a raw `FileExistsError` traceback — no cause, no cure, three identical
    retries, and the coder declared done without tests. The failure must name the blocking file."""

    def test_a_blocked_parent_gets_a_plain_cause_not_a_traceback(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as ws:
            blocker = os.path.join(ws, "tests")
            with open(blocker, "w") as fh:
                fh.write("</parameter>\n</function>\n")
            cmd = writeproxy._write_command(os.path.join(ws, "tests", "test_x.py"), "import x\n")
            r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            out = r.stdout + r.stderr
            self.assertNotIn("Traceback", out)
            self.assertIn("tests", out)
            self.assertIn("FILE", out)          # names the real cause: parent exists as a file

    def test_a_normal_nested_write_still_creates_parents(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as ws:
            cmd = writeproxy._write_command(os.path.join(ws, "pkg", "mod.py"), "x = 1\n")
            r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(ws, "pkg", "mod.py")))


class FusedContentRefusalTests(unittest.TestCase):
    """Same run, one call earlier: the mis-split handed write_file a `content` that was NOTHING BUT
    the model's own protocol tags plus the next call's path — and cria wrote it ('Wrote tests'),
    planting the blocker. Content that is pure tool-syntax debris is a fused call, not a file."""

    OBSERVED = ("</parameter>\n</function>\n</tool_call>\n<tool_call>\n<function=write_file>\n"
                "<parameter=path>\n/tmp/ws/tests/test_resolve_handle.py")

    @staticmethod
    def _lower(args):
        import json as _json
        comp = {"choices": [{"message": {"tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "write_file", "arguments": _json.dumps(args)}}]}}]}
        out = writeproxy.translate_outbound(
            comp, {"name": "shell", "parameters": {"properties": {"command": {"type": "string"}},
                                                   "required": ["command"]}},
            injected={"write_file"})
        return out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]

    def test_the_observed_soup_is_refused_with_the_true_cause(self):
        cmd = self._lower({"path": "tests", "content": self.OBSERVED})
        self.assertIn("fused", cmd)
        self.assertIn(f"exit {writeproxy.REFUSED_EXIT_CODE}", cmd)

    def test_real_content_mentioning_a_tag_is_untouched(self):
        code = ('MARKS = ("</tool_call>", "<function=")\n'
                "def has_leak(text):\n    return any(m in text for m in MARKS)\n")
        cmd = self._lower({"path": "leakcheck.py", "content": code})
        self.assertNotIn("fused", cmd)

    def test_an_empty_or_plain_file_is_untouched(self):
        self.assertNotIn("fused", self._lower({"path": "a.txt", "content": "hello world\n"}))
        self.assertNotIn("fused", self._lower({"path": "b.txt", "content": ""}))


if __name__ == "__main__":
    unittest.main()
