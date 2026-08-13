"""The judge answered on the tool channel because that is the channel cria gave it.

cria offers the completion judge `list_dir` and `read_file` as real tools, then demands the verdict
as JSON in message content — with the CODER's own tool signatures printed in the same prompt as
`write_file(path, content)`. Asked to speak in one channel and answer in another, with a callable
template in front of it, the judge did the obvious thing:

    <function=satisfied>          <function=exec_command>

cria discarded those replies as unparseable, and "unverified — keep working" or a canned redirect
reached a finished, correct workspace. 10 occurrences, four languages.

    qwen35/ruby 0138 — the reasoning-off retry answered
    '{"satisfied": false, "reason": "All five task requirements are met: tests pass (21/21) ..."}'
    and cria built from it: "The repo's automated checks pass, but the task is NOT fully done yet:
    All five task requirements are met ..."

TWO CHANGES, BOTH INSIDE CRIA.

1. A `verdict` tool on the judge's own menu, beside the inspection tools. The answer arrives as a
   structured tool_call cria reads off the event (#12) instead of matching text in prose. OPT-IN by
   key: three judges share this loop under three different verdict keys, and the STEER AUTHOR shares
   it too and answers in prose — handing the author a verdict tool would be cria instructing the
   role collapse it already had to guard against once.

2. The coder's tool block is defanged to names and prose. Parameter names stay, because grounding a
   suggested action in what the coder can actually do is why the block exists; the callable syntax
   goes. Same lesson selfcompact applies to the transcript printed beside it, where imitation was
   measured at 8% once a prompt showed 30-59 tool shapes.

NOT DONE: no phantom-call repair and no extra retry. That would be a fallback on a fallback (#4).
Policy is untouched — the careful pass alone may approve, and an unparseable verdict still fails
closed (#13).
"""

import json
import types
import unittest

from cria import loop, verifytools


