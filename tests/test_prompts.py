import unittest

from cria import prompts


class PromptAgnosticismTests(unittest.TestCase):
    """The core coding prompts were overfit to the ONE dev task (a Python script that browses the
    api.handle.me REST API). They must describe investigation/research/deliverables GENERICALLY, with
    the API/spec case as ONE example — else a non-API, non-Python task (Rust CLI, SQL, a data script)
    gets mis-planned, mis-verified, or steered toward an API that doesn't exist."""

    def test_planner_research_rule_is_not_api_only(self):
        p = prompts.load("plan")
        self.assertIn("external", p.lower())                 # generalized beyond "the API"
        self.assertIn("no external dependency", p)           # explicit opt-out for non-external tasks
        # it must NOT command an unconditional API-spec first step as the sole framing
        self.assertNotIn("DON'T GUESS THE API's ENDPOINTS", p)

    def test_verifier_investigative_step_accepts_non_web_sources(self):
        v = prompts.load("verify")
        # a file read / --help / schema must be able to satisfy an investigative step, not only a web_fetch
        self.assertTrue(any(w in v for w in ("a file's actual contents", "--help", "schema's columns")),
                        "verify.txt still defines a research step only in API/web terms")
        self.assertNotIn("resolved_addresses", v)            # the Ada-specific proposed_fix example is gone

    def test_research_step_done_when_facts_obtained_not_when_used_in_code(self):
        # A research/investigative step is fulfilled the MOMENT the coder OBTAINS the real facts via a tool
        # call (visible in a `->` result) — NOT when any code USES them (that is a later step's job). Judging
        # it by code-usage made the critic keep failing an already-satisfied research step, trapping the coder
        # re-fetching a spec it already had (churn). The critic is now the ONLY thing that says so — cria no
        # longer injects a research step of its own to carry the rule.
        v = prompts.load("verify").lower()
        self.assertIn("obtained", v)                              # done = facts obtained/visible in evidence
        self.assertIn("does not require", v)                      # ...NOT that any code used them

    def test_research_step_is_not_held_open_for_facts_the_source_lacks(self):
        # THE TRAP (measured, 3 runs): a step lists what to find BEFORE anyone has read the source, so
        # it names things that are not there. Run 0726-214428 re-derived step 1 to require "fields for
        # resolved_address, holder_address, total_handles" — names invented from the plan's own output
        # dict, in no spec — and the critic rejected that step 10 times over 111 calls with ZERO files
        # written. Run 0726-220739 demanded "authentication requirements" from an API that needs none,
        # and the coder started writing a spec-parsing program to hunt for them. The coder cannot prove
        # a negative, so the step is UNFALSIFIABLE: no action can ever satisfy it.
        # Both halves must hold together — the loosening may not swallow the guard that a research step
        # requires reading the REAL source, or "it isn't there" becomes an excuse for never looking.
        v = prompts.load("verify").lower()
        self.assertIn("cannot be obtained", v)              # a missing fact does not block the step
        self.assertTrue(any(w in v for w in ("demonstrably lacks", "not there")),
                        "verify.txt does not say a sought fact the source lacks can't hold a step open")
        self.assertIn("never actually read the real source", v)   # ...and the guard is still there

    def test_every_prompt_that_shapes_a_plan_says_research_is_not_runtime_discovery(self):
        # THE FOOTGUN (live run 0727-102822): the ungrounded-route challenge told the planner to
        # "word the step to READ the route from that source instead of naming one". Its reasoning
        # quoted that clause back — "So we need to incorporate fetching the API documentation first"
        # — and it re-drafted step 1 as "Implement fetch_api_docs() function to retrieve API
        # documentation and locate the resolve endpoint": the shipped program discovering its own
        # endpoint at runtime, which plan.txt explicitly forbids. cria's own steer overrode cria's
        # own rule, because only ONE of the four texts that shape a plan carried it.
        # Same class as the searching-vs-reading invariant below: one rule, every prompt that can
        # rewrite a plan must know it.
        steers = prompts.load_map("planner_steers")
        texts = {"plan": prompts.load("plan"), "replan": prompts.load("replan"),
                 "planner_steers.submit_ungrounded": steers["submit_ungrounded"],
                 "planner_steers.host_unread": steers["host_unread"]}
        # Phrasing is the prompt's own business — a model-facing steer says "when it runs" where a
        # rule-sheet says "at RUNTIME" — so match the concept, not one wording.
        for name, p in texts.items():
            low = p.lower()
            self.assertTrue(any(w in low for w in ("runtime", "when it runs", "every time it runs")),
                            f"{name} says nothing about the shipped program looking the route up itself")
            self.assertTrue(any(w in low for w in ("never", "must not", "not part of")),
                            f"{name} does not FORBID the shipped program discovering its own endpoint")

    def test_all_three_plan_prompts_agree_a_search_is_not_research(self):
        # THE CONTRADICTION (live runs 0726-131603 / -132211): plan.txt tells the DRAFTER "a web_search
        # does NOT satisfy this — read the thing the task actually points at", and verify.txt tells the
        # CRITIC "merely SEARCHING is not obtaining". replan.txt — the ONLY prompt that rewrites the plan
        # mid-run, and the one that fires precisely because the coder is stuck — said nothing. So a step
        # worded "Perform an initial web search ... to obtain the base URL, request method, required
        # parameters, and response schema" was drafted, survived every re-derivation verbatim, and was
        # rejected by cria's own critic forever: the coder searched, was refused, searched again, for the
        # whole run. Three prompts, one rule — they must not drift apart again.
        for name in ("plan", "replan", "verify"):
            p = prompts.load(name).lower()
            self.assertIn("web_search", p, f"{name}.txt says nothing about searching-vs-reading")
            self.assertTrue(any(w in p for w in ("not satisfy", "is not obtaining", "never search",
                                                 "not the source")),
                            f"{name}.txt does not say a search fails to satisfy a research step")

    def test_no_model_facing_string_carries_the_literal_project_name(self):
        # THE VIOLATION (live run 0726-142841, every red gate): the briefing's check-state line shipped
        # as "⟦ctx:checks⟧ GROUND TRUTH — cria ran the repo's own checks and they currently FAIL". The
        # model must NEVER see the literal project name (principle #17) — a distinctive proper noun
        # makes a weak model meta-reason about the mechanism instead of coding. It survived because
        # nothing checked: the rule was doctrine and convention, never an invariant.
        # A source line that builds ⟦ctx:…⟧ text is model-facing by construction, so it may not also
        # carry the bare word. ⟦cria⟧ (the human indicator, stripped before the model) is exempt.
        import pathlib, re
        root = pathlib.Path(prompts.__file__).parent.parent
        offenders = []
        for py in sorted(root.glob("*.py")):
            in_doc = False
            for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                fences = line.count('"""') + line.count("'''")
                was_doc = in_doc
                if fences % 2:
                    in_doc = not in_doc
                if was_doc or in_doc:      # docstrings/prose blocks are written FOR humans
                    continue
                code = line.split("#", 1)[0]                      # …and so are trailing comments
                if "⟦ctx:" not in code:
                    continue
                if re.search(r"(?<!⟦)\bcria\b(?!⟧)", code, re.I):
                    offenders.append(f"{py.name}:{n}: {line.strip()[:100]}")
        self.assertEqual(offenders, [], "model-facing ⟦ctx:…⟧ string carries the literal project name")

    def test_coder_system_research_rule_is_language_neutral(self):
        c = prompts.load("coder_system")
        self.assertNotIn("Python/requests/curl", c)          # the Python-only callout is generalized
        self.assertIn("library", c.lower())                  # covers more than "an API"

    def test_no_ada_handle_example_leaks_into_core_prompts(self):
        # the compaction/critic examples must not anchor a small model on the one dev task
        for name in ("done_summary", "satisfaction"):
            self.assertNotIn("no-resolved-address", prompts.load(name))
            self.assertNotIn("goose", prompts.load(name))

    def test_reasoner_prompts_do_not_hardcode_a_harness_tool_name(self):
        # the critic proposed_fix + steer coder-tools examples named Codex's `exec_command` — a tool the
        # coder may not have under a different harness (its real shell name is in the rendered {{TOOLS}}).
        self.assertNotIn("exec_command", prompts.load("verify"))
        self.assertNotIn("exec_command", prompts.load("reasoner_coder_tools"))

    def test_tool_descs_own_web_tool_behavior_without_drift(self):
        # tool_descs.txt is the SINGLE behavior source for cria's synthetic web tools (the cheatsheet now
        # carries only arg shapes). So the behavior it owns must be correct and complete: web_fetch names
        # the REAL spill dir (./tmp/read-only, not ./tmp/), documents cursor paging (previously only the
        # cheatsheet did) and raw; web_search must NOT claim results are always inline (the synthetic Brave
        # path spills them to ./tmp/read-only).
        d = prompts.load_map("tool_descs")
        wf = d["web_fetch"]
        self.assertIn("./tmp/read-only/", wf)   # the real spill dir
        self.assertNotIn("./tmp/<file>", wf)    # the old shallow path is gone
        self.assertIn("cursor=", wf)            # cursor paging documented here now
        self.assertIn("raw=true", wf)
        ws = d["web_search"].lower()
        self.assertIn("tmp/read-only", ws)      # results may be saved to a file, not asserted inline-only

    def test_coder_cwd_guidance_stands_alone(self):
        # the cwd rule must not depend on Codex's "working-environment line" being present
        c = prompts.load("coder_system")
        self.assertIn("current working directory", c)

    def test_planner_plans_the_deliverable_not_the_plumbing(self):
        # the plan must not include steps for what the harness does automatically (run tests/lint) or the
        # environment already provides (install X) — those padded the plan and made the coder fumble pytest.
        p = prompts.load("plan")
        self.assertIn("PLAN THE DELIVERABLE", p)
        # model-facing prompt: never leak the literal project name (only ⟦ctx:…⟧ markers are model-facing)
        self.assertNotIn("cria", p.lower())

    def test_noise_judge_catches_compound_env_setup_steps(self):
        # LIVE footgun: the noise judge answered NONE on "Create a virtual environment and install requests
        # and pytest" across every plan revision — the compound / "create a project skeleton" phrasing slid
        # past the old "its ONLY action is …" wording, and the venv/install step (requests was already
        # installed) trapped the run for the full timeout. The criterion must judge by the REAL action, not
        # a tidy leading verb, and name the scaffold/add-dependency forms.
        n = prompts.load("plan_noise_steps")
        low = n.lower()
        self.assertIn("skeleton", low)                 # scaffolding a "project skeleton" is setup
        self.assertIn("real action", low)              # judge the action, not the leading verb
        self.assertTrue("add" in low and "dependen" in low)   # "add requests" counts as installing a dependency

    def test_no_task_less_step_judge_prompt_exists(self):
        # A judge that DELETES a plan step must see the task. The retired plan_setup_steps.txt deliberately
        # withheld it, and measured over the captures deleted a research step ("Fetch the OpenAPI
        # specification…") and a README twice as often as it caught a real venv step. No prompt that drives
        # a step deletion may be task-less again.
        import pathlib
        self.assertFalse((pathlib.Path(prompts.__file__).parent / "prompts" / "plan_setup_steps.txt").exists())

    def test_critics_do_not_treat_exit0_as_proof_it_works(self):
        # Green-but-wrong (observed live): a resolver that 404s but CATCHES the error and exits 0 passed
        # the gate (compile+lint exit 0) and the step critic marked it "runs successfully". Both critics
        # must know exit-0/clean-compile is NOT proof the deliverable works; a printed runtime failure is.
        for name in ("verify", "satisfaction"):
            p = prompts.load(name)
            self.assertIn("EXIT 0", p, name)          # the explicit guidance is present
            low = p.lower()
            self.assertTrue("parses" in low and ("4xx" in low or "runtime failure" in p.lower()), name)

    def test_stuck_detector_veto_sentinel_is_positive_not_a_negation(self):
        # A weak reasoner reasoning "the coder is NOT progressing / IS stuck" collapses a NEGATION
        # sentinel ("NOT_STUCK") into the trigger word and emits it for the WRONG reason, vetoing its
        # own rescue while looping (observed live: reasoning "stuck in an infinite loop" → emitted
        # NOT_STUCK). The "fine, no help" verdict must be a POSITIVE token the trigger can't produce.
        for name in ("steer_diagnose", "steer_diagnose_user"):
            p = prompts.load(name)
            self.assertIn("ON_TRACK", p, name)
            self.assertNotIn("NOT_STUCK", p, name)  # the negation-trap token must be gone from the prompt


