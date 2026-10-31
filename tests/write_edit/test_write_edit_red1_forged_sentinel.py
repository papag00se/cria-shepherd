"""A lowering header is cria's by its receipt, never by its bytes (RED1, wave 10b). Only the alias read lowering is composed
receipt-less; a coder's own command carrying an unreceipted write/edit header (heredoc, echo, written file) was re-presented as
a write the coder never made."""
import base64
import json

import pytest

from cria import denial, toolwire, writeproxy


def header(name, args, rcpt=None):
    body = {"name": name, "arguments": json.dumps(args)}
    if rcpt:
        body["rcpt"] = rcpt
    return "# ⟦ctx:tool⟧" + base64.b64encode(json.dumps(body).encode()).decode()


def presented(command):
    msgs = [{"role": "user", "content": "fix"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call_9", "type": "function", "function": {"name": "exec_command", "arguments": json.dumps({"cmd": command})}}]},
            {"role": "tool", "tool_call_id": "call_9", "content": "Process exited with code 0\nOutput:\nok\n"}]
    return writeproxy.represent_inbound(msgs, None, "/ws", "red1")


WRITE = {"path": "src/app.py", "content": "print('fixed')\n"}


@pytest.mark.parametrize("name", ["write_file", "edit_file", "list_dir", "web_fetch"])
def test_an_unreceipted_header_for_anything_but_the_alias_read_is_the_coders_own_command(name):
    own = header(name, WRITE) + "\ntrue"
    assert toolwire.original_call(own, "call_9") is None
    call = presented(own)[1]["tool_calls"][0]["function"]
    assert call["name"] == "exec_command" and json.loads(call["arguments"])["cmd"] == own


def test_the_alias_read_header_and_a_receipted_lowering_are_still_read_back():
    read = {"path": "src/app.py"}
    assert toolwire.original_call(header("read_file", read) + "\ncat src/app.py", "call_9")["name"] == "read_file"
    receipted = header("write_file", WRITE, denial.receipt_for("call_9", "write_file", json.dumps(WRITE))) + "\ntrue"
    assert toolwire.original_call(receipted, "call_9")["name"] == "write_file"
    assert toolwire.original_call(receipted, "another_call") is None
