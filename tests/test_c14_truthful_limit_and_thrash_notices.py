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

from cria import denial, generation, loop, prompts

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
        refused = [{"role": "tool", "tool_call_id": "w1", "content": denial.mark("write_file REFUSED (not written): x")}]
        loop.guard_track_write_streak(gs, {"choices": []}, _Rlog(), messages=refused)
        loop.track_gate_progress(gs, "E")
        self.assertIn("w1", gs.refused_write_ids)
        self.assertIn("no file edit landed", loop._STEER_TRIGGER["thrash"](gs, None))

    def test_prompt_has_no_unmeasured_claim(self):
        self.assertNotIn("kept editing", prompts.load_map("steer_triggers")["thrash"])
