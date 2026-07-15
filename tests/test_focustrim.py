import unittest

from cria.focustrim import trim


def _asst(cid, name, args):
    return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function",
            "function": {"name": name, "arguments": args}}]}


def _result(cid, content):
    return {"role": "tool", "tool_call_id": cid, "content": content}


class FocusTrimTests(unittest.TestCase):
    def test_collapses_exact_duplicate_calls_keeping_last(self):
        msgs = [
            {"role": "user", "content": "build it"},
            _asst("A", "exec", '{"cmd": "cat x"}'), _result("A", "no such file"),
            _asst("B", "exec", '{"cmd": "cat x"}'), _result("B", "no such file"),  # dup
            _asst("C", "exec", '{"cmd": "cat x"}'), _result("C", "def f(): ..."),  # dup (last → kept)
        ]
        out, rep = trim(msgs)
        self.assertTrue(rep.applied)
        self.assertEqual(rep.dropped_calls, 2)
        self.assertEqual(rep.dropped_msgs, 2)                 # both emptied assistant turns dropped
        ids = [tc["id"] for m in out if m.get("role") == "assistant" for tc in m["tool_calls"]]
        self.assertEqual(ids, ["C"])                          # only the last occurrence survives
        tool_ids = [m["tool_call_id"] for m in out if m.get("role") == "tool"]
        self.assertEqual(tool_ids, ["C"])                     # its result stays; the orphans go
        self.assertEqual(out[0], {"role": "user", "content": "build it"})

    def test_no_orphaned_results_and_distinct_calls_kept(self):
        msgs = [
            _asst("A", "exec", '{"cmd": "ls"}'), _result("A", "a\nb"),
            _asst("B", "exec", '{"cmd": "cat y"}'), _result("B", "content"),   # distinct → kept
            _asst("C", "exec", '{"cmd": "ls"}'), _result("C", "a\nb"),         # dup of A
        ]
        out, rep = trim(msgs)
        self.assertEqual(rep.dropped_calls, 1)
        # every tool result still has a matching assistant tool_call
        call_ids = {tc["id"] for m in out if m.get("role") == "assistant" for tc in m["tool_calls"]}
        res_ids = {m["tool_call_id"] for m in out if m.get("role") == "tool"}
        self.assertEqual(res_ids, call_ids)                   # no orphans
        self.assertIn("B", call_ids)                          # the distinct call survives

    def test_arguments_normalized_key_order_and_whitespace(self):
        msgs = [
            _asst("A", "exec", '{"cmd": "x", "timeout": 5}'), _result("A", "r"),
            _asst("B", "exec", '{"timeout": 5, "cmd": "x"}'), _result("B", "r"),  # same, reordered
        ]
        out, rep = trim(msgs)
        self.assertEqual(rep.dropped_calls, 1)                # canonicalized → recognized as dup

    def test_keeps_assistant_text_when_dropping_its_dup_call(self):
        # keep-LAST drops the EARLIER occurrence, so put the text on the earlier (dropped) call:
        # its call+result go, but the text stays (the message is not emptied).
        msgs = [
            {"role": "assistant", "content": "thinking out loud",
             "tool_calls": [{"id": "A", "type": "function", "function": {"name": "exec", "arguments": '{"cmd": "x"}'}}]},
            _result("A", "r"),
            _asst("B", "exec", '{"cmd": "x"}'), _result("B", "r"),   # later dup → kept
        ]
        out, rep = trim(msgs)
        self.assertEqual(rep.dropped_calls, 1)                # the earlier call A removed
        self.assertEqual(rep.dropped_msgs, 0)                 # message has text → not dropped
        keep = [m for m in out if m.get("content") == "thinking out loud"]
        self.assertEqual(len(keep), 1)
        self.assertEqual(keep[0].get("tool_calls"), [])       # its dup call removed, text kept
        self.assertNotIn("A", [m.get("tool_call_id") for m in out if m.get("role") == "tool"])

    def test_no_dupes_returns_same_list(self):
        msgs = [_asst("A", "exec", '{"cmd": "a"}'), _result("A", "r")]
        out, rep = trim(msgs)
        self.assertFalse(rep.applied)
        self.assertIs(out, msgs)                              # no copy when nothing to do

    def test_does_not_mutate_input(self):
        msgs = [_asst("A", "e", '{"c":1}'), _result("A", "r"), _asst("B", "e", '{"c":1}'), _result("B", "r")]
        before = len(msgs)
        trim(msgs)
        self.assertEqual(len(msgs), before)                  # original untouched


if __name__ == "__main__":
    unittest.main()


def _fail_action(cid, cmd):
    return [{"role": "assistant", "tool_calls": [{"id": cid, "type": "function",
             "function": {"name": "exec_command", "arguments": '{"cmd": "%s"}' % cmd}}]},
            {"role": "tool", "tool_call_id": cid, "content": "%s: No such file or directory\nProcess exited with code 1" % cmd}]


class ErrorSquashTests(unittest.TestCase):
    def test_squashes_a_run_of_distinct_failures_keeping_recent(self):
        msgs = [{"role": "user", "content": "build it"}]
        for i, cmd in enumerate(["cat a", "cat b", "find c", "ls d", "grep e", "cat f"]):
            msgs += _fail_action(f"c{i}", cmd)   # 6 DISTINCT failing commands (v1 dup-collapse won't touch)
        out, rep = trim(msgs)
        self.assertEqual(rep.squashed_runs, 1)
        self.assertEqual(rep.dropped_calls, 4)               # 6 - keep(2) = 4 dropped
        # exactly the last 2 failing commands survive
        survived = [tc["function"]["arguments"] for m in out if m.get("role") == "assistant" for tc in m.get("tool_calls", [])]
        self.assertEqual(len(survived), 2)
        self.assertIn('grep e', survived[0]); self.assertIn('cat f', survived[1])
        # the note names what was dropped
        note = [m for m in out if m.get("role") == "user" and "cria removed" in str(m.get("content", ""))]
        self.assertEqual(len(note), 1)
        self.assertIn("cat a", note[0]["content"])
        # no orphaned tool results
        calls = {tc["id"] for m in out if m.get("role") == "assistant" for tc in m.get("tool_calls", [])}
        res = {m["tool_call_id"] for m in out if m.get("role") == "tool"}
        self.assertEqual(res, calls)

    def test_short_run_below_threshold_is_left_alone(self):
        msgs = [{"role": "user", "content": "x"}]
        for i, cmd in enumerate(["cat a", "cat b", "find c"]):   # only 3 < threshold(4)
            msgs += _fail_action(f"c{i}", cmd)
        out, rep = trim(msgs)
        self.assertEqual(rep.squashed_runs, 0)
        self.assertIs(out, msgs)                                 # untouched

    def test_success_breaks_the_run(self):
        # 3 fails, a SUCCESS, then 2 fails — no run reaches the threshold, nothing squashed
        msgs = [{"role": "user", "content": "x"}]
        msgs += _fail_action("a", "cat a") + _fail_action("b", "cat b") + _fail_action("c", "cat c")
        msgs += [{"role": "assistant", "tool_calls": [{"id": "ok", "type": "function",
                  "function": {"name": "exec_command", "arguments": '{"cmd": "ls"}'}}]},
                 {"role": "tool", "tool_call_id": "ok", "content": "handler.py\ntests"}]
        msgs += _fail_action("d", "cat d") + _fail_action("e", "cat e")
        out, rep = trim(msgs)
        self.assertEqual(rep.squashed_runs, 0)
        self.assertTrue(any(m.get("tool_call_id") == "ok" for m in out))  # the success is preserved
