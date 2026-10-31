"""Cycle 14 — two notices that asserted things nobody measured (#5b).

D1: A10 call 0018 was a COMPLETE one-call edit_file (1.4K) that reached the output limit after a
long lead; call 0019's prompt told the model its WHOLE-FILE WRITE was cut off partway and to build the
file in small pieces. D2: the thrash trigger said the coder "kept editing" when the last rounds had no
write between them.
"""
import copy
import json
import pathlib
import unittest

from cria import bodykeys
from cria import denial, editrecovery, generation, loop, prompts

FIX = pathlib.Path(__file__).parent / "fixtures" / "a10_0018_complete_edit_at_length.json"


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def _sent(coder):
    """What the model is told on the retry guard_truncation sends."""
    body = {"messages": [{"role": "user", "content": "go"}]}
    seen = {}

    def chat(b, rlog):
        seen["msgs"] = b["messages"]
        return json.dumps({"choices": [{"index": 0, "finish_reason": "stop",
                                        "message": {"role": "assistant", "content": "ok"}}]}).encode()
    loop.guard_truncation(coder, body, chat, _Rlog(), step=1)
    return seen["msgs"][-1]["content"]


class LimitNoticeIsTrueOfTheEventTests(unittest.TestCase):
    def _real(self):
        return json.loads(FIX.read_text())

    def _check_truthful(self, text):
        self.assertIn("edit_file", text)
        self.assertIn("pom.xml", text)
        self.assertIn("4450 tokens", text)
        self.assertIn("arguments complete", text)
        self.assertIn("withheld", text)
        for false in ("whole-file", "SMALL pieces", "partway through writing", "does not exist on disk",
                      "WRITE WAS CUT OFF"):
            self.assertNotIn(false, text)
        self.assertNotIn("cria", text.lower())

    def test_real_0018_raw_length_reply(self):
        self._check_truthful(_sent(self._real()))

    def test_real_0018_after_the_wire_withholds_the_call(self):
        c = generation.safe_completion(self._real())
        self.assertNotIn("tool_calls", c["choices"][0]["message"])
        self._check_truthful(_sent(c))

    def test_text_and_call_sizes_are_the_measured_ones(self):
        c = self._real()
        msg = c["choices"][0]["message"]
        t = _sent(c)
        self.assertIn(f"{len(msg['content'])} characters of text", t)
        self.assertIn(f"({len(msg['tool_calls'][0]['function']['arguments'])} characters", t)

    def test_a_cut_off_whole_file_write_keeps_the_pieces_advice(self):
        c = {"choices": [{"index": 0, "finish_reason": "length", "message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "write_file", "arguments": '{"path": "pom.xml", "content": "<project>'}}]}}],
            "usage": {"completion_tokens": 4450}}
        for variant in (copy.deepcopy(c), generation.safe_completion(copy.deepcopy(c))):
            t = _sent(variant)
            self.assertIn("SMALL pieces", t)
            self.assertIn("pom.xml", t)
            self.assertIn("4450 tokens", t)

    def test_a_cut_off_edit_does_not_get_the_pieces_advice(self):
        c = {"choices": [{"index": 0, "finish_reason": "length", "message": {
            "role": "assistant", "content": "lead",
            "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "edit_file", "arguments": '{"path": "pom.xml", "old_string": "<a>'}}]}}],
            "usage": {"completion_tokens": 100}}
        t = _sent(c)
        self.assertNotIn("SMALL pieces", t)
        self.assertIn("cut off at the limit", t)


class ThrashClauseIsMeasuredTests(unittest.TestCase):
    def _gs(self):
        return loop.GuardState()

    def _write(self, gs, cid):
        coder = {"choices": [{"message": {"tool_calls": [{"id": cid, "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": "a.java", "content": "x"})}}]}}]}
        loop.guard_track_write_streak(gs, coder, _Rlog(), messages=[])

    def test_real_sequence_two_writes_then_five_red_rounds_with_none_between(self):
        gs = self._gs()
        self._write(gs, "w1")
        self._write(gs, "w2")
        for _ in range(5):                      # 16:34:15 … 16:35:25, no write between them
            loop.track_gate_progress(gs, "ERROR same")
        text = loop._STEER_TRIGGER["thrash"](gs, None)
        self.assertIn("no file edit landed between those rounds", text)
        self.assertNotIn("kept editing", text)
        self.assertIn("for 5 rounds", text)

    def test_edits_between_rounds_are_counted_and_idle_tail_is_stated(self):
        gs = self._gs()
        loop.track_gate_progress(gs, "E")
        self._write(gs, "w1")
        loop.track_gate_progress(gs, "E")
        self._write(gs, "w2")
        loop.track_gate_progress(gs, "E")
        loop.track_gate_progress(gs, "E")
        loop.track_gate_progress(gs, "E")
        text = loop._STEER_TRIGGER["thrash"](gs, None)
        self.assertIn("2 file edits landed between those rounds, none of them between the last 3 rounds", text)

    def test_a_refused_write_is_not_counted(self):
        gs = self._gs()
        loop.track_gate_progress(gs, "E")
        self._write(gs, "w1")
        refused = [_asst(_tc("w1", "write_file", {"path": "A.java", "content": "x"})),
                   _res("w1", denial.mark("write_file REFUSED (not written): x"), denial.REFUSED)]
        loop.guard_track_write_streak(gs, {"choices": []}, _Rlog(), messages=refused)
        loop.track_gate_progress(gs, "E")
        self.assertIn("w1", gs.refused_write_ids)
        self.assertIn("no file edit landed", loop._STEER_TRIGGER["thrash"](gs, None))

    def test_prompt_has_no_unmeasured_claim(self):
        self.assertNotIn("kept editing", prompts.load_map("steer_triggers")["thrash"])


def _selfcut(name, args):
    return {"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": args}}]}}]}


