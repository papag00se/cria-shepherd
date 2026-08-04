"""A research step with no exit traps the run; no research step at all lets it invent the API.

Two fabliq runs of the same task, same code, same model, failed from opposite sides:

  * PLANNER-ON (1785804243) — step 1 was "Research the Ada Handles API documentation by fetching the
    GitHub repo root directory". That fetch is denied, so the critic refused the step forever: 114 of
    195 calls on step 1, step 2 never reached.
  * PLANNER-OFF (1785805694) — nothing said research, so nothing researched. ZERO web_fetch calls in
    237. It built everything against `api.handle.me/v1/handle/` with `address`/`holder`/
    `totalHandles`, an invented API. 1/4, structurally capped.

These pin the two halves the operator asked for: a periodic "did the reading happen?" check that can
END research mode, and a reading step on the plan-off path that has that check as its exit.
"""
import unittest

from cria import loop, research


class TheFactsAreGatheredNotAskedForTests(unittest.TestCase):
    """The ledger decides what counts as a source. A judge cannot be talked past an empty one."""

    def test_a_page_that_defined_nothing_is_not_a_source(self):
        """Run 1785804243's ledger, in shape: five HTTP 200s, not one endpoint parsed from any."""
        ledger = {"https://api.handle.me": ("200", "", ""),
                  "https://github.com/koralabs/api.handle.me": ("200", "", ""),
                  "https://handle.me": ("200", "", "")}
        self.assertEqual(research.grounded_sources(ledger), [])

    def test_a_failed_fetch_is_not_a_source_even_with_routes(self):
        self.assertEqual(research.grounded_sources({"u": ("404", "/handles/{handle}", "")}), [])

    def test_a_2xx_that_defined_routes_or_fields_is_a_source(self):
        ledger = {"https://api.handle.me/openapi.json": ("200", "/handles/{handle}", "holder(string)"),
                  "https://x": ("200", "", "")}
        self.assertEqual([u for u, _r, _s in research.grounded_sources(ledger)],
                         ["https://api.handle.me/openapi.json"])

    def test_no_sources_means_no_model_call_at_all(self):
        """Not an optimisation — the guarantee. With nothing parsed there is no evidence any reading
        happened, so there is nothing for a judge to weigh."""
        def must_not_ask(sysp, usr):
            raise AssertionError("asked the model with an empty ledger")
        self.assertEqual(
            research.step_reading_verdict(must_not_ask, "task", "step", []), research.NOT_DONE)


class TheVerdictIsThreeValuedTests(unittest.TestCase):
    SOURCES = [("https://api.handle.me/openapi.json", "/handles/{handle}", "holder(string)")]

    def _verdict(self, answer):
        return research.step_reading_verdict(lambda s, u: answer, "task", "step", self.SOURCES)

    def test_done_clears(self):
        self.assertEqual(self._verdict('{"verdict": "DONE"}'), research.DONE)

    def test_not_research_is_the_ordinary_answer_and_does_not_clear(self):
        """Most steps ask for something to be BUILT. A two-valued question would force those into
        DONE or NOT_DONE, and either would be cria ruling on work it was not asked about."""
        self.assertEqual(self._verdict('{"verdict": "NOT_RESEARCH"}'), research.NOT_RESEARCH)

    def test_an_unreadable_answer_leaves_the_step_open(self):
        for answer in ("", "yes it is done", "{}", '{"verdict": "MAYBE"}', None):
            with self.subTest(answer=answer):
                self.assertEqual(self._verdict(answer), research.NOT_DONE)

    def test_the_question_carries_the_parsed_facts_not_the_urls_alone(self):
        seen = {}

        def ask(sysp, usr):
            seen["user"] = usr
            return '{"verdict": "DONE"}'

        research.step_reading_verdict(ask, "resolve a handle", "read the spec", self.SOURCES)
        self.assertIn("/handles/{handle}", seen["user"])
        self.assertIn("holder(string)", seen["user"])


