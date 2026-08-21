"""Four words appended to a directive turned the dictated-code guard off.

Walked on `rust-toml-cli x nemotron-elastic` 1787257904. The reasoner authored:

    Replace the line `let json = serde_json::to_string(value)…;` with
    `let json = serde_json::to_string(&value)…;`

`_dictates_code` answered DICTATES — correct — so cria ran `_restate_without_code`, whose job is to
say the same thing without the code. It returned the SAME two code lines with `" must be true."`
appended. That suffix moved the trailing `;` off end-of-line, so the statement-line shape stopped
matching; the inline-call shape could not see `serde_json::to_string(...)` because it accepted `.`
as a separator and not `::`; and with no shape matching, `_dictates_code` returned False **without
making a model call at all** — the reasoned judge never ruled, the "one attempt then silence" branch
never fired, and the raw code shipped to the coder verbatim.

cria's own restater defeating cria's own guard. It did no harm in that run — the code was rustc's
own suggestion and correct — but the same hole passed `⟦ctx:steer⟧ edit src/main.rs "…" "…"`, which
is cria's tool-call syntax handed to the model as a directive.

The gap is language-shaped, so the fix is (#20): the head-of-line shape has accepted `[.:]{1,2}`
since it was written; the INLINE one accepted only `.`. Rust, C++ and PHP write calls with `::`.
"""

import unittest

from cria import loop


def _judge_says_dictates(*_a, **_k):
    return "DICTATES"


class TheGuardSeesCallsWithEitherSeparatorTests(unittest.TestCase):
    MEASURED = ('Replace the line let json = serde_json::to_string(value); '
                'with let json = serde_json::to_string(&value); must be true.')

    def test_the_measured_bypass_is_closed(self):
        self.assertTrue(loop._CODE_SHAPED.search(self.MEASURED))
        self.assertTrue(loop._dictates_code(self.MEASURED, ask=_judge_says_dictates))

    def test_a_trailing_clause_no_longer_hides_the_code(self):
        """The pre-filter must not depend on the code sitting at end-of-line."""
        base = "change it to std::mem::swap(&a, &b)"
        for tail in ("", " must be true.", " — do it now.", ", then re-run the tests."):
            with self.subTest(tail=tail):
                self.assertTrue(loop._CODE_SHAPED.search(base + tail))

    def test_both_separators_fire_inline(self):
        for text in ("call pytest.register_pytest_mark('live') there",
                     "use serde_json::to_string(&v) instead",
                     "call Foo::bar(x) from the handler"):
            with self.subTest(text=text):
                self.assertTrue(loop._CODE_SHAPED.search(text))


class OrdinaryProseStillDoesNotFireTests(unittest.TestCase):
    """Over-firing costs one reasoner call and is cheap; firing on every steer is not."""

    def test_a_deliverable_named_in_words_is_not_code(self):
        for text in (
                "The README rate table is missing the express zone and its per-kilogram rate.",
                "Fix the loading; the code that uses it is not what failed here.",
                "Shipping.zone_for is missing for two-letter country codes.",
                "The import spawned no threads, so the parallel path is not exercised.",
                "Add a third-party gem that determines EU membership and use it for the lookup."):
            with self.subTest(text=text[:40]):
                self.assertFalse(loop._CODE_SHAPED.search(text))


if __name__ == "__main__":
    unittest.main()
