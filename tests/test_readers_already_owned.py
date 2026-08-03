"""Two readers cria already owned and did not call — measured over ~/.cria/calls, 2026-08-02.

Both defects have the same shape: the model answered, cria held a reader that could read the answer,
and the answer was thrown away because it reached the wrong one.

  1. A COMPLETE VERDICT LOST TO ONE MISSING BRACE. Replaying all 18,655 captured final replies
     through ``jsontext.extract_json_object``: 14 came back unreadable while holding a syntactically
     complete JSON object short exactly one ``}``. All 14 stopped on their own
     (``finish_reason: stop``). Twelve are NOT-done rulings carrying both a written ``reason`` and a
     written ``proposed_fix``; one is an APPROVAL and one carries no verdict flag at all.

     WHAT THAT COST, followed to the next captured call rather than assumed: mostly one wasted
     reasoner call — the reasoning-off retry answered in 4 of the 8 step-critic cases, so the coder
     read the retry's words instead of the careful pass's. In exactly ONE call across 126 sessions
     did the coder read cria saying it had no verdict (run 20260728T092146 call 0019, both passes
     unclosed), and its reply reasoned "they haven't given me a specific check to perform" and made
     no tool call. This is a reader fix, not a rescue, and the tests below assert the reading.

  2. A BARE JSON ARRAY THE RE-DERIVATION COULD NOT READ. Over 232 captured re-derivation calls, 19
     were unreadable to ``reassess_remaining`` and 13 of those are a bare top-level array — 7 with
     real steps, 6 the empty ``[]`` that cria's own ``replan.txt`` asks for when nothing remains. The
     plan was left unchanged on all 13.

ONE DIRECTION, in both, is what makes them shippable. A recovered verdict must rule NOT-done; a
recovered "done" would be a false finish reached through a defect in the bytes, which is the
fail-open-on-missing-ground-truth root of every early exit (principle 13). The re-derivation's own
brake is the caller's: an empty tail is re-asked of ``judge_satisfaction`` before anything is
dropped, and a non-empty one still passes the noise judge, the coverage check and the tool-leak
check, each of which keeps the prior plan on trouble.
"""
import json
import types
import unittest

from cria import jsontext, loop, planner
from cria.config import Role


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def _comp(content="", reasoning=None, finish="stop"):
    msg = {"role": "assistant", "content": content}
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    return {"choices": [{"finish_reason": finish, "message": msg}]}


def _scripted(replies):
    seen = []

    def chat(body, rlog):
        seen.append(body)
        return json.dumps(replies[min(len(seen) - 1, len(replies) - 1)]).encode()

    chat.bodies = seen
    chat.calls = 0
    return chat


def _text(s):
    """A plain-text reasoner reply, for the judge calls that follow a re-derivation."""
    return _comp(s)


def _loop_with(reasoner_chat):
    lp = loop.Loop.__new__(loop.Loop)
    lp._ctx = types.SimpleNamespace(reasoner_chat=reasoner_chat,
                                    reasoner_role=Role(name="reasoner", backend="local"))
    return lp


def _role():
    return Role(name="reasoner", backend="local")


# ---------------------------------------------------------------------------------------------
# The captures, verbatim. Each is the reply's `content` exactly as the model produced it — note
# every one of them ENDS without its closing brace; that is the whole defect.

