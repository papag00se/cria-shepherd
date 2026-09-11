"""The steer author supplies an action, never a checker quote plus an action.

Replay: cart-billing-go calls 0075-0076 (2026-09-05).  The checker said, as part of its own
diagnostic, ``go get cartsvc``.  The author was required to quote that line before proposing
``go mod tidy``; the whole-action validator then mistook the quoted command for the proposal and
rejected the useful action.  Checker evidence already has its own ground-truth channel and is
passed separately to the validator, so the authored value has exactly one job.
"""

import json
import re
import unittest

from cria import loop, probegate, prompts


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, name, **kw):
        self.events.append((name, kw))


GO_FINDING = (
    "$ go test -count=1 -v ./... — cart.go:7: missing go.sum entry for module providing "
    "package github.com/shopspring/decimal (imported by cartsvc); to add:\n"
    "go get cartsvc"
)
GO_ACTION = "Run go mod tidy now."


class TheAuthorOwnsOnlyTheActionTests(unittest.TestCase):
    def test_every_author_prompt_separates_evidence_from_the_one_action(self):
        for name in ("steer_diagnose", "steer_diagnose_user", "steer_reasoning_recover"):
            with self.subTest(prompt=name):
                text = prompts.load(name)
                self.assertRegex(text, r"(?i)(only|output).{0,80}(exactly )?one action")
                self.assertRegex(text, r"(?is)(do not|never|must not).{0,100}(quote|restate).{0,100}(evidence|check)")
        self.assertNotRegex(prompts.load("steer_diagnose"),
                            r"(?i)quote the exact thing that is wrong")

    def test_two_structural_actions_are_rejected_without_a_verb_dictionary(self):
        rlog = _Rlog()
        for reply in (
            "Frobnicate alpha. Quux beta.",
            "1. Frobnicate alpha.\n2. Quux beta.",
            "Frobnicate alpha! Quux beta?",
            "- Alpha\n- Beta",
            "1) Alpha\n2) Beta",
        ):
            with self.subTest(reply=reply):
                self.assertIsNone(loop._authored_action(reply, rlog).action)
        self.assertEqual(loop._authored_action("Frobnicate alpha.", rlog).action,
                         "Frobnicate alpha.")

    def test_typed_outcome_distinguishes_no_action_from_structural_refusal(self):
        rlog = _Rlog()
        accepted = loop._authored_action("Read Importer.java now.", rlog)
        on_track = loop._authored_action("ON_TRACK", rlog)
        empty = loop._authored_action("", rlog)
        refused = loop._authored_action("Read Importer.java. Run the compile check.", rlog)
        self.assertEqual(accepted.state, loop._AuthoredActionState.ACCEPTED)
        self.assertEqual(on_track.state, loop._AuthoredActionState.NO_ACTION)
        self.assertEqual(empty.state, loop._AuthoredActionState.NO_ACTION)
        self.assertEqual(refused.state, loop._AuthoredActionState.STRUCTURAL_REFUSAL)


class GoCalls0075And0076ReplayTests(unittest.TestCase):
    def test_checker_quote_cannot_become_the_proposed_action(self):
        """The exact checker command stays evidence; call 0076 judges only ``go mod tidy``."""
        calls = []

        def reasoner(body, _rlog):
            system = body["messages"][0]["content"]
            calls.append(system)
            answer = "SUPPORTED" if "safety classifier" in system else GO_ACTION
            return json.dumps({"choices": [{"message": {"content": answer}}]}).encode()

        sess = loop.GuardState()
        sess.last_gate_flag = GO_FINDING
        out = loop.author_steer(
            reasoner, None, None, sess,
            {"messages": [{"role": "user", "content": "Repair the cart."}], "tools": []},
            _Rlog(), condition="thrash", truth_text=GO_FINDING)

        self.assertEqual(out, GO_ACTION)
        validator_calls = [p for p in calls if "safety classifier" in p]
        self.assertEqual(len(validator_calls), 1)
        validator = validator_calls[0]
        self.assertIn(GO_FINDING, validator)
        proposed = re.search(
            r"A supervisor proposes this one action:\n\n(.*?)\n\nJudge the relationship",
            validator, re.S)
        self.assertIsNotNone(proposed)
        self.assertEqual(proposed.group(1), GO_ACTION)
        self.assertNotIn("go get cartsvc", proposed.group(1))

    def test_checker_lines_remain_in_the_existing_ground_truth_turn(self):
        raw = (f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
               f"{GO_FINDING}\nEXIT:1\n"
               f"{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}\nabc\n")
        framed = loop._frame_for_item(
            [{"role": "tool", "tool_call_id": "gate-1", "content": raw}],
            "", "", 1, 1, synthetic=True, gate_plan=None)
        checks = [m["content"] for m in framed
                  if isinstance(m.get("content"), str)
                  and m["content"].startswith("⟦ctx:checks⟧")]

        self.assertEqual(len(checks), 1)
        self.assertIn(GO_FINDING, checks[0])
        self.assertNotIn(GO_ACTION, checks[0])


if __name__ == "__main__":
    unittest.main()
