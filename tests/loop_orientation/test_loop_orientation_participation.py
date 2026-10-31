"""What did a green or red command actually reach? Participation is evidence from the runner, never inference from an
exit code; every unknown stays non-approving."""
import json
from pathlib import Path

import pytest
from cria import loop, participation as pt, probediscovery as pd, wsview
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401

E = pd.Ecosystem
PASSING = {
    E.JsTs: ("npm test", "Tests:       2 passed, 2 total"),
    E.Python: ("python3 -m pytest -q", "2 passed in 0.04s"),
    E.Rust: ("cargo test --no-fail-fast", "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out"),
    E.Go: ("go test -count=1 -v ./...", "=== RUN   TestOne\n--- PASS: TestOne (0.00s)\nok  example.test/app  0.01s"),
    E.Jvm: ("mvn test", "[INFO] Running example.AppTest\nTests run: 2, Failures: 0, Errors: 0, Skipped: 0"),
    E.DotNet: ("dotnet test", "Failed:     0, Passed:     2, Skipped:     0, Total:     2"),
    E.Php: ("vendor/bin/phpunit", "OK (2 tests, 2 assertions)"),
    E.Ruby: ("rake test", "2 runs, 2 assertions, 0 failures, 0 errors, 0 skips"),
    E.Elixir: ("mix test", "2 tests, 0 failures"),
}

def cand(eco, command, kind=pd.ProbeKind.Test, cwd="/workspace"):
    return pd.ProbeCandidate(kind, command.split(), Path(cwd), 90, 90, pd.ProbeCost.Moderate, False, False, False,
                             "fixture", ecosystem=eco)

def test_each_ecosystems_runner_carries_its_exact_tally_line_and_a_build_check_proves_a_build():
    assert {a.ecosystem for a in pt.ADAPTERS} == set(E)                     # no discovery ecosystem lacks an adapter
    for eco, (command, output) in PASSING.items():
        event = pt.observe(cand(eco, command), output, 0)
        assert (event.test.participated, event.test.passed, event.test.support()) == (True, True, pt.Support.PROVEN), eco
        assert set(event.test.output_lines) & set(output.splitlines()), eco   # the runner's own line, verbatim
        assert pt.observe(cand(eco, command, pd.ProbeKind.BuildCheck), "", 0).build.support() is pt.Support.PROVEN, eco

@pytest.mark.parametrize("eco,command,output,code,expected,passed", [
    (E.JsTs, "npm run test", "the project-specific runner finished", 0, pt.Support.UNKNOWN, None),  # not pass, not zero
    (E.Jvm, "mvn test", "[INFO] No tests to run.", 0, pt.Support.ABSENT, None),                      # empty suite
    (E.Rust, "cargo test", PASSING[E.Rust][1], 127, pt.Support.UNKNOWN, None),                      # launch failure
], ids=["unreadable-green", "empty-suite", "launch-failure"])
def test_only_runner_evidence_moves_support_off_unknown(eco, command, output, code, expected, passed):
    """A green exit stands in for nothing, a launch failure cannot borrow plausible output, a failure is a failure."""
    event = pt.observe(cand(eco, command), output, code)
    assert (event.test.support(), event.test.passed) == (expected, passed)

def test_source_reach_is_per_named_file_and_a_missing_section_or_red_phase_is_never_outvoted_by_green():
    """A Maven build that compiled '3 source files' does not prove App.java; a Go package pass is not a file."""
    gone = pt.observe(cand(E.Go, "go test ./..."), "", None, event_missing=True)
    assert gone.event_complete is None and gone.as_dict()["test"]["count"] == "unknown"
    green = pt.observe(cand(E.Python, "python3 -m pytest -q"), "2 passed in 0.04s", 0)
    red = pt.observe(cand(E.Python, "python3 -m pytest -q"), "1 failed, 1 passed in 0.04s", 1)
    assert pt.report([green, red]).support("test") is pt.Support.FAILED
    maven = pt.observe(cand(E.Jvm, "mvn -q compile", pd.ProbeKind.BuildCheck),
                       "[INFO] Compiling 3 source files to /workspace/target/classes", 0)
    assert maven.source.count == 3 and maven.source.participants is None
    assert not pt.report([maven]).supports_source_file("src/main/java/example/App.java")
    assert pt.report([maven]).support("source") is pt.Support.UNKNOWN
    golang = pt.observe(cand(E.Go, "go test -count=1 -v ./..."), PASSING[E.Go][1], 0)
    assert golang.source.participant_kind == "package" and not golang.source.supports_file("app.go")
    assert pt.report([golang]).support("source") is pt.Support.UNKNOWN
    check = pt.report([pt.observe(cand(E.JsTs, "node --check src/index.js", pd.ProbeKind.SyntaxCheck), "", 0)])
    assert check.supports_source_file("src/index.js") and not check.supports_source_file("src/other.js")

