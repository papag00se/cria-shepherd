"""Every guard shipped 2026-08-01, checked against docs/principles.md.

Not a style test. Each case names the rule and the incident behind it, so a later change that
violates one fails here instead of in a run.
"""
import inspect
import unittest

from cria import execcheck, loop, prompts

TODAYS_PROMPTS = ("step_repair_note", "steer_checks_repeat", "gate_oscillating",
                  "exec_intent", "exec_markers", "external_install_refusal")


class Rule17_ModelNeverSeesCria(unittest.TestCase):
    """The model never sees the literal token 'cria' — ⟦ctx:…⟧ markers only. A distinctive proper
    noun makes a weak model meta-reason about the mechanism instead of coding."""

    def test_no_prompt_shipped_today_names_it(self):
        for name in TODAYS_PROMPTS:
            with self.subTest(prompt=name):
                body = "\n".join(l for l in prompts.load(name).splitlines()
                                 if not l.lstrip().startswith("#"))
                self.assertNotIn("cria", body.lower())


class Rule2_AdditiveNeverBlocks(unittest.TestCase):
    """Interventions are additive / regression-only — never block the first fix. A guard that can
    refuse the FIRST attempt at something can trap the loop forever."""

    def test_execcheck_has_no_refusing_verdict(self):
        for v in (execcheck.CONFIRMED, execcheck.NOT_OBSERVED,
                  execcheck.INCONCLUSIVE, execcheck.NOT_APPLICABLE):
            self.assertIsInstance(execcheck.ExecResult(v).marker, str)

    def test_the_live_execution_marker_is_APPENDED_to_a_completion(self):
        src = inspect.getsource(loop.satisfaction_done_note)
        self.assertIn("exec_marker", src)
        self.assertIn("Task complete", src)   # the completion still stands on its own

    def test_a_failed_exec_check_never_affects_the_completion(self):
        src = inspect.getsource(loop.live_execution_marker)
        self.assertIn('return ""', src)       # every failure path returns empty, never raises out

    def test_step_reframe_stays_silent_on_a_file_that_does_not_exist(self):
        # Never interfere with a FIRST attempt at writing something.
        self.assertEqual(loop._repair_note("Write `nope.py`", "/tmp", True), "")


class Rule3_SilenceOverNoise(unittest.TestCase):
    """On a clean signal, say nothing. Unactionable doubt on a passing check told a model to 'fix'
    green tests ~20x in one session."""

    def test_execcheck_says_nothing_when_confirmed_or_not_applicable(self):
        self.assertEqual(execcheck.ExecResult(execcheck.CONFIRMED).marker, "")
        self.assertEqual(execcheck.ExecResult(execcheck.NOT_APPLICABLE).marker, "")

    def test_step_reframe_says_nothing_when_the_checks_are_green(self):
        self.assertEqual(loop._repair_note("Write `x.py`", "/tmp", False), "")


class Rule5b_NeverStateAFalseFact(unittest.TestCase):
    """Everything cria says in its own voice must be true of the world NOW, and cria must be able to
    say what makes it true."""

    def test_step_reframe_asks_the_FILESYSTEM_not_a_remembered_flag(self):
        self.assertIn("os.path.isfile", inspect.getsource(loop.step_artifacts_on_disk))

    def test_entrypoints_reads_files_never_a_claim(self):
        self.assertIn("os.walk", inspect.getsource(execcheck.entrypoints))

    def test_execcheck_runs_the_program_rather_than_believing_the_model(self):
        # The model supplies the command; the OUTPUT is cria's own observation.
        self.assertIn("subprocess.run", inspect.getsource(execcheck.run))


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


class Rule13_FailSafe(unittest.TestCase):
    """Fail CLOSED on completion; fail open only toward 'keep working'."""

    def test_an_unreadable_exec_intent_never_guesses(self):
        self.assertEqual(execcheck.parse_intent("maybe run it?"), {})

    def test_the_periodic_check_is_gated_on_GREEN(self):
        src = inspect.getsource(loop.Loop._periodic_satisfaction)
        self.assertIn("blocked", src)         # a red gate is one of the caller's blockers
        self.assertIn("return None", src)     # not satisfied -> carry on, never end


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


class BothCompletionPathsRunTheDeliverable(unittest.TestCase):
    """The repo's own checks prove a workspace compiles, lints and passes its tests. None of that
    can tell you the delivered program does anything — so cria runs it. That check reached ONE of
    the ways a session can end: _periodic_satisfaction. The plan-ON path ends because every STEP
    verified individually, and shipped without ever running what it built. Two judges wrote
    'Let me run it' into their reasoning and structurally could not.

    'Before shipping any fix, grep for its sibling' — this IS the sibling."""

    def test_the_plan_ON_completion_critic_runs_the_deliverable(self):
        src = inspect.getsource(loop.Loop._reopen_if_unsatisfied)
        self.assertIn("live_execution_marker", src)

    def test_the_plan_OFF_completion_check_still_does(self):
        src = inspect.getsource(loop.Loop._periodic_satisfaction)
        self.assertIn("live_execution_marker", src)

    def test_the_result_reaches_the_JUDGE_as_evidence_not_just_a_closing_note(self):
        # Appending it to the closing message tells nobody who can act. The completion critic is
        # what decides whether to re-open the plan, so that is what must see it.
        src = inspect.getsource(loop.Loop._reopen_if_unsatisfied)
        marker_at = src.index("live_execution_marker")
        judge_at = src.index("judge_satisfaction(task")   # the CALL, not the docstring
        self.assertLess(marker_at, judge_at, "the run happens after the verdict it should inform")

    def test_it_stays_silent_on_a_clean_run(self):
        # Empty marker adds nothing to the evidence — principle 3, and it keeps a confirmed run
        # from changing what the judge sees at all.
        self.assertEqual(execcheck.ExecResult(execcheck.CONFIRMED).marker, "")
        self.assertIn("if exec_marker:", inspect.getsource(loop.Loop._reopen_if_unsatisfied))
