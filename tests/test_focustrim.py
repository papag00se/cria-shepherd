import unittest

from cria.focustrim import trim


def _asst(cid, name, args):
    return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function",
            "function": {"name": name, "arguments": args}}]}


def _result(cid, content):
    return {"role": "tool", "tool_call_id": cid, "content": content}


class FocusTrimTests(unittest.TestCase):
    def test_collapses_only_calls_with_identical_output_keeping_last(self):
        # The dedup key is (name, args, RESULT). A and B are byte-identical (same cmd, same output) →
        # they collapse to the last (B). C reruns the same cmd but its OUTPUT differs (the file now
        # exists after an edit) → it is NOT a duplicate; both B and C survive so the before/after
        # content is preserved (the earlier output is never silently lost).
        msgs = [
            {"role": "user", "content": "build it"},
            _asst("A", "exec", '{"cmd": "cat x"}'), _result("A", "no such file"),
            _asst("B", "exec", '{"cmd": "cat x"}'), _result("B", "no such file"),  # identical → dup of A
            _asst("C", "exec", '{"cmd": "cat x"}'), _result("C", "def f(): ..."),  # DIFFERENT output → kept
        ]
        out, rep = trim(msgs)
        self.assertTrue(rep.applied)
        self.assertEqual(rep.dropped_calls, 1)                # only A (its output matches B) is dropped
        self.assertEqual(rep.dropped_msgs, 1)                 # A's emptied assistant turn dropped
        ids = [tc["id"] for m in out if m.get("role") == "assistant" for tc in m["tool_calls"]]
        self.assertEqual(ids, ["B", "C"])                     # the differing-output rerun survives
        tool_ids = [m["tool_call_id"] for m in out if m.get("role") == "tool"]
        self.assertEqual(tool_ids, ["B", "C"])                # both distinct outputs kept
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
    # A SOFT dead-end lookup (file-not-found, no hard non-zero-exit line). These are the noise the
    # squash collapses. A HARD failure (non-zero exit carrying a traceback) is exempt — see
    # HardFailKeptTests — so squash-behavior fixtures must be soft-only.
    return [{"role": "assistant", "tool_calls": [{"id": cid, "type": "function",
             "function": {"name": "exec_command", "arguments": '{"cmd": "%s"}' % cmd}}]},
            {"role": "tool", "tool_call_id": cid, "content": "%s: No such file or directory" % cmd}]


class GateDupCollapseTests(unittest.TestCase):
    def test_identical_gate_probes_are_not_collapsed(self):
        from cria.probegate import SECTION_PREFIX as GATE
        gate_args = f'{{"cmd": "echo {GATE}probe-0___"}}'
        msgs = [
            {"role": "user", "content": "x"},
            _asst("g1", "exec_command", gate_args),
            {"role": "tool", "tool_call_id": "g1", "content": f"{GATE}probe-0___\nEXIT:0"},
            _asst("g2", "exec_command", gate_args),   # byte-identical gate script
            {"role": "tool", "tool_call_id": "g2", "content": f"{GATE}probe-0___\nEXIT:1\nSyntaxError"},
        ]
        out, rep = trim(msgs)
        self.assertEqual(rep.dropped_calls, 0)                       # neither gate collapsed
        ids = {tc["id"] for m in out if m.get("role") == "assistant" for tc in m.get("tool_calls", [])}
        self.assertEqual(ids, {"g1", "g2"})                          # both survive


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
        note = [m for m in out if m.get("role") == "user" and "[removed" in str(m.get("content", ""))]
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

    def test_squashes_across_a_success_keeping_it_in_place(self):
        # 3 fails, a SUCCESS, then 2 fails — 5 failures total, scattered, NOT consecutive. The stale
        # failures still collapse (dead ends are noise wherever they sit); the success is preserved.
        msgs = [{"role": "user", "content": "x"}]
        msgs += _fail_action("a", "cat a") + _fail_action("b", "cat b") + _fail_action("c", "cat c")
        msgs += [{"role": "assistant", "tool_calls": [{"id": "ok", "type": "function",
                  "function": {"name": "exec_command", "arguments": '{"cmd": "ls"}'}}]},
                 {"role": "tool", "tool_call_id": "ok", "content": "handler.py\ntests"}]
        msgs += _fail_action("d", "cat d") + _fail_action("e", "cat e")
        out, rep = trim(msgs)
        self.assertEqual(rep.squashed_runs, 1)                            # squashed despite the success
        self.assertEqual(rep.dropped_calls, 3)                           # 5 failures - keep(2)
        self.assertTrue(any(m.get("tool_call_id") == "ok" for m in out))  # the success is preserved
        # the two most recent FAILURES survive; the earlier three are gone
        surviving_fail_ids = [m["tool_call_id"] for m in out if m.get("role") == "tool" and m["tool_call_id"] != "ok"]
        self.assertEqual(surviving_fail_ids, ["d", "e"])
        note = [m for m in out if "[removed" in str(m.get("content", ""))]
        self.assertEqual(len(note), 1)
        self.assertIn("cat a", note[0]["content"])                        # the scattered dead-ends are named

    def test_gate_probe_is_never_squashed_as_a_failed_action(self):
        # cria's OWN ground-truth gate probe exits non-zero BY DESIGN (a failing check is the signal).
        # It must survive the failure-squash — squashing it removes the exact error cria surfaced.
        from cria.probegate import SECTION_PREFIX as GATE
        gate_out = (f"{GATE}probe-0___\n  File \"./mcp_client.py\", line 14\n"
                    "SyntaxError: ':' expected after dictionary key\nProcess exited with code 1")
        msgs = [{"role": "user", "content": "x"}]
        for c in ("a", "b", "c", "d"):                                    # 4 real dead-ends (over threshold)
            msgs += _fail_action(c, f"cat {c}")
        msgs += [{"role": "assistant", "tool_calls": [{"id": "gate", "type": "function",
                  "function": {"name": "exec_command", "arguments": f'{{"cmd": "echo {GATE}probe-0___"}}'}}]},
                 {"role": "tool", "tool_call_id": "gate", "content": gate_out}]
        out, rep = trim(msgs)
        self.assertEqual(rep.squashed_runs, 1)                            # the cat dead-ends still collapse
        # the gate probe + its ground-truth result survive untouched
        self.assertTrue(any(m.get("tool_call_id") == "gate" for m in out))
        surviving = "".join(str(m.get("content", "")) for m in out)
        self.assertIn("expected after dictionary key", surviving)         # the error is still present
        # …and the gate is NOT named in the "removed failed attempts" note
        note = [m for m in out if "[removed" in str(m.get("content", ""))][0]
        self.assertNotIn(GATE, note["content"])

    def test_full_command_and_tried_list_are_not_clipped_in_the_note(self):
        # The squash note names what was tried so the model won't retry it. A model can't recognize a
        # command that was cut to 60 chars ("python -m pytest tests/really/long/pa…"), nor a Tried:
        # list cut at 400 — so the full command text of every dropped attempt must appear in full.
        long_paths = [f"tests/really/long/path/that/exceeds/sixty/characters/module_{i}/test_case_{i}.py"
                      for i in range(6)]
        msgs = [{"role": "user", "content": "x"}]
        for i, p in enumerate(long_paths):
            cmd = f"python -m pytest {p}"
            msgs += [{"role": "assistant", "tool_calls": [{"id": f"c{i}", "type": "function",
                      "function": {"name": "exec_command", "arguments": '{"cmd": "%s"}' % cmd}}]},
                     {"role": "tool", "tool_call_id": f"c{i}", "content": "%s: No such file or directory" % cmd}]
        out, rep = trim(msgs)
        self.assertEqual(rep.squashed_runs, 1)
        note = [m for m in out if "[removed" in str(m.get("content", ""))][0]["content"]
        self.assertNotIn("…", note)                                   # nothing elided
        # every dropped command appears in full (the 4 oldest of the 6 are dropped)
        for p in long_paths[:4]:
            self.assertIn(p, note)


