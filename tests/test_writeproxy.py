import base64
import json
import unittest

from cria.writeproxy import (
    TranslationStore,
    advertise,
    needs_translation,
    represent_inbound,
    translate_outbound,
)

_SHELL = {"type": "function", "function": {"name": "shell", "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}
_WRITE = {"type": "function", "function": {"name": "write_file"}}


class DetectTests(unittest.TestCase):
    def test_translate_when_shell_but_no_write(self):
        self.assertEqual(needs_translation([_SHELL])["name"], "shell")

    def test_passthrough_when_harness_has_write_file(self):
        self.assertIsNone(needs_translation([_SHELL, _WRITE]))

    def test_none_when_no_shell(self):
        self.assertIsNone(needs_translation([]))


class AdvertiseTests(unittest.TestCase):
    def test_adds_write_file_for_the_model(self):
        body = {"tools": [_SHELL]}
        advertise(body)
        names = [t["function"]["name"] for t in body["tools"]]
        self.assertIn("write_file", names)

    def test_idempotent(self):
        body = {"tools": [_SHELL, _WRITE]}
        advertise(body)
        self.assertEqual(sum(t["function"]["name"] == "write_file" for t in body["tools"]), 1)

    def test_adds_read_and_list_tools_and_returns_injected(self):
        body = {"tools": [_SHELL]}
        injected = advertise(body)
        names = [t["function"]["name"] for t in body["tools"]]
        self.assertIn("read_file", names)   # lean named tools, not the raw shell/PTY
        self.assertIn("list_dir", names)
        self.assertEqual(injected, {"write_file", "read_file", "list_dir"})

    def test_does_not_inject_a_harness_native_tool(self):
        native_read = {"type": "function", "function": {"name": "read_file"}}
        body = {"tools": [_SHELL, native_read]}
        injected = advertise(body)
        self.assertNotIn("read_file", injected)  # harness runs it → cria must not lower it
        self.assertEqual(sum(t["function"]["name"] == "read_file" for t in body["tools"]), 1)


class TranslateTests(unittest.TestCase):
    def _completion(self, name, args, call_id="c1"):
        return {"choices": [{"message": {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}

    def test_outbound_lowers_to_base64_shell(self):
        store = TranslationStore()
        comp = self._completion("write_file", {"path": "src/h.py", "content": "print('hi')\n"})
        translate_outbound(comp, {"name": "shell", "schema": {"properties": {"command": {"type": "array"}}}}, store, "k")
        tc = comp["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "shell")
        cmd = " ".join(json.loads(tc["function"]["arguments"])["command"])
        self.assertIn("base64 -d > src/h.py", cmd)
        # and the base64 in the command decodes back to the exact content
        b64 = cmd.split("printf %s ")[1].split(" |")[0]
        self.assertEqual(base64.b64decode(b64).decode(), "print('hi')\n")
        # recorded for the inbound swap
        self.assertEqual(store.get("k", "c1")["path"], "src/h.py")

    _ARR_SHELL = {"name": "shell", "schema": {"properties": {"command": {"type": "array"}}}}

    def test_outbound_lowers_read_file_to_cat(self):
        comp = self._completion("read_file", {"path": "src/h.py"})
        translate_outbound(comp, self._ARR_SHELL, TranslationStore(), "k", injected={"read_file"})
        tc = comp["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "shell")
        self.assertIn("cat src/h.py", " ".join(json.loads(tc["function"]["arguments"])["command"]))

    def test_outbound_read_file_line_range_uses_sed(self):
        comp = self._completion("read_file", {"path": "h.py", "start_line": 10, "end_line": 20})
        translate_outbound(comp, self._ARR_SHELL, TranslationStore(), "k", injected={"read_file"})
        cmd = " ".join(json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["command"])
        self.assertIn("sed -n '10,20p' h.py", cmd)

    def test_outbound_lowers_list_dir_to_ls(self):
        comp = self._completion("list_dir", {"path": "src"})
        translate_outbound(comp, self._ARR_SHELL, TranslationStore(), "k", injected={"list_dir"})
        cmd = " ".join(json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["command"])
        self.assertIn("ls -la src", cmd)

    def test_read_file_not_lowered_when_not_injected(self):
        # a harness-native read_file (cria didn't inject it) is left for the harness to run
        comp = self._completion("read_file", {"path": "h.py"})
        translate_outbound(comp, self._ARR_SHELL, TranslationStore(), "k", injected=set())
        self.assertEqual(comp["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "read_file")

    def test_inbound_represents_shell_as_write_file(self):
        store = TranslationStore()
        store.record("k", "c1", "src/h.py", "print('hi')\n")
        # the harness ran the shell call; history now has the shell call cria emitted
        history = [{"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "shell", "arguments": '{"command":"..."}'}}]}]
        out = represent_inbound(history, store, "k")
        fn = out[0]["tool_calls"][0]["function"]
        self.assertEqual(fn["name"], "write_file")  # model sees its own tool again
        self.assertEqual(json.loads(fn["arguments"]), {"path": "src/h.py", "content": "print('hi')\n"})

    def test_inbound_leaves_unrelated_calls_alone(self):
        store = TranslationStore()
        history = [{"role": "assistant", "tool_calls": [{"id": "other", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]}]
        out = represent_inbound(history, store, "k")
        self.assertEqual(out[0]["tool_calls"][0]["function"]["name"], "shell")  # unchanged

    def test_round_trip_content_is_byte_exact(self):
        store = TranslationStore()
        content = 'def h():\n    return {"a": "b\'c", "n": 1}\n'  # quotes, braces, newlines
        comp = self._completion("write_file", {"path": "h.py", "content": content})
        translate_outbound(comp, {"name": "shell", "schema": {}}, store, "k")
        back = represent_inbound(
            [{"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]}],
            store, "k",
        )
        self.assertEqual(json.loads(back[0]["tool_calls"][0]["function"]["arguments"])["content"], content)

    def test_reframes_empty_result_but_keeps_errors(self):
        store = TranslationStore()
        store.record("k", "c1", "h.py", "x")
        history = [
            {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "  "},  # empty shell success
        ]
        out = represent_inbound(history, store, "k")
        self.assertEqual(out[1]["content"], "Wrote h.py")
        # an error result is preserved, not reframed
        store.record("k", "c2", "h.py", "x")
        err = represent_inbound([{"role": "tool", "tool_call_id": "c2", "content": "permission denied"}], store, "k")
        self.assertEqual(err[0]["content"], "permission denied")


class ChunkTests(unittest.TestCase):
    def test_large_file_splits_into_multiple_shell_calls(self):
        store = TranslationStore()
        content = "x" * 200_000  # > _CHUNK_BYTES (65536) → 4 chunks
        comp = {"choices": [{"message": {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "big.txt", "content": content})}}]}}]}
        translate_outbound(comp, {"name": "shell", "schema": {}}, store, "k")
        calls = comp["choices"][0]["message"]["tool_calls"]
        self.assertGreater(len(calls), 1)
        cmds = [json.loads(c["function"]["arguments"])["command"] for c in calls]
        self.assertIn(" > big.txt", cmds[0])  # first writes
        self.assertTrue(all(" >> big.txt" in c for c in cmds[1:]))  # rest append

    def test_inbound_collapses_chunks_to_one_write_file(self):
        store = TranslationStore()
        content = "y" * 200_000
        comp = {"choices": [{"message": {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "big.txt", "content": content})}}]}}]}
        translate_outbound(comp, {"name": "shell", "schema": {}}, store, "k")
        # the harness ran all N shell calls; history has them + their results
        history = [{"role": "assistant", "tool_calls": comp["choices"][0]["message"]["tool_calls"]}]
        out = represent_inbound(history, store, "k")
        calls = out[0]["tool_calls"]
        self.assertEqual(len(calls), 1)  # the model sees ONE write_file
        self.assertEqual(calls[0]["function"]["name"], "write_file")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"])["content"], content)


if __name__ == "__main__":
    unittest.main()


class DoubleEscapeTests(unittest.TestCase):
    def test_literal_newlines_decoded(self):
        from cria.writeproxy import _repair_double_escaped
        self.assertEqual(_repair_double_escaped("def f():\\n    return 1"), "def f():\n    return 1")

    def test_real_newlines_left_alone(self):
        from cria.writeproxy import _repair_double_escaped
        self.assertEqual(_repair_double_escaped("has\nreal\nnewlines"), "has\nreal\nnewlines")
        self.assertEqual(_repair_double_escaped("no escapes here"), "no escapes here")
