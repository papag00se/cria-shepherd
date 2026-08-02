"""A judge's thinking often holds the verdict its answer did not. Recover it — one direction only."""
import unittest

from cria import loop


class _Rlog:
    def __init__(self): self.events = []
    def emit(self, kind, **kw): self.events.append((kind, kw))


# Verbatim from run 20260729T224807/0130-satisfaction. cria's prompt ended "Answer NOW with ONLY the
# JSON verdict"; the content field held a leaked <|tool_call>call:read_file{...} and this was the
# thinking that came with it.
REAL = ("The task is not done. The live test output shows Holder: unknown and Total Handles: 0 for "
        "papagoose, while the real data in papagoose.txt has holder=\"stake1...\" and a non-zero "
        "total (the API response contains it). This means resolve_handle is not correctly "
        "extracting the holder name.")


class RecoveryTests(unittest.TestCase):
    def test_the_real_discarded_verdict_is_recovered(self):
        out = loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "satisfaction")
        self.assertIsNotNone(out)
        self.assertIs(out["satisfied"], False)
        self.assertIn("not done", out["reason"])

    def test_the_reason_carries_the_DIAGNOSIS_not_just_a_refusal(self):
        out = loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "satisfaction")
        self.assertIn("Holder: unknown", out["reason"])

    def test_it_is_traced_never_silent(self):
        rlog = _Rlog()
        loop.verdict_from_reasoning(REAL, "satisfied", rlog, "satisfaction")
        self.assertIn("loop.verdict_from_reasoning", [k for k, _ in rlog.events])

    def test_the_phase_key_is_whatever_the_caller_needs(self):
        for flag in ("satisfied", "done", "consistent"):
            with self.subTest(flag=flag):
                self.assertIs(loop.verdict_from_reasoning(REAL, flag, _Rlog(), "x")[flag], False)


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
                self.assertIsNone(loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x"))

    def test_a_recovered_verdict_is_always_False(self):
        for text in (REAL, "The README does not exist.", "The task is not complete."):
            out = loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x")
            if out is not None:
                self.assertIs(out["satisfied"], False)


class QuietWhenThereIsNothingTests(unittest.TestCase):
    def test_empty_reasoning_recovers_nothing(self):
        for text in ("", "   ", None):
            self.assertIsNone(loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x"))

    def test_reasoning_with_no_ruling_recovers_nothing(self):
        # 10 of the 46 measured cases look like this — thinking present, no verdict in it.
        text = ("Let me look at the workspace. There is a handle_client.py and a test file. "
                "The API base URL is https://api.handle.me and the client uses requests.")
        self.assertIsNone(loop.verdict_from_reasoning(text, "satisfied", _Rlog(), "x"))

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
        out = loop.verdict_from_reasoning(self.PROSE, "consistent", _Rlog(), "x")
        self.assertIsNotNone(out)
        self.assertIs(out["consistent"], False)

    def test_prose_approval_is_still_never_recovered(self):
        approve = ("All six tests pass and the real API resolves goose/papagoose correctly; "
                   "the work is complete and the claim matches reality.")
        self.assertIsNone(loop.verdict_from_reasoning(approve, "consistent", _Rlog(), "x"))


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


class NeverCutMidWordTests(unittest.TestCase):
    """The reason is the diagnosis the coder is handed and must act on. It was built from whole
    sentences and then hard-sliced at 300 characters, so a long verdict arrived amputated —
    an instruction that stops mid-sentence is one the coder finishes by guessing."""

    LONG = ("The task is not done. " + " ".join(
        f"Observation number {i} concerns the resolver and its handling of the holder field."
        for i in range(1, 12)))

    def test_the_reason_ends_on_a_sentence(self):
        out = loop.verdict_from_reasoning(self.LONG, "satisfied", _Rlog(), "x")
        self.assertTrue(out["reason"].rstrip().endswith((".", "!", "?", "…")),
                        f"cut mid-text: …{out['reason'][-60:]!r}")

    def test_no_partial_word_survives_the_bound(self):
        out = loop.verdict_from_reasoning(self.LONG, "satisfied", _Rlog(), "x")
        words = {w.strip(".!?…,") for w in self.LONG.split()}
        self.assertIn(out["reason"].split()[-1].strip(".!?…,"), words)

    def test_it_is_still_bounded(self):
        out = loop.verdict_from_reasoning(self.LONG, "satisfied", _Rlog(), "x")
        self.assertLessEqual(len(out["reason"]), loop.REASON_HARD_CEILING)
        self.assertLess(len(out["reason"]), len(self.LONG))

    def test_a_single_long_sentence_rides_WHOLE_rather_than_amputated(self):
        one = "The task is not done because " + "the resolver mishandles the holder field " * 12
        out = loop.verdict_from_reasoning(one.strip() + ".", "satisfied", _Rlog(), "x")
        self.assertTrue(out["reason"].endswith("."))
        self.assertGreater(len(out["reason"]), loop.REASON_BUDGET_CHARS)

    def test_text_with_no_punctuation_at_all_cuts_on_a_word_and_says_so(self):
        run_on = "the task is not done " + "and the resolver still returns the wrong holder " * 20
        out = loop.verdict_from_reasoning(run_on, "satisfied", _Rlog(), "x")
        self.assertTrue(out["reason"].endswith("…"))          # the cut is DISCLOSED
        self.assertNotIn("  ", out["reason"])
        self.assertTrue(all(w in run_on.split() for w in out["reason"].rstrip("…").split()))

    def test_the_short_real_case_is_untouched(self):
        out = loop.verdict_from_reasoning(REAL, "satisfied", _Rlog(), "x")
        self.assertEqual(out["reason"], REAL)                 # fits the budget: carried whole