# run 20260728T000013, call 0469-critic, 763 chars, finish_reason=stop
CRITIC_0469 = (
    '{"done": false, "reason": "The coder\'s summary claims Step 6 is complete (README already '
    'contains install/run instructions and live-test note), but the real tool output shows only '
    'three web_fetch calls — no read_file, edit_file, or write_file on README.md appears in '
    'the evidence.", "proposed_fix": "Check if README.md exists via list_dir, then read it with '
    'read_file to see current contents."'
)
# run 20260801T232511, call 0173-critic — the one APPROVAL in the population.
CRITIC_0173_APPROVED = (
    '{"done": true, "reason": "resolve_handle.py IS in the workspace (list_dir output shows it, '
    'despite the coder\'s summary claiming it isn\'t).", "proposed_fix": "Create '
    'get_holder_handle_count.py using the existing resolve_handle_with_count.py as a reference."'
)
# run 20260801T232511, call 0083-satisfaction
SATISFACTION_0083 = (
    '{"satisfied": false, "reason": "Three major deliverables are missing: resolve_handle.py and '
    'get_holder_handle_count.py are imported but not in the workspace; no README.md exists; the '
    'task explicitly requires a LIVE test against the real api.handle.me API.", "proposed_fix": '
    '"Write resolve_handle.py and get_holder_handle_count.py using the api.handle.me endpoint."'
)
# run 20260802T214153, call 0120-critic-confirm
CONFIRM_0120 = (
    '{"consistent": false, "why": "The coder performed web_search for \'Ada Handles API '
    'specification\' and read_file the first 100 lines of the saved search results."'
)
# run 20260727T234416, call 0024-reasoner — a complete four-step re-derivation as a bare array.
# Its own thinking: "I need to produce JSON steps only, no extra commentary."
REPLAN_0024 = json.dumps([
    "Verify resolve_handle('goose') returns non-empty resolved_address, holder_address, "
    "total_handles",
    "Write resolve_all_handles(holder) using the /holders/{address} endpoint from the spec",
    "Add unit tests for resolve_all_handles covering an existing holder and a 404",
    "Write README.md explaining pip install, how to run the script and how to run the tests",
], indent=4)
# run 20260728T101412, call 0121-reasoner — the reply that decides the JSON-only rule. It is a
# README in markdown, and parse_steps reads four of its bullet lines as plan steps.
REPLAN_0121_README = """```markdown
# Ada Handle Resolver

The tests verify that:
- `resolve_handle` returns the expected structure from `/handles/{handle}`
- `get_holder_stats` returns total_handles for a Cardano address
- The composed `resolve_handle_with_stats` produces the three fields requested
- Error handling works when an unknown handle is passed
```"""


# ---------------------------------------------------------------------------------------------
# 1. THE MISSING BRACE — the reader


class CloseUnclosedObjectTests(unittest.TestCase):
    """``jsontext.close_unclosed_object`` supplies CLOSERS and nothing else."""

    def test_the_measured_verdict_is_recovered_whole(self):
        obj = jsontext.close_unclosed_object(CRITIC_0469)
        self.assertIsNotNone(obj, "a complete verdict was read as no verdict at all")
        self.assertIs(obj["done"], False)
        self.assertIn("no read_file, edit_file, or write_file on README.md", obj["reason"])
        self.assertIn("list_dir", obj["proposed_fix"])

    def test_nothing_is_authored__every_key_and_value_is_the_models_own(self):
        # RESHAPE, NEVER AUTHOR (#5b/#2). The recovered object may hold exactly the keys the model
        # wrote, and each value must appear verbatim in the bytes it produced.
        obj = jsontext.close_unclosed_object(CRITIC_0469)
        self.assertEqual(sorted(obj), ["done", "proposed_fix", "reason"])
        for value in obj.values():
            if isinstance(value, str):
                self.assertIn(value[:60], CRITIC_0469)

    def test_a_balanced_object_is_left_to_the_ordinary_reader(self):
        # This is not a second parser. An object that closes on its own is None here, so the two
        # readers can never disagree about a reply both could read.
        self.assertIsNone(jsontext.close_unclosed_object('{"done": false, "reason": "x"}'))

    def test_closers_are_supplied_in_the_nesting_order_the_text_opened_them(self):
        obj = jsontext.close_unclosed_object('{"a": {"b": [1, 2, {"c": 3}')
        self.assertEqual(obj, {"a": {"b": [1, 2, {"c": 3}]}})

    def test_a_reply_that_ends_INSIDE_a_string_is_refused(self):
        # ADVERSARIAL — the input that would make it fire when it must not. Closing braces around a
        # half-written value hands the coder a sentence that stops mid-word: the truncation lie
        # rule #5 exists to prevent. The reader has no way to finish the sentence, so it refuses.
        self.assertIsNone(jsontext.close_unclosed_object(
            '{"done": false, "reason": "the README was never writ'))

    def test_a_trailing_comma_is_refused__that_needs_more_than_a_closer(self):
        self.assertIsNone(jsontext.close_unclosed_object('{"done": false, "reason": "x",'))

    def test_mismatched_nesting_is_refused(self):
        self.assertIsNone(jsontext.close_unclosed_object('{"a": [1, 2}'))

    def test_a_brace_inside_a_string_value_does_not_count_as_nesting(self):
        obj = jsontext.close_unclosed_object('{"reason": "use /handles/{handle} then stop"')
        self.assertEqual(obj, {"reason": "use /handles/{handle} then stop"})

    def test_fences_and_think_preambles_come_off_the_same_way_as_the_ordinary_reader(self):
        obj = jsontext.close_unclosed_object(
            '<think>weighing it</think>\n```json\n{"done": false, "reason": "no tests"')
        self.assertEqual(obj, {"done": False, "reason": "no tests"})


