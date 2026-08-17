"""A "read the library's documentation" step could never be closed, however completely it was read.

`grounded_sources` counts a fetch as a source only when the ledger holds parsed ROUTES or response
FIELDS, and every marker that fills those needs a doc that parsed as a REST spec. Library
documentation never does — docs.rs, rubydoc, godoc, javadoc, pkg.go.dev are HTML prose — so the
ledger stayed empty and `step_reading_verdict` short-circuited to `NOT_DONE` **with no model call**.

Cycle 4 cell 18, `rust-toml-cli × ternary-bonsai`, 5% useful. The coder fetched `docs.rs/toml` at
call 0007 and got 7,925 characters carrying the whole API the task needed — `pub enum Value`,
`Table`, `from_str`, `to_string`. cria recorded it as *"this page answered, but no endpoint
definitions were found in it"*, and the step pin — *"Do ONLY this step (1 of 2): Visit crates.io to
identify a suitable TOML parser crate"* — was then recited on **20 of the run's 21 coder calls**,
nine of them re-fetches of pages already fetched. Zero bytes reached the workspace after call 0010.

**THE SHORT-CIRCUIT WAS #11b INVERTED.** That rule says a mechanism which cannot observe the thing it
is asked about must SAY SO, never convert its own blindness into a verdict — and this converted "cria
parsed nothing out of it" into "the coder read nothing".

The guarantee the short-circuit was built for is about an EMPTY ledger: nothing came back, so nothing
was read, and there is nothing for a judge to weigh. That still holds and still costs no call. What
changed is the other case — a page that ANSWERED and yielded no structure now goes to the judge,
labelled as exactly that, because judging it is a reasoner's job and not a parser's (#8).

The incident the guard was built for survives the change. Run 1785804243's five HTTP 200s that
defined nothing are still five pages that defined nothing; the judge is told in as many words to
treat a home page, a registry landing page or a search-result list as answering nothing.

Replayed against the real fetch ledgers: `rust-toml-cli × ternary-bonsai` (2 fetched, 0 parsed) and
`shipping-rates-rb × ternary-bonsai` (11 fetched, 0 parsed) both went from "NOT_DONE, no model call"
to a judged question.
"""

import unittest

from cria import prompts, research


class _Ask:
    def __init__(self, verdict="DONE"):
        self.verdict = verdict
        self.seen = []

    def __call__(self, system, user):
        self.seen.append(user)
        return '{"verdict": "%s"}' % self.verdict


DOCS = {"https://docs.rs/toml": ("HTTP 200", "", "")}
SPEC = {"https://api.example.com/openapi.json": ("HTTP 200", "/handles/{h}", "GET /handles/{h} -> holder")}
DEAD = {"https://nope.example/x": ("HTTP 404", "", "")}


class TheDocsPageReachesAJudgeTests(unittest.TestCase):
    def test_a_page_that_answered_but_parsed_to_nothing_is_judged(self):
        ask = _Ask()
        v = research.step_reading_verdict(ask, "task", "read the toml crate docs",
                                          research.grounded_sources(DOCS), ledger_urls=DOCS)
        self.assertTrue(ask.seen, "it short-circuited instead of asking")
        self.assertEqual(v, research.DONE)

    def test_the_judge_is_told_the_pages_were_unparsed(self):
        """Not hidden: the judge must know cria parsed nothing, or it is weighing a phantom."""
        ask = _Ask()
        research.step_reading_verdict(ask, "task", "step", research.grounded_sources(DOCS),
                                      ledger_urls=DOCS)
        self.assertIn("no endpoint list, no response fields", ask.seen[0])
        self.assertIn("docs.rs/toml", ask.seen[0])

    def test_it_says_the_gap_is_the_parsing_not_the_page(self):
        body = prompts.load("research_unparsed")
        self.assertIn("fact about the parsing, NOT about the pages", body)

    def test_a_parsed_spec_still_reaches_the_judge_with_its_fields(self):
        ask = _Ask()
        research.step_reading_verdict(ask, "task", "step", research.grounded_sources(SPEC),
                                      ledger_urls=SPEC)
        self.assertIn("/handles/{h}", ask.seen[0])


class TheNoCallGuaranteeStillHoldsTests(unittest.TestCase):
    """It was always about an EMPTY ledger, and that has not moved."""

    def test_nothing_fetched_costs_no_model_call(self):
        ask = _Ask()
        v = research.step_reading_verdict(ask, "task", "step", [], ledger_urls={})
        self.assertEqual(v, research.NOT_DONE)
        self.assertEqual(ask.seen, [])

    def test_only_FAILED_fetches_costs_no_model_call(self):
        """A 404 answered nothing. This is not the blindness case — it is a real fact."""
        ask = _Ask()
        v = research.step_reading_verdict(ask, "task", "step", research.grounded_sources(DEAD),
                                          ledger_urls=DEAD)
        self.assertEqual(v, research.NOT_DONE)
        self.assertEqual(ask.seen, [])

    def test_an_absent_ledger_behaves_as_before(self):
        ask = _Ask()
        self.assertEqual(research.step_reading_verdict(ask, "t", "s", []), research.NOT_DONE)
        self.assertEqual(ask.seen, [])


class TheOriginalIncidentSurvivesTests(unittest.TestCase):
    def test_a_landing_page_is_named_as_answering_nothing(self):
        """Run 1785804243: five HTTP 200s whose ledger lines all read "no endpoint definitions were
        found in it". They now reach the judge — with this sentence attached."""
        body = prompts.load("research_unparsed")
        for phrase in ("home page", "registry landing page", "search result list",
                       "as answering nothing"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_the_judge_is_still_told_to_judge_the_STEP(self):
        self.assertIn("STEP's question is answered", prompts.load("research_unparsed"))


class AnsweredIsADifferentQuestionFromParsedTests(unittest.TestCase):
    def test_answered_counts_what_came_back(self):
        self.assertEqual(research.answered_sources(DOCS), ["https://docs.rs/toml"])
        self.assertEqual(research.answered_sources(DEAD), [])

    def test_parsed_counts_what_cria_could_read(self):
        self.assertEqual(research.grounded_sources(DOCS), [])
        self.assertEqual(len(research.grounded_sources(SPEC)), 1)


if __name__ == "__main__":
    unittest.main()