class Rlog:
    def __init__(self):
        self.events = []
        self.phase = None

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def call(name, args):
    return {"id": "t1", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def completion(content=None, calls=None):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = calls
    return {"choices": [{"message": msg}]}


class TheVerdictToolIsOfferedToJudgesOnlyTests(unittest.TestCase):
    def test_a_judge_that_declares_a_key_gets_it(self):
        names = [t["function"]["name"] for t in verifytools.tools_for("satisfied")]
        self.assertIn("verdict", names)
        self.assertIn("read_file", names)

    def test_the_key_is_the_judges_own(self):
        for key in ("satisfied", "done", "consistent"):
            with self.subTest(key=key):
                props = verifytools.verdict_tool(key)["function"]["parameters"]["properties"]
                self.assertIn(key, props)

    def test_a_caller_with_no_key_gets_the_plain_menu(self):
        """The steer author shares this loop and answers in prose."""
        names = [t["function"]["name"] for t in verifytools.tools_for()]
        self.assertNotIn("verdict", names)
        self.assertEqual(names, [t["function"]["name"] for t in verifytools.VERIFY_TOOLS])

    def test_it_says_to_call_it_once_and_alone(self):
        d = verifytools.verdict_tool("satisfied")["function"]["description"]
        self.assertIn("once", d)
        self.assertIn("Do not call it and another tool in the same turn", d)


class AVerdictCallEndsTheInspectionTests(unittest.TestCase):
    def judge(self, replies, **kw):
        seq = list(replies)
        rlog = Rlog()

        def chat(body, _rlog):
            return json.dumps(seq.pop(0))

        import tempfile
        with tempfile.TemporaryDirectory() as ws:
            comp = loop._judge_completion(chat, None, "sys", "usr", rlog, phase="satisfaction",
                                          workspace_root=ws, **kw)
        return comp, rlog

    def test_the_verdict_is_read_off_the_tool_call(self):
        comp, rlog = self.judge(
            [completion(calls=[call("verdict", {"satisfied": False, "reason": "no README",
                                                "proposed_fix": "write README.md"})])],
            verdict_key="satisfied")
        obj = json.loads(loop._completion_text(comp))
        self.assertIs(obj["satisfied"], False)
        self.assertEqual(obj["reason"], "no README")
        self.assertIn("loop.verdict_by_tool", [k for k, _ in rlog.events])

    def test_the_tool_calls_do_not_survive_into_the_answer(self):
        comp, _ = self.judge(
            [completion(calls=[call("verdict", {"satisfied": True, "reason": "all present"})])],
            verdict_key="satisfied")
        self.assertNotIn("tool_calls", comp["choices"][0]["message"])

    def test_inspection_still_happens_first(self):
        comp, rlog = self.judge(
            [completion(calls=[call("list_dir", {"path": "."})]),
             completion(calls=[call("verdict", {"satisfied": True, "reason": "looked, all there"})])],
            verdict_key="satisfied")
        self.assertIn("loop.verify_inspect", [k for k, _ in rlog.events])
        self.assertIs(json.loads(loop._completion_text(comp))["satisfied"], True)

    def test_a_verdict_call_missing_its_key_is_not_an_answer(self):
        """Fail closed: the loop keeps going rather than inventing a ruling."""
        comp, _ = self.judge(
            [completion(calls=[call("verdict", {"reason": "hmm"})]),
             completion(content='{"satisfied": false, "reason": "still no README"}')],
            verdict_key="satisfied")
        self.assertIn("still no README", loop._completion_text(comp))

    def test_without_a_key_a_verdict_call_is_just_an_unknown_tool(self):
        comp, rlog = self.judge(
            [completion(calls=[call("verdict", {"satisfied": True, "reason": "x"})]),
             completion(content="ON_TRACK")])
        self.assertNotIn("loop.verdict_by_tool", [k for k, _ in rlog.events])
        self.assertEqual(loop._completion_text(comp), "ON_TRACK")

    def test_a_plain_json_answer_still_works(self):
        comp, _ = self.judge([completion(content='{"satisfied": true, "reason": "done"}')],
                             verdict_key="satisfied")
        self.assertIs(json.loads(loop._completion_text(comp))["satisfied"], True)


class TheCoderToolBlockCarriesNoTemplateTests(unittest.TestCase):
    def block(self):
        return loop._coder_tools_summary([
            {"function": {"name": "write_file",
                          "parameters": {"properties": {"path": {}, "content": {}}}}},
            {"function": {"name": "exec_command", "parameters": {"properties": {"cmd": {}}}}}])

    def test_no_callable_syntax(self):
        self.assertNotIn("write_file(", self.block())
        self.assertNotIn("(path, content)", self.block())

    def test_the_grounding_it_exists_for_survives(self):
        b = self.block()
        self.assertIn("write_file", b)
        self.assertIn("takes path, content", b)
        self.assertIn("runs ANY shell command", b)

    def test_the_names_still_parse_back_out(self):
        """_tool_names reads this block for the harness-leak check — defanging must not blind it."""
        self.assertEqual(loop._tool_names(self.block()), ["write_file", "exec_command"])

    def test_no_prose_word_is_harvested_as_a_tool(self):
        """The old parser pulled `command` out of "runs ANY shell command"."""
        self.assertNotIn("command", loop._tool_names(self.block()))

    def test_an_unrendered_string_still_parses(self):
        self.assertIn("web_fetch", loop._tool_names("web_fetch(url)"))


class ThePolicyIsUnchangedTests(unittest.TestCase):
    def test_the_toolless_retry_declares_no_key(self):
        import inspect
        src = inspect.getsource(loop._satisfaction_verdict)
        self.assertIn('verdict_key="" if reasoning_off else "satisfied"', src)

    def test_the_retry_still_only_confirms_not_satisfied(self):
        import inspect
        src = inspect.getsource(loop.judge_satisfaction)
        self.assertIn("competent to REJECT, not to APPROVE", src)


if __name__ == "__main__":
    unittest.main()
