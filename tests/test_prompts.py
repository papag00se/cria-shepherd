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

    def test_research_named_source_is_not_api_spec_only(self):
        # The INJECTED research step (fired when a task names a domain) assumed the domain was an API with
        # an openapi.json — so for a docs/service domain it steered the coder at a phantom openapi.json. It
        # must also name docs/reference sources, not only an API spec.
        r = prompts.render("research_named_source", domain="example.com")
        self.assertTrue(any(w in r.lower() for w in ("docs", "documentation", "reference")),
                        "research_named_source still frames research as API-spec only")
        self.assertIn("don't assume a spec file exists", r.lower())

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
        # re-fetching a spec it already had (churn). Both the injected step and the critic must say so.
        r = prompts.render("research_named_source", domain="example.com").lower()
        self.assertIn("not writing code in this step", r)
        self.assertNotIn("so the code uses concrete values", r)   # the code-usage clause that misjudged it
        v = prompts.load("verify").lower()
        self.assertIn("obtained", v)                              # done = facts obtained/visible in evidence
        self.assertIn("does not require", v)                      # ...NOT that any code used them

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