def _all_sent(coder):
    """Every user message the guard appends (retry remedy + closing refusal) with a chat that keeps cutting."""
    body = {"messages": [{"role": "user", "content": "go"}]}
    sent = []

    def chat(b, rlog):
        sent.append(b["messages"][-1]["content"])
        return json.dumps(copy.deepcopy(coder)).encode()
    loop.guard_truncation(copy.deepcopy(coder), body, chat, _Rlog(), step=1)
    return sent, body["messages"][-1]["content"]


class SelfCutWordingFollowsTheCallTests(unittest.TestCase):
    EDIT = _selfcut("edit_file", '{"path": "pom.xml", "old_string": "<a>')
    WRITE = _selfcut("write_file", '{"path": "pom.xml", "content": "<project>')

    def test_a_self_cut_edit_is_not_called_a_whole_file_write(self):
        sent, closing = _all_sent(self.EDIT)
        for t in sent + [closing]:
            self.assertNotIn("whole-file write:", t)
            self.assertNotIn("SMALL pieces", t)
            self.assertNotIn("write_file, then APPEND", t)
        self.assertIn("edit_file", sent[0])
        self.assertIn("not a whole-file write", sent[0])
        self.assertIn("not a whole-file write", closing)

    def test_a_self_cut_whole_file_write_keeps_the_pieces_advice_both_places(self):
        sent, closing = _all_sent(self.WRITE)
        self.assertIn("SMALL pieces", sent[0])
        self.assertIn("SMALL pieces", closing)

    def test_the_limit_notice_does_not_presume_the_text_was_the_cost(self):
        t = _sent(json.loads(FIX.read_text()))
        self.assertNotIn("brief", t)
        self.assertIn("were delivered", t)


