"""Lowering a read into a paged (multipart) read through the real writeproxy: a registration that fails leaves the ORDINARY read exactly as if multipart did not exist (and says why), and a
registration that succeeds swaps in the replacement under the new call id while the original command is handed to the fallback observer under the original receipt."""
import base64
import json
import re
from types import SimpleNamespace

import pytest

from cria import multipartcontext, writeproxy
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


def test_a_shell_call_the_normalizer_privately_aliased_to_a_read_is_paged_and_an_ordinary_shell_call_is_not():
    """A call named for the harness shell that the normalization producer recorded as a read (the held identity, never a guess from its text) is lowered AS that read and offered to the paged-read
    registration; the same shell call with no held identity, or outside the request scope, is the harness's own command and is never registered."""
    def lower_shell(alias=None, scoped=True):
        call = {"id": "shell", "type": "function", "function": {"name": "exec_command", "arguments": json.dumps({"cmd": "ls"})}}
        completion, registered = {"choices": [{"message": {"tool_calls": [call]}}]}, []
        def register(original, effect, receipt):
            registered.append((original["function"]["name"], json.loads(original["function"]["arguments"])))
            return "echo BRIDGED"
        def run():
            if alias is not None:
                multipartcontext.record(call, json.dumps(alias))
            writeproxy.translate_outbound(completion, SHELL, injected={"read_file"}, workspace_root="/ws", multipart_command=register, multipart_new_id=lambda: "newid")
        if scoped:
            with multipartcontext.bound():
                run()
        else:
            run()
        return completion["choices"][0]["message"]["tool_calls"][0], registered
    bridged, registered = lower_shell({"path": "/ws/f.txt"})
    assert registered == [("read_file", {"path": "/ws/f.txt"})] and bridged["id"] == "newid" and command(bridged).endswith("\necho BRIDGED")
    ordinary, registered = lower_shell()
    assert registered == [] and ordinary["id"] == "shell" and command(ordinary) == "ls"
    unscoped, registered = lower_shell({"path": "/ws/f.txt"}, scoped=False)
    assert registered == [] and command(unscoped) == "ls"
