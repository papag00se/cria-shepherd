"""nemotron-nano 1786243834 died in a 400 loop (calls 0075-0081): six identical
`Conversation roles must alternate between user/tool and assistant` template exceptions, then the
harness gave up on an empty workspace.

The body that 400d ended `tool` (a denied read result) then `user` (focustrim's repeat-note). Both
are user-side turns to a Llama-lineage template. The merge that exists to fix that —
`merge_consecutive_turns` — ran inside `Role.apply`, MID-PIPELINE, so anything appended afterwards
undid it. Four call sites append user-side turns after `Role.apply`:

  * `loop._drive_single_item` (plan-off) — role.apply, THEN focustrim.trim. Every one of calls
    0075-0081 was phase `coder-s1` from this driver; the run made zero proxy calls.
  * `loop.guard_rumination` and `loop.guard_truncation` — both append a `user` retry turn to a
    `framed` body the coder role has already been applied to.
  * `server.py`'s streaming proxy — applies the role and never trims at all.

The FIRST fix for this swapped two lines in `server.py`, on the strength of a mis-read of which
driver produced the 400s. It was reverted: it fixed a path that made no calls, and ordering two
lines per call site is a band-aid per site (#4) that the next appender breaks again.

The merge now runs at the WIRE (`Upstream._prep` → `massage.merge_for_alternation`), as the last
message transform before serialization, next to the assistant-side twin and the unconditional
orphan-`tool` repair that live there for the same reason. `Role.apply` only sets the hint. There
is no "later" at the wire, so no call site can defeat it.
"""
import inspect
import unittest

from cria import focustrim, massage, upstream
from cria.config import Role


def _dup_history():
    """A body whose tail is `assistant(tool_call), tool` — so focustrim's appended repeat-note
    lands directly after a tool result, the exact 0075 shape."""
    msgs = [{"role": "system", "content": "sys"},
            {"role": "user", "content": "task"}]
    for i in range(3):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path": "./tmp/read-only/spec.json"}'}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}",
                     "content": "⟦ctx:denied⟧ large reference document ..."})
    return msgs


def _alternates(msgs):
    side = lambda r: "u" if r in ("user", "tool") else "a"
    seq = [side(m["role"]) for m in msgs if m["role"] != "system"]
    return all(a != b for a, b in zip(seq, seq[1:]))


NANO = Role(name="coder", backend="local", think_protocol="system_directive",
            merge_consecutive_turns=True)
PLAIN = Role(name="coder", backend="local")


class TheMergeSurvivesALaterAppendTests(unittest.TestCase):
    """The property the old placement could not hold: apply the role FIRST (as the plan-off driver
    and both retry guards do), append after, and the wire still emits an alternating body."""

    def test_role_then_append_still_alternates_at_the_wire(self):
        body = {"messages": _dup_history()}
        NANO.apply(body)                                     # role first, as the drivers do
        trimmed, rep = focustrim.trim(body["messages"])       # …then the appending transform
        self.assertTrue(rep.applied)
        self.assertFalse(_alternates(trimmed), "precondition: the appended note breaks alternation")
        body["messages"] = trimmed
        self.assertTrue(_alternates(massage.merge_for_alternation(body["messages"])))

    def test_a_retry_turn_appended_after_the_role_also_survives(self):
        """guard_rumination / guard_truncation shape: a bare user turn after a tool result."""
        body = {"messages": _dup_history()}
        NANO.apply(body)
        body["messages"] = body["messages"] + [{"role": "user", "content": "that write was cut off"}]
        self.assertTrue(_alternates(massage.merge_for_alternation(body["messages"])))


