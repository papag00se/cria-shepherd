"""Cross-ecosystem build/source/test participation is evidence, never inference.

Every fixture below is shaped like the raw body of a completion-gate section.  The adapters must
carry the runner's exact supporting line, keep unsupported fields unknown, and refuse to let a
green exit stand in for evidence that a named implementation file participated.
"""
import json
import pathlib
import unittest

from cria import loop, participation, probediscovery, probegate, wsview


def candidate(ecosystem, command, kind=probediscovery.ProbeKind.Test, cwd="/workspace"):
    return probediscovery.ProbeCandidate(
        kind=kind, command=command.split(), working_dir=pathlib.Path(cwd), confidence=90,
        expected_value=90, cost=probediscovery.ProbeCost.Moderate, mutates_code=False,
        may_hang=False, may_need_services=False, reason="fixture", ecosystem=ecosystem)


PASSING = {
    probediscovery.Ecosystem.JsTs: (
        "npm test", "Tests:       2 passed, 2 total"),
    probediscovery.Ecosystem.Python: (
        "python3 -m pytest -q", "2 passed in 0.04s"),
    probediscovery.Ecosystem.Rust: (
        "cargo test --no-fail-fast", "     Running unittests src/lib.rs\n"
        "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out"),
    probediscovery.Ecosystem.Go: (
        "go test -count=1 -v ./...", "=== RUN   TestOne\n--- PASS: TestOne (0.00s)\n"
        "=== RUN   TestTwo\n--- PASS: TestTwo (0.00s)\nok  example.test/app  0.01s"),
    probediscovery.Ecosystem.Jvm: (
        "mvn test", "[INFO] Running example.AppTest\n"
        "Tests run: 2, Failures: 0, Errors: 0, Skipped: 0"),
    probediscovery.Ecosystem.DotNet: (
        "dotnet test", "Failed:     0, Passed:     2, Skipped:     0, Total:     2"),
    probediscovery.Ecosystem.Php: (
        "vendor/bin/phpunit", "OK (2 tests, 2 assertions)"),
    probediscovery.Ecosystem.Ruby: (
        "rake test", "2 runs, 2 assertions, 0 failures, 0 errors, 0 skips"),
    probediscovery.Ecosystem.Elixir: (
        "mix test", "2 tests, 0 failures"),
}


class EveryDiscoveryEcosystemHasAnAdapterTests(unittest.TestCase):
    def test_the_registry_is_the_nine_ecosystem_enum(self):
        self.assertEqual({adapter.ecosystem for adapter in participation.ADAPTERS},
                         set(probediscovery.Ecosystem))
        self.assertEqual(len(participation.ADAPTERS), 9)

    def test_each_runner_carries_its_exact_tally_line(self):
        for ecosystem, (command, output) in PASSING.items():
            with self.subTest(ecosystem=ecosystem.value):
                event = participation.observe(candidate(ecosystem, command), output, 0)
                self.assertIs(event.test.participated, True)
                self.assertIs(event.test.passed, True)
                self.assertIs(event.test.completed, True)
                self.assertIs(event.test.support(), participation.Support.PROVEN)
                exact = set(event.test.output_lines)
                self.assertTrue(any(line in exact for line in output.splitlines()), exact)

    def test_a_build_candidate_has_build_evidence_in_every_ecosystem(self):
        for ecosystem, (command, _output) in PASSING.items():
            with self.subTest(ecosystem=ecosystem.value):
                event = participation.observe(
                    candidate(ecosystem, command, probediscovery.ProbeKind.BuildCheck), "", 0)
                self.assertIs(event.build.attempted, True)
                self.assertIs(event.build.completed, True)
                self.assertIs(event.build.participated, True)
                self.assertIs(event.build.support(), participation.Support.PROVEN)

    def test_the_jvm_adapter_reads_gradle_as_well_as_maven(self):
        line = "2 tests completed, 0 failed"
        event = participation.observe(
            candidate(probediscovery.Ecosystem.Jvm, "./gradlew test"), line, 0)
        self.assertIs(event.test.support(), participation.Support.PROVEN)
        self.assertEqual(event.test.count, 2)
        self.assertIn(line, event.test.output_lines)


