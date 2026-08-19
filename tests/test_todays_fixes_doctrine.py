"""Every guard shipped 2026-08-01, checked against docs/principles.md.

Not a style test. Each case names the rule and the incident behind it, so a later change that
violates one fails here instead of in a run.
"""

# The live-execution seat this file tested was REMOVED on 2026-08-18 (operator: "drop the
# 'something needs to be ran' assertion altogether — it is more trouble than it is worth").
# The classes that exercised it are gone with it; what remains below tests mechanisms that
# outlived it. See docs/audits/finish-and-remeasure-progress.md for the reasoning.

import inspect
import json
import unittest

from cria import execcheck, loop, prompts
from tests.test_loop import _SHELL, _Recorder, _Rlog, _ctx, _plan, _single_loop, _synth, _toolcall

TODAYS_PROMPTS = ("step_repair_note", "steer_checks_repeat", "gate_oscillating",
                  "external_install_refusal")


class Rule17_ModelNeverSeesCria(unittest.TestCase):
    """The model never sees the literal token 'cria' — ⟦ctx:…⟧ markers only. A distinctive proper
    noun makes a weak model meta-reason about the mechanism instead of coding."""

    def test_no_prompt_shipped_today_names_it(self):
        # The raw file text IS what reaches the model — prompts.load()/render() strip nothing (a
        # '#' line is a real comment only for the load_map() family, a different set of files).
        # An earlier version of this test filtered out '#'-prefixed lines before searching, which
        # would have HIDDEN a real leak in one of these four files: none currently start a line
        # with '#', but nothing stops one from being added and silently reaching the model while
        # this test looked away.
        for name in TODAYS_PROMPTS:
            with self.subTest(prompt=name):
                self.assertNotIn("cria", prompts.load(name).lower())


class Rule96_NeverSpeakOverATool(unittest.TestCase):
    """cria may SELECT which of a checker's real lines to show, never SUBSTITUTE its own words."""

    def test_the_reattach_prompt_carries_the_findings_verbatim(self):
        out = prompts.render("steer_checks_repeat", findings="x.py:1: E999 boom")
        self.assertIn("x.py:1: E999 boom", out)

    def test_the_oscillation_note_rides_WITH_the_findings_never_instead(self):
        rec = _Recorder([_toolcall()])
        l = loop.Loop(_ctx(rec, None))
        sess = loop.PlanSession(plan=_plan(2))
        sess.oscillation_note = "this has recurred 3 times"
        l._renudge(sess, "k", {"messages": [{"role": "user", "content": "resolve"}], "tools": [_SHELL]},
                  "checker findings: x.py:1: E999 boom", _Rlog())
        sent = json.dumps(rec.bodies[-1]["messages"], ensure_ascii=False)
        self.assertIn("x.py:1: E999 boom", sent)          # the checker's own findings, whole
        self.assertIn("this has recurred 3 times", sent)  # ...WITH the oscillation note, not instead


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
        rec = _Recorder([_toolcall()])
        l = loop.Loop(_ctx(rec, None))
        sess = loop.PlanSession(plan=_plan(2))
        sess.fetched_pages = {"https://api.handle.me/openapi.json":
                              (200, "/handles/{handle}, /holders/{address}")}
        item = sess.plan.items[0]
        l._work_item(sess, "k", {"messages": [{"role": "user", "content": "resolve a handle"}],
                                 "tools": [_SHELL]}, _Rlog(), item, 1)
        sent = json.dumps(rec.bodies[-1]["messages"], ensure_ascii=False)
        self.assertIn("/handles/{handle}", sent)   # the real endpoint reaches the coder...

    def test_the_plan_OFF_driver_injects_it_TOO(self):
        rec = _Recorder([_toolcall()])
        l = _single_loop(rec)
        sess = _synth()
        sess.fetched_pages = {"https://api.handle.me/openapi.json":
                              (200, "/handles/{handle}, /holders/{address}")}
        body = {"messages": [{"role": "user", "content": "resolve a handle"}],
                "tools": [_SHELL], "stream": True}
        l._drive_single_item(sess, body, "sid:x", _Rlog())
        sent = json.dumps(rec.bodies[-1]["messages"], ensure_ascii=False)
        self.assertIn("/handles/{handle}", sent)   # ...on the plan-off path too

    def test_both_place_it_in_the_protected_head(self):
        # After the system message(s): always visible, never the oldest droppable turn.
        from cria import selfcompact

        rec = _Recorder([_toolcall()])
        l = loop.Loop(_ctx(rec, None))
        sess = loop.PlanSession(plan=_plan(2))
        sess.fetched_pages = {"u": (200, "/h")}
        l._work_item(sess, "k", {"messages": [{"role": "user", "content": "resolve"}],
                                 "tools": [_SHELL]}, _Rlog(), sess.plan.items[0], 1)
        msgs = rec.bodies[-1]["messages"]
        sys_idx = max(i for i, m in enumerate(msgs) if m["role"] == "system")
        self.assertIn(selfcompact.FACTS_MARKER, msgs[sys_idx + 1].get("content") or "")

        rec2 = _Recorder([_toolcall()])
        l2 = _single_loop(rec2)
        sess2 = _synth()
        sess2.fetched_pages = {"u": (200, "/h")}
        body2 = {"messages": [{"role": "user", "content": "resolve"}],
                "tools": [_SHELL], "stream": True}
        l2._drive_single_item(sess2, body2, "sid:x", _Rlog())
        msgs2 = rec2.bodies[-1]["messages"]
        sys_idx2 = max(i for i, m in enumerate(msgs2) if m["role"] == "system")
        self.assertIn(selfcompact.FACTS_MARKER, msgs2[sys_idx2 + 1].get("content") or "")

    def test_an_empty_ledger_injects_nothing(self):
        # A task with no web_fetch (a bash/git chore) must not gain an empty block.
        class _S:
            fetched_pages = {}
        self.assertIsNone(loop._fetched_facts_anchor(_S()))