class TheHintIsCarriedNotTheTransformTests(unittest.TestCase):
    def test_apply_sets_the_hint_and_leaves_the_messages_alone(self):
        body = {"messages": _dup_history()}
        before = [dict(m) for m in body["messages"]]
        NANO.apply(body)
        self.assertTrue(body[massage.MERGE_TURNS_KEY])
        self.assertEqual(body["messages"], before)   # the merge is the wire's job now

    def test_a_role_without_the_flag_sets_no_hint(self):
        body = {"messages": _dup_history()}
        PLAIN.apply(body)
        self.assertNotIn(massage.MERGE_TURNS_KEY, body)

    def test_the_wire_consumes_and_strips_the_hint(self):
        """Asserts the OUTCOME, not the line that produces it.

        This used to pin the literal source `out.pop(massage.MERGE_TURNS_KEY, None)`, which made a
        strictly better implementation fail: the wire now strips every cria-internal key from
        `bodykeys.ALL` in one loop, so the hint is removed by the list rather than by name. Pinning
        an instance where the rule is about a class is how a guard passes while the rule ships
        broken — see tests/test_no_internal_key_reaches_the_wire.py."""
        from cria import bodykeys
        src = inspect.getsource(upstream.Upstream._prep)
        self.assertIn("massage.merge_for_alternation", src)   # the transform is still AT the wire
        self.assertIn(massage.MERGE_TURNS_KEY, bodykeys.ALL)  # and the hint is in the stripped set
        self.assertIn("bodykeys.ALL", src)

    def test_the_merge_is_the_last_message_transform(self):
        """If a transform is ever added after it, the bug comes straight back."""
        src = inspect.getsource(upstream.Upstream._prep)
        after = src[src.index("massage.merge_for_alternation"):]
        self.assertNotIn("msgs =", after.split('out["messages"]')[0],
                         "a message transform runs after the alternation merge")


class NoOpForEveryModelThatDoesNotAskTests(unittest.TestCase):
    """gemma4, qwen35, qwythos, mellum2, ornith, ternary-bonsai, nemotron-elastic: no role sets
    merge_consecutive_turns, so their bodies must be byte-identical to before this moved."""

    def test_without_the_hint_the_wire_changes_nothing(self):
        msgs = _dup_history() + [{"role": "user", "content": "a second user turn in a row"}]
        self.assertEqual(massage.merge_for_alternation(msgs), msgs if _alternates(msgs) else
                         massage.merge_for_alternation(msgs))
        # the real invariant: the wire only calls it when the hint is present
        src = inspect.getsource(upstream.Upstream._prep)
        self.assertIn("if body.get(massage.MERGE_TURNS_KEY):", src)

    def test_consecutive_user_turns_are_untouched_without_the_flag(self):
        body = {"messages": [{"role": "system", "content": "s"},
                             {"role": "user", "content": "a"},
                             {"role": "user", "content": "b"}]}
        PLAIN.apply(body)
        self.assertEqual(len(body["messages"]), 3)


class TheMergeItselfTests(unittest.TestCase):
    def test_it_merges_a_tool_then_user_pair(self):
        out = massage.merge_for_alternation(
            [{"role": "system", "content": "s"},
             {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function",
              "function": {"name": "f", "arguments": "{}"}}]},
             {"role": "tool", "tool_call_id": "c", "content": "result"},
             {"role": "user", "content": "note"}])
        self.assertEqual(out[-1]["role"], "tool")          # the run keeps its FIRST role
        self.assertIn("result", out[-1]["content"])
        self.assertIn("note", out[-1]["content"])

    def test_it_never_folds_a_turn_carrying_tool_calls(self):
        msgs = [{"role": "assistant", "content": "a", "tool_calls": [{"id": "1"}]},
                {"role": "assistant", "content": "b"}]
        self.assertEqual(len(massage.merge_for_alternation(msgs)), 2)

    def test_the_system_head_is_left_in_place(self):
        out = massage.merge_for_alternation([{"role": "system", "content": "s"},
                                             {"role": "user", "content": "a"}])
        self.assertEqual(out[0]["role"], "system")

    def test_short_and_malformed_inputs_pass_through(self):
        for m in ([], [{"role": "user", "content": "x"}], None, "not a list"):
            self.assertEqual(massage.merge_for_alternation(m), m)


if __name__ == "__main__":
    unittest.main()
