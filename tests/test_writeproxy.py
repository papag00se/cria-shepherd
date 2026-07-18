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
    def test_write_lowers_to_one_atomic_base64_command_no_chunking(self):
        big = "x" * 500_000  # far over any old chunk size — must still be ONE call (heredoc stdin)
        comp = _call("write_file", {"path": "a/b.py", "content": big})
        translate_outbound(comp, _ARR_SHELL, injected={"write_file"})
        calls = comp["choices"][0]["message"]["tool_calls"]
        self.assertEqual(len(calls), 1)            # no chunking
        cmd = _lowered_cmd(comp)
        self.assertIn("base64 -d", cmd)
        self.assertIn("mv ", cmd)                  # atomic: temp then move
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


class TranslateEditReadTests(unittest.TestCase):
    def test_edit_file_lowers_to_python_replace_and_round_trips(self):
        comp = _call("edit_file", {"path": "m.py", "old_string": 'x, "id"}', "new_string": 'x, "id": id}'})
        translate_outbound(comp, _CMD_SHELL, injected={"edit_file"})
        cmd = _lowered_cmd(comp)
        self.assertIn("python3", cmd)
        self.assertIn("old_string is NOT in", cmd)   # fail-closed on a miss (with a helpful error)
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

    def test_native_search_name(self):
        self.assertEqual(native_search_name([_t("local_web_search")]), "local_web_search")
        self.assertEqual(native_search_name([_t("web_search")]), "web_search")
        self.assertIsNone(native_search_name([_t("shell")]))

    def test_literal_newlines_decoded_real_left_alone(self):
        self.assertEqual(_repair_double_escaped("a\\nb\\nc"), "a\nb\nc")
        self.assertEqual(_repair_double_escaped("a\nb"), "a\nb")


if __name__ == "__main__":
    unittest.main()