# ---------------------------------------------------------------------------------------------
# 1. THE MISSING BRACE — the one-way gate and the three call sites


class VerdictFromUnclosedTests(unittest.TestCase):
    def test_a_not_done_ruling_is_recovered_and_traced(self):
        rlog = _Rlog()
        obj = loop.verdict_from_unclosed(CRITIC_0469, "done", rlog, "critic")
        self.assertIs(obj["done"], False)
        self.assertIn("loop.verdict_from_unclosed", rlog.kinds())

    def test_an_APPROVAL_is_refused__the_one_direction(self):
        # ADVERSARIAL — the real capture that must NOT fire (run 20260801T232511 call 0173). The
        # bytes repair perfectly; the ruling is `done: true`, and recovering it would advance a step
        # on a defect. Refusing costs a work turn, which is the direction failure must fall.
        rlog = _Rlog()
        self.assertIsNotNone(jsontext.close_unclosed_object(CRITIC_0173_APPROVED))
        self.assertIsNone(loop.verdict_from_unclosed(CRITIC_0173_APPROVED, "done", rlog, "critic"))
        self.assertNotIn("loop.verdict_from_unclosed", rlog.kinds())

    def test_an_object_with_no_verdict_flag_is_refused(self):
        # run 20260802T030826 call 0050-reasoner: a plan re-derivation, repairable, carrying no
        # ruling. Which way a recovered PLAN falls is not knowable here, so it is not recovered here.
        self.assertIsNone(loop.verdict_from_unclosed(
            '{"steps": ["Write resolve.py", "Write resolve_test.py"', "done", _Rlog(), "critic"))

    def test_a_flag_that_is_not_literally_false_is_refused(self):
        for spelling in ('"false"', "0", "null"):
            with self.subTest(spelling=spelling):
                self.assertIsNone(loop.verdict_from_unclosed(
                    '{"done": %s, "reason": "x"' % spelling, "done", _Rlog(), "critic"))


class StepCriticReadsTheVerdictItWasSentTests(unittest.TestCase):
    def test_the_measured_capture_now_yields_a_not_done_verdict(self):
        lp = _loop_with(_scripted([_comp(CRITIC_0469)]))
        obj, _raw = lp._verdict("sys", "user", _Rlog(), reasoning_off=False)
        self.assertIsNotNone(obj, "the judge's own verdict was discarded over one brace")
        self.assertIs(obj["done"], False)

    def test_the_coder_gets_the_judges_OWN_diagnosis_not_a_paraphrase(self):
        # The value over the reasoning recovery: the reason and the proposed_fix are the bytes the
        # judge wrote, so the corrective step names the real action.
        lp = _loop_with(_scripted([_comp(CRITIC_0469)]))
        obj, _raw = lp._verdict("sys", "user", _Rlog(), reasoning_off=False)
        self.assertIn("README.md", obj["reason"])
        self.assertIn("list_dir", obj["proposed_fix"])
        self.assertIn("README.md", loop._verdict_nudge(obj, False))

    def test_a_TRUNCATED_reply_is_still_refused_however_neatly_it_closes(self):
        # ADVERSARIAL — the input that must make it stay silent. Same bytes, cut at the output cap.
        # A generation that stopped because it ran out of room is not a finished answer.
        rlog = _Rlog()
        lp = _loop_with(_scripted([_comp(CRITIC_0469, finish="length")]))
        obj, _raw = lp._verdict("sys", "user", rlog, reasoning_off=False)
        self.assertIsNone(obj)
        self.assertIn("loop.verify_truncated", rlog.kinds())
        self.assertNotIn("loop.verdict_from_unclosed", rlog.kinds())

    def test_an_unclosed_APPROVAL_still_falls_to_the_fail_closed_path(self):
        lp = _loop_with(_scripted([_comp(CRITIC_0173_APPROVED)]))
        obj, _raw = lp._verdict("sys", "user", _Rlog(), reasoning_off=False)
        self.assertIsNone(obj, "a repaired approval must never stand as a verdict")

    def test_a_readable_verdict_is_untouched(self):
        # The recovery sits AFTER extract_json_object, so nothing that already parsed changes.
        approved = json.dumps({"done": True, "reason": "the CLI exists", "proposed_fix": ""})
        lp = _loop_with(_scripted([_comp(approved)]))
        obj, _raw = lp._verdict("sys", "user", _Rlog(), reasoning_off=False)
        self.assertIs(obj["done"], True)


