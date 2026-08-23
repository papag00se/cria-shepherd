"""The model's own history showed it running an empty command, with cria's answer under it.

`_strip_gate_plumbing` returns "" when no probe in a gate script is retypable — "a cria-authored
call the model never made has nothing in it for the model", in its own words. It emptied the
command and left the CALL standing, so 188 prompts carried:

    <function=exec_command>
    <parameter=cmd>

    </parameter>
    …
    <tool_response>
    ⟦ctx:checks⟧ the repo's own checks that ran reported no error-class problems. …

All 188 are from 2026-08-22 on the node cell, where every probe is a `node --check` cria composed,
so nothing in the script was ever the model's to retype.

The RESULT is real ground truth and is the whole point of the gate, so it stays — as a plain
message, which is what it always was. A result with no call is not a result, and the drop path for
exactly this already existed ten lines away (`drop_ids`).

A gate that DOES carry something the coder could retype keeps its call and its tool result, because
there the pair is true: the script holds a command the model can run itself.
"""

import json
import unittest

from cria import probegate as pg

_RESULT = f"{pg.SECTION_PREFIX}probe-0___\nno problems reported\nEXIT:0"


def _gate(retypable):
    script = (pg._gate_sentinel(retypable) + "\ncd /ws || exit 97\n"
              + "echo " + pg._marker("probe-0") + "\nnode --check a.js\n")
    return [
        {"role": "user", "content": "build it"},
        {"role": "assistant", "tool_calls": [{"id": "g1", "type": "function", "function": {
            "name": "exec_command", "arguments": json.dumps({"cmd": script})}}]},
        {"role": "tool", "tool_call_id": "g1", "content": _RESULT},
    ]


class ACriaAuthoredGateIsNotTheModelsCallTests(unittest.TestCase):
    def test_the_empty_call_never_reaches_the_model(self):
        out = pg.clean_gate_results(_gate([]), None)
        self.assertEqual([m.get("role") for m in out], ["user", "user"])
        self.assertFalse(any(m.get("tool_calls") for m in out))

    def test_the_checks_block_survives_whole(self):
        out = pg.clean_gate_results(_gate([]), None)
        self.assertIn(pg.CHECKS_MARKER, out[-1]["content"])

    def test_no_result_is_left_without_its_call(self):
        """An orphan `tool` message 400s a strict template; it is a message, not a result."""
        out = pg.clean_gate_results(_gate([]), None)
        self.assertNotIn("tool", [m.get("role") for m in out])

    def test_a_retypable_gate_keeps_its_call_and_its_result(self):
        """There the pair is TRUE — the script holds a command the coder can run itself."""
        out = pg.clean_gate_results(_gate(["pytest -q"]), None)
        self.assertEqual([m.get("role") for m in out], ["user", "assistant", "tool"])
        cmd = json.loads(out[1]["tool_calls"][0]["function"]["arguments"])["cmd"]
        self.assertIn("pytest -q", cmd)

    def test_the_id_set_is_read_from_the_command_not_guessed(self):
        msgs = _gate([])
        self.assertEqual(pg.cria_authored_call_ids(msgs[1]), {"g1"})
        self.assertEqual(pg.cria_authored_call_ids(_gate(["pytest -q"])[1]), set())

    def test_an_ordinary_model_call_is_untouched(self):
        m = {"role": "assistant", "tool_calls": [{"id": "x", "type": "function", "function": {
            "name": "exec_command", "arguments": json.dumps({"cmd": "ls -la"})}}]}
        self.assertEqual(pg.cria_authored_call_ids(m), set())


if __name__ == "__main__":
    unittest.main()