class EditCommandTests(unittest.TestCase):
    """The edit executor: exact match, whitespace-flexible fallback (indent/blank-line drift), and a
    helpful actual-content error on a real miss — instead of byte-exact-only failing ~1/3 of edits."""

    def _run(self, content, old, new):
        import base64, os, subprocess, sys, tempfile
        from cria.writeproxy import _EDIT_PY, _WROTE, EDIT_SHOW_FULL_MAX
        fd, path = tempfile.mkstemp(suffix=".py")
        os.write(fd, content.encode()); os.close(fd)
        b = lambda x: base64.b64encode(x.encode()).decode()
        script = _EDIT_PY.format(path=b(path), old=b(old), new=b(new), wrote=_WROTE, small=EDIT_SHOW_FULL_MAX)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        out = open(path).read(); os.unlink(path)
        return r.returncode, (r.stdout + r.stderr), out

    def test_exact_match_replaces(self):
        rc, msg, out = self._run("foo\nbar\n", "foo", "FOO")
        self.assertEqual(rc, 0); self.assertIn("⟦ctx:wrote⟧", msg); self.assertEqual(out, "FOO\nbar\n")

    def test_blank_line_drift_still_matches(self):
        # old has an EXTRA blank line vs the file — byte-exact would fail; whitespace-flexible matches.
        rc, msg, out = self._run("a = 1\n\nb = 2\n", "a = 1\n\n\nb = 2", "a = 1\n\nc = 3")
        self.assertEqual(rc, 0); self.assertIn("⟦ctx:wrote⟧", msg); self.assertIn("c = 3", out)

    def test_indentation_drift_still_matches(self):
        rc, msg, out = self._run("    x = 1\n", "x = 1", "x = 2")
        self.assertEqual(rc, 0); self.assertEqual(out, "    x = 2\n")   # file's indent preserved

    def test_ambiguous_fails_closed(self):
        rc, msg, out = self._run("x\nx\n", "x", "y")
        self.assertNotEqual(rc, 0); self.assertIn("occurs 2 times", msg); self.assertEqual(out, "x\nx\n")

    def test_miss_returns_actual_content(self):
        rc, msg, out = self._run("def resolve(handle):\n    y = 2\n", "def resolve(handle):\n    x = 1", "z")
        self.assertNotEqual(rc, 0)
        self.assertIn("is NOT in", msg)
        self.assertIn("y = 2", msg)                 # shows the file's ACTUAL content near the target
        self.assertEqual(out, "def resolve(handle):\n    y = 2\n")   # unchanged

    def test_no_op_edit_is_rejected(self):
        # old_string == new_string changes nothing; reporting "wrote" wasted a turn in a live spiral
        rc, msg, out = self._run("a = 1\n", "a = 1", "a = 1")
        self.assertNotEqual(rc, 0)
        self.assertIn("IDENTICAL", msg)
        self.assertEqual(out, "a = 1\n")            # file untouched

    def test_identical_edit_on_a_small_file_offers_the_rewrite_escape(self):
        # THE 707-call spiral: the model kept submitting old==new on a whitespace fix and never escaped.
        # For a small file, the IDENTICAL rejection now points it at the write_file rewrite + shows the
        # current contents, so a 1-char fix doesn't burn hundreds of calls.
        rc, msg, out = self._run("    x = 1\n    y = 2\n", "    x = 1", "    x = 1")
        self.assertNotEqual(rc, 0)
        self.assertIn("IDENTICAL", msg)
        self.assertIn("REWRITE THE WHOLE FILE with write_file", msg)
        self.assertIn("y = 2", msg)                  # current contents handed over to rewrite from
        self.assertEqual(out, "    x = 1\n    y = 2\n")  # file untouched

    def test_miss_with_deleted_anchor_small_file_offers_rewrite(self):
        # THE 0063->0067 re-fail: a prior edit deleted the anchor line, so there's no near-context. For a
        # small file, point the model at a whole-file write_file rewrite + hand it the current contents.
        rc, msg, out = self._run("[project]\nname = \"x\"\n", "[tool.setuptools]\npackage-dir = 1", "z")
        self.assertNotEqual(rc, 0)
        self.assertIn("is NOT in", msg)
        self.assertIn("REWRITE THE WHOLE FILE with write_file", msg)  # the small-file escape
        self.assertIn('name = "x"', msg)                 # actual current contents handed over
        self.assertNotIn("Read the file again to get", msg)  # not the bare fallback

    def test_miss_with_deleted_anchor_large_file_falls_back(self):
        # A large file is NOT dumped/rewritten — the bare "read the file again" fallback still applies.
        big = "\n".join(f"line_{i} = {i}" for i in range(400))  # > EDIT_SHOW_FULL_MAX chars
        rc, msg, out = self._run(big + "\n", "[tool.setuptools]\nx = 1", "z")
        self.assertNotEqual(rc, 0)
        self.assertIn("Read the file again to get", msg)
        self.assertNotIn("REWRITE THE WHOLE FILE", msg)

    def test_phantom_bug_already_applied_tells_the_model_to_stop(self):
        # THE observed loop: the model re-fixes a line that is already correct. Its old_string
        # misremembers the current text (`base_user`), new_string is what the file ALREADY says
        # (`base_url`) → cria tells it the change is DONE and to move on, not to keep editing.
        rc, msg, out = self._run(
            '    x = get(f"{base_url}/h")\n',
            '    x = get(f"{base_user}/h")',   # old: misremembered
            '    x = get(f"{base_url}/h")')    # new: already what the file reads
        self.assertNotEqual(rc, 0)
        self.assertIn("already", msg.lower())
        self.assertIn("do NOT edit this line again", msg)
        self.assertNotIn("reads IN FULL", msg)            # the phantom branch, not the full dump

    def test_near_miss_points_at_the_closest_line(self):
        # old_string is close to a real line but new_string is a GENUINE change → point at the exact
        # line to copy (you likely mistyped a token), not "the anchor line is gone".
        rc, msg, out = self._run("    timeout = 30\n",
                                 "    timeoutt = 30",      # old: typo'd near-miss
                                 "    timeout = 60")       # new: a real 30->60 change
        self.assertNotEqual(rc, 0)
        self.assertIn("very CLOSE", msg)
        self.assertIn("timeout = 30", msg)                # the actual file line to copy
        self.assertIn("VERBATIM", msg)


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
        self.assertNotIn("base64 -d", cmd)          # the real write was never composed

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
        self.assertIn("base64 -d", cmd)             # normal lowering, not refused
        self.assertNotIn("off-limits", cmd)

    def test_absolute_path_outside_cria_home_is_allowed(self):
        cmd = self._lowered("write_file", {"path": "/tmp/scratch/app.py", "content": "x"})
        self.assertIn("base64 -d", cmd)
        self.assertNotIn("off-limits", cmd)


if __name__ == "__main__":
    unittest.main()