class UnknownNeverApprovesTests(unittest.TestCase):
    def test_an_unreadable_green_runner_is_unknown_not_pass_or_zero(self):
        event = participation.observe(
            candidate(probediscovery.Ecosystem.JsTs, "npm run test"),
            "the project-specific runner finished", 0)
        self.assertIsNone(event.test.participated)
        self.assertIsNone(event.test.passed)
        self.assertIsNone(event.test.count)
        self.assertIsNone(event.test.passed_count)
        self.assertIs(event.test.support(), participation.Support.UNKNOWN)
        self.assertIs(participation.report([event]).support("test"),
                      participation.Support.UNKNOWN)

    def test_a_green_build_without_source_identities_cannot_approve_a_claimed_file(self):
        """The exact defect: Maven compiled some sources, but its event did not name which files.
        A count and a green exit are useful facts; neither proves App.java participated."""
        event = participation.observe(
            candidate(probediscovery.Ecosystem.Jvm, "mvn -q compile",
                      probediscovery.ProbeKind.BuildCheck),
            "[INFO] Compiling 3 source files to /workspace/target/classes", 0)
        report = participation.report([event])
        self.assertIs(event.source.participated, True)
        self.assertEqual(event.source.count, 3)
        self.assertIsNone(event.source.participants)
        self.assertIs(report.support("source"), participation.Support.UNKNOWN)
        self.assertFalse(report.supports_source_file("src/main/java/example/App.java"))

    def test_a_missing_gate_section_is_all_unknown(self):
        event = participation.observe(
            candidate(probediscovery.Ecosystem.Go, "go test -count=1 -v ./..."),
            "", None, event_missing=True)
        self.assertIsNone(event.event_complete)
        self.assertIs(event.test.support(), participation.Support.UNKNOWN)
        rendered = event.as_dict()
        self.assertEqual(rendered["test"]["passed"], "unknown")
        self.assertEqual(rendered["test"]["count"], "unknown")

    def test_an_explicit_empty_suite_is_absent_not_passing(self):
        event = participation.observe(
            candidate(probediscovery.Ecosystem.Jvm, "mvn test"),
            "[INFO] No tests to run.", 0)
        self.assertIs(event.test.participated, False)
        self.assertIsNone(event.test.passed)
        self.assertIs(event.test.support(), participation.Support.ABSENT)

    def test_an_explicit_zero_is_zero_but_never_a_pass(self):
        event = participation.observe(
            candidate(probediscovery.Ecosystem.JsTs, "npm test"),
            "Tests:       0 passed, 0 total", 0)
        self.assertEqual(event.test.count, 0)
        self.assertEqual(event.test.passed_count, 0)
        self.assertIs(event.test.participated, False)
        self.assertIsNone(event.test.passed)
        self.assertIs(event.test.support(), participation.Support.ABSENT)

    def test_a_launch_failure_cannot_borrow_plausible_output(self):
        output = ("     Running unittests src/lib.rs\n"
                  "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out")
        event = participation.observe(
            candidate(probediscovery.Ecosystem.Rust, "cargo test --no-fail-fast"),
            output, 127)
        self.assertIs(event.test.attempted, False)
        self.assertIsNone(event.test.participated)
        self.assertIsNone(event.source.participated)
        self.assertIs(event.test.support(), participation.Support.UNKNOWN)

    def test_a_failed_phase_cannot_be_outvoted_by_a_green_phase(self):
        green = participation.observe(
            candidate(probediscovery.Ecosystem.Python, "python3 -m pytest -q"),
            "2 passed in 0.04s", 0)
        red = participation.observe(
            candidate(probediscovery.Ecosystem.Python, "python3 -m pytest -q"),
            "1 failed, 1 passed in 0.04s", 1)
        self.assertIs(participation.report([green, red]).support("test"),
                      participation.Support.FAILED)


class SourceIdentityTests(unittest.TestCase):
    def test_a_per_file_source_check_can_support_only_the_file_it_named(self):
        event = participation.observe(
            candidate(probediscovery.Ecosystem.JsTs, "node --check src/index.js",
                      probediscovery.ProbeKind.SyntaxCheck), "", 0)
        report = participation.report([event])
        self.assertIs(report.support("source"), participation.Support.PROVEN)
        self.assertTrue(report.supports_source_file("src/index.js"))
        self.assertFalse(report.supports_source_file("src/other.js"))

    def test_package_participation_is_not_a_claim_about_a_go_file(self):
        event = participation.observe(
            candidate(probediscovery.Ecosystem.Go, "go test -count=1 -v ./..."),
            "=== RUN   TestOne\n--- PASS: TestOne (0.00s)\nok  example.test/app  0.01s", 0)
        self.assertEqual(event.source.participant_kind, "package")
        self.assertIs(participation.report([event]).support("source"),
                      participation.Support.UNKNOWN)
        self.assertFalse(event.source.supports_file("app.go"))

    def test_aggregate_source_inputs_are_the_plan_time_set(self):
        cand = candidate(probediscovery.Ecosystem.Python,
                         "python3 -m compileall -q .",
                         probediscovery.ProbeKind.SyntaxCheck)
        cand.participation_inputs = ("before.py",)
        cand.participation_inputs_complete = True
        view = wsview.View("/workspace", "later-view")
        view.note_read("/workspace/after.py", "created after the probe was planned\n")
        token = wsview.bind(view)
        try:
            event = participation.observe(cand, "", 0)
        finally:
            wsview.unbind(token)
        self.assertEqual(event.source.participants, ("before.py",))
        self.assertTrue(event.source.supports_file("before.py"))
        self.assertTrue(event.source.supports_file("/workspace/before.py"))
        self.assertFalse(event.source.supports_file("after.py"))


