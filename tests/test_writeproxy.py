import json
import unittest

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
        self.assertIn("⟦cria:tool⟧", cmd)          # the stateless sentinel

    def test_write_round_trip_is_byte_exact_and_stateless(self):
        content = "line1\n\ttabbed 'quotes' \"dq\" $VAR `bt`\nend\n"
        comp = _call("write_file", {"path": "x.py", "content": content})
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"})
        # NO store handed back — re-presentation reads the sentinel from the command itself
        out = represent_inbound(_history_from(comp))
        tc = out[0]["tool_calls"][0]["function"]
        self.assertEqual(tc["name"], "write_file")
        self.assertEqual(json.loads(tc["arguments"])["content"], content)

    def test_empty_write_result_reframed_error_kept(self):
        comp = _call("write_file", {"path": "x.py", "content": "y"}, cid="c9")
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"})
        hist = _history_from(comp) + [{"role": "tool", "tool_call_id": "c9", "content": "  "}]
        out = represent_inbound(hist)
        self.assertIn("x.py", str(out[-1]["content"]))            # empty success → confirmation
        hist2 = _history_from(comp) + [{"role": "tool", "tool_call_id": "c9", "content": "permission denied"}]
        self.assertEqual(represent_inbound(hist2)[-1]["content"], "permission denied")  # real error kept


class TranslateEditReadTests(unittest.TestCase):
    def test_edit_file_lowers_to_python_replace_and_round_trips(self):
        comp = _call("edit_file", {"path": "m.py", "old_string": 'x, "id"}', "new_string": 'x, "id": id}'})
        translate_outbound(comp, _CMD_SHELL, injected={"edit_file"})
        cmd = _lowered_cmd(comp)
        self.assertIn("python3", cmd)
        self.assertIn("must occur exactly once", cmd)   # fail-closed on absent/ambiguous
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
    def test_web_fetch_lowers_to_curl_with_find(self):
        plain = _call("web_fetch", {"url": "https://x/openapi.json"})
        translate_outbound(plain, _CMD_SHELL, injected={"web_fetch"})
        self.assertIn("curl -sL", _lowered_cmd(plain))
        find = _call("web_fetch", {"url": "https://x", "find": "holders"})
        translate_outbound(find, _CMD_SHELL, injected={"web_fetch"})
        self.assertIn("grep", _lowered_cmd(find))     # find → section grep, not a re-fetch

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