def _tc(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _asst(*calls):
    return {"role": "assistant", "content": "", "tool_calls": list(calls)}


def _res(cid, text="ok", outcome=None):
    """A tool result as `represent_inbound` hands it on; ``outcome`` is the PROVEN hint, never the wording."""
    m = {"role": "tool", "tool_call_id": cid, "content": text}
    if outcome:
        m[bodykeys.RESULT_OUTCOME] = outcome
    return m


class ThrashClauseInRealDriverOrderTests(unittest.TestCase):
    """The driver records a gate round AFTER the coder turn's results are in the request history but the
    write tracker saw the call BEFORE its result existed; the count must come from the results present."""

    def _sent(self, gs, call):
        loop.guard_track_write_streak(gs, {"choices": [{"message": {"tool_calls": [call]}}]},
                                      _Rlog(), messages=[])

    def test_a_failed_edit_before_the_gate_is_not_counted(self):
        gs = loop.GuardState()
        msgs = []
        for _ in range(3):
            loop.track_gate_progress(gs, "E", msgs)
        e1 = _tc("e1", "edit_file", {"path": "A.java", "old_string": "x", "new_string": "y"})
        self._sent(gs, e1)                                  # tracker sees the call, no result yet
        msgs += [_asst(e1), _res("e1", editrecovery.EDIT_MARK + " no match", denial.UNAPPLIED)]
        loop.track_gate_progress(gs, "E", msgs)
        text = loop._STEER_TRIGGER["thrash"](gs, None)
        self.assertIn("no file edit landed between those rounds", text)

    def test_a_refusal_known_only_at_a_later_round_is_taken_back(self):
        gs = loop.GuardState()
        msgs = []
        loop.track_gate_progress(gs, "E", msgs)
        w1 = _tc("w1", "write_file", {"path": "A.java", "content": "x"})
        self._sent(gs, w1)
        msgs += [_asst(w1), _res("w1", denial.mark("write_file REFUSED (not written): x"), denial.REFUSED)]
        loop.track_gate_progress(gs, "E", msgs)
        w2 = _tc("w2", "write_file", {"path": "B.java", "content": "y"})
        self._sent(gs, w2)
        msgs += [_asst(w2), _res("w2")]
        loop.track_gate_progress(gs, "E", msgs)
        loop.track_gate_progress(gs, "E", msgs)
        text = loop._STEER_TRIGGER["thrash"](gs, None)
        self.assertIn("1 file edit landed between those rounds, none of them between the last 2 rounds", text)

    def test_writes_the_tracker_never_saw_are_read_from_the_history(self):
        gs = loop.GuardState()
        loop.track_gate_progress(gs, "E", [])
        w = _tc("w1", "write_file", {"path": "A.java", "content": "x"})
        loop.track_gate_progress(gs, "E", [_asst(w), _res("w1")])
        self.assertIn("1 file edit landed", loop._STEER_TRIGGER["thrash"](gs, None))


class TwoCallReplyAtTheLimitTests(unittest.TestCase):
    def _two(self):
        a = {"id": "a", "type": "function", "function": {
            "name": "edit_file", "arguments": json.dumps({"path": "A.java", "old_string": "x", "new_string": "y"})}}
        b = {"id": "b", "type": "function", "function": {
            "name": "write_file", "arguments": '{"path": "B.java", "content": "<project>'}}
        return {"choices": [{"index": 0, "finish_reason": "length", "message": {
            "role": "assistant", "content": "lead", "tool_calls": [a, b]}}],
            "usage": {"completion_tokens": 900}}

    def test_cut_write_after_a_complete_edit_is_named_and_gets_the_pieces_advice(self):
        for c in (self._two(), generation.safe_completion(self._two())):
            t = _sent(c)
            self.assertIn("B.java", t)
            self.assertIn("SMALL pieces", t)
            self.assertIn("A.java", t)                 # the other withheld call is named, not erased
            self.assertIn("edit_file", t)
            self.assertNotIn("LAST edit_file CALL", t)

    def test_cut_edit_after_a_complete_write_names_both_and_no_pieces_advice(self):
        c = self._two()
        calls = c["choices"][0]["message"]["tool_calls"]
        calls[0]["function"]["name"], calls[0]["function"]["arguments"] = "write_file", json.dumps(
            {"path": "A.java", "content": "x"})
        calls[1]["function"]["name"], calls[1]["function"]["arguments"] = "edit_file", '{"path": "B.java", "old_string": "<a'
        for v in (copy.deepcopy(c), generation.safe_completion(copy.deepcopy(c))):
            t = _sent(v)
            self.assertNotIn("SMALL pieces", t)
            self.assertIn("A.java", t)
            self.assertIn("B.java", t)
            self.assertIn("arguments cut off at the limit", t)
            self.assertIn("arguments complete", t)


def _call(cid, name, args):
    return {"id": cid, "type": "function", "function": {
        "name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}


def _reply(calls, finish):
    return {"choices": [{"index": 0, "finish_reason": finish, "message": {
        "role": "assistant", "content": "", "tool_calls": calls}}], "usage": {"completion_tokens": 700}}


class SelfCutNamesTheCutCallAndTheRestTests(unittest.TestCase):
    EDIT_A = _call("a", "edit_file", {"path": "A.java", "old_string": "x", "new_string": "y"})

    def test_complete_edit_then_cut_shell_call_is_not_called_an_edit_cut(self):
        shell = _call("s", "exec_command", '{"cmd": "python3 -c \\"print(')
        sent, closing = _all_sent(_reply([copy.deepcopy(self.EDIT_A), shell], "tool_calls"))
        for t in sent + [closing]:
            self.assertNotIn("stopped partway through the arguments of a `edit_file`", t)
            self.assertNotIn("SMALL pieces", t)
        refusal = closing if not sent else sent[0]
        self.assertIn("A.java", refusal)                      # the complete edit is named as withheld
        self.assertIn("`edit_file` on `A.java`", refusal)
        self.assertIn("arguments complete", refusal)

    def test_self_cut_whole_file_write_after_a_complete_edit_names_the_edit(self):
        wf = _call("w", "write_file", '{"path": "B.java", "content": "<project>')
        sent, closing = _all_sent(_reply([copy.deepcopy(self.EDIT_A), wf], "tool_calls"))
        self.assertIn("B.java", sent[0])
        self.assertIn("SMALL pieces", sent[0])
        self.assertIn("`edit_file` on `A.java`", sent[0])
        self.assertIn("`edit_file` on `A.java`", closing)

    def test_self_cut_edit_after_a_complete_edit_names_both(self):
        cut = _call("c", "edit_file", '{"path": "B.java", "old_string": "<a')
        sent, closing = _all_sent(_reply([copy.deepcopy(self.EDIT_A), cut], "tool_calls"))
        self.assertIn("call on `B.java`", sent[0])
        self.assertIn("`edit_file` on `A.java`", sent[0])
        self.assertNotIn("SMALL pieces", sent[0])
        self.assertIn("`edit_file` on `A.java`", closing)


class AlsoListKeepsAnIdenticalCallTests(unittest.TestCase):
    def test_a_call_identical_to_the_cut_one_is_still_listed(self):
        wf = '{"path": "B.java", "content": "<project>'
        base = _reply([_call("w1", "write_file", wf), _call("w2", "write_file", wf)], "length")
        for c in (copy.deepcopy(base), generation.safe_completion(copy.deepcopy(base))):
            t = _sent(c)
            self.assertIn("SMALL pieces", t)
            self.assertIn("also carried", t)
            self.assertIn("`write_file` on `B.java`", t)     # the identical first call, by position


class ClosingRefusalDescribesTheDroppedReplyTests(unittest.TestCase):
    """When retries run out the reply dropped is the one answering the LAST retry, which the loop never
    examined; the closing refusal must describe THAT reply, not an earlier pass."""
    EDIT_A = _call("a", "edit_file", {"path": "A.java", "old_string": "x", "new_string": "y"})

    def _run(self, first, later):
        body = {"messages": [{"role": "user", "content": "go"}]}
        n = [0]

        def chat(b, rlog):
            n[0] += 1
            r = later if n[0] > loop.MAX_TRUNCATION_RETRIES - 1 else first
            return json.dumps(copy.deepcopy(r)).encode()
        loop.guard_truncation(copy.deepcopy(first), body, chat, _Rlog(), step=1)
        self.assertEqual(n[0], loop.MAX_TRUNCATION_RETRIES)
        return body["messages"][-1]["content"]

    def test_dropped_reply_without_the_edit_does_not_name_it(self):
        wf = _call("w", "write_file", '{"path": "B.java", "content": "<project>')
        cut_c = _call("c", "write_file", '{"path": "C.java", "content": "<project>')
        closing = self._run(_reply([copy.deepcopy(self.EDIT_A), wf], "tool_calls"),
                            _reply([cut_c], "tool_calls"))
        self.assertNotIn("A.java", closing)
        self.assertNotIn("also carried", closing)

    def test_dropped_reply_with_the_edit_names_it_though_earlier_passes_did_not(self):
        cut_c = _call("c", "write_file", '{"path": "C.java", "content": "<project>')
        wf = _call("w", "write_file", '{"path": "B.java", "content": "<project>')
        closing = self._run(_reply([cut_c], "tool_calls"),
                            _reply([copy.deepcopy(self.EDIT_A), wf], "tool_calls"))
        self.assertIn("`edit_file` on `A.java`", closing)

    def test_closing_wording_follows_the_dropped_reply_not_an_earlier_one(self):
        edit_cut = _call("e", "edit_file", '{"path": "B.java", "old_string": "<a')
        wf = _call("w", "write_file", '{"path": "B.java", "content": "<project>')
        closing = self._run(_reply([edit_cut], "tool_calls"), _reply([wf], "tool_calls"))
        key_whole = loop.prompts.load_map("call_refused")["selfcut_write"]
        self.assertTrue(closing.startswith(key_whole))
