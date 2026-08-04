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

    def test_a_self_contained_task_gets_no_step_because_the_MODEL_says_NONE(self):
        """The model decides, not a domain regex. Research is reading — of files on disk, a schema, a
        library's source — and a task that needs none says so."""
        task = "write a function that reverses a string, with unit tests"
        for answer in ("NONE", "none", "NONE."):
            with self.subTest(answer=answer):
                plan = loop._synthetic_plan(task, ask=self._ask(answer))
                self.assertEqual([it.text for it in plan.items], [task])

    def test_a_task_with_no_domain_can_still_get_a_reading_step(self):
        """The narrow version only asked when the task's words held a domain, which made every
        non-web research invisible: reading the CSVs already in the workspace is research too."""
        task = "build a report from the CSV files already in this directory"
        authored = "Read the CSV files in the working directory to learn their columns before writing the report."
        plan = loop._synthetic_plan(task, ask=self._ask(authored), files="data.csv  sales.csv")
        self.assertEqual([it.text for it in plan.items], [authored, task])
        self.assertIn("data.csv", self.seen)      # cria supplied the listing; the model chose

    def test_a_location_the_TASK_named_is_not_a_guess(self):
        """The refusal is for INVENTED locations. When the user named it, it is a fact."""
        task = "read ./schema.json and generate the model classes"
        authored = "Read ./schema.json to learn the field names before generating the classes."
        plan = loop._synthetic_plan(task, ask=self._ask(authored))
        self.assertEqual(plan.items[0].text, authored)

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


class WhichQuestionCriaAsksTests(unittest.TestCase):
    """cria settles what it can settle. A domain in the task's own words is a FACT — that the task
    names an external source — and asking a small model to re-decide it got the answer fabliq gave
    on the first live run: NONE, for a task whose own sentence reads "using the Ada Handles API
    (api.handle.me)". With no domain, whether anything must be read is a real judgement and NONE is
    a real answer."""

    TASK_WITH = "resolve an Ada Handle using the Ada Handles API (api.handle.me)"
    TASK_WITHOUT = "build a report from the files already in this directory"

    def _system_for(self, task, **kw):
        seen = {}

        def ask(sysp, usr):
            seen["system"] = sysp
            return "Read it and learn what it returns."

        research.authored_research_step(ask, task, **kw)
        return seen["system"]

    def test_a_named_domain_is_not_re_litigated(self):
        self.assertNotIn("NONE", self._system_for(self.TASK_WITH, domain="api.handle.me"))

    def test_without_a_domain_the_model_may_decline(self):
        self.assertIn("NONE", self._system_for(self.TASK_WITHOUT, files="a.csv"))

    def test_NONE_is_still_honoured_where_it_is_offered(self):
        self.assertEqual(
            research.authored_research_step(lambda s, u: "NONE", self.TASK_WITHOUT, files="a.csv"), "")


class AReadingStepDoesNotProduceAnythingTests(unittest.TestCase):
    """Asked for a reading step, fabliq wrote back the whole task (run 20260803T210043):

        "Write a Python script that accepts an Ada Handle as input, resolves it via the
         api.handle.me API to obtain the Cardano address, holder address, and total handles,
         includes unit tests for the script, creates a live test resolving the handles 'goose' and
         'papagoose', and adds a README explaining installation and execution."

    As a first plan item that is strictly WORSE than no item: the plan then holds two steps that both
    say "do the whole job". A small model handed "write one step" defaults to restating the request,
    so cria refuses the sentence rather than trusting it."""

    TASK = "resolve an Ada Handle using the Ada Handles API (api.handle.me), with unit tests"
    RESTATED = ("Write a Python script that accepts an Ada Handle as input, resolves it via the "
                "api.handle.me API to obtain the Cardano address, holder address, and total "
                "handles, includes unit tests for the script, creates a live test resolving the "
                "handles 'goose' and 'papagoose', and adds a README explaining installation.")

    def _step(self, answer):
        return research.authored_research_step(lambda s, u: answer, self.TASK, domain="api.handle.me")

    def test_the_captured_restatement_is_refused(self):
        self.assertEqual(self._step(self.RESTATED), "")

    def test_every_production_verb_is_refused(self):
        for verb in ("Write", "Create", "Add", "Implement", "Build", "Generate"):
            with self.subTest(verb=verb):
                self.assertEqual(self._step(f"{verb} the resolver against api.handle.me."), "")

    def test_a_real_reading_step_survives(self):
        for good in ("Read what api.handle.me publishes to learn the endpoint and response fields.",
                     "Fetch the api.handle.me reference and note the field names it returns.",
                     "Consult the api.handle.me documentation for how a handle resolves."):
            with self.subTest(good=good):
                self.assertEqual(self._step(good), good)

    def test_the_word_must_be_a_WORD_not_a_substring(self):
        """'addressed' contains 'add'; a substring match would refuse a valid reading step."""
        good = "Read how holder addresses are addressed in the api.handle.me reference."
        self.assertEqual(self._step(good), good)