def declared(script, files):
    """The project's declared `npm test` script over a workspace holding `files`, as the harness's survey shows it."""
    root = "/workspace"
    view = wsview.View(root, "declared")
    view.note_read(root + "/package.json", json.dumps({"scripts": {"test": script}}))
    for name in files:
        view.note_read(f"{root}/{name}", "require('assert').ok(true);\n")
    token = wsview.bind(view)
    try:
        found = []
        pd.build_js(Path(root), pd.ProjectDir(Path(root), {"package.json"}), found)
    finally:
        wsview.unbind(token)
    return next(c for c in found if c.kind is pd.ProbeKind.Test)

@pytest.mark.parametrize("script,files,code,participated,support", [
    ("node test/real.test.js", ["test/real.test.js"], 0, True, pt.Support.PROVEN),
    ("node --ignore test/skip.test.js test/real.test.js", ["test/skip.test.js", "test/real.test.js"], 0, None,
     pt.Support.UNKNOWN),                                                                       # operand slot is a flag
    ("mocha test/a.test.js || true", ["test/a.test.js"], 0, None, pt.Support.UNKNOWN),         # `|| true` masks the exit
    ("node a.test.js && node b.test.js", ["a.test.js", "b.test.js"], 1, True, pt.Support.FAILED),
], ids=["exit0", "flag-value", "or-true", "and-chain-fail"])
def test_a_declared_test_command_that_directly_runs_its_test_file_participates_without_a_tally(
        script, files, code, participated, support):
    """P23 Handles (C32): `npm test` = `node test/real.test.js` has no framework tally, so a genuinely green run stayed
    'unknown' and the completion barrier held it as unproven. Participation is credited only where the operand is
    structurally executed and the exit code is trustworthy."""
    event = pt.observe(declared(script, files), "", code)
    assert event.test.participated is participated
    assert pt.report([event]).support("test") is support
    if "&&" in script and code:
        assert event.test.participants is None          # a failing chain proves nothing about later segments

SATISFIED = json.dumps({"satisfied": True, "reason": "all deliverables are present"})
E2E_TASK = "Build a Node CLI that resolves a handle. Add an end-to-end test that verifies the tool end to end."

@pytest.mark.parametrize("task,answer,satisfied", [
    (E2E_TASK, "REQUIRED", False),
    ("Add a --json option to the CLI.", "NOT_REQUIRED", True),
], ids=["test-required", "no-test-required"])
def test_a_positive_satisfaction_verdict_cannot_promote_a_required_test_that_never_ran(task, answer, satisfied):
    """C23: the Handles run wrote test/lookup.test.js, ran only `node --check`, test participation was unknown, and
    the judge still returned satisfied=true. An unexecuted required test blocks; an unrelated task is not blocked."""
    report = pt.report([pt.observe(cand(E.JsTs, "node --check lookup.js", pd.ProbeKind.SyntaxCheck), "", 0)])
    assert report.support("test") is pt.Support.UNKNOWN
    state = loop.GuardState()
    state.last_gate_participation, state.gate_fresh = report, True
    queue = [SATISFIED, answer]                                  # the judge's verdict, then the participation question
    chat = lambda body, _log: json.dumps({"choices": [{"message": {"content": queue.pop(0)}}]}).encode()
    ok, _reason, _fix = loop.judge_satisfaction(task, "Wrote lookup.js", chat, None, Log(), sess=state)
    assert ok is satisfied and not queue
