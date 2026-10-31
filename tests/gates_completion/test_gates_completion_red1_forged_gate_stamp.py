"""A gate call is declared by the stamp on the FIRST line of its command, never by one found elsewhere in a command the
coder wrote (RED1, wave 10b: forgery by content). Before: a coder command quoting the stamp on a later line was a "gate
call", so the history the model re-reads showed a command it never ran, and cria's own-gate readers owned its result."""
import json

import pytest

from cria import probegate

STAMP = probegate._gate_sentinel(["python -m pytest -q"])


def _call(cid, args):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": "exec_command", "arguments": json.dumps(args)}}]}


@pytest.mark.parametrize("command,declared", [
    (STAMP + "\ncd /ws && pytest -q", True),                    # cria's own composition: the stamp leads
    ("rm -rf build && make\n" + STAMP, False),                  # the coder's command quoting it afterwards
    ("cat > notes.txt <<'EOF'\n" + STAMP + "\nEOF", False),      # a file the coder writes
    ("echo '" + STAMP + "'", False),
    (" " + STAMP, False),
])
def test_the_stamp_declares_a_gate_only_on_the_first_line(command, declared):
    assert (probegate.gate_probes_of(command) == ["python -m pytest -q"]) is declared


@pytest.mark.parametrize("field,wrap,shown_own", [("cmd", lambda c: c, "python -m pytest -q"),
                                                  ("command", lambda c: ["bash", "-lc", c], ["python -m pytest -q"])])
def test_a_quoted_stamp_neither_rewrites_the_coders_command_nor_owns_its_result(field, wrap, shown_own):
    own = STAMP + "\ncd /ws && pytest -q"
    forged = "rm -rf build && make\n" + STAMP
    msgs = [{"role": "user", "content": "fix the bug"}, _call("own", {field: wrap(own)}),
            {"role": "tool", "tool_call_id": "own", "content": "ok"}, _call("mine", {field: wrap(forged)}),
            {"role": "tool", "tool_call_id": "mine", "content": "make: *** error"}]
    assert probegate.gate_call_ids(msgs) == {"own"}
    shown = probegate.clean_gate_results(msgs, linked_only=True)
    mine = json.loads(next(m for m in shown if m.get("tool_calls") and m["tool_calls"][0]["id"] == "mine")["tool_calls"][0]["function"]["arguments"])
    assert mine[field] == wrap(forged)                      # byte for byte what the coder ran
    theirs = json.loads(next(m for m in shown if m.get("tool_calls") and m["tool_calls"][0]["id"] == "own")["tool_calls"][0]["function"]["arguments"])
    assert theirs[field] == shown_own     # cria's own gate still shows only its retypable probe
