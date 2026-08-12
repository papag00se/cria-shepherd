"""Whether a directive QUOTES the coder's failing line or DICTATES a fix is a judgment, and it was
being made by a regex. That regex was wrong in both directions:

  * it dropped whole steers on a leading `import ` — a quote of the file under discussion, which the
    author's own prompt explicitly permits;
  * it fired exactly TWICE in the whole capture history, while the directive telling the coder to add
    `pytest.register_pytest_mark("live")` — not a real function — sailed through, because that code
    sat inline in prose with no fence and no line-leading keyword (run 20260801T232511 call 0132).

Chasing inline code with more pattern is deterministic code doing a judgment's job. The pattern is
now a TRIGGER for one focused question.
"""
import unittest

from cria import loop


class _Rlog:
    def __init__(self): self.events = []
    def emit(self, kind, **kw): self.events.append((kind, kw))


# Verbatim from run 20260801T232511 call 0132 — the steer the coder actually received.
REAL_DICTATION = ("UNSTUCK You are stuck because pytest is warning about an unknown mark named live. "
                  "The fix is to register the mark so pytest knows it is valid. 1. Register the mark "
                  "in resolve_handle.py (both already have register_assert_rewrite, so just add one "
                  'more line): pytest.register_pytest_mark("live")')

REAL_QUOTE = ("Two bugs each named by the check: resolve_handles.py line 14 has data=response.json() "
              "where one mock's json is a dict, not callable; fix the mock so it matches how line 14 "
              "uses it, then re-run the failing test.")


class TriggerTests(unittest.TestCase):
    def test_inline_dotted_calls_now_trip_the_trigger(self):
        # The exact miss: no fence, no line-leading keyword, and it reached the coder.
        self.assertTrue(loop._CODE_SHAPED.search(REAL_DICTATION))

    def test_the_trigger_still_catches_what_it_always_did(self):
        for text in ("here:\n```python\nx = 1\n```", "\nimport os\n", "\n$ pytest -q\n"):
            with self.subTest(text=text[:20]):
                self.assertTrue(loop._CODE_SHAPED.search(text))

    def test_plain_prose_never_trips_it(self):
        self.assertIsNone(loop._CODE_SHAPED.search(
            "You keep rewriting the same file. Read it first, then change only the line the check names."))


class OneQuestionTests(unittest.TestCase):
    def test_a_DESCRIBES_verdict_keeps_a_steer_the_regex_would_have_eaten(self):
        asked = {}

        def ask(system, user):
            asked["system"] = system
            return "DESCRIBES"

        self.assertFalse(loop._dictates_code(REAL_QUOTE, ask))
        self.assertIn("DIRECTIVE:", asked["system"])
        self.assertIn("response.json()", asked["system"])

    def test_a_DICTATES_verdict_drops_it(self):
        self.assertTrue(loop._dictates_code(REAL_DICTATION, lambda s, u: "DICTATES"))

    def test_no_question_is_asked_when_nothing_is_code_shaped(self):
        calls = []

        def ask(system, user):
            calls.append(system)
            return "DESCRIBES"

        self.assertFalse(loop._dictates_code("Read the file before you rewrite it.", ask))
        self.assertEqual(calls, [])          # the pre-filter is what makes the call affordable

    def test_the_verdict_survives_a_models_decoration(self):
        for ans in ("DESCRIBES.", "  describes  ", "`DESCRIBES`", "DESCRIBES — it only quotes."):
            with self.subTest(ans=ans):
                self.assertFalse(loop._dictates_code(REAL_QUOTE, lambda s, u, a=ans: a))

    def test_an_unreadable_answer_leaves_the_pre_filters_verdict_STANDING(self):
        # The safe null is today's behaviour, so this change can only move steers from dropped to
        # delivered, never the other way.
        for ans in ("", "I think it depends", None, "MAYBE"):
            with self.subTest(ans=ans):
                self.assertTrue(loop._dictates_code(REAL_DICTATION, lambda s, u, a=ans: a))

    def test_no_reasoner_at_all_is_the_same_safe_null(self):
        self.assertTrue(loop._dictates_code(REAL_DICTATION, None))


