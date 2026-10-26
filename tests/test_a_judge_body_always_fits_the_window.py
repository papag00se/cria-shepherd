"""A judge's evidence must be something the context floor can reduce, never a protected message.

Walked on phi4 A11 (feed-pipeline-java, 16,384-token window, 8,192 reserved for the answer). Two
closed-question judges died at the wire with "Measured input cannot fit the context window without
losing protected input" — both passes each:

* the steer-diagnostic judge (``summarize.error`` x2): the WHOLE session, ~17.7k estimated tokens, sat
  inside the SYSTEM message. ``floor-trim`` reported ``turns_dropped: 0`` — a system message is
  protected, so there was nothing it was allowed to touch. The steer was then withheld as UNDECIDABLE
  for a reason that had nothing to do with the steer.
* the completion judge (``loop.satisfaction_error`` x2): the action log (~22.2k estimated tokens) sat
  in the ACTIVE user message — protected too. ``fail closed`` cost the coder a "not yet verified"
  steer instead of the judge's real reading.

The fix is not a wider window or a clip: the unbounded record rides as composed evidence blocks, the one
floor drops the OLDEST ones with a label, and the task/question/newest actions survive. These tests
replay the reconstructed A11 sizes through the real ``contextfloor.fit`` at the live window.
"""
import copy
import json
import unittest

from cria import contextfloor, loop

WINDOW, RESERVE = 16384, 8192      # context.floor events of the failing calls: window / reserve_requested
SAFETY = 1.09                      # the tighter, measured ratio of the second floor pass


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, name, **kw):
        self.events.append((name, kw))


def _log(chars: int, newest: str) -> str:
    """An action log of ``chars`` characters of distinct lines ending in a unique newest action."""
    lines, n, size = [], 0, 0
    while size < chars:
        ln = f"tool exec_command #{n}: mvn -q test -Dtest=ImporterTest{n} exited 1 at Importer.java:{n % 240}\n"
        lines.append(ln)
        size += len(ln)
        n += 1
    return "".join(lines) + newest + "\n"


def _fit(messages):
    work, _tools, rep = contextfloor.fit(messages, None, window=WINDOW, reserve=RESERVE, safety=SAFETY)
    return work, rep


def _text(messages) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages)


class _Capture:
    """A fake model that records each body it is sent and answers with ``reply``."""

    def __init__(self, reply):
        self.bodies, self.reply = [], reply

    def __call__(self, body, rlog):
        # This is the raw pre-floor input. JSON serialization would erase the
        # producer enum's in-process authority, not copy the body the floor reads.
        self.bodies.append(copy.deepcopy(body))
        return json.dumps({"choices": [{"message": {"role": "assistant", "content": self.reply},
                                        "finish_reason": "stop"}]}).encode()


class TheSteerDiagnosticJudgeFitsTests(unittest.TestCase):
    NEWEST = "NEWEST-GROUNDING-LINE the coder read pom.xml at 01:58"

    def _verdict(self, grounding):
        chat = _Capture("SUPPORTED")

        def ask(system, user="", evidence_blocks=None):
            return loop.summarize(chat, None, system, user or loop._ASK_USER_TURN, _Rlog(),
                                  phase="steer-code", temperature=0.0, evidence_blocks=evidence_blocks)
        ask.composes_evidence = True
        verdict = loop._diagnostic_action_verdict(
            "Set the source level to 17 in pom.xml.", "Importer.java:12: error: cannot find symbol",
            set(), _Rlog(), (lambda sysm: ask(sysm, "")), grounding=grounding,
            ask_with_evidence=lambda sysm, blocks: ask(sysm, "", blocks))
        return verdict, chat.bodies

    def test_a_session_sized_grounding_fits_the_window(self):
        # 66k characters ~ the 17.7k estimated tokens the A11 call measured.
        verdict, bodies = self._verdict(_log(66000, self.NEWEST))
        self.assertEqual(verdict, "SUPPORTED")
        work, rep = _fit(bodies[0]["messages"])
        self.assertFalse(rep.over_budget, "the judge body must fit the window the way the floor reduces it")
        self.assertGreater(rep.turns_dropped, 0)

    def test_the_reduction_is_labelled_and_the_newest_evidence_and_question_survive(self):
        _, bodies = self._verdict(_log(66000, self.NEWEST))
        work, rep = _fit(bodies[0]["messages"])
        text = _text(work)
        self.assertIn("⟦ctx:compacted⟧", text)                     # the drop says it happened
        self.assertIn(self.NEWEST, text)                           # oldest first, newest kept
        self.assertIn("Set the source level to 17 in pom.xml.", text)   # the action under judgment
        self.assertIn("Importer.java:12: error: cannot find symbol", text)   # the checker evidence

    def test_small_grounding_is_carried_whole_and_unreduced(self):
        grounding = _log(2000, self.NEWEST)
        _, bodies = self._verdict(grounding)
        work, rep = _fit(bodies[0]["messages"])
        self.assertEqual(rep.turns_dropped, 0)
        self.assertEqual("".join(m["content"] for m in bodies[0]["messages"][2:-1]), grounding)

    def test_every_block_re_concatenates_to_the_original_evidence(self):
        text = _log(30000, "end") + "x" * 9000 + "\nlast\n"        # includes one over-long line
        self.assertEqual("".join(loop._evidence_blocks(text)), text)