class ThePlanOffReadingStepTests(unittest.TestCase):
    TASK = ("write a Python script that resolves an Ada Handle using the Ada Handles API "
            "(api.handle.me). Unit tests are required.")

    AUTHORED = ("Read what api.handle.me publishes about resolving a handle, so the resolver uses "
                "the real response field names.")

    def _ask(self, answer):
        def ask(sysp, usr):
            self.seen = usr
            return answer
        return ask

    def test_a_task_naming_a_source_gets_a_MODEL_AUTHORED_reading_step_first(self):
        plan = loop._synthetic_plan(self.TASK, ask=self._ask(self.AUTHORED))
        self.assertEqual(len(plan.items), 2)
        self.assertEqual(plan.items[0].text, self.AUTHORED)   # the MODEL's sentence, verbatim
        self.assertEqual(plan.items[1].text, self.TASK)       # the task itself is untouched
        self.assertIn("api.handle.me", self.seen)             # cria supplied only the domain + task

    def test_cria_writes_no_step_of_its_own_when_the_model_declines(self):
        """Safe null, not a fallback: no usable sentence means no step, never cria's own words."""
        for answer in ("", "   ", None):
            with self.subTest(answer=answer):
                plan = loop._synthetic_plan(self.TASK, ask=self._ask(answer))
                self.assertEqual([it.text for it in plan.items], [self.TASK])

    def test_a_step_naming_a_PATH_is_refused(self):
        """The exact defect that cost run 1785804243 its window: a step naming WHERE can be
        unsatisfiable ("the GitHub repo root directory" returns denied); a step naming WHAT cannot."""
        for answer in ("Fetch https://api.handle.me/openapi.json and read the routes.",
                       "Read the openapi.json the site publishes.",
                       "Read api.handle.me/swagger for the endpoints."):
            with self.subTest(answer=answer):
                plan = loop._synthetic_plan(self.TASK, ask=self._ask(answer))
                self.assertEqual([it.text for it in plan.items], [self.TASK])

    def test_an_essay_is_not_a_step(self):
        plan = loop._synthetic_plan(self.TASK, ask=self._ask("word " * 200))
        self.assertEqual([it.text for it in plan.items], [self.TASK])

    def test_a_task_with_no_external_source_never_asks_the_model(self):
        def must_not_ask(sysp, usr):
            raise AssertionError("no domain in the task — nothing to research")
        task = "write a function that reverses a string, with unit tests"
        plan = loop._synthetic_plan(task, ask=must_not_ask)
        self.assertEqual([it.text for it in plan.items], [task])

    def test_no_author_available_means_the_old_one_item_plan(self):
        plan = loop._synthetic_plan(self.TASK)
        self.assertEqual([it.text for it in plan.items], [self.TASK])

    def test_the_reading_step_is_an_ordinary_item(self):
        """Not pinned, not immutable — the living re-derivation may drop it like any other step, and
        the step critic judges it like any other. Pinning is what made the retired one inescapable."""
        item = loop._synthetic_plan(self.TASK, ask=self._ask(self.AUTHORED)).items[0]
        self.assertFalse(item.done)
        self.assertFalse(getattr(item, "pinned", False))

    def test_the_plan_id_is_unchanged_by_the_extra_item(self):
        """A resumed synthetic session must keep its id, which is keyed on the task alone."""
        a = loop._synthetic_plan(self.TASK, clock=lambda: _FIXED, ask=self._ask(self.AUTHORED))
        b = loop._synthetic_plan(self.TASK, clock=lambda: _FIXED)
        self.assertEqual(a.id, b.id)


from datetime import datetime, timezone  # noqa: E402  (fixture clock for the id test)
_FIXED = datetime(2026, 8, 3, 18, 0, 0, tzinfo=timezone.utc)


class TheCadenceTests(unittest.TestCase):
    def test_ten_is_the_cadence(self):
        self.assertEqual(research.RESEARCH_CHECK_EVERY, 10)


if __name__ == "__main__":
    unittest.main()
