"""The compaction briefing is the one injected channel with no factual guard on it.

Every steer cria authors runs a stack — `_prescribes_what_the_checks_reject`,
`_symbol_not_in_the_file`, `_invented_version`, `_blames_a_service_that_answered`. The briefing is
model-authored text, injected verbatim as the session's memory, outranking the transcript and
surviving every later fold. It passed through none of them.

Walked on cart-billing-go x nemotron-elastic, 2026-08-27. At call 0043 the model reached the answer
in its own words — "decimal.NewDecimal is not a function; the package provides NewFromString" — and
its edit failed to apply. cria compacted at 0044. The briefing came back listing
`decimal.NewFromString`, the CORRECT name, among the undefined symbols, and instructing the coder to
"replace decimal.NewDecimal with decimal.NewFromFloat64". The live compiler output in the SAME prompt
named three symbols and NewFromString was not one of them. cria injected that briefing as
⟦ctx:continuation⟧ from 0046 to the end of the run, so for the last fifteen calls the only mentions
of the right answer were two lines calling it broken.

Additive, like its sibling `_briefing_disk_truth`: cria states its fact, the briefing keeps its
words, and the reader is told which to trust. That function already records what deleting the
sentence costs — a regex cannot tell a true claim about a name from a false one.
"""

import unittest

from cria import loop


FINDINGS = ("$ go build ./... — ./cart.go:41:21: undefined: decimal.NewDecimal\n"
            "./cart.go:59:24: undefined: pct")
BRIEFING = ("The build fails with undefined symbols decimal.NewDecimal, decimal.NewFromString, and "
            "decimal.RoundingModeHalfUp. Next step: replace decimal.NewDecimal with "
            "decimal.NewFromFloat64 for numeric literals.")


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class TheMeasuredCaseTests(unittest.TestCase):
    def test_the_symbol_the_checks_never_named_is_reported(self):
        got = loop._briefing_denies_working_symbols(BRIEFING, FINDINGS)
        self.assertIn("decimal.NewFromString", got)

    def test_a_symbol_the_checks_did_name_is_not(self):
        """The briefing is right about that one. Correcting it would be the false fact."""
        self.assertNotIn("decimal.NewDecimal",
                         loop._briefing_denies_working_symbols(BRIEFING, FINDINGS))

    def test_the_correction_is_appended_and_names_them(self):
        rlog = _Rlog()
        out = loop._briefing_symbol_truth(BRIEFING, FINDINGS, rlog)
        self.assertTrue(out.startswith(BRIEFING), "the briefing keeps its own words")
        self.assertIn("decimal.NewFromString", out[len(BRIEFING):])
        self.assertIn("do NOT report a problem with", out)
        self.assertEqual([k for k, _ in rlog.events], ["context.briefing_denies_symbols"])

    def test_a_dotted_name_survives_as_one_token(self):
        """The first cut bounded the window with `[^.\\n]`, which cut `decimal.NewFromString` down to
        `decimal` and left the guard with nothing to say. A qualified name has dots in it."""
        got = loop._briefing_denies_working_symbols(
            "undefined: pkg.SomeQualifiedName is missing", "nothing about it here")
        self.assertIn("pkg.SomeQualifiedName", got)


class ItSpeaksOnlyWhenItCanTests(unittest.TestCase):
    def test_no_check_output_means_silence(self):
        """cria cannot contradict what it never ran (#11b)."""
        self.assertEqual(loop._briefing_denies_working_symbols(BRIEFING, ""), [])
        self.assertEqual(loop._briefing_symbol_truth(BRIEFING, "", None), BRIEFING)

    def test_a_briefing_that_names_only_real_failures_is_untouched(self):
        b = "The build fails: decimal.NewDecimal is undefined and pct is undefined."
        self.assertEqual(loop._briefing_symbol_truth(b, FINDINGS, None), b)

    def test_prose_about_missing_work_is_not_a_symbol_claim(self):
        """"The README is missing a rate table" is a true statement about remaining work, and the
        thing this guard must never do is contradict one."""
        prose = "The README is missing a rate table and the express zone is not defined yet."
        self.assertEqual(loop._briefing_denies_working_symbols(prose, FINDINGS), [])

    def test_it_runs_where_its_sibling_runs(self):
        import inspect
        src = inspect.getsource(loop.Loop)
        self.assertIn("_briefing_symbol_truth(_briefing_disk_truth(", src)


if __name__ == "__main__":
    unittest.main()
