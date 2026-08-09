"""The nemotron-nano 1786243834 run died in a 400 loop (calls 0075-0081): six identical
`Conversation roles must alternate between user/tool and assistant` template exceptions, harness
exit, empty workspace.

The shape that 400d: body 0075 ended `tool` (the denied read result) then `user` (focustrim's
repeat-note). Both are user-side turns to a Llama-lineage template. The alternation merge exists
for exactly this — but on the PROXY path it ran FIRST: server.py had

    self._focus_trim(self._apply_route_role(pbody, indic), rlog)

so the note focustrim appends landed AFTER the merge had already run, unmerged. The drive path
orders these correctly (loop.py: trim, then coder_role.apply) — at call 0073 the very same note
was folded into the tool message. One path merged, the other 400d, same code state.
"""
import inspect
import re
import unittest

from cria import focustrim, server
from cria.config import _merge_for_alternation


def _mk_dup_history():
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


class TheMergeMustSeeTheFinalMessageListTests(unittest.TestCase):
    def test_trim_then_merge_alternates(self):
        trimmed, rep = focustrim.trim(_mk_dup_history())
        self.assertTrue(rep.applied)
        body = {"messages": trimmed}
        _merge_for_alternation(body)
        self.assertTrue(_alternates(body["messages"]))

    def test_merge_then_trim_is_the_400_shape(self):
        """Documents WHY the order matters — the reverse order ends tool,user: the exact body
        the Nemotron template rejects. If this ever starts passing, the trim stopped appending
        user-side notes and the ordering constraint can be revisited."""
        body = {"messages": _mk_dup_history()}
        _merge_for_alternation(body)
        trimmed, _ = focustrim.trim(body["messages"])
        self.assertFalse(_alternates(trimmed))

    def test_the_proxy_path_trims_before_applying_the_role(self):
        src = inspect.getsource(server)
        self.assertIsNone(
            re.search(r"_focus_trim\(\s*self\._apply_route_role", src),
            "the proxy path still applies the role before focustrim — the trim's appended "
            "user note lands after the alternation merge and 400s strict templates")
        self.assertRegex(src, r"_apply_route_role\(\s*self\._focus_trim")


if __name__ == "__main__":
    unittest.main()
