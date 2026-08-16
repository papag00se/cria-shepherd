"""A judge's thinking often holds the verdict its answer did not. Recover it — one direction only.

THE READING IS A REASONER'S JOB (operator, 2026-08-08). This used to decide with a regex of ruling
phrasings — "task is not done", "remains incomplete". It was the most fragile matcher in cria: every
other word-hunter reads text cria composed or a tool emitted; this one reads a model's unconstrained
private prose and turns the answer into a verdict. It now asks.

`_ask` below stands in for the reasoner and answers the way the prompt asks it to, so these tests
pin the CONTRACT — what cria does with each answer — not the model's judgement. The one-direction
guarantee is still structural: the function can only ever return {flag: False}, whatever comes back.
"""
import unittest

from cria import loop


class _Rlog:
    def __init__(self): self.events = []
    def emit(self, kind, **kw): self.events.append((kind, kw))


def _ask(answer):
    """A stub reasoner returning one fixed line."""
    return lambda _prompt: answer


def _reads(text):
    """A stub that behaves like the prompt asks: rules NOT_DONE on an unfinished-work conclusion.

    Deliberately crude — its job is to feed the contract, not to be a judge. The fixtures below are
    the real captured thinkings, so what is exercised is cria's handling of each answer shape."""
    low = (text or "").lower()
    if any(w in low for w in ("not done", "not complete", "inconsistent", "still missing",
                              "unfinished", "no readme", "no live test")):
        first = (text or "").strip().split(". ")[0]
        return _ask(f"NOT_DONE: {first}.")
    return _ask("UNCLEAR")


# Verbatim from run 20260729T224807/0130-satisfaction. cria's prompt ended "Answer NOW with ONLY the
# JSON verdict"; the content field held a leaked <|tool_call>call:read_file{...} and this was the
# thinking that came with it.
REAL = ("The task is not done. The live test output shows Holder: unknown and Total Handles: 0 for "
        "papagoose, while the real data in papagoose.txt has holder=\"stake1...\" and a non-zero "
        "total (the API response contains it). This means resolve_handle is not correctly "
        "extracting the holder name.")


class RecoveryTests(unittest.TestCase):
    def test_the_real_discarded_verdict_is_recovered(self):
        out = loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "satisfaction", _reads(REAL))
        self.assertIsNotNone(out)
        self.assertIs(out["satisfied"], False)
        self.assertIn("not done", out["reason"])

    def test_the_reason_carries_the_DIAGNOSIS_not_just_a_refusal(self):
        out = loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "satisfaction", _reads(REAL))
        self.assertIn("Holder: unknown", out["reason"])

    def test_it_is_traced_never_silent(self):
        rlog = _Rlog()
        loop.verdict_from_reasoning(REAL, "satisfied", rlog, "satisfaction", _reads(REAL))
        self.assertIn("loop.verdict_from_reasoning", [k for k, _ in rlog.events])

    def test_the_phase_key_is_whatever_the_caller_needs(self):
        for flag in ("satisfied", "done", "consistent"):
            with self.subTest(flag=flag):
                self.assertIs(loop.verdict_from_reasoning(REAL, flag, _Rlog(), "x", _reads(REAL))[flag], False)


