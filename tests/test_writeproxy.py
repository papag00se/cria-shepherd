import json
import unittest

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
            self.assertIn("base64 -d > ", cmd)      # full doc written to disk
            self.assertIn("./tmp/read-only/", cmd)  # dedicated read-only scratch dir
            self.assertIn("chmod 444", cmd)         # marked read-only
            self.assertIn("grep", cmd)              # pointer message tells the model how to read it
        finally:
            webfetch.fetch = orig

    def test_whole_read_of_a_big_file_is_size_guarded(self):
        # A whole read_file lowers to a size-check: cat a small file, but hand a grep/range pointer for a
        # big one (a raw cat is truncated head+tail by the harness). A ranged read is a plain sed.
        from cria.writeproxy import _read_command
        whole = _read_command({"path": "big.json"})
        self.assertIn("wc -c", whole)          # size-checked
        self.assertIn("cat big.json", whole)   # small-file path still cats
        self.assertIn("grep", whole)           # big-file path steers to grep
        self.assertEqual(_read_command({"path": "f.py", "start_line": 2, "end_line": 9}), "sed -n '2,9p' f.py")

    def test_web_search_spills_results_to_read_only(self):
        comp = _call("web_search", {"query": "ada handle resolve endpoint"})
        translate_outbound(comp, _CMD_SHELL, injected={"web_search"}, brave_key="k")
        cmd = _lowered_cmd(comp)
        self.assertIn("curl -sL", cmd)                    # still the Brave curl
        self.assertIn("./tmp/read-only/search-", cmd)     # saved to the read-only spill dir
        self.assertIn("chmod 444", cmd)                   # read-only
        self.assertIn("grep", cmd)                        # pointer tells the model to grep/line-read

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


if __name__ == "__main__":
    unittest.main()


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
        script = (_VALIDATE_FN + _EDIT_PY).format(path=b(path), old=b(old), new=b(new),
                                                  wrote=_WROTE, editfail=editrecovery.EDITFAIL)
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
        self.assertIn("VERBATIM", early)                              # surgical: copy the exact text
        self.assertNotIn("FULL file", early)
        late = editrecovery.compose(fail, prior=editrecovery.ESCALATE_AFTER - 1)
        self.assertIn("produce the corrected FULL file", late)        # committed rewrite
        self.assertIn("a = 1\nb = 2", late)                           # grounded in the real current bytes

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


if __name__ == "__main__":
    unittest.main()
