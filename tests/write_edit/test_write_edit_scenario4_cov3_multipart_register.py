"""Lowering a read into a paged (multipart) read through the real writeproxy: a registration that fails leaves the ORDINARY read exactly as if multipart did not exist (and says why), and a
registration that succeeds swaps in the replacement under the new call id while the original command is handed to the fallback observer under the original receipt."""
import base64
import json
import re
from types import SimpleNamespace

import pytest

from cria import writeproxy
from cria.filecommands import MultipartCommandTooLarge
from cria.multipart import BridgeError

SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}


def lower(**hooks):
    call = {"id": "orig", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": "/ws/f.txt"})}}
    completion, events = {"choices": [{"message": {"tool_calls": [call]}}]}, []
    writeproxy.translate_outbound(completion, SHELL, SimpleNamespace(emit=lambda kind, **fields: events.append((kind, fields))), injected={"read_file"}, workspace_root="/ws", **hooks)
    return completion["choices"][0]["message"]["tool_calls"][0], events


def command(call):
    return json.loads(call["function"]["arguments"])["cmd"]


def receipt(cmd):
    """The correlation token a lowered command declares in its leading sentinel line."""
    return json.loads(base64.b64decode(cmd.splitlines()[0].split("⟧")[1]))["rcpt"]


def program(cmd):
    """The command's program with every per-lowering correlation token neutralised."""
    return re.sub(r"[0-9a-f]{16}", "R", cmd.split("\n", 1)[1])


def test_a_failed_multipart_registration_leaves_the_ordinary_read_and_says_why():
    """Whatever the bridge cannot do (no room, command too large), the model still gets the plain read byte for byte (same id, same receipt) and the operator one warn naming the cause."""
    plain, _ = lower()
    for error in (BridgeError("no room"), MultipartCommandTooLarge("too large")):
        def register(original, effect, receipt, error=error):
            raise error
        call, events = lower(multipart_command=register, multipart_new_id=lambda: "newid")
        assert call == plain
        assert [f for k, f in events if k == "multipart.register_failed"] == [{"level": "warn", "error": str(error)}]


def test_a_registered_multipart_read_replaces_the_command_and_the_original_goes_to_the_fallback_observer():
    """The replacement runs under the NEW id with its own receipt; the observer is handed the unreplaced read, under the new id, still stamped with the ORIGINAL receipt, so a lost paged read can
    fall back to the plain one; a registration answering None changes nothing."""
    plain, _ = lower()
    seen = []
    call, events = lower(multipart_command=lambda original, effect, receipt: "echo BRIDGED", multipart_new_id=lambda: "newid",
                         observe_multipart_fallback=lambda call_id, fallback: seen.append((call_id, fallback)))
    assert call["id"] == "newid" and command(call).endswith("\necho BRIDGED") and program(command(call)) == "echo BRIDGED"
    (fallback_id, fallback), = seen
    assert fallback_id == "newid" and fallback["id"] == "orig" and program(command(fallback)) == program(command(plain)) and not [k for k, _ in events if k == "multipart.register_failed"]
    assert receipt(command(fallback)) != receipt(command(call))               # the replacement is correlated to the new id; the fallback keeps the original read's token
    declined, _ = lower(multipart_command=lambda original, effect, receipt: None, multipart_new_id=lambda: "newid")
    assert program(command(declined)) == program(command(plain)) and not [k for k, _ in events if k == "multipart.register_failed"]
