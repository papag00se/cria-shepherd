"""C13-C: a satisfaction judge approved a 29-byte file for a task that required 30 bytes (a final
line break), with the task, the write and the read intact in its prompt (captured: nosession call
0018, `satisfied:true` 3/3 on replay, and again with counts appended to the broad prompt).

Fix: deterministic code measures the CURRENT content of the files the session wrote/edited; an
approving verdict is put to ONE focused question about those counts, and only `contradicted: false`
lets it stand.  Review B1 of the first design: counts of what was SENT are history, not the disk —
a file rewritten, edited, or written by a shell must never be vetoed by its stale first write.
"""
import json
import tempfile
import unittest
from pathlib import Path

from cria import bodykeys, denial, filefacts, loop, wsview

TASK = ('Use the file tools to create probe.txt containing exactly these three lines, including the '
        'final newline:\nsnow 雪\n"quoted"\nbackslash \\\nThen read probe.txt back using a tool. '
        'After seeing the read result, report whether it matches the requested content. Do not '
        'claim a tool ran until you receive its result.')
C29 = 'snow 雪\n"quoted"\nbackslash \\'
C30 = C29 + "\n"
APPROVE = json.dumps({"satisfied": True, "reason": "matches", "proposed_fix": "", "diagnosis_kind": "",
                      "subject": "", "task_quote": "", "evidence_source": "", "evidence_quote": ""})
Q = "QUESTION: does the task fix, in exact terms"


def _call(cid, name, args):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}


def _res(cid, text, outcome=None):
    # a result that says "ok"/"Wrote …" with no stated outcome is a LANDED write as `represent_inbound` hands it on
    outcome = outcome or (denial.LANDED if text in ("ok",) or text.startswith("Wrote ") else None)
    return {"role": "tool", "tool_call_id": cid, "content": text,
            **({bodykeys.RESULT_OUTCOME: outcome} if outcome else {})}


def write(cid, content, path="probe.txt", result=None, outcome=None):
    return [_call(cid, "write_file", {"path": path, "content": content}),
            _res(cid, result if result is not None else json.dumps({"written": True, "bytes": len(content.encode())}),
                 outcome or (denial.LANDED if result is None else None))]   # a genuine write: its own typed landed fact


def read(cid="r"):
    return [_call(cid, "read_file", {"path": "probe.txt"}), _res(cid, '{"content": "..."}')]


class _Rlog:
    phase = ""

    def emit(self, *_a, **_k):
        pass


CONFIRM = "QUESTION: does the quote itself state"
BYTES = "QUESTION: does the quote itself fix the EXACT size"


class _Chat:
    def __init__(self, focused, states="ends_with_break", exact="same"):
        self.focused, self.states, self.exact, self.bodies = focused, states, exact, []

    def __call__(self, body, _rlog):
        self.bodies.append(body)
        system = body["messages"][0]["content"]
        if BYTES in system:
            if self.exact == "same":                       # a faithful reader: whatever number the quote fixes
                import re
                nums = re.findall(r"exactly (\d+) bytes", body["messages"][0]["content"])
                content = json.dumps({"exact_bytes": int(nums[0]) if nums else None})
            else:
                content = json.dumps({"exact_bytes": self.exact}) if self.exact != "unreadable" else "no idea"
        elif CONFIRM in system:
            content = json.dumps({"states": self.states}) if self.states else "no idea"
        elif Q in system:
            content = self.focused.pop(0) if isinstance(self.focused, list) else self.focused
        else:
            content = APPROVE
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def asked(self):
        return sum(Q in b["messages"][0]["content"] for b in self.bodies)


def extraction(file="probe.txt", quote="including the final newline", bytes_=None, ends=True):
    """What the focused judge returns: it only EXTRACTS the exact figure; cria compares."""
    return json.dumps({"quote": quote, "file": file, "bytes": bytes_, "ends_with_line_break": ends})


REQUIRES_FINAL_LF = extraction()


def judge(messages, focused=REQUIRES_FINAL_LF, root="", task=TASK, states="ends_with_break", exact="same"):
    chat = _Chat(focused, states, exact)
    ev = loop._satisfaction_evidence(messages, workspace_root=root)
    sat, reason, _ = loop.judge_satisfaction(task, ev, chat, None, _Rlog(), workspace_root="")
    return sat, reason, chat, ev