class TheSharedSteerGateRoutesGroundingAsEvidenceTests(unittest.TestCase):
    def test_the_gate_hands_a_composing_seat_the_grounding_as_blocks(self):
        from types import SimpleNamespace
        seen = {}

        def ask(system, user="", evidence_blocks=None):
            seen.update(system=system, blocks=evidence_blocks)
            return "SUPPORTED"
        ask.composes_evidence = True
        sess = SimpleNamespace(last_gate_flag="Importer.java:12: error: cannot find symbol",
                               refused_names=set(), fetched_pages={}, plan=None)
        evidence = _log(66000, "NEWEST")
        out = loop._grounded_steer_or_none("Add the missing import.", evidence, _Rlog(), ask=ask,
                                           sess=sess, messages=[])
        self.assertEqual("".join(seen["blocks"]), evidence)
        self.assertNotIn("NEWEST", seen["system"])      # the system message no longer carries the session
        self.assertLess(len(seen["system"]), 8000)
        self.assertIsNotNone(out)


class TheCompletionJudgeFitsTests(unittest.TestCase):
    NEWEST = "NEWEST-ACTION the coder ran mvn test and it exited 0"
    TASK = "Fix these three problems in the supplier feed importer: make it 4x faster."

    def _judge(self, evidence_chars):
        chat = _Capture(json.dumps({"satisfied": False, "reason": "not yet"}))
        result = loop.judge_satisfaction(self.TASK, _log(evidence_chars, self.NEWEST), chat, None, _Rlog())
        return result, chat.bodies

    def test_an_a11_sized_action_log_fits_the_window(self):
        # 88k characters ~ the 22.2k estimated tokens of the failing satisfaction call.
        _, bodies = self._judge(88000)
        work, rep = _fit(bodies[0]["messages"])
        self.assertFalse(rep.over_budget)
        self.assertGreater(rep.turns_dropped, 0)

    def test_the_task_the_question_and_the_newest_actions_survive_a_labelled_reduction(self):
        _, bodies = self._judge(88000)
        work, _rep = _fit(bodies[0]["messages"])
        text = _text(work)
        self.assertIn("⟦ctx:compacted⟧", text)
        self.assertIn(self.NEWEST, text)
        self.assertIn(self.TASK, text)
        self.assertEqual(work[-1]["role"], "user")
        self.assertIn(self.TASK, work[-1]["content"])          # the active turn is the question

    def test_a_judge_that_can_see_the_record_still_reaches_a_verdict_not_a_failure(self):
        (satisfied, _nudge, _action), bodies = self._judge(88000)
        self.assertFalse(satisfied)
        self.assertEqual(len(bodies), 1, "one verdict call, no failed pass and no reasoning-off retry")

    def test_the_whole_record_is_still_sent_when_it_fits(self):
        evidence = _log(3000, self.NEWEST)
        _, bodies = self._judge(3000)
        carried = "".join(m["content"] for m in bodies[0]["messages"][1:-1])
        self.assertEqual(carried, evidence)


class TheNegativeDiagnosisQuestionFitsTests(unittest.TestCase):
    """Behind a NOT-satisfied verdict the support question embeds the same action log. Making the
    verdict fit and leaving this one in a protected system message would only move the failure."""
    TASK_QUOTE = "make it 4x faster"
    EVIDENCE_QUOTE = "mvn -q test -Dtest=ImporterTest7 exited 1"

    def _nudge(self, composed):
        chat = _Capture("SUPPORTED")

        def ask(question, evidence_blocks=None):
            return loop.ask_closed(chat, None, question, _Rlog(), phase="negative-diagnosis",
                                   evidence_blocks=evidence_blocks)
        if composed:
            ask.composes_evidence = True
        obj = {"satisfied": False, "diagnosis_kind": "unverified_requirement", "subject": "",
               "task_quote": self.TASK_QUOTE, "evidence_source": "action_log",
               "evidence_quote": self.EVIDENCE_QUOTE, "reason": "tests fail"}
        nudge = loop._negative_diagnosis_nudge(
            obj, task="Fix the importer and make it 4x faster.", action_log=_log(88000, "end"),
            checks="", ask=ask, rlog=_Rlog())
        return nudge, chat.bodies

    def test_an_a11_sized_action_log_in_the_question_fits_the_window(self):
        nudge, bodies = self._nudge(True)
        self.assertIsNotNone(nudge)
        work, rep = _fit(bodies[0]["messages"])
        self.assertFalse(rep.over_budget)
        self.assertIn("⟦ctx:compacted⟧", _text(work))

    def test_a_plain_ask_still_gets_the_whole_question_in_one_message(self):
        _nudge, bodies = self._nudge(False)
        self.assertEqual(len(bodies[0]["messages"]), 2)


