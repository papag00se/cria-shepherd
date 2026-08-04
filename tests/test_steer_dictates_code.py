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

    def test_a_DICTATES_steer_is_delivered_and_traced(self):
        # OBSERVE-ONLY (operator ruling, 2026-08-04): the drop's harm evidence came from a BLIND
        # author (since fixed); the 08-01 dense passes were carried by sighted dictation. The judge
        # still runs and logs — the steer is DELIVERED, pending the cross-cohort re-measure.
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(REAL_DICTATION, "evidence", rlog,
                                           ask=lambda s, u: "DICTATES")
        self.assertEqual(out, REAL_DICTATION)
        self.assertIn("loop.steer_dictated_code", [k for k, _ in rlog.events])


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
