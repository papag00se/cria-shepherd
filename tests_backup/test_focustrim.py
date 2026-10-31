import json
import unittest

from cria import bodykeys, denial, prompts, toolwire, writeproxy
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


def _fail_action(cid, cmd):
    # Historical native lookup diagnostic. Its wording proves neither refusal nor
    # uselessness; Rule B now preserves it, including when the exit status is unknown.
    return [{"role": "assistant", "tool_calls": [{"id": cid, "type": "function",
             "function": {"name": "exec_command", "arguments": '{"cmd": "%s"}' % cmd}}]},
            {"role": "tool", "tool_call_id": cid, "content": "%s: No such file or directory" % cmd}]


def _refused_action(cid, cmd):
    """A real authored refusal packet, restored through the canonical inbound owner.

    Nothing executes: the producer authors its typed record and the consumer verifies
    its declared receipt. Multiline evidence deliberately rides beneath the refusal.
    """
    args = json.dumps({"cmd": cmd})
    receipt = denial.receipt_for(cid, "exec_command", args)
    with denial.receipt_scope(receipt):
        stdout = denial.mark(f"Refused {cmd}\nObserved source detail for {cid}\nFinal detail for {cid}\n")
    command = toolwire._sentinel("exec_command", args, receipt) + "\n:"
    call = toolwire._shell_call(cid, {"name": "exec_command", "parameters": {
        "type": "object", "properties": {"cmd": {"type": "string"}}}}, command)
    restored = writeproxy.represent_inbound([
        {"role": "assistant", "tool_calls": [call]}, _result(cid, stdout)])
    assert denial.refused_call_ids(restored) == {cid}
    return restored


def _public(messages):
    return [{k: v for k, v in m.items() if k not in bodykeys.ALL} for m in messages]


