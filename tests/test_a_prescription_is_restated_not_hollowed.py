"""Stripping a PRESCRIBED line leaves an imperative with its operands deleted.

Walked on `rust-toml-cli x ternary-bonsai`, 2026-08-19 call 0015. The steer author wrote three
numbered fixes, each naming code it had invented. `_strip_invented_code` replaced the code and
shipped the rest:

    **Line 12**: [code removed — written by this supervisor…] fails because TOML tables use
    `String` keys, not `&str`. Change to [code removed — written by this supervisor…].

"Change X to Y" with both X and Y deleted. And the strip keeps the half that does the damage: the
cause — *"because TOML tables use `String` keys"* — is wrong, and by the steer prompt's own
measurement an unverified cause was wrong in twenty-four cases out of twenty-four.

THE DISTINCTION IS QUOTED vs PRESCRIBED, and the strip already measures it. Code the author READ
survives untouched (`stripped == 0`), which is the case the 2026-08-04 ruling protects and which
carried the ladder passes. Code the author INVENTED is what `stripped > 0` counts, and a sentence
built around invented code cannot survive losing it.

Prevalence before building (#15): of 100 `loop.steer_dictated_code` events in the captures, 66
stripped zero spans. This path is the other 34.

The rewriter is handed the directive AND NOTHING ELSE — no session, no evidence, no tools — so it
cannot swap one invention for another. It can only say less.
"""

import unittest

from cria import loop, prompts


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


# The real directive, verbatim from call 0015.
PRESCRIPTION = (
    "Read lines 12, 84, 103, and 157 of `src/main.rs` and apply these three targeted fixes:\n\n"
    "1. **Line 12**: `map.get(key)` fails because TOML tables use `String` keys, not `&str`. "
    "Change to `map.get(&key.to_string())`.\n\n"
    "2. **Lines 84, 103, 157**: The `toml` crate v0.8 uses `I64`, not `Int`. "
    "Replace `toml::Value::Int(ref i)` with `toml::Value::I64(ref i)`.")


def _reasoner(rewrite: str, verdict: str = "DESCRIBES", log=None):
    """A stand-in for the two questions this path asks: rewrite the directive, then rule on the
    rewrite. They are told apart by their system prompt, the way the real reasoner sees them."""
    def ask(system, user):
        if log is not None:
            log.append((system, user))
        return rewrite if system == prompts.load("steer_restate") else verdict
    return ask


class TheRewriterIsBlindTests(unittest.TestCase):
    def test_it_is_given_the_directive_and_nothing_else(self):
        """The safety property. A rewriter with context could substitute one invention for another;
        this one holds no facts to substitute."""
        log = []
        loop._restate_without_code(
            PRESCRIPTION,
            _reasoner("Read src/main.rs line 12 and make the key lookup compile. Run cargo build.",
                      log=log),
            _Rlog())
        self.assertEqual(log[0], (prompts.load("steer_restate"), PRESCRIPTION))

    def test_the_rewrite_is_ruled_on_even_when_it_reads_as_prose(self):
        """The verdict TRAVELS. This input was already ruled a dictation, so the rewrite does not
        have to look code-shaped to earn the question — that trigger is documented as missing inline
        dictation, and prose is exactly what a rewrite comes back as."""
        log = []
        rewrite = "Call pytest.register_pytest_mark for the live marker, then re-run."
        out = loop._restate_without_code(
            PRESCRIPTION, _reasoner(rewrite, verdict="DICTATES", log=log), _Rlog())
        self.assertIsNone(out)
        self.assertEqual(len(log), 2, "the rewrite must be ruled on, not re-triggered")
        self.assertEqual(log[1][0], prompts.render("steer_dictates_code", directive=rewrite))

    def test_no_reasoner_means_no_directive(self):
        self.assertIsNone(loop._restate_without_code(PRESCRIPTION, None, _Rlog()))


class OneAttemptThenSilenceTests(unittest.TestCase):
    def test_a_clean_restatement_is_kept(self):
        clean = "Read `src/main.rs` line 12, make the key lookup compile, then run cargo build."
        out = loop._restate_without_code(PRESCRIPTION, _reasoner(clean), _Rlog())
        self.assertEqual(out, clean)

    def test_a_restatement_that_still_dictates_is_refused(self):
        """One attempt. A second ask is a second guess (#3)."""
        rlog = _Rlog()
        still = "Change line 12 to `map.get(&key.to_string())` and rebuild."
        out = loop._restate_without_code(still, _reasoner(still, verdict="DICTATES"), rlog)
        self.assertIsNone(out)
        self.assertIn(("loop.steer_restate", {"level": "info", "kept": False,
                                              "reason": "still dictates"}), rlog.events)

    def test_the_refusal_sentinel_yields_nothing(self):
        out = loop._restate_without_code(PRESCRIPTION, lambda s, u: "NO_DIRECTIVE", _Rlog())
        self.assertIsNone(out)

    def test_an_empty_answer_yields_nothing(self):
        self.assertIsNone(loop._restate_without_code(PRESCRIPTION, lambda s, u: "   ", _Rlog()))

    def test_the_sentinel_is_not_the_negation_of_the_trigger(self):
        """A sentinel a weak model emits must not be the lexical negation of what tripped it (#21)."""
        body = prompts.load("steer_restate")
        self.assertIn("NO_DIRECTIVE", body)
        self.assertNotIn("NOT_DICTAT", body.upper())


class QuotedCodeStillSurvivesUntouchedTests(unittest.TestCase):
    """The 2026-08-04 ruling, unchanged: a steer quoting the coder's OWN failing line ships whole.
    That is 66 of the 100 dictated steers in the captures, and it never reaches the rewriter."""

    def test_a_quoted_line_strips_nothing(self):
        observed = "map.get(key) fails here"
        kept, stripped = loop._strip_invented_code(
            "Your line `map.get(key)` is what the compiler rejects. Read src/main.rs:12.", observed)
        self.assertEqual(stripped, 0)
        self.assertIn("map.get(key)", kept)

    def test_an_invented_line_is_counted(self):
        _kept, stripped = loop._strip_invented_code(
            "Change to `map.get(&key.to_string())`.", "map.get(key) fails here")
        self.assertGreater(stripped, 0)


class ThePromptSaysWhatToKeepTests(unittest.TestCase):
    def setUp(self):
        self.body = prompts.load("steer_restate")

    def test_it_preserves_files_lines_and_quoted_errors(self):
        for keep in ("file path", "line number", "error message"):
            with self.subTest(keep=keep):
                self.assertIn(keep, self.body)

    def test_it_drops_the_cause_too(self):
        """The strip left the wrong cause standing, which is the half that misleads."""
        self.assertRegex(self.body, r"(?i)explanation of WHY|a cause is a guess")

    def test_it_may_not_add_anything(self):
        self.assertRegex(self.body, r"(?i)did not already say|may not add")

    def test_it_never_names_the_program_to_the_model(self):
        import re
        self.assertIsNone(re.search(r"\bcria\b", self.body, re.I))


if __name__ == "__main__":
    unittest.main()
