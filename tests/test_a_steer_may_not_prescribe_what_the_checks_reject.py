"""A steer that tells the coder to USE a symbol the checks report as broken is refused.

THE STRIP CANNOT CATCH THIS, and its own contract is why. `_strip_invented_code` asks "did the author
READ this, or invent it?", and answers from what cria OBSERVED — which includes tool results. A
compiler error is a tool result. So on any "replace X with Y" steer, the BROKEN symbol X is the
best-attested string in the whole prompt and survives, while the correct replacement Y was never
observed and is stripped. The strip inverts the fix.

Delivered to a coder on 2026-08-16: "replace `decimal.NewFromInt64` with [code removed]`)`" — that
symbol appears 7 times in the same prompt, every one inside an `undefined: …` error. Two more steers
in the same run told it to USE `decimal.NewFromFloat64` while the prompt carried
`undefined: decimal.NewFromFloat64` twenty-three times. The cell scored 1 of 5 on four wrong names.

Deterministic gather, reasoned judgment (#8): code finds a token present in BOTH the red finding-set
and the directive; one focused question decides whether the directive PRESCRIBES it or merely QUOTES
the failure. No reasoner, or an unreadable answer, and the directive stands — this can only move a
steer from delivered to refused when a model says so, never on a pattern alone.
"""

import unittest

from cria import loop


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


FINDINGS = ("./cart.go:58:27: undefined: decimal.NewFromFloat64\n"
            "./cart.go:49:17: undefined: decimal.NewFromFloat64")
PRESCRIBE = "Edit cart.go to convert the subtotal using decimal.NewFromFloat64 before rounding."
QUOTE = "The build fails on decimal.NewFromFloat64, which does not exist in that package. Read the module's own source for the real constructor name."


class ItRefusesAPrescriptionTests(unittest.TestCase):
    def test_the_measured_case(self):
        rlog = _Rlog()
        out = loop._prescribes_what_the_checks_reject(
            PRESCRIBE, FINDINGS, rlog, lambda _s: "PRESCRIBES")
        self.assertEqual(out, "decimal.NewFromFloat64")
        self.assertTrue(any(k == "loop.steer_prescribes_broken" for k, _ in rlog.events))

    def test_a_directive_that_only_quotes_the_failure_is_untouched(self):
        self.assertEqual(loop._prescribes_what_the_checks_reject(
            QUOTE, FINDINGS, _Rlog(), lambda _s: "QUOTES"), "")

    def test_the_question_is_only_asked_when_a_token_is_shared(self):
        asked = []
        loop._prescribes_what_the_checks_reject(
            "Add a README table listing every zone.", FINDINGS, _Rlog(),
            lambda s: asked.append(s) or "PRESCRIBES")
        self.assertEqual(asked, [], "a call was spent with no discrepancy to judge (#9's bound)")


class ItFailsTowardDeliveryTests(unittest.TestCase):
    """It may only ever move a steer from delivered to refused, and only on a model's word."""

    def test_no_reasoner_means_the_directive_stands(self):
        self.assertEqual(loop._prescribes_what_the_checks_reject(
            PRESCRIBE, FINDINGS, _Rlog(), None), "")

    def test_an_unreadable_answer_means_the_directive_stands(self):
        for reply in ("", "   ", "maybe?", "I think it quotes it"):
            self.assertEqual(loop._prescribes_what_the_checks_reject(
                PRESCRIBE, FINDINGS, _Rlog(), lambda _s, r=reply: r), "", reply)

    def test_no_findings_means_nothing_to_contradict(self):
        self.assertEqual(loop._prescribes_what_the_checks_reject(
            PRESCRIBE, "", _Rlog(), lambda _s: "PRESCRIBES"), "")


class TheTokenRuleIsLanguageAgnosticTests(unittest.TestCase):
    def test_it_matches_identifier_shapes_across_languages(self):
        cases = [
            ("Use ISO3166::Country.in_european_union? for the lookup.",
             "NoMethodError: undefined method `in_european_union?'"),
            ("Call cart.getTotalAmount() after applying the discount.",
             "error: cannot find symbol: getTotalAmount"),
            ("Import mapstructure_decode and pass the config.",
             "ModuleNotFoundError: No module named 'mapstructure_decode'"),
        ]
        for directive, findings in cases:
            with self.subTest(directive=directive):
                self.assertTrue(loop._prescribes_what_the_checks_reject(
                    directive, findings, _Rlog(), lambda _s: "PRESCRIBES"))