def _unfold_refusals(messages):
    """Decode the historical record to compare ALL original events, not selected lines."""
    prefix = prompts.load("work_log_denied").strip() + "\n"
    out = []
    for message in messages:
        if message.get("role") == "user" and str(message.get("content", "")).startswith(prefix):
            out.extend(json.loads(message["content"][len(prefix):]))
        else:
            out.extend(_public([message]))
    return out


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
        """Distinct-attempt history survives: words no longer authorize its deletion.

        The old soft-error expectation was unsafe. Only proven authored refusals
        fold now, with complete bodies and call arguments still recoverable.
        """
        commands = ["cat a", "cat b", "find c", "ls d", "grep e", "cat f"]
        native = [{"role": "user", "content": "build it"}]
        for i, cmd in enumerate(commands):
            native += _fail_action(f"c{i}", cmd)
        out, rep = trim(native)
        self.assertEqual(out, native)
        self.assertFalse(rep.applied)

        msgs = [{"role": "user", "content": "build it"}]
        for i, cmd in enumerate(commands):
            msgs += _refused_action(f"c{i}", cmd)
        out, rep = trim(msgs)
        self.assertEqual(rep.squashed_runs, 1)
        self.assertEqual(rep.dropped_calls, 4)
        self.assertEqual(rep.dropped_msgs, 8)
        self.assertEqual(out[-4:], msgs[-4:])  # the latest two ordinary pairs survive
        self.assertEqual(_unfold_refusals(out), _public(msgs))
        calls = {tc["id"] for m in out if m.get("role") == "assistant" for tc in m.get("tool_calls", [])}
        res = {m["tool_call_id"] for m in out if m.get("role") == "tool"}
        self.assertEqual(calls, {"c4", "c5"})
        self.assertEqual(res, calls)

    def test_short_run_below_threshold_is_left_alone(self):
        msgs = [{"role": "user", "content": "x"}]
        for i, cmd in enumerate(["cat a", "cat b", "find c"]):   # only 3 < threshold(4)
            msgs += _fail_action(f"c{i}", cmd)
        out, rep = trim(msgs)
        self.assertEqual(rep.squashed_runs, 0)
        self.assertIs(out, msgs)                                 # untouched

    def test_squashes_across_a_success_keeping_it_in_place(self):
        """Intervening success must retain its bytes AND position among earlier facts.

        Native soft-looking results are no longer deletable; genuine refusals fold
        in place rather than collecting their evidence into one later note.
        """
        success = [_asst("ok", "exec_command", '{"cmd": "ls"}'), _result("ok", "handler.py\ntests")]
        for make_action in (_fail_action, _refused_action):
            with self.subTest(producer=make_action.__name__):
                msgs = [{"role": "user", "content": "x"}]
                msgs += make_action("a", "cat a") + make_action("b", "cat b") + make_action("c", "cat c")
                msgs += success
                msgs += make_action("d", "cat d") + make_action("e", "cat e")
                out, rep = trim(msgs)
                self.assertEqual(_unfold_refusals(out), _public(msgs))
                self.assertEqual(next(m for m in out if m.get("tool_call_id") == "ok"), success[1])
                if make_action is _fail_action:
                    self.assertEqual(out, msgs)
                    self.assertFalse(rep.applied)
                else:
                    self.assertEqual(rep.squashed_runs, 1)
                    self.assertEqual(rep.dropped_calls, 3)
                    self.assertEqual(out[-4:], msgs[-4:])
                    surviving = [m["tool_call_id"] for m in out if m.get("role") == "tool"]
                    self.assertEqual(surviving, ["ok", "d", "e"])

    def test_gate_probe_is_never_squashed_as_a_failed_action(self):
        # cria's OWN ground-truth gate probe exits non-zero BY DESIGN (a failing check is the signal).
        # It must survive the failure-squash — squashing it removes the exact error cria surfaced.
        from cria.probegate import SECTION_PREFIX as GATE
        gate_out = (f"{GATE}probe-0___\n  File \"./mcp_client.py\", line 14\n"
                    "SyntaxError: ':' expected after dictionary key\nProcess exited with code 1")
        # Native phrase-based deletion is superseded, not gate protection. Exercise
        # the original native diagnostics AND a genuinely active refusal fold.
        gate = [_asst("gate", "exec_command", json.dumps({"cmd": f"echo {GATE}probe-0___"})),
                _result("gate", gate_out)]
        for make_action in (_fail_action, _refused_action):
            with self.subTest(producer=make_action.__name__):
                msgs = [{"role": "user", "content": "x"}]
                for c in ("a", "b", "c", "d"):
                    msgs += make_action(c, f"cat {c}")
                msgs += gate
                out, rep = trim(msgs)
                self.assertEqual(rep.squashed_runs, 0 if make_action is _fail_action else 1)
                self.assertEqual(out[-2:], gate)  # exact call and entire diagnostic, not a substring
                self.assertEqual(_unfold_refusals(out), _public(msgs))
                surviving = "".join(str(m.get("content", "")) for m in out)
                self.assertIn("expected after dictionary key", surviving)
                for note in out:
                    if note.get("role") == "user":
                        self.assertNotIn(GATE, note["content"])

    def test_full_command_and_tried_list_are_not_clipped_in_the_note(self):
        """Long commands AND multiline answers survive the removal of the old Tried note.

        Its phrase-based deletion was unsafe; its no-clipping incident remains a
        contract for both native results and the surviving authored-refusal fold.
        """
        long_paths = [f"tests/really/long/path/that/exceeds/sixty/characters/module_{i}/test_case_{i}.py"
                      for i in range(6)]
        for make_action in (_fail_action, _refused_action):
            with self.subTest(producer=make_action.__name__):
                msgs = [{"role": "user", "content": "x"}]
                for i, path in enumerate(long_paths):
                    msgs += make_action(f"c{i}", f"python -m pytest {path}")
                out, rep = trim(msgs)
                self.assertEqual(rep.squashed_runs, 0 if make_action is _fail_action else 1)
                self.assertEqual(_unfold_refusals(out), _public(msgs))
                visible = json.dumps(out, ensure_ascii=False)
                self.assertNotIn("…", visible)
                for path in long_paths:
                    self.assertIn(path, visible)


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


if __name__ == "__main__":
    unittest.main()
