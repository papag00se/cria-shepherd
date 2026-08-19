"""Every guard shipped 2026-08-01, checked against docs/principles.md.

Not a style test. Each case names the rule and the incident behind it, so a later change that
violates one fails here instead of in a run.
"""

# The live-execution seat this file tested was REMOVED on 2026-08-18 (operator: "drop the
# 'something needs to be ran' assertion altogether — it is more trouble than it is worth").
# The classes that exercised it are gone with it; what remains below tests mechanisms that
# outlived it. See docs/audits/finish-and-remeasure-progress.md for the reasoning.

import inspect
import unittest

from cria import execcheck, loop, prompts

TODAYS_PROMPTS = ("step_repair_note", "steer_checks_repeat", "gate_oscillating",
                  "external_install_refusal")


class Rule17_ModelNeverSeesCria(unittest.TestCase):
    """The model never sees the literal token 'cria' — ⟦ctx:…⟧ markers only. A distinctive proper
    noun makes a weak model meta-reason about the mechanism instead of coding."""

    def test_no_prompt_shipped_today_names_it(self):
        for name in TODAYS_PROMPTS:
            with self.subTest(prompt=name):
                body = "\n".join(l for l in prompts.load(name).splitlines()
                                 if not l.lstrip().startswith("#"))
                self.assertNotIn("cria", body.lower())


class Rule96_NeverSpeakOverATool(unittest.TestCase):
    """cria may SELECT which of a checker's real lines to show, never SUBSTITUTE its own words."""

    def test_the_reattach_prompt_carries_the_findings_verbatim(self):
        out = prompts.render("steer_checks_repeat", findings="x.py:1: E999 boom")
        self.assertIn("x.py:1: E999 boom", out)

    def test_the_oscillation_note_rides_WITH_the_findings_never_instead(self):
        src = inspect.getsource(loop.Loop._renudge)
        self.assertIn("reason + ", src)       # appended to the checker's reason, not replacing it


class Rule2Corollary_CriaAuthorsNoWork(unittest.TestCase):
    """ADDITIVE is necessary, not sufficient. cria does not AUTHOR work — it shapes context.
    Learned from the steer author shipping code that could not execute."""

    def test_no_prompt_shipped_today_dictates_code(self):
        for name in ("step_repair_note", "gate_oscillating", "steer_checks_repeat"):
            with self.subTest(prompt=name):
                body = prompts.load(name)
                self.assertNotIn("```", body)
                self.assertNotIn("def ", body)

    def test_the_step_text_passes_through_untouched(self):
        step = "Write unit tests in `t.py` covering the error paths"
        out = loop._item_prompt(step, "", 1, 1)
        self.assertIn(step, out)


class Rule15_MeasureFirst(unittest.TestCase):
    """Measure prevalence before building a heuristic. A detector built for a one-off is dead weight
    that can itself misfire."""

    def test_every_new_detector_cites_its_base_rate_in_the_source(self):
        for fn, needle in ((loop._repair_note, "33"),          # 33 prompts vs 15 corrections
                           (loop._checks_already_visible, "176"),  # 129 of 176
                           (execcheck.entrypoints, "")):
            src = inspect.getsource(fn) if fn is not execcheck.entrypoints \
                else execcheck.__doc__
            with self.subTest(fn=getattr(fn, "__name__", "module")):
                self.assertTrue(any(ch.isdigit() for ch in src),
                                "no measured number cited for this detector")
                if needle:
                    self.assertIn(needle, src)


class Rule22_PromptsLiveInFiles(unittest.TestCase):
    """Every model-facing string lives in cria/prompts/*.txt, never an inline f-string."""

    def test_all_of_todays_model_facing_text_loads_from_a_file(self):
        for name in TODAYS_PROMPTS:
            with self.subTest(prompt=name):
                self.assertTrue(prompts.load(name).strip())


class BothDriversKeepTheFetchLedger(unittest.TestCase):
    """_fetched_facts_anchor re-injects cria's durable fetch ledger into the coder's view every turn,
    so the real endpoints survive a HARNESS compaction that cria cannot anchor against. It was wired
    into the plan-ON step driver only.

    Planner off is how every dense model on the ladder runs, and how mellum2 runs. In
    ada-handles_mellum2_codex_poff_1785693138 the ⟦ctx:facts⟧ marker appears in 0 of 166 prompts. At
    call 0102 a harness compaction took the fetched /handles/{handle} and /holders/{address} field
    shapes out of the coder's view; they never came back, for the 25 prompts to the end of the run —
    while the reasoner kept being given them. cria held them the whole time."""

    def test_the_plan_ON_driver_injects_it(self):
        self.assertIn("_fetched_facts_anchor", inspect.getsource(loop.Loop._work_item))

    def test_the_plan_OFF_driver_injects_it_TOO(self):
        self.assertIn("_fetched_facts_anchor", inspect.getsource(loop.Loop._drive_single_item))

    def test_both_place_it_in_the_protected_head(self):
        # After the system message(s): always visible, never the oldest droppable turn.
        for fn in (loop.Loop._work_item, loop.Loop._drive_single_item):
            with self.subTest(fn=fn.__name__):
                self.assertIn("_insert_after_system", inspect.getsource(fn))

    def test_an_empty_ledger_injects_nothing(self):
        # A task with no web_fetch (a bash/git chore) must not gain an empty block.
        class _S:
            fetched_pages = {}
        self.assertIsNone(loop._fetched_facts_anchor(_S()))