class OneDirectionOnlyTests(unittest.TestCase):
    """Principle 13: fail CLOSED on completion. An approval recovered from prose would be failing
    OPEN, which is the one thing this must never do."""

    APPROVALS = (
        "The task is done. Every deliverable is present and the tests pass.",
        "All requirements are met — script, tests, live test and README are all there.",
        "Nothing is missing. This is fully satisfied.",
        "The work is complete and correct.",
    )

    def test_no_approval_is_EVER_recovered(self):
        for text in self.APPROVALS:
            with self.subTest(text=text[:40]):
                self.assertIsNone(loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x", _reads(text)))

    def test_a_recovered_verdict_is_always_False(self):
        for text in (REAL, "The README does not exist.", "The task is not complete."):
            out = loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x", _reads(text))
            if out is not None:
                self.assertIs(out["satisfied"], False)


class TheContractWithTheReasonerTests(unittest.TestCase):
    """What cria does with each answer shape. The reasoner's judgement is its own; these pin cria's."""

    def test_no_reasoner_recovers_nothing(self):
        self.assertIsNone(loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "x", None))

    def test_UNCLEAR_recovers_nothing(self):
        self.assertIsNone(loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "x",
                                                      _ask("UNCLEAR")))

    def test_an_unreadable_answer_recovers_nothing(self):
        for junk in ("", "  ", "I think probably the task is not done?", "{\"done\": false}"):
            self.assertIsNone(loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "x",
                                                          _ask(junk)), junk)

    def test_a_bare_NOT_DONE_with_no_reason_still_recovers(self):
        out = loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "x", _ask("NOT_DONE"))
        self.assertIsNotNone(out)
        self.assertIs(out["satisfied"], False)
        self.assertTrue(out["reason"])            # falls back to the judge's own text

    def test_the_answer_can_never_produce_an_approval(self):
        """Structural, not prompt-dependent: even a reasoner that says the work is DONE cannot make
        this return one — the function only ever emits {flag: False}."""
        for answer in ("NOT_DONE: the work is complete and every test passes.",
                       "NOT_DONE: everything is satisfied."):
            out = loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "x", _ask(answer))
            self.assertIs(out["satisfied"], False)

    def test_the_prompt_offers_only_the_two_answers(self):
        from cria import prompts
        text = prompts.load("verdict_in_reasoning")
        self.assertIn("NOT_DONE", text)
        self.assertIn("UNCLEAR", text)
        self.assertIn("Approval is never recovered from thinking", text)


