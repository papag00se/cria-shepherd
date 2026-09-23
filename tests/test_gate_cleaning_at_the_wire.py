"""The coder wire never carries cria's completion-gate implementation."""

import base64
import hashlib
import json
import unittest

from cria import probegate, upstream


class _Rlog:
    phase = "coder-s1"

    def emit(self, *args, **kwargs):
        pass


def _transport_page(transport_id: str, result: str) -> str:
    data = result.encode()
    path = f"/tmp/.cria-gate-{transport_id}.wire"
    return "\n".join([
        probegate._transport_marker(transport_id),
        "path\t" + base64.b64encode(path.encode()).decode(),
        "offset\t0",
        f"total\t{len(data)}",
        "sha256\t" + hashlib.sha256(data).hexdigest(),
        "data\t" + base64.b64encode(data).decode(),
        probegate._transport_marker(transport_id, end=True),
    ])


def _wire(messages):
    raw, _estimate, _capture = upstream.Upstream(
        "http://unused", context_window=49152,
    )._prep({"model": "m", "messages": messages}, False, _Rlog())
    return json.loads(raw)


class GateCleaningAtTheWireTests(unittest.TestCase):
    def test_stamped_transport_gate_reaches_coder_only_as_probe_and_check_finding(self):
        transport_id = "0123456789abcdef01234567"
        command = "\n".join([
            probegate._gate_sentinel(["pytest -q tests/test_widget.py"]),
            "__cria_gate_file=/tmp/.cria-gate-internal",
            "echo ___CRIA_SURVEY___",
            probegate._transport_reader('"/tmp/.cria-gate-internal"', 0, transport_id),
        ])
        result = (f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
                  "tests/test_widget.py:17: AssertionError: expected 200\nEXIT:1\n")
        sent = _wire([
            {"role": "user", "content": "finish the fix"},
            {"role": "assistant", "tool_calls": [{
                "id": "gate-1", "type": "function", "function": {
                    "name": "exec_command", "arguments": json.dumps({"cmd": command}),
                },
            }]},
            {"role": "tool", "tool_call_id": "gate-1",
             "content": _transport_page(transport_id, result)},
        ])

        rendered = json.dumps(sent)
        self.assertIn("pytest -q tests/test_widget.py", rendered)
        self.assertIn("tests/test_widget.py:17", rendered)
        for internal in (
            probegate.GATE_SENTINEL, "__cria_", probegate.SECTION_PREFIX,
            "___CRIA_SURVEY_", probegate.TRANSPORT_PREFIX, "/tmp/.cria-gate-",
            "import base64, hashlib, os, sys", "data\\t",
        ):
            self.assertNotIn(internal, rendered)

    def test_unstamped_user_and_tool_marker_text_are_byte_identical(self):
        incidental = "user documentation mentions ___CRIA_GATE_probe-0___ literally"
        tool_text = "server echoed ___CRIA_GATE_TRANSPORT_0123456789abcdef01234567___ literally"
        messages = [
            {"role": "user", "content": incidental},
            {"role": "assistant", "tool_calls": [{
                "id": "ordinary-1", "type": "function", "function": {
                    "name": "exec_command", "arguments": json.dumps({"cmd": "echo ordinary"}),
                },
            }]},
            {"role": "tool", "tool_call_id": "ordinary-1", "content": tool_text},
        ]
        sent = _wire(messages)
        self.assertEqual(sent["messages"], messages)

    def test_gate_dedup_does_not_rewrite_ordinary_checker_results(self):
        transport_id = "fedcba987654321001234567"
        command = "\n".join([
            probegate._gate_sentinel(["pytest -q"]),
            "__cria_gate_file=/tmp/.cria-gate-internal",
            probegate._transport_reader('"/tmp/.cria-gate-internal"', 0, transport_id),
        ])
        gate_result = (f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
                       "tests/test_widget.py:17: AssertionError: expected 200\nEXIT:1\n")
        ordinary = probegate.CHECKS_MARKER + " ordinary_checker.py:9: duplicate finding"
        messages = [
            {"role": "user", "content": "finish the fix"},
            {"role": "assistant", "tool_calls": [{
                "id": "gate-1", "type": "function", "function": {
                    "name": "exec_command", "arguments": json.dumps({"cmd": command}),
                },
            }]},
            {"role": "tool", "tool_call_id": "gate-1",
             "content": _transport_page(transport_id, gate_result)},
        ]
        for call_id in ("ordinary-1", "ordinary-2"):
            messages.extend([
                {"role": "assistant", "tool_calls": [{
                    "id": call_id, "type": "function", "function": {
                        "name": "exec_command", "arguments": json.dumps({"cmd": "echo ordinary"}),
                    },
                }]},
                {"role": "tool", "tool_call_id": call_id, "content": ordinary},
            ])

        sent = _wire(messages)
        ordinary_results = [m["content"] for m in sent["messages"]
                            if m.get("tool_call_id") in {"ordinary-1", "ordinary-2"}]
        self.assertEqual(ordinary_results, [ordinary, ordinary])

    def test_no_gate_body_is_byte_identical(self):
        messages = [{"role": "system", "content": "system"},
                    {"role": "user", "content": "ordinary request"}]
        sent = _wire(messages)
        self.assertEqual(sent, {"model": "m", "messages": messages, "stream": False})


if __name__ == "__main__":
    unittest.main()
