"""C13-C: a satisfaction judge approved a 29-byte file for a task that required 30 bytes (a final
line break), with the task, the write and the read intact in its prompt (captured: call 0018 of the
nosession probe; the same verdict 3/3 on replay, and again with exact counts appended).

Fix under test: deterministic code measures the string values the coder SENT (``argfacts``); an
approving verdict is put to one focused question about them and only ``contradicted: false`` lets
it stand.  The task, write and read below are the captured ones.
"""
import json
import unittest

from cria import argfacts, loop

TASK = ('Use the file tools to create probe.txt containing exactly these three lines, including the '
        'final newline:\nsnow 雪\n"quoted"\nbackslash \\\nThen read probe.txt back using a tool. '
        'After seeing the read result, report whether it matches the requested content. Do not '
        'claim a tool ran until you receive its result.')
WRITE_29 = json.dumps({"path": "probe.txt", "content": 'snow 雪\n"quoted"\nbackslash \\'},
                      ensure_ascii=False)
WRITE_30 = json.dumps({"path": "probe.txt", "content": 'snow 雪\n"quoted"\nbackslash \\\n'},
                      ensure_ascii=False)
READ = '{"path": "probe.txt"}'
APPROVE = json.dumps({"satisfied": True, "reason": "matches", "proposed_fix": "", "diagnosis_kind": "",
                      "subject": "", "task_quote": "", "evidence_source": "", "evidence_quote": ""})


def _messages(write_args, result, read_result='{"content": "…"}'):
    return [
        {"role": "user", "content": TASK},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "w", "type": "function", "function": {"name": "write_file", "arguments": write_args}}]},
        {"role": "tool", "tool_call_id": "w", "content": result},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "r", "type": "function", "function": {"name": "read_file", "arguments": READ}}]},
        {"role": "tool", "tool_call_id": "r", "content": read_result},
    ]


class _Rlog:
    phase = ""

    def emit(self, *_a, **_k):
        pass


class _Chat:
    """The broad judge approves (the recorded verdict); the focused question answers `focused`."""

    def __init__(self, focused):
        self.focused = focused
        self.bodies = []

    def __call__(self, body, _rlog):
        self.bodies.append(body)
        system = body["messages"][0]["content"]
        content = self.focused if "QUESTION: does the task state an exact requirement" in system \
            else APPROVE
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def focused_asked(self):
        return sum("QUESTION: does the task state an exact requirement" in b["messages"][0]["content"]
                   for b in self.bodies)


def _judge(messages, focused):
    chat = _Chat(focused)
    evidence = loop._satisfaction_evidence(messages)
    sat, reason, _fix = loop.judge_satisfaction(TASK, evidence, chat, None, _Rlog())
    return sat, reason, chat


class ArgumentFacts(unittest.TestCase):
    def test_the_captured_write_is_29_bytes_with_no_final_break(self):
        facts = argfacts.render([("write_file", WRITE_29)])
        self.assertIn("`content`: 29 bytes, 2 line break(s), the value does NOT end with a line break", facts)

    def test_the_required_30_bytes_is_measured_as_such(self):
        facts = argfacts.render([("write_file", WRITE_30)])
        self.assertIn("`content`: 30 bytes, 3 line break(s), the value ends with a line break", facts)

    def test_no_string_argument_means_no_facts(self):
        self.assertEqual(argfacts.render([("list_dir", '{"depth": 2}'), ("x", "not json")]), "")

    def test_evidence_carries_the_facts_after_the_log(self):
        ev = loop._satisfaction_evidence(_messages(WRITE_29, '{"written": true, "bytes": 29}'))
        self.assertIn("29 bytes", ev)
        self.assertEqual(argfacts.extract(ev).count("\n- call "), 3)   # path, content, path

    def test_tool_results_are_never_measured(self):
        ev = loop._satisfaction_evidence(_messages(WRITE_29, '{"written": true, "bytes": 29}'))
        self.assertNotIn("written", argfacts.extract(ev))


class ApprovalIsHeldToTheMeasurement(unittest.TestCase):
    def test_a_contradicted_approval_does_not_stand(self):          # fails before the change
        sat, reason, _ = _judge(_messages(WRITE_29, '{"written": true, "bytes": 29}'),
                                '{"requirement": "r", "counts": "c", "contradicted": true}')
        self.assertFalse(sat)
        self.assertIn("29 bytes", reason)          # cria's own measurement, never the judge's words
        self.assertNotIn("matches", reason)

    def test_a_consistent_write_still_completes(self):
        sat, _, chat = _judge(_messages(WRITE_30, '{"written": true, "bytes": 30}'),
                              '{"requirement": "r", "counts": "c", "contradicted": false}')
        self.assertTrue(sat)
        self.assertEqual(chat.focused_asked(), 1)

    def test_an_unreadable_focused_answer_fails_closed(self):
        sat, _, _ = _judge(_messages(WRITE_29, "{}"), "I cannot tell")
        self.assertFalse(sat)

    def test_no_counts_no_extra_question(self):
        msgs = [{"role": "user", "content": TASK},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "l", "type": "function", "function": {"name": "list_dir", "arguments": '{"d": 1}'}}]},
                {"role": "tool", "tool_call_id": "l", "content": "x"}]
        sat, _, chat = _judge(msgs, "never asked")
        self.assertTrue(sat)
        self.assertEqual(chat.focused_asked(), 0)


if __name__ == "__main__":
    unittest.main()