class QuietWhenThereIsNothingTests(unittest.TestCase):
    def test_empty_reasoning_recovers_nothing(self):
        for text in ("", "   ", None):
            self.assertIsNone(loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x", _reads(text)))

    def test_reasoning_with_no_ruling_recovers_nothing(self):
        # 10 of the 46 measured cases look like this — thinking present, no verdict in it.
        text = ("Let me look at the workspace. There is a handle_client.py and a test file. "
                "The API base URL is https://api.handle.me and the client uses requests.")
        self.assertIsNone(loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x", _reads(text)))

    def test_a_mere_mention_of_a_failing_test_is_not_a_ruling(self):
        # "the tests fail" inside a description must not become a verdict on the whole task.
        self.assertIsNone(loop.verdict_from_reasoning(
            "I ran pytest and looked at the output.", "satisfied", _Rlog(), "x"))


class WiringTests(unittest.TestCase):
    def test_the_satisfaction_parser_falls_back_to_the_reasoning(self):
        import inspect
        src = inspect.getsource(loop._satisfaction_verdict)
        self.assertIn("verdict_from_reasoning", src)
        self.assertIn("extract_json_object", src)   # the normal path is still tried FIRST


class ProseVerdictTests(unittest.TestCase):
    """4 of the 46 stated the ruling in plain prose in the CONTENT field, with no JSON at all."""

    # Verbatim, run 20260730T210615/0451-satisfaction-confirm.
    PROSE = ("The claim is inconsistent. The script's entry point is pyproject.toml -> src.models, "
             "but there is no src/__init__.py, so the import will fail in any real install/run. "
             "Fix: add src/__init__.py and rename tests' imports.")

    def test_a_prose_ruling_is_recovered(self):
        out = loop.verdict_from_reasoning(self.PROSE, "consistent", _Rlog(), "x", _reads(self.PROSE))
        self.assertIsNotNone(out)
        self.assertIs(out["consistent"], False)

    def test_prose_approval_is_still_never_recovered(self):
        approve = ("All six tests pass and the real API resolves goose/papagoose correctly; "
                   "the work is complete and the claim matches reality.")
        self.assertIsNone(loop.verdict_from_reasoning(approve, "consistent", _Rlog(), "x", _reads(approve)))


class PhantomToolTests(unittest.TestCase):
    """The judge holds exactly list_dir + read_file. Across 46 unparseable replies it called Bash,
    Grep, Read, Edit, EditFile, Write, ReadAll, ReadMe, web_fetch — and once a tool named after
    itself. Bash/Grep/Read/Edit/Write are another harness's vocabulary."""

    def test_every_phantom_seen_in_the_captures_is_named(self):
        for name in ("Bash", "Grep", "Read", "Edit", "EditFile", "Write", "ReadAll",
                     "ReadMe", "Gemma4Judge", "web_fetch", "write_file", "edit_file"):
            with self.subTest(tool=name):
                self.assertEqual(
                    loop.leaked_judge_tool('<|tool_call>call:%s{path:<|"|>x<|"|>}<tool_call|>' % name),
                    name)

    def test_the_judges_REAL_tools_are_not_flagged(self):
        for name in ("list_dir", "read_file"):
            with self.subTest(tool=name):
                self.assertEqual(loop.leaked_judge_tool(f'<|tool_call>call:{name}{{}}<tool_call|>'), "")

    def test_ordinary_text_flags_nothing(self):
        self.assertEqual(loop.leaked_judge_tool('{"satisfied": true}'), "")
        self.assertEqual(loop.leaked_judge_tool(""), "")

    def test_the_parse_path_records_it_by_name(self):
        import inspect
        self.assertIn("loop.judge_phantom_tool", inspect.getsource(loop._satisfaction_verdict))


class TheReasonIsNeverCutTests(unittest.TestCase):
    """The reason is the diagnosis the coder is handed and must act on, so it is content a model
    reads and #5 applies: it is never clipped. A long one is restated in a line BY THE JUDGE, and if
    that is unavailable it rides whole. The old behaviour built whole sentences up to 300 characters
    and hard-sliced at 600, which handed the coder an instruction that stopped mid-thought."""

    LONG = ("The task is not done. " + " ".join(
        f"Observation number {i} concerns the resolver and its handling of the holder field."
        for i in range(1, 12)))

    def test_the_reason_ends_on_a_sentence(self):
        out = loop.verdict_from_reasoning(self.LONG, "satisfied", _Rlog(), "x", _reads(self.LONG))
        self.assertTrue(out["reason"].rstrip().endswith((".", "!", "?", "…")),
                        f"cut mid-text: …{out['reason'][-60:]!r}")

    def test_no_partial_word_survives_the_bound(self):
        out = loop.verdict_from_reasoning(self.LONG, "satisfied", _Rlog(), "x", _reads(self.LONG))
        words = {w.strip(".!?…,") for w in self.LONG.split()}
        self.assertIn(out["reason"].split()[-1].strip(".!?…,"), words)

    def test_a_long_reason_is_restated_by_the_judge_not_sliced(self):
        """The only allowed way to shorten it: the judge says it again, shorter."""
        asked = {}

        def ask(prompt):
            if "Restate it in ONE line" in prompt:
                asked["prompt"] = prompt
                return "The resolver does not extract the holder field."
            return "NOT_DONE: " + self.LONG.split(". ")[0] + "."

        out = loop.verdict_from_reasoning(self.LONG, "satisfied", _Rlog(), "x", ask)
        self.assertEqual(out["reason"], "The resolver does not extract the holder field.")
        self.assertIn("Observation number 11", asked["prompt"])   # it saw the WHOLE reason

    def test_without_the_restatement_the_long_reason_rides_WHOLE(self):
        def ask(prompt):
            if "Restate it in ONE line" in prompt:
                return ""                                     # the judge could not condense it
            return "NOT_DONE: " + self.LONG.split(". ")[0] + "."

        out = loop.verdict_from_reasoning(self.LONG, "satisfied", _Rlog(), "x", ask)
        self.assertIn("Observation number 11", out["reason"])

    def test_a_single_long_sentence_rides_WHOLE_rather_than_amputated(self):
        one = ("The task is not done because " + "the resolver mishandles the holder field " * 12).strip() + "."
        out = loop.verdict_from_reasoning(one, "satisfied", _Rlog(), "x", _reads(one))
        self.assertTrue(out["reason"].endswith("."))
        self.assertIn("the resolver mishandles the holder field", out["reason"])

    def test_text_with_no_punctuation_at_all_is_not_cut(self):
        run_on = "the task is not done " + "and the resolver still returns the wrong holder " * 20
        out = loop.verdict_from_reasoning(run_on, "satisfied", _Rlog(), "x", _reads(run_on))
        self.assertNotIn("…", out["reason"])
        self.assertIn(run_on.strip(), out["reason"])
        self.assertNotIn("  ", out["reason"])
        self.assertTrue(all(w in run_on.split() for w in out["reason"].rstrip("…").split()))

    def test_the_short_real_case_is_untouched(self):
        out = loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "x", _reads(REAL))
        self.assertEqual(out["reason"], REAL)                 # fits the budget: carried whole


class TheAnchorMissMustNotShipSentenceZeroTests(unittest.TestCase):
    """When the reasoner's quoted sentence is not found in the thinking, the anchored excerpt is
    worthless — and this defaulted to index 0, shipping the model warming up instead of its ruling.

    ternary-bonsai/ruby 0085. Recovered: "the code was broken because it used the wrong API
    (`EuCountries.eu_members` instead of `ISO3166.EUCountry.codes.include?(code)`)". Delivered to
    the coder: "Let me check if there's a way to see what happened after my write_file call." —
    sentence zero. cria paid for the recovery, it worked, and the answer was binned at the last step.
    """

    THINKING = ("Let me check if there's a way to see what happened after my write_file call. "
                "I will look at the gem docs. The constant is wrong.")

    def test_an_unfound_anchor_uses_the_recovered_sentence(self):
        recovered = "the code used EuCountries.eu_members instead of ISO3166.EUCountry.codes"
        out = loop.verdict_from_reasoning(self.THINKING, "satisfied", _Rlog(), "x",
                                          _ask("NOT_DONE: " + recovered))
        self.assertIn("EuCountries.eu_members", out["reason"])

    def test_it_does_not_ship_the_opening_sentence(self):
        out = loop.verdict_from_reasoning(
            self.THINKING, "satisfied", _Rlog(),
            "x", _ask("NOT_DONE: the code used the wrong constant for EU membership"))
        self.assertNotIn("Let me check if there", out["reason"])

    def test_the_miss_is_recorded(self):
        rlog = _Rlog()
        loop.verdict_from_reasoning(self.THINKING, "satisfied", rlog, "x",
                                    _ask("NOT_DONE: a sentence that is not in the thinking"))
        kw = next(kw for k, kw in rlog.events if k == "loop.verdict_from_reasoning")
        self.assertTrue(kw.get("anchor_missed"))

    def test_a_found_anchor_still_carries_the_sentences_after_it(self):
        """Unchanged: the diagnosis usually lives in the sentences FOLLOWING the ruling."""
        out = loop.verdict_from_reasoning(self.THINKING, "satisfied", _Rlog(), "x",
                                          _ask("NOT_DONE: I will look at the gem docs"))
        self.assertIn("The constant is wrong", out["reason"])

    def test_a_bare_NOT_DONE_still_falls_back_to_the_judges_text(self):
        """Deliberately kept: with no quoted sentence there is no anchor to miss."""
        out = loop.verdict_from_reasoning(self.THINKING, "satisfied", _Rlog(), "x",
                                          _ask("NOT_DONE"))
        self.assertTrue(out["reason"])