class ThePromptFencesTheJudgeTests(unittest.TestCase):
    def test_it_asks_for_one_word_and_offers_both(self):
        from cria import prompts
        p = prompts.render("steer_prescribes_broken", directive="d", findings="f", symbol="s")
        self.assertIn("PRESCRIBES", p)
        self.assertIn("QUOTES", p)
        self.assertIn("ONE word", p)
        self.assertNotIn("cria", p.lower())



class TheJudgeIsAskedAboutOneNameAtATimeTests(unittest.TestCase):
    """Walked on the sub-40 pass: ternary-bonsai x feed-pipeline-java, scored 12.

    cria's supervisor produced the one correct directive of the whole run at call 0024 — add the
    `AtomicInteger` import, and rename the local that shadows the static field. Two names went to the
    judge inside a single `Answer with ONE word`, the answer was PRESCRIBES, and cria refused its own
    fix. Nothing in that answer says WHICH name it was about, and the missing import is the one the
    checks were asking for."""

    TWO = ("Add `import java.util.concurrent.atomic.AtomicInteger;` at the top of Importer.java, "
           "and rename the local variable `localTotals` on line 254.")
    RED = ("Importer.java:28: error: cannot find symbol\n"
           "  symbol:   class AtomicInteger\n"
           "Importer.java:254: error: variable localTotals is already defined")

    def test_each_shared_name_gets_its_own_question(self):
        asked = []

        def ask(prompt):
            asked.append(prompt)
            return "QUOTES"

        loop._prescribes_what_the_checks_reject(self.TWO, self.RED, _Rlog(), ask)
        self.assertGreater(len(asked), 1, "more than one name was shared; each needs its own call")
        for prompt in asked:
            names = [n for n in ("AtomicInteger", "localTotals") if n in prompt.split("both:")[-1]]
            self.assertEqual(len(names), 1, "the judge was handed a set, not a name")

    def test_a_quotes_on_one_name_does_not_end_the_asking(self):
        seen = []

        def ask(prompt):
            sym = prompt.split("both:")[-1].split("\n")[0].strip()
            seen.append(sym)
            return "PRESCRIBES" if sym == "localTotals" else "QUOTES"

        out = loop._prescribes_what_the_checks_reject(self.TWO, self.RED, _Rlog(), ask)
        self.assertEqual(out, "localTotals")

    def test_the_refusal_names_the_symbol_the_judge_answered_about(self):
        rlog = _Rlog()

        def ask(prompt):
            sym = prompt.split("both:")[-1].split("\n")[0].strip()
            return "PRESCRIBES" if sym == "localTotals" else "QUOTES"

        loop._prescribes_what_the_checks_reject(self.TWO, self.RED, rlog, ask)
        fired = [kw for k, kw in rlog.events if k == "loop.steer_prescribes_broken"]
        self.assertEqual([f["symbol"] for f in fired], ["localTotals"])


class SupplyingWhatIsMissingIsNotPrescribingTests(unittest.TestCase):
    """The judge's own instructions have to answer the case, because the checks cannot.

    `cannot find symbol: class AtomicInteger` and `undefined: decimal.NewFromFloat64` are the same
    sentence from a checker. In the first the right fix is to import the name; in the second the name
    does not exist and the fix is to use another. Only the DIRECTIVE separates them — so the prompt
    has to say that supplying a missing name is QUOTES, and no pattern over the findings can."""

    def test_the_prompt_names_the_supply_case(self):
        from cria import prompts
        p = prompts.render("steer_prescribes_broken", directive="d", findings="f", symbol="s")
        low = p.lower()
        self.assertIn("quotes", low)
        for word in ("import", "declar", "defin", "depend"):
            self.assertIn(word, low, "the supply case must be spelled out for the judge")

if __name__ == "__main__":
    unittest.main()
