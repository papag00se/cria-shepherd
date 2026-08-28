"""`{}` is not a repair of a tool call — it is the deletion of one.

`repair_tool_args` falls back to `extract_json_object` when a call's arguments will not parse. That
returns the FIRST brace-balanced span which parses to a dict. On a CUT argument string the first such
span is very often an empty brace pair belonging to the code the model was writing:

    {"cmd":"cat > t.go <<EOF\\nfunc main() {}\\nEOF\\ncat > u.go <<EOF\\nfunc x() {

`func main() {}` gives `{}`. It is a dict. The arguments were replaced with it, and the command the
model wrote was gone.

Found four times on this machine's captures, by scanning every tool-call argument string in every
session — 14,392 of them, 14 not valid JSON. Four `write_file` calls of 6,026, 6,277, 6,893 and
28,571 characters, one of them a whole test file, all recovering to `{}`.

All four sat on turns the rumination backstop had already aborted, so no damage is observed. The
hazard is the same shape on a turn the MODEL cut itself (`finish_reason="length"`), which the same
corpus also has — three of them in the ladder runs alone.

The rule is the narrow one: an empty object never replaces a non-empty raw string. No threshold, no
schema. Every partial recovery still lands, because those carry values the model actually wrote.
"""

import copy
import json
import unittest

from cria import massage


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def call(name, raw):
    return {"choices": [{"finish_reason": "length", "message": {"content": "", "tool_calls": [
        {"id": "a", "type": "function", "function": {"name": name, "arguments": raw}}]}}]}


def args_of(c):
    return c["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]


CUT = '{"cmd":"cat > t.go <<EOF\\nfunc main() {}\\nEOF\\ncat > u.go <<EOF\\nfunc x() {'


class AnEmptyRecoveryIsRefusedTests(unittest.TestCase):
    def test_the_measured_shape(self):
        rlog = _Rlog()
        out = massage.repair_tool_args(copy.deepcopy(call("exec_command", CUT)), rlog)
        self.assertEqual(args_of(out), CUT, "the model's own bytes must survive")
        self.assertIn("massage.args_recovery_refused", rlog.kinds())

    def test_it_is_the_empty_object_that_is_refused_not_the_truncation(self):
        """A cut string with no empty brace pair in it recovers nothing anyway — this rule is about
        what the fallback RETURNS, not about how the string ended."""
        raw = '{"cmd":"echo hello'
        out = massage.repair_tool_args(copy.deepcopy(call("exec_command", raw)), _Rlog())
        self.assertEqual(args_of(out), raw)

    def test_an_empty_object_the_model_actually_wrote_is_untouched(self):
        """`{}` that PARSES is valid JSON and never reaches the fallback. A tool with no arguments
        is a real call."""
        out = massage.repair_tool_args(copy.deepcopy(call("list_dir", "{}")), _Rlog())
        self.assertEqual(args_of(out), "{}")


class EveryRealRepairStillLandsTests(unittest.TestCase):
    """The fix may only remove the case where nothing was recovered. These carry the model's values."""

    def test_a_fenced_object(self):
        out = massage.repair_tool_args(
            copy.deepcopy(call("write_file", '```json\n{"path": "x"}\n```')), _Rlog())
        self.assertEqual(json.loads(args_of(out)), {"path": "x"})

    def test_an_object_with_prose_after_it(self):
        out = massage.repair_tool_args(copy.deepcopy(call("x", '{"a": 1} hope that helps')), _Rlog())
        self.assertEqual(json.loads(args_of(out)), {"a": 1})

    def test_a_write_rebuilt_from_raw_newlines(self):
        raw = '{"path": "h.py", "content": "def h():\n    return 1\n"}'
        out = massage.repair_tool_args(copy.deepcopy(call("write_file", raw)), _Rlog())
        got = json.loads(args_of(out))
        self.assertEqual(got["path"], "h.py")
        self.assertIn("def h():", got["content"])

    def test_valid_arguments_are_never_touched(self):
        out = massage.repair_tool_args(copy.deepcopy(call("x", '{"a": 1}')), _Rlog())
        self.assertEqual(args_of(out), '{"a": 1}')


class TheRefusalIsVisibleTests(unittest.TestCase):
    def test_it_says_which_tool_and_how_much_was_at_stake(self):
        """A silent refusal is a mechanism nobody can measure (#12)."""
        rlog = _Rlog()
        massage.repair_tool_args(copy.deepcopy(call("write_file", CUT)), rlog)
        kw = dict(rlog.events)["massage.args_recovery_refused"]
        self.assertEqual(kw["tool"], "write_file")
        self.assertEqual(kw["raw_chars"], len(CUT))


if __name__ == "__main__":
    unittest.main()
