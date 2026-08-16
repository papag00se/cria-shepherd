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
        """Driven, not read: the wording moved into prompts/ (#22), so a source scan for the literal
        was asserting where the string LIVES, not that the completion still stands on its own."""
        note = loop.satisfaction_done_note("The CLI resolves handles.", "⟦ctx:live-execution⟧ ran ok")
        self.assertIn("Task complete", note)
        self.assertIn("The CLI resolves handles.", note)
        self.assertTrue(note.endswith("⟦ctx:live-execution⟧ ran ok"))
        # …and with no marker the completion is unchanged, never emptied by its absence.
        self.assertIn("Task complete", loop.satisfaction_done_note("done."))

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

    def test_EVERY_caller_of_the_completion_judge_runs_the_deliverable(self):
        """The sibling grep, done properly. `judge_satisfaction` decides whether a session may end, and
        it has THREE callers, not two — the third is `_done_critic_reason`, the plan-OFF critic on a
        green `task_complete`, and it was the one that actually fired.

        Measured on ada-handles_mellum2_codex_poff_1785693138 (planner off, 166 calls, 2/4):
        `loop.done_critic` fired at calls 0158 and 0164, `loop.satisfaction_check` fired ZERO times, so
        both fixes landed that day missed the run they were written for. Both judges approved a CLI that
        dies with `NameError: name 'json' is not defined`."""
        for name in ("_periodic_satisfaction", "_reopen_if_unsatisfied", "_done_critic_reason"):
            with self.subTest(caller=name):
                src = inspect.getsource(getattr(loop.Loop, name))
                self.assertIn("judge_satisfaction(", src)
                marker_at = src.index("live_execution_marker(")
                judge_at = src.index("judge_satisfaction(")
                self.assertLess(marker_at, judge_at,
                                f"{name}: the run must inform the verdict, not follow it")

    def test_the_plan_ON_completion_critic_runs_the_deliverable(self):
        src = inspect.getsource(loop.Loop._reopen_if_unsatisfied)
        self.assertIn("live_execution_marker", src)

    def test_the_plan_OFF_completion_check_still_does(self):
        src = inspect.getsource(loop.Loop._periodic_satisfaction)
        self.assertIn("live_execution_marker", src)

    def test_the_plan_OFF_path_runs_it_BEFORE_the_verdict_too(self):
        """It was on this path already — but past `if not satisfied: return None`, so it could only
        decorate a completion the judge had already approved, never inform one.

        Measured on ada-handles_mellum2_codex_poff_1785693138 (planner off, 166 calls, 2/4):
        `loop.satisfaction_check` fired twice, `loop.exec_check` fired ZERO times. The delivered CLI
        crashes with `NameError: name 'json' is not defined`, the unit tests pass, and cria's lint
        floor says "no problems reported" — a green gate over a program that cannot run, and the one
        mechanism built to catch that was never asked."""
        src = inspect.getsource(loop.Loop._periodic_satisfaction)
        marker_at = src.index("exec_marker = live_execution_marker")
        judge_at = src.index("judge_satisfaction(")
        bail_at = src.index("if not satisfied:")
        self.assertLess(marker_at, judge_at, "the run happens after the verdict it should inform")
        self.assertLess(marker_at, bail_at, "a not-satisfied verdict returns before the run")

    def test_the_deliverable_is_never_run_TWICE_in_one_check(self):
        # The completion note reuses the marker rather than re-running the program.
        src = inspect.getsource(loop.Loop._periodic_satisfaction)
        self.assertEqual(src.count("live_execution_marker("), 1)

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


class ExecIntentAsksASimpleQuestionTests(unittest.TestCase):
    """The live-execution check asks for three JSON fields. Its first and only live firing —
    ada-handles_mellum2_codex_poff_1785714194 call 0032 — came back `finish_reason=length` with
    EMPTY content and all 8,192 tokens spent in reasoning, ending in a degenerate `5x5x5…` loop.
    No JSON, so the delivered program was never run: the one check built to catch a green gate over
    a broken program, 0 for 1. Every sibling judge already forces thinking off or retries a cut
    answer; this call did neither."""

    def test_it_forces_thinking_off(self):
        self.assertIn("force_think_off=True", inspect.getsource(loop.live_execution_marker))

    def test_a_CUT_answer_is_not_used_as_an_intent(self):
        self.assertIn("massage.is_truncated", inspect.getsource(loop.live_execution_marker))

    def test_it_still_never_affects_a_completion_on_failure(self):
        src = inspect.getsource(loop.live_execution_marker)
        self.assertIn('return ""', src)     # every failure path is silent, never a raise