class EveryPointerIsTrueOfTheLayoutItDescribesTests(unittest.TestCase):
    """The words that tell the model where the evidence is must match the body actually sent. The
    closed-question seats put the QUESTION in the system message, the evidence in the user messages
    that FOLLOW it, and a closing "answer the question above" turn; the completion judge has no
    system question — its pinned final message asks it and the evidence is ABOVE that message."""
    GROUNDING = _log(9000, "NEWEST")

    def _roles(self, messages):
        return [m["role"] for m in messages]

    def _assert_system_question_layout(self, messages, joined_evidence, pointer):
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn(pointer, messages[0]["content"])          # says the evidence FOLLOWS
        self.assertNotIn(joined_evidence[:80], messages[0]["content"])   # and it truly is not in here
        self.assertIn("question asked in the system message", messages[1]["content"])
        self.assertIn("follow this one", messages[1]["content"])
        self.assertEqual("".join(m["content"] for m in messages[2:-1]), joined_evidence)
        self.assertEqual(set(self._roles(messages[1:])), {"user"})
        self.assertEqual(messages[-1]["content"], loop._ASK_USER_TURN)
        for m in messages:
            self.assertNotIn("messages before this one", m["content"])
            self.assertNotIn("question in the final message", m["content"])

    def test_the_steer_diagnostic_body(self):
        chat = _Capture("SUPPORTED")
        seat = loop._composed_closed_ask(chat, None, _Rlog(), phase="steer-code")
        loop._diagnostic_action_verdict(
            "Add the missing import.", "Importer.java:12: error: cannot find symbol", set(), _Rlog(),
            lambda q: "", grounding=self.GROUNDING, ask_with_evidence=seat)
        self._assert_system_question_layout(chat.bodies[0]["messages"], self.GROUNDING,
                                            "user messages that follow this one")

    def test_the_negative_diagnosis_body(self):
        chat = _Capture("SUPPORTED")
        seat = loop._composed_closed_ask(chat, None, _Rlog(), phase="negative-diagnosis")
        obj = {"satisfied": False, "diagnosis_kind": "unverified_requirement", "subject": "",
               "task_quote": "make it 4x faster", "evidence_source": "action_log",
               "evidence_quote": "mvn -q test -Dtest=ImporterTest7 exited 1", "reason": "x"}
        loop._negative_diagnosis_nudge(obj, task="Fix it and make it 4x faster.",
                                       action_log=self.GROUNDING, ask=seat, rlog=_Rlog())
        self._assert_system_question_layout(chat.bodies[0]["messages"], self.GROUNDING,
                                            "user messages that follow this one")

    def test_the_completion_judge_body(self):
        chat = _Capture(json.dumps({"satisfied": False, "reason": "no"}))
        loop.judge_satisfaction("Make it 4x faster.", self.GROUNDING, chat, None, _Rlog())
        messages = chat.bodies[0]["messages"]
        self.assertEqual(self._roles(messages)[0], "system")
        self.assertNotIn("question asked in the system message", _text(messages))
        self.assertEqual("".join(m["content"] for m in messages[1:-1]), self.GROUNDING)
        self.assertIn("user messages above this one", messages[-1]["content"])
        self.assertIn("Make it 4x faster.", messages[-1]["content"])


class TheCurrentFilesOutlastTheOlderRecordTests(unittest.TestCase):
    NEWEST = "NEWEST-ACTION exit 0"
    FILES = "THE FILES AS THEY ARE ON DISK NOW: Importer.java " + "class Importer {} " * 200

    def _body(self):
        from types import SimpleNamespace
        from unittest import mock
        chat = _Capture(json.dumps({"satisfied": False, "reason": "no"}))
        view = SimpleNamespace(surveyed=True)
        with mock.patch.object(loop.wsview, "current", return_value=view), \
             mock.patch.object(loop.groundtruth, "files_for_a_judge", return_value=self.FILES):
            loop.judge_satisfaction("Make it 4x faster.", _log(88000, self.NEWEST), chat, None,
                                    _Rlog(), workspace_root="/ws")
        return chat.bodies[0]

    def test_the_files_message_sits_after_the_record_and_before_the_question(self):
        msgs = self._body()["messages"]
        at = [i for i, m in enumerate(msgs) if m["content"] == self.FILES]
        self.assertEqual(at, [len(msgs) - 2])

    def test_through_the_real_wire_fit_the_older_record_goes_before_the_current_files(self):
        body = self._body()
        work, _t, rep = contextfloor.fit(body["messages"], body.get("tools"), window=WINDOW,
                                         reserve=RESERVE, safety=SAFETY,
                                         pinned_task=body["cria_pinned_task"])
        self.assertFalse(rep.over_budget)
        self.assertGreater(rep.turns_dropped, 0)
        text = _text(work)
        self.assertIn(self.FILES, text)
        self.assertIn(self.NEWEST, text)


if __name__ == "__main__":
    unittest.main()
