"""The verbatim tail of a compacted view starts at a whole exchange.

A tool result is the answer to one assistant call. When the token budget put the tail's first message on a
RESULT, the issuing assistant turn went into the rollup and the result rode on alone: the wire
(`contextfloor.ensure_tool_integrity`) could only turn it into a bare ``user`` message, so the coder read a
file's text, a compiler transcript or "Wrote src/main/java/pipeline/Importer.java" in the user's voice with
the call (and its path) gone. Rebuilt from 315 real self-compactions (ornith1.5_9b / Java, 2026-10-22..28)
by the current code, 60 shipped such a result; ornith-java-overnight-c7dd… call 0039 index 4 is one.
"""
import unittest

from cria import contextfloor, selfcompact
from cria.selfcompact import CompactState, compact


def _call(cid, name="read_file", args="{}"):
    return {"role": "assistant", "content": f"calling {name}",
            "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": args}}]}


def _result(cid, text):
    return {"role": "tool", "tool_call_id": cid, "content": text}


def _history():
    """Every exchange is ~140 tokens, so a tail budget of 145 can only hold the LAST result without
    its call — the cut lands between a call and its result."""
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "the task"}]
    for i in range(6):
        msgs.append(_call(f"c{i}", args='{"path": "f%d"}' % i))
        msgs.append(_result(f"c{i}", f"result-{i} " + "y" * 560))
    return msgs


def _pairing(msgs):
    calls = {tc["id"] for m in msgs if m.get("role") == "assistant" for tc in m.get("tool_calls") or []}
    results = {m["tool_call_id"] for m in msgs if m.get("role") == "tool"}
    return calls, results


class TailStartsAtAnExchangeTests(unittest.TestCase):
    def test_a_budget_cut_between_call_and_result_keeps_the_pair_together(self):
        msgs = _history()
        out, _state, applied = compact(msgs, lambda mm, **kw: "ROLLUP", CompactState(),
                                       room_tokens=100, keep_tail_tokens=145, recompact_tokens=20)
        self.assertTrue(applied)
        calls, results = _pairing(out)
        self.assertEqual(results - calls, set(), "a tool result rode on without its call")
        self.assertEqual(calls - results, set(), "a call rode on without its result")
        self.assertTrue(results, "the newest result must stay verbatim")

    def test_the_wire_has_nothing_to_repair_on_a_compacted_view(self):
        msgs = _history()
        out, _state, _applied = compact(msgs, lambda mm, **kw: "ROLLUP", CompactState(),
                                        room_tokens=100, keep_tail_tokens=145, recompact_tokens=20)
        _fixed, repaired = contextfloor.ensure_tool_integrity(out)
        self.assertEqual(repaired, 0)

    def test_the_writer_is_not_shown_a_result_whose_call_stays_verbatim(self):
        msgs = _history()
        seen = []
        compact(msgs, lambda mm, **kw: (seen.append(mm), "ROLLUP")[1], CompactState(),
                room_tokens=100, keep_tail_tokens=145, recompact_tokens=20)
        calls, results = _pairing(seen[0])
        self.assertEqual(calls, results, "the summarized middle must hold whole exchanges")

    def test_a_tail_that_would_swallow_the_whole_history_folds_nothing(self):
        msgs = [{"role": "system", "content": "sys"}, _call("only"), _result("only", "z" * 600)]
        out, _state, applied = compact(msgs, lambda mm, **kw: "ROLLUP", CompactState(),
                                       room_tokens=10, keep_tail_tokens=40, recompact_tokens=5)
        self.assertFalse(applied)
        self.assertIs(out, msgs)

    def test_a_step_boundary_still_keeps_no_tail(self):
        msgs = _history()
        out, _state, applied = compact(msgs, lambda mm, **kw: "ROLLUP", CompactState(), force=True,
                                       room_tokens=100, keep_tail_tokens=145, recompact_tokens=20,
                                       boundary_keep_tail_tokens=0)
        self.assertTrue(applied)
        self.assertFalse([m for m in out if m.get("role") in ("tool",) or m.get("tool_calls")])


if __name__ == "__main__":
    unittest.main()