class PromptLoaderTests(unittest.TestCase):
    def test_load_trims_trailing_newline_only(self):
        text = prompts.load("classify")
        self.assertTrue(text.startswith("You are a REQUEST CLASSIFIER"))
        self.assertFalse(text.endswith("\n"))
        self.assertIn("\n", text)  # internal newlines preserved

    def test_render_fills_double_brace_tokens_case_insensitively(self):
        # nudge.txt content is user-tunable, so assert the MECHANISM (the {{REASON}} token is filled
        # from the case-insensitive kwarg), not the surrounding wording.
        out = prompts.render("nudge", reason="tests are red")
        self.assertIn("tests are red", out)      # the token was substituted
        self.assertNotIn("{{REASON}}", out)      # no placeholder left behind
        self.assertNotIn("{{", out)

    def test_nudge_carries_a_cria_marker(self):
        # The steer/nudge is injected as a USER-role message; the ⟦ctx:⟧ marker makes
        # classify.latest_user_text SKIP it so an injected steer can't be misread as the user's task.
        from cria.classify import _CRIA_INJECTION_MARKERS
        out = prompts.render("nudge", reason="you keep rewriting the same file")
        self.assertTrue(any(m in out for m in _CRIA_INJECTION_MARKERS))   # classify will skip it
        self.assertIn("you keep rewriting the same file", out)            # the steer itself is intact

    def test_render_leaves_literal_single_braces_untouched(self):
        # the critic must be told to emit `{"done": true}` — a single-brace literal that
        # must survive rendering (only {{TOKEN}} is substituted).
        self.assertIn('{"done": true|false, "reason": "<short>", "proposed_fix": "<brief fix prose>"}',
                      prompts.render("verify"))

    def test_unknown_token_is_left_in_place(self):
        self.assertIn("{{STEP}}", prompts.render("step_framing", idx=1, total=3, completed=""))

    def test_load_map_parses_key_values_and_skips_comments(self):
        m = prompts.load_map("cheatsheet")
        self.assertEqual(set(m) & {"header", "shell", "write_file"}, {"header", "shell", "write_file"})
        self.assertNotIn("#", "".join(m))  # comment lines are skipped, not keys
        self.assertIn("{{SHELL}}", m["shell"])  # token preserved for the caller to fill

    def test_load_map_converts_backslash_n_to_newline(self):
        m = prompts.load_map("verify_user")
        self.assertIn("\n", m["evidence"])       # `\n` in the file → real newline
        self.assertNotIn("\\n", m["evidence"])   # not left as a literal backslash-n


if __name__ == "__main__":
    unittest.main()