class FactsAreOfCurrentContent(unittest.TestCase):
    def test_the_original_incident_29_bytes_is_still_blocked(self):
        sat, reason, chat, _ = judge(write("w", C29) + read())
        self.assertFalse(sat)
        self.assertIn("probe.txt (as last written): 29 bytes, 2 line break(s), the content does NOT end", reason)
        self.assertEqual(chat.asked(), 1)

    def test_A_a_stale_write_rewritten_correctly_is_not_stated_and_completes(self):
        msgs = write("w1", C29) + write("w2", C30) + read()
        facts = filefacts.extract(loop._satisfaction_evidence(msgs))
        self.assertIn("probe.txt (as last written): 30 bytes, 3 line break(s), the content ends with", facts)
        self.assertNotIn("29 bytes", facts)
        sat, _, _, _ = judge(msgs)
        self.assertTrue(sat)

    def test_B_a_later_landed_edit_silences_the_fact(self):
        msgs = write("w", C29) + [_call("e", "edit_file", {"path": "probe.txt", "old_string": "\\", "new_string": "\\\n"}),
                                  _res("e", "ok")] + read()
        sat, _, chat, ev = judge(msgs)
        self.assertEqual(filefacts.extract(ev), "")
        self.assertTrue(sat)
        self.assertEqual(chat.asked(), 0)

    def test_B_an_edit_of_another_file_does_not_silence_this_one(self):
        msgs = write("w", C29) + [_call("e", "edit_file", {"path": "other.txt", "old_string": "a", "new_string": "b"}),
                                  _res("e", "ok")]
        self.assertIn("probe.txt", filefacts.extract(loop._satisfaction_evidence(msgs)))

    def test_C_a_file_made_by_a_shell_is_never_measured_from_the_command(self):
        msgs = [_call("s", "exec_command", {"cmd": "printf 'snow\\n' > probe.txt"}), _res("s", "")] + read()
        sat, _, chat, ev = judge(msgs)
        self.assertEqual(filefacts.extract(ev), "")
        self.assertTrue(sat)
        self.assertEqual(chat.asked(), 0)

    def test_a_shell_that_writes_after_the_write_silences_it(self):
        msgs = write("w", C29) + [_call("s", "exec_command", {"cmd": "echo >> probe.txt"}), _res("s", "")]
        self.assertEqual(filefacts.extract(loop._satisfaction_evidence(msgs)), "")

    def test_a_read_only_command_after_the_write_does_not(self):
        msgs = write("w", C29) + [_call("s", "exec_command", {"cmd": "cat probe.txt"}), _res("s", "x")]
        self.assertIn("29 bytes", filefacts.extract(loop._satisfaction_evidence(msgs)))

    def test_a_refused_write_is_never_presented_as_sent(self):
        msgs = write("w", C29, result=denial.DENIED_MARKER + " refused", outcome=denial.REFUSED)
        sat, _, chat, ev = judge(msgs)
        self.assertEqual(filefacts.extract(ev), "")
        self.assertEqual(chat.asked(), 0)
        self.assertTrue(sat)

    def test_a_write_with_no_result_is_not_stated(self):
        self.assertEqual(filefacts.extract(loop._satisfaction_evidence(
            [_call("w", "write_file", {"path": "probe.txt", "content": C29})])), "")

    def test_program_output_tasks_have_no_files_to_count(self):
        msgs = [_call("s", "exec_command", {"cmd": "python3 hello.py"}), _res("s", "Hello, World!\n")]
        self.assertEqual(filefacts.extract(loop._satisfaction_evidence(msgs)), "")

    def test_the_byte_comparison_is_arithmetic_on_the_counts(self):
        task = "Create probe.txt of exactly 30 bytes."
        ok = extraction(quote="exactly 30 bytes", bytes_=30, ends=None)
        self.assertTrue(judge(write("w", C30), ok, task=task)[0])
        sat, reason, _, _ = judge(write("w", C29), ok, task=task)
        self.assertFalse(sat)
        self.assertIn("29 bytes", reason)

    def test_a_number_in_the_quote_that_is_not_a_byte_size_cannot_veto(self):
        # captured live: each of these blocked 3/3 (or 1/3) when any number in the quote could veto
        for task, quote, number in (
                ("Write README.md of at most 200 words.", "of at most 200 words", 200),
                ("Keep it under 100 lines.", "under 100 lines", 100),
                ("Set max_size to 1024 bytes in limits.json.", "max_size to 1024 bytes", 1024)):
            sat, _, chat, _ = judge(write("w", C29), extraction(quote=quote, bytes_=number, ends=None),
                                    task=task, exact=None)
            self.assertTrue(sat, quote)
            self.assertEqual(chat.asked(), 1)

    def test_exactly_16_bytes_vetoes_when_the_size_differs(self):
        task = "Create probe.txt of exactly 16 bytes."
        sat, reason, _, _ = judge(write("w", C29), extraction(quote="exactly 16 bytes", bytes_=16, ends=None),
                                  task=task)
        self.assertFalse(sat)
        self.assertIn("29 bytes", reason)

    def test_a_confirmation_naming_another_number_cannot_veto(self):
        task = "Create probe.txt of exactly 16 bytes."
        self.assertTrue(judge(write("w", C29), extraction(quote="exactly 16 bytes", bytes_=16, ends=None),
                              task=task, exact=17)[0])

    def test_an_unreadable_byte_confirmation_is_reasked_then_fails_closed(self):
        task = "Create probe.txt of exactly 16 bytes."
        sat, _, chat, _ = judge(write("w", C29), extraction(quote="exactly 16 bytes", bytes_=16, ends=None),
                                task=task, exact="unreadable")
        self.assertFalse(sat)
        self.assertEqual(sum(BYTES in b["messages"][0]["content"] for b in chat.bodies), 2)

    def test_F3_a_byte_count_the_quote_does_not_contain_cannot_veto(self):
        # the quote fixes nothing; the judge mis-copied a count into `bytes`
        task = "Add probe.txt describing the risks."
        sat, _, _, _ = judge(write("w", C29), extraction(quote="describing the risks", bytes_=30, ends=None), task=task)
        self.assertTrue(sat)

    def test_F3_an_ending_the_quote_does_not_state_cannot_veto(self):
        task = "Add probe.txt describing the risks."
        sat, _, _, _ = judge(write("w", C29), extraction(quote="describing the risks", ends=True),
                             task=task, states="neither")
        self.assertTrue(sat)

    def test_F3_a_confirmed_ending_requirement_vetoes(self):
        self.assertFalse(judge(write("w", C29), states="ends_with_break")[0])

    def test_F3_a_confirmation_that_says_the_opposite_cannot_veto(self):
        self.assertTrue(judge(write("w", C29), states="ends_without_break")[0])

    def test_F2_one_reask_recovers_an_unreadable_extraction(self):
        sat, _, chat, _ = judge(write("w", C29), ["garbage", REQUIRES_FINAL_LF])
        self.assertFalse(sat)
        self.assertEqual(chat.asked(), 2)

    def test_F2_two_unreadable_answers_fail_closed(self):
        sat, _, chat, _ = judge(write("w", C30), ["garbage", "still garbage"])
        self.assertFalse(sat)
        self.assertEqual(chat.asked(), 2)

    def test_F2_an_unreadable_confirmation_fails_closed(self):
        self.assertFalse(judge(write("w", C29), states=None)[0])

    def test_F4_dot_slash_and_bare_spellings_are_one_path(self):
        sat, _, _, _ = judge(write("w", C29, path="./probe.txt"))
        self.assertFalse(sat)
        msgs = write("w1", C29, path="./probe.txt") + write("w2", C30, path="probe.txt")
        facts = filefacts.extract(loop._satisfaction_evidence(msgs))
        self.assertEqual(facts.count("\n- "), 1)
        self.assertIn("30 bytes", facts)

    def test_F1_a_native_patch_after_the_write_silences_the_fact(self):
        patch = "*** Begin Patch\n*** Update File: probe.txt\n@@\n-x\n+y\n*** End Patch"
        for name, args in (("apply_patch", {"input": patch}),
                           ("Edit", {"file_path": "probe.txt", "old_string": "a", "new_string": "b"}),
                           ("edit_file", {"path": "probe.txt", "old_string": "a", "new_string": "b"})):
            msgs = write("w", C29) + [_call("p", name, args), _res("p", "ok")]
            self.assertEqual(filefacts.extract(loop._satisfaction_evidence(msgs)), "", name)

    def test_a_quote_the_task_never_made_cannot_veto(self):
        sat, _, _, _ = judge(write("w", C29), extraction(quote="the file must be 3219 bytes"))
        self.assertTrue(sat)

    def test_a_file_nobody_counted_cannot_veto(self):
        sat, _, _, _ = judge(write("w", C29), extraction(file="README.md"))
        self.assertTrue(sat)

    def test_a_task_that_fixes_nothing_cannot_veto(self):
        sat, _, _, _ = judge(write("w", C29), extraction(quote="", file="", ends=None))
        self.assertTrue(sat)

    def test_an_unreadable_focused_answer_fails_closed(self):
        sat, _, _, _ = judge(write("w", C29), "I cannot tell")
        self.assertFalse(sat)


class TheViewIsTheDiskProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "probe.txt")
        self.tok = wsview.bind(wsview.DirectView(self.tmp.name))
        self.addCleanup(wsview.unbind, self.tok)

    def test_the_disk_outranks_what_the_write_payload_said(self):
        Path(self.path).write_bytes(C30.encode())          # the disk is correct, the old write was not
        msgs = write("w", C29, path=self.path)
        facts = filefacts.extract(loop._satisfaction_evidence(msgs, workspace_root=self.tmp.name))
        self.assertIn("(on disk): 30 bytes, 3 line break(s)", facts)
        sat, _, _, _ = judge(msgs, extraction(self.path), root=self.tmp.name)
        self.assertTrue(sat)

    def test_F1_the_view_body_is_not_trusted_after_a_native_patch(self):
        Path(self.path).write_bytes(C29.encode())          # the view still holds the pre-patch bytes
        msgs = write("w", C29, path=self.path) + [
            _call("p", "apply_patch", {"input": f"*** Begin Patch\n*** Update File: {self.path}\n@@\n-x\n+y\n*** End Patch"}),
            _res("p", "ok")]
        self.assertEqual(filefacts.extract(loop._satisfaction_evidence(msgs, workspace_root=self.tmp.name)), "")

    def test_a_disk_that_is_wrong_is_stated_and_blocks(self):
        Path(self.path).write_bytes(C29.encode())
        msgs = write("w", C30, path=self.path)
        sat, reason, _, _ = judge(msgs, extraction(self.path), root=self.tmp.name)
        self.assertFalse(sat)
        self.assertIn("(on disk): 29 bytes", reason)


if __name__ == "__main__":
    unittest.main()