class SatisfactionJudgeReadsTheVerdictItWasSentTests(unittest.TestCase):
    def test_the_measured_capture_now_yields_a_not_satisfied_verdict(self):
        obj = loop._satisfaction_verdict("sys", "user", _scripted([_comp(SATISFACTION_0083)]),
                                         _role(), _Rlog(), reasoning_off=False)
        self.assertIsNotNone(obj)
        self.assertIs(obj["satisfied"], False)
        self.assertIn("README.md", obj["reason"])

    def test_a_repaired_SATISFIED_is_refused(self):
        claim = '{"satisfied": true, "reason": "everything is present", "proposed_fix": ""'
        obj = loop._satisfaction_verdict("sys", "user", _scripted([_comp(claim)]),
                                         _role(), _Rlog(), reasoning_off=False)
        self.assertIsNone(obj, "a repaired 'satisfied' would end a session on a defect in the bytes")

    def test_a_truncated_satisfaction_reply_is_refused(self):
        rlog = _Rlog()
        obj = loop._satisfaction_verdict("sys", "user",
                                         _scripted([_comp(SATISFACTION_0083, finish="length")]),
                                         _role(), rlog, reasoning_off=False)
        self.assertIsNone(obj)
        self.assertIn("loop.satisfaction_truncated", rlog.kinds())