class WiringTests(unittest.TestCase):
    def test_the_gate_passes_its_reasoner_through(self):
        import inspect
        src = inspect.getsource(loop._grounded_steer_or_none)
        self.assertIn("_dictates_code(directive, ask)", src)

    def test_author_steer_supplies_one_on_both_of_its_paths(self):
        import inspect
        src = inspect.getsource(loop.author_steer)
        self.assertEqual(src.count("ask=_steer_ask"), 2)   # tooled path and plain path

    def test_a_DICTATES_steer_is_still_delivered_not_dropped(self):
        """The operator's 2026-08-04 ruling stands: the steer SHIPS. The drop's harm evidence came
        from a BLIND author (since fixed) and the 08-01 dense passes were carried by sighted
        dictation."""
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(REAL_DICTATION, "evidence", rlog,
                                           ask=lambda s, u: "DICTATES")
        self.assertTrue(out)                                   # delivered, never None
        self.assertIn("loop.steer_dictated_code", [k for k, _ in rlog.events])

    def test_the_prose_survives_and_the_invented_call_does_not(self):
        """The ruling's own reasoning, enforced. It turned on SIGHTED versus BLIND dictation, so the
        question is not "does this contain code" but "did the author read it or invent it" — and
        cria holds the evidence the author was shown.

        REAL_DICTATION is the measured example: `pytest.register_pytest_mark("live")` is not a real
        function, and it reached a coder because it sat inline in prose with no fence. The diagnosis
        around it is correct and worth keeping."""
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(REAL_DICTATION, "evidence", rlog,
                                           ask=lambda s, u: "DICTATES")
        self.assertIn("unknown mark named live", out)          # the diagnosis survives
        self.assertNotIn("register_pytest_mark", out)          # the invention does not
        self.assertIn("code removed", out)                     # and the removal is disclosed

    def test_a_quote_of_something_cria_showed_the_author_survives(self):
        """The case the ladder passes were built on: a steer quoting the coder's own failing line."""
        rlog = _Rlog()
        directive = 'Your assertion cart.go:22: if got != 48.58 { is the line that fails. Fix the total.'
        out = loop._grounded_steer_or_none(directive, "cart.go:22: if got != 48.58 {", rlog,
                                           ask=lambda s, u: "DICTATES")
        self.assertEqual(out, directive)

    def test_with_no_evidence_nothing_is_stripped(self):
        """cria cannot call code invented when it has nothing to check against."""
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(REAL_DICTATION, "", rlog, ask=lambda s, u: "DICTATES")
        self.assertEqual(out, REAL_DICTATION)


if __name__ == "__main__":
    unittest.main()


class ACutReplyIsNotADirectiveTests(unittest.TestCase):
    """The tool-inspecting steer branch took `_completion_text(comp)` with no truncation check, while
    its toolless sibling `summarize()` has had one since the truncation guard landed and
    `live_execution_marker` says it outright: "a cut intent is not an intent".

    Walked on ada-handles_fabliq_codex_pon_1785721353 call 0139: the author returned
    finish_reason=length with 8,192 tokens of the coder's OWN pytest failures repeated about nine
    times, and cria delivered roughly 27,000 characters of that to the coder in cria's voice — under
    a prompt asking for "a SHORT directive (under 120 words)". The real directive was sitting in the
    discarded reasoning_content."""

    def test_the_tooled_author_path_drops_a_cut_reply(self):
        import inspect
        src = inspect.getsource(loop.author_steer)
        self.assertIn("massage.is_truncated(comp)", src)

    def test_it_is_traced_never_silent(self):
        import inspect
        self.assertIn("loop.steer_truncated", inspect.getsource(loop.author_steer))

    def test_the_toolless_sibling_still_has_its_own_guard(self):
        import inspect
        self.assertIn("massage.is_truncated", inspect.getsource(loop.summarize))


class ARuminatingReplyIsNotADirectiveTests(unittest.TestCase):
    """The rumination guard is wired to the streaming coder path alone (classify.py says so
    outright); the steer author's calls are non-streamed, so a ruminating reply that STOPPED
    cleanly sailed through every guard. Walked on ada-handles_maple-preview_codex_poff_1785956867
    call 0055: the answer-NOW retry returned one first-person paragraph repeated ~45 times
    (finish=stop, not truncated), and cria injected the whole ~10KB blob verbatim as ⟦ctx:steer⟧
    at call 0056. Same run, call 0020, delivered a triple-duplicated ~21KB dictation. A reply
    whose tail is a periodic repetition of one block is the author looping, not directing —
    the same pure detector the stream watcher uses (rumination.degenerate_tail) decides, and
    the reply is dropped like a truncated one (a safe null, never delivered noise)."""

    _PARA = ("The tests are failing - 4 tests fail because of test/source mismatch (missing "
             "api_status key in simulated mode, overly strict hex validation). The tests don't "
             "represent real progress. I need to fix these issues so tests pass, then run live "
             "tests to verify the API integration works. After fixing these issues and running "
             "live tests, I need to create a README. ")

    def test_the_walked_blob_is_detected(self):
        self.assertTrue(loop._ruminating_reply(self._PARA * 30))

    def test_a_short_directive_is_not(self):
        self.assertFalse(loop._ruminating_reply(
            'You added api_status with the wrong value: the tests expect "simulated". '
            'Change it in resolve_adaptive_handle.py and rerun pytest.'))

    def test_a_long_but_varied_reply_is_not(self):
        varied = "\n".join(f"tests/test_x.py:{n}: AssertionError: value {n} mismatch "
                           f"in case {n * 7 % 13}" for n in range(80))
        self.assertFalse(loop._ruminating_reply(varied))

    def test_both_author_branches_drop_it_and_trace_it(self):
        import inspect
        src = inspect.getsource(loop.author_steer)
        self.assertEqual(src.count("_ruminating_reply("), 2)   # tooled + toolless branch
        self.assertIn("loop.steer_degenerate", src)