class HardFailKeptTests(unittest.TestCase):
    """A HARD failure (non-zero exit — a failing pytest / build / live-test) carries the traceback /
    assertion the coder needs. It must NEVER be folded into a 'tried' note or dropped as spam, no
    matter how many pile up — every one is kept in full, in place."""

    def test_hard_failures_are_never_squashed(self):
        # 5 DISTINCT failing pytest runs (distinct args + distinct output so Rule-A dedup can't touch
        # them either). All exit non-zero → all exempt → nothing squashed, nothing dropped.
        msgs = [{"role": "user", "content": "fix it"}]
        for i in range(5):
            tb = f"tests/test_{i}.py::test_case FAILED\nAssertionError: expected 3 got {i}\nProcess exited with code 1"
            msgs += [{"role": "assistant", "tool_calls": [{"id": f"h{i}", "type": "function",
                      "function": {"name": "exec_command", "arguments": '{"cmd": "pytest tests/test_%d.py"}' % i}}]},
                     {"role": "tool", "tool_call_id": f"h{i}", "content": tb}]
        out, rep = trim(msgs)
        self.assertEqual(rep.squashed_runs, 0)                        # no hard fail squashed
        self.assertEqual(rep.dropped_calls, 0)                        # none dropped
        self.assertFalse(rep.applied)
        # every traceback is still present in full
        surviving = "".join(str(m.get("content", "")) for m in out)
        for i in range(5):
            self.assertIn(f"expected 3 got {i}", surviving)
        kept_ids = [m["tool_call_id"] for m in out if m.get("role") == "tool"]
        self.assertEqual(kept_ids, [f"h{i}" for i in range(5)])

    def test_is_hard_failure_matches_only_nonzero_exit(self):
        from cria.focustrim import _is_hard_failure
        self.assertTrue(_is_hard_failure("AssertionError\nProcess exited with code 1"))
        self.assertFalse(_is_hard_failure("cat: x: No such file or directory"))  # soft dead-end, no exit line
        self.assertFalse(_is_hard_failure("all good\nProcess exited with code 0"))


class IsFailureExitCodeTests(unittest.TestCase):
    """A tool that exited 0 (or returned HTTP 2xx) is a SUCCESS whose body may merely mention 'not
    found' — it must NOT be squashed as a failed attempt. The exit-0 api.handle.me curl carried the
    exact route hint + docs URL the model needed; the old bare `\\bnot found\\b` threw it away."""

    def test_exit_zero_body_mentioning_not_found_is_not_a_failure(self):
        from cria.focustrim import _is_failure
        body = '{"error":"route_not_found","message":"Route not found: /api/handles/goose","docs":"https://api.handle.me/"}\nProcess exited with code 0'
        self.assertFalse(_is_failure(body))

    def test_http_2xx_fetch_is_not_a_failure(self):
        from cria.focustrim import _is_failure
        self.assertFalse(_is_failure("HTTP 200 OK · https://api.handle.me/\nSwagger UI ... not found in nav"))

    def test_exit_nonzero_not_found_is_a_failure(self):
        from cria.focustrim import _is_failure
        self.assertTrue(_is_failure("cat: package.json: No such file or directory\nProcess exited with code 1"))

    def test_soft_signature_without_a_success_marker_is_a_failure(self):
        from cria.focustrim import _is_failure
        self.assertTrue(_is_failure("bash: frobnicate: command not found"))