class ConfirmBrakeReadsTheVerdictItWasSentTests(unittest.TestCase):
    """The APPROVE-path brake. Its direction is inverted: a recovered NOT-consistent WITHHOLDS an
    approval (more work), so that is the only one recovered."""

    def _confirm(self, content, tmpdir, finish="stop"):
        return loop._confirm_completion("write the README", "it is written", tmpdir,
                                        _scripted([_comp(content, finish=finish)]), _role(),
                                        _Rlog(), phase="critic-confirm")

    def test_a_not_consistent_check_is_recovered_and_withholds_the_approval(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            confirmed, why = self._confirm(CONFIRM_0120, d)
        self.assertFalse(confirmed)
        self.assertIn("web_search", why)

    def test_a_repaired_CONSISTENT_never_confirms(self):
        # ADVERSARIAL — the fire-when-it-should-not case for this site. Recovering a `true` here
        # would confirm a done, the one direction principle 13 forbids. It falls to the unparseable
        # path instead, which already fails closed.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            confirmed, _why = self._confirm('{"consistent": true, "why": "the file is there"', d)
        self.assertFalse(confirmed)

    def test_a_truncated_confirm_reply_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            confirmed, _why = self._confirm(CONFIRM_0120, d, finish="length")
        self.assertFalse(confirmed)


# ---------------------------------------------------------------------------------------------
# 2. THE BARE ARRAY


class JsonStepsTests(unittest.TestCase):
    def test_the_measured_bare_array_is_read(self):
        steps = planner.json_steps(REPLAN_0024)
        self.assertEqual(len(steps), 4)
        self.assertTrue(steps[0].startswith("Verify resolve_handle"))

    def test_an_empty_array_is_an_ANSWER_not_a_miss(self):
        self.assertEqual(planner.json_steps("[]"), [])
        self.assertEqual(planner.json_steps('{"steps": []}'), [])
        self.assertIsNone(planner.json_steps("no json here at all"))

    def test_a_fenced_bare_array_is_read(self):
        self.assertEqual(planner.json_steps('```json\n["Add the live test", "Write the README"]\n```'),
                         ["Add the live test", "Write the README"])

    def test_a_synonym_key_is_read__the_shape_parse_steps_already_knew(self):
        # run 20260802T214153 call 0038: {"remaining_steps": [{"step": ..., "status": ...}]}
        text = json.dumps({"remaining_steps": [{"step": "Research the API", "status": "pending"},
                                               {"step": "Write the resolver", "status": "pending"}]})
        self.assertEqual(planner.json_steps(text), ["Research the API", "Write the resolver"])

    def test_an_array_the_reply_merely_CONTAINS_is_not_a_plan(self):
        # ADVERSARIAL — the input that would make it fire when it must not, and the exact capture
        # that produced it (run 20260801T232511 call 0067, a pytest file). Its first bracket is a
        # subscript, `result["resolved_ada_address"]`; a scan for the first `[` hands that back as a
        # one-step plan. The rule is that the REPLY IS an array, never that it holds one.
        self.assertIsNone(planner.json_steps(
            'resolve_handles_test.py\n\n```python\n'
            'def test_it():\n    assert isinstance(result["resolved_ada_address"], str)\n```'))

    def test_prose_and_markdown_are_not_read_as_JSON_steps(self):
        # ADVERSARIAL — run 20260728T101412 call 0121 answered the re-derivation with a README.
        # parse_steps reads four of its bullets; json_steps reads nothing, which is why the
        # re-derivation calls json_steps and not parse_steps.
        self.assertIsNone(planner.json_steps(REPLAN_0121_README))
        self.assertEqual(len(planner.parse_steps(REPLAN_0121_README) or []), 4)


class ParseStepsStillReadsEverythingItDidTests(unittest.TestCase):
    """The shared reader gained the bare array; nothing it already read may change. Measured over
    every captured reply on this box (6,714): parse_steps changes on 3, all three re-derivations
    that returned a bare array, all three from None to real steps."""

    def test_the_bare_array_is_now_read_here_too(self):
        self.assertEqual(len(planner.parse_steps(REPLAN_0024) or []), 4)

    def test_an_EMPTY_json_list_still_falls_through_to_the_prose_fallbacks(self):
        # parse_steps' callers DRAFT a plan, for whom "no steps" is a failed draft. Only the living
        # re-derivation has a meaning for [], and it reads json_steps directly.
        self.assertIsNone(planner.parse_steps('{"steps": []}'))
        self.assertIsNone(planner.parse_steps("[]"))
        self.assertEqual(planner.parse_steps('{"steps": []}\n1. Write it\n2. Test it'),
                         ["Write it", "Test it"])

    def test_a_numbered_plan_still_reads(self):
        self.assertEqual(planner.parse_steps("1. Fetch the spec\n2. Write the resolver"),
                         ["Fetch the spec", "Write the resolver"])

    def test_prose_is_still_not_a_plan(self):
        self.assertIsNone(planner.parse_steps('I think the answer is "probably yes".'))


class ReassessRemainingReadsTheReplyItWasSentTests(unittest.TestCase):
    def test_the_measured_bare_array_now_re_derives_the_plan(self):
        # Three reasoner calls: the re-derivation, the noise judge (NONE → drop nothing), the
        # coverage check (NONE → nothing missing).
        steps = loop.reassess_remaining(
            _scripted([_comp(REPLAN_0024), _text("NONE"), _text("NONE")]),
            _role(), "resolve an Ada Handle", "- researched the API", "- old step", "ev", _Rlog())
        self.assertIsNotNone(steps, "a complete four-step re-derivation left the plan unchanged")
        self.assertEqual(len(steps), 4)

    def test_a_bare_empty_array_means_nothing_remains(self):
        # The contract this function's own docstring and cria's own replan.txt already define:
        # "Return [] ONLY when the evidence shows every remaining deliverable is already done."
        # It is not a false finish — the CALLER re-asks judge_satisfaction before dropping the tail.
        self.assertEqual(
            loop.reassess_remaining(_scripted([_comp("[]")]), _role(), "t", "- done", "- old",
                                    "ev", _Rlog()),
            [])

    def test_a_README_is_never_read_as_the_remaining_plan(self):
        # ADVERSARIAL — the fire-when-it-should-not case, and the reason this call reads JSON only.
        # Replacing a correct plan with a README's bullet lines is worse than reading nothing
        # (principle 2: the dangerous class of intervention REPLACES a correct prior).
        self.assertIsNone(
            loop.reassess_remaining(_scripted([_comp(REPLAN_0121_README)]), _role(), "t",
                                    "- done", "- old step", "ev", _Rlog()))

    def test_an_unreadable_reply_still_keeps_the_plan_untouched(self):
        self.assertIsNone(
            loop.reassess_remaining(_scripted([_comp("I am not sure what remains.")]), _role(),
                                    "t", "- done", "- old", "ev", _Rlog()))

    def test_the_coverage_check_still_refuses_a_tail_that_drops_a_deliverable(self):
        # The recovered tail is NOT privileged: it goes through every guard a readable one does.
        steps = loop.reassess_remaining(
            _scripted([_comp(REPLAN_0024), _text("NONE"),
                       _text('{"missing": ["a live test against the real API"]}')]),
            _role(), "script + unit tests + README + live test", "- researched", "- old", "ev",
            _Rlog())
        self.assertIsNone(steps, "an uncovered tail must leave the plan untouched")


if __name__ == "__main__":
    unittest.main()
