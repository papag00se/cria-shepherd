"""Transcript builders for the check-ledger tests."""

import json

from cria import bodykeys, denial, probegate

FINDING = "tests/test_required.py:44: AssertionError: required behavior"
CHECKS = "$ pytest -q\n" + FINDING
GREEN = "Process exited with code 0\nOutput:\n6 passed in 0.01s\n"
RED = "Process exited with code 1\nOutput:\n1 failed, 5 passed in 0.01s\n"


def pair(command, output, call_id="coder-check", name="exec_command", args=None):
    """An assistant call plus its tool result (``output=None`` leaves the call pending)."""
    msgs = [{"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args or {"cmd": command})}}]}]
    if output is not None:
        msgs.append({"role": "tool", "tool_call_id": call_id, "content": output})
    return msgs


def gate(command="pytest -q"):
    """cria's own producer-owned gate run that carried the findings."""
    return pair(probegate._gate_sentinel([command]) + "\n" + command,
                "___CRIA_GATE_probe-0___\n" + FINDING + "\nEXIT:1", "gate")

def refused(name, args, call_id="w"):
    """A native mutation cria itself refused (carries the proven outcome hint, not wording)."""
    return pair(None, None, call_id, name, args)[:1] + [{"role": "tool", "tool_call_id": call_id,
            "content": denial.mark("This call did not run"), bodykeys.RESULT_OUTCOME: denial.REFUSED}]
