"""The judge's own analysis must survive its own inspection rounds.

`_judge_completion` is the shared loop behind the step critic, the completion critic, the confirm
brake, the exec-intent judge and the steer author. It lets the judge LOOK first — call `read_file`
or `list_dir` — and rebuilds the conversation itself between rounds so the final round can ask for
a verdict with the tools withdrawn.

Both write-back sites took `content` alone. For a thinking model calling a tool that field is
EMPTY: the analysis lives in `reasoning_content`. So the turn cria wrote back was
`{"content": None, "tool_calls": [...]}`, and by the final "answer now" round the judge was looking
at a transcript in which it appeared to have inspected five files and said nothing about any of
them.

Measured across one campaign arm: 140 of 329 judgment calls returned empty content — 42%. cria sent
ZERO tools on all 140, and 91 came back with `finish_reason: tool_calls` anyway, the phantom calls
only ever `read_file` (83) and `list_dir` (41). The judge was not trying to act; it was trying to
look, and being asked to rule on evidence its own transcript no longer contained. On one run the
steer author spent 28,777 characters reaching the correct root cause — that the database functions
capture the path in a default argument, so setting it later has no effect — and cria discarded it.
Found it, then lost it.
"""
import json
import tempfile
import unittest
from pathlib import Path

from cria import massage
from cria.config import Role
from cria.loop import judge_satisfaction

ANALYSIS = ("The route regex is present in app.py and the handler branch calls "
            "db.get_customer_orders, so the endpoint deliverable is done.")


class _Rlog:
    phase = ""

    def emit(self, *a, **k):
        pass


class TurnTextReadsEitherChannelTests(unittest.TestCase):
    def test_content_wins_when_the_model_wrote_there(self):
        self.assertEqual(massage.turn_text({"content": "the answer", "reasoning_content": "musing"}),
                         "the answer")

    def test_the_reasoning_channel_is_used_when_content_is_empty(self):
        self.assertEqual(massage.turn_text({"content": "", "reasoning_content": ANALYSIS}), ANALYSIS)

    def test_a_missing_content_field_still_reads_the_reasoning(self):
        self.assertEqual(massage.turn_text({"reasoning": ANALYSIS}), ANALYSIS)

    def test_a_parts_list_content_is_read_as_text(self):
        msg = {"content": [{"type": "text", "text": "parts reply"}], "reasoning_content": "musing"}
        self.assertEqual(massage.turn_text(msg), "parts reply")

    def test_nothing_anywhere_is_empty(self):
        self.assertEqual(massage.turn_text({"content": "", "reasoning_content": ""}), "")
        self.assertEqual(massage.turn_text({}), "")
        self.assertEqual(massage.turn_text(None), "")

    def test_it_does_not_mutate_what_it_reads(self):
        msg = {"content": "", "reasoning_content": ANALYSIS}
        massage.turn_text(msg)
        self.assertEqual(msg, {"content": "", "reasoning_content": ANALYSIS})


class TheJudgeSeesWhatItAlreadyWorkedOutTests(unittest.TestCase):
    """The regression itself, driven through the real loop: a thinking model inspects with a tool,
    writes its analysis to the reasoning channel, and must find that analysis in the transcript it
    is later asked to rule on."""

    def _run(self):
        role = Role(name="reasoner", backend="local")
        bodies = []

        def chat(body, rlog):
            bodies.append(body)
            if len(bodies) == 1:
                # Round 1: a thinking model looks first. content EMPTY, analysis in the other channel.
                return json.dumps({"choices": [{"message": {
                    "content": "",
                    "reasoning_content": ANALYSIS,
                    "tool_calls": [{"id": "s1", "type": "function",
                                    "function": {"name": "list_dir", "arguments": "{}"}}]}}]}).encode()
            return json.dumps({"choices": [{"message": {"content": json.dumps(
                {"satisfied": True, "reason": "the route is on disk"})}}]}).encode()

        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "app.py").write_text("x = 1\n")
            judge_satisfaction("add a route", "ev", chat, role, _Rlog(), workspace_root=ws)
        return bodies

    def _inspection_round(self):
        """The judge's own follow-up round — the one whose transcript carries the tool call it
        just made. NOT the last body: a satisfied verdict is followed by the confirm brake, which
        opens a fresh conversation and would make this test pass for the wrong reason."""
        for body in self._run():
            if any(m.get("role") == "tool" for m in body["messages"]):
                return body
        self.fail("no round carried a tool result — the judge never got to inspect")

    def test_the_judges_analysis_is_in_the_transcript_it_rules_on(self):
        body = self._inspection_round()
        self.assertIn(ANALYSIS, json.dumps(body["messages"]),
                      "the judge inspected, worked something out, and cria erased it before "
                      "asking for the verdict")

    def test_the_assistant_turn_is_not_written_back_empty(self):
        assistants = [m for m in self._inspection_round()["messages"]
                      if m.get("role") == "assistant" and m.get("tool_calls")]
        self.assertTrue(assistants, "the inspecting turn should be in the rebuilt transcript")
        self.assertTrue(all(m.get("content") for m in assistants),
                        "an assistant turn with tool_calls and no content is the erasure")

    def test_the_tool_result_still_follows_its_call(self):
        """The repair must not break the pairing — a dangling tool_call is a 400 on strict
        templates, which is why the write-back exists at all."""
        msgs = self._inspection_round()["messages"]
        for i, m in enumerate(msgs):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                self.assertEqual(msgs[i + 1]["role"], "tool")


if __name__ == "__main__":
    unittest.main()