class ManifestEvidenceTests(unittest.TestCase):
    def test_config_lines_come_from_wsview_and_are_explicitly_not_execution(self):
        root = "/harness-only/workspace"
        line = "    <sourceDirectory>src/handwritten</sourceDirectory>"
        view = wsview.View(root, "participation-fixture")
        view.note_read(root + "/pom.xml", "<build>\n" + line + "\n</build>\n")
        token = wsview.bind(view)
        try:
            event = participation.observe(
                candidate(probediscovery.Ecosystem.Jvm, "mvn -q compile",
                          probediscovery.ProbeKind.BuildCheck, root), "BUILD SUCCESS", 0)
        finally:
            wsview.unbind(token)
        self.assertEqual(event.manifests[0].lines, (line,))
        rendered = participation.render_for_judge(participation.report([event]))
        self.assertIn("declarations only, not execution", rendered)


class GateAndJudgeWiringTests(unittest.TestCase):
    def test_interpretation_carries_the_event_to_every_satisfaction_call(self):
        eco = probediscovery.Ecosystem.Jvm
        cand = candidate(eco, "mvn test")
        plan = probegate.GatePlan(workspace="/workspace", candidates=[cand])
        tally = "Tests run: 2, Failures: 0, Errors: 0, Skipped: 0"
        raw = f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n{tally}\nEXIT:0\n"
        outcome = probegate.interpret_gate(plan, raw)
        state = loop.GuardState(workspace_root="/workspace")
        loop.record_gate_state(state, outcome, "")

        calls = []
        def judge(body, _rlog):
            calls.append(body)
            return json.dumps({"choices": [{"message": {"content":
                '{"satisfied": false, "reason": "not proven", "proposed_fix": "deliverable"}'}}]}).encode()

        loop.judge_satisfaction("do the thing", "ordinary evidence", judge, None, _Rlog(), sess=state)
        prompt = calls[0]["messages"][-1]["content"]
        self.assertIn("BUILD / SOURCE / TEST PARTICIPATION", prompt)
        self.assertIn(tally, prompt)
        self.assertIn('"source": "unknown"', prompt)

    def test_the_step_completion_critic_receives_the_same_facts(self):
        event = participation.observe(
            candidate(probediscovery.Ecosystem.Python, "python3 -m pytest -q"),
            "2 passed in 0.04s", 0)
        facts = participation.render_for_judge(participation.report([event]), fresh=True)
        calls = []

        def judge(body, _rlog):
            calls.append(body)
            return json.dumps({"choices": [{"message": {"content":
                '{"done": false, "reason": "source reach unknown", "proposed_fix": "verify it"}'}}]}).encode()

        context = loop.LoopContext(planner=None, coder_chat=judge, reasoner_chat=judge, runs_dir="")
        subject = loop.Loop(context)
        done, _reason = subject._verify("implement app.py", "done", "", "", _Rlog(),
                                        participation_facts=facts)
        self.assertFalse(done)
        prompt = calls[0]["messages"][-1]["content"]
        self.assertIn("BUILD / SOURCE / TEST PARTICIPATION", prompt)
        self.assertIn("2 passed in 0.04s", prompt)
        self.assertIn('"source": "unknown"', prompt)

    def test_a_cut_section_reaches_the_judge_as_unknown(self):
        cand = candidate(probediscovery.Ecosystem.Python, "python3 -m pytest -q")
        plan = probegate.GatePlan(workspace="/workspace", candidates=[cand])
        raw = f"{probegate.SECTION_PREFIX}probe-other{probegate.SECTION_SUFFIX}\nEXIT:0\n"
        outcome = probegate.interpret_gate(plan, raw)
        self.assertIs(outcome.participation.support("test"), participation.Support.UNKNOWN)
        self.assertIn('"test": "unknown"', participation.render_for_judge(outcome.participation))


class _Rlog:
    def emit(self, *_args, **_kwargs):
        pass


if __name__ == "__main__":
    unittest.main()
