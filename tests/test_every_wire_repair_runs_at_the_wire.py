"""Three of the five repairs in `Upstream._prep` could be deleted and the suite stayed green.

Rule 24 is the only doctrine rule whose whole point is WHERE the code runs. `_prep` is that place —
the last thing before the JSON goes on the wire — and it holds five message transforms. A mutation
pass over the repo (217 mutations, 119 survivors) deleted each one in turn:

    contextfloor.fit(...)                        deleting it is KILLED
    massage.repair_history_tool_args(msgs, rlog) deleting it SURVIVES
    contextfloor.ensure_tool_integrity(msgs)     deleting it SURVIVES
    _merge_consecutive_assistant(msgs)           deleting it SURVIVES
    massage.merge_for_alternation(msgs)          deleting it is KILLED

Every test for the three survivors calls the function DIRECTLY — `tests/test_massage.py`,
`tests/test_contextfloor.py`, `tests/test_upstream.py`'s five thorough `_merge_consecutive_assistant`
tests. The one test whose name asserts the wire property,
`test_ensure_tool_integrity_converts_orphan_to_user_unconditionally`, is exactly the one that cannot
see whether the unconditional call site exists.

It can happen and it has: the sibling file's own docstring records the alternation fix being "two
lines swapped in `server.py`", reverted. Each of these three is a repair for a structural 400 that
poisons every later turn of a session:

* a malformed `tool_call` in replayed history 500s a strict template on EVERY turn until it is
  repaired, not just the turn that produced it;
* an orphan `tool` message — its assistant call folded away by compaction — 400s a strict template,
  and the floor's own orphan strip runs only when the request is OVER budget, so a fitting request
  ships the orphan;
* a bare assistant turn is a structural 400 on the gemma template.

So each is asserted on the OUTCOME of the real `_prep`, the way the alternation hint already is.
"""

import json
import unittest

from cria import massage, upstream


class _NullRlog:
    phase = ""

    def emit(self, *a, **k):
        pass


def _out(msgs, **extra):
    up = upstream.Upstream("http://x", context_window=8192)
    raw, _est, _path = up._prep({"model": "m", "messages": msgs, **extra}, True, _NullRlog())
    return json.loads(raw)


class ARepairedHistoryReachesTheWireTests(unittest.TestCase):
    def test_a_malformed_historical_tool_call_is_repaired_before_it_is_sent(self):
        msgs = [
            {"role": "user", "content": "fix it"},
            {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {
                # over-escaped nested quotes — what a weak model emits for a shell command
                "name": "exec_command", "arguments": '{"cmd": "echo \\\\"hi\\\\""}}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "hi"},
        ]
        sent = _out(msgs)
        args = sent["messages"][1]["tool_calls"][0]["function"]["arguments"]
        json.loads(args)   # the whole point: what goes on the wire must re-parse

    def test_an_orphan_tool_message_never_reaches_the_wire(self):
        """Its assistant call was folded away by compaction. A strict template 400s on it."""
        msgs = [
            {"role": "user", "content": "go"},
            {"role": "tool", "tool_call_id": "gone", "content": "the result of a call nobody sees"},
            {"role": "user", "content": "and now?"},
        ]
        sent = _out(msgs)
        self.assertNotIn("tool", [m.get("role") for m in sent["messages"]])
        self.assertIn("the result of a call nobody sees",
                      "".join(str(m.get("content") or "") for m in sent["messages"]))

    def test_a_bare_assistant_turn_never_reaches_the_wire(self):
        """A structural 400 on the gemma template — recorded in the module and re-verified here."""
        msgs = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "here is the answer"},
        ]
        sent = _out(msgs)
        empties = [m for m in sent["messages"]
                   if m.get("role") == "assistant" and not (m.get("content") or m.get("tool_calls"))]
        self.assertEqual(empties, [])
        self.assertIn("here is the answer",
                      "".join(str(m.get("content") or "") for m in sent["messages"]))

    def test_the_alternation_merge_still_runs_here_too(self):
        """The control: this one was already killed by a mutation, and must stay that way."""
        msgs = [{"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
                {"role": "user", "content": "c"},
                {"role": "user", "content": "d"}]
        sent = _out(msgs, **{massage.MERGE_TURNS_KEY: True})
        roles = [m["role"] for m in sent["messages"]]
        self.assertEqual(roles, sorted(set(roles), key=roles.index) if len(roles) < 2 else roles)
        self.assertFalse(any(a == b for a, b in zip(roles, roles[1:])), roles)


if __name__ == "__main__":
    unittest.main()
