"""Incident: a completion gate planned after the coder's own shell command saw no held manifest body as current, so discovery composed
only syntax checks (no `rake test`), the test participation stayed "unknown", and the gate refused the same finished work 13 times. The
survey riding home with that very gate delivers the bodies; the plan must be re-selected against them."""
import subprocess

import pytest

from cria import probegate, wsview
from gates_completion_helpers import gates_completion_view, run_in_harness  # noqa: F401

SESS = "blind-plan"


def _ruby_project(root):
    (root / "lib").mkdir()
    (root / "test").mkdir()
    (root / "Gemfile").write_text('source "https://rubygems.org"\n')
    (root / "Rakefile").write_text('require "rake/testtask"\nRake::TestTask.new(:test) { |t| t.test_files = FileList["test/**/test_*.rb"] }\n')
    (root / "lib/s.rb").write_text("module S; end\n")
    (root / "test/test_s.rb").write_text('require "minitest/autorun"\nclass T < Minitest::Test; def test_a; assert true; end; end\n')


def _node_project(root):
    (root / "package.json").write_text('{"name": "h", "scripts": {"start": "node lookup.js", "test": "node lookup.test.js"}}\n')
    (root / "lookup.js").write_text("module.exports = 1;\n")
    (root / "lookup.test.js").write_text("require('./lookup.js');\n")


def _tests(plan):
    return [" ".join(c.command) for c in plan.candidates if c.kind.name == "Test"]


@pytest.mark.parametrize("build,manifest,tools,expected", [
    (_ruby_project, "Rakefile", "ruby && command -v rake", "rake test"),
    (_node_project, "package.json", "node && command -v npm", "npm run test"),
], ids=["ruby", "node"])
def test_a_gate_planned_after_a_mutating_command_is_replanned_once_its_survey_delivers_the_manifest(tmp_path, build, manifest, tools, expected):
    if subprocess.run(["sh", "-c", f"command -v {tools}"], capture_output=True).returncode != 0:
        pytest.skip("the project's own toolchain is not installed")
    build(tmp_path)
    root = str(tmp_path)
    view = wsview.View(root, SESS)
    token = wsview.bind(view)
    try:
        tree = subprocess.run(["sh", "-c", wsview.survey_command(SESS, cd=root)], capture_output=True, text=True).stdout
        assert wsview.apply_survey(view, wsview.strip_survey(tree)[1])
        view.note_unknown_mutation()                      # the coder ran `rake test` itself: no held body is current any more
        plan = probegate.plan_gate(root, SESS)
        assert plan.surveyed_before and _tests(plan) == [] and manifest in plan.unanswered_reads
        subprocess.run(["git", "init", "-q", root], check=True)
        raw = run_in_harness(plan.script, tmp_path, "sh")
        outcome = probegate.interpret_gate(plan, raw)
        while outcome.transport_pending:
            raw = run_in_harness(probegate.continue_transport_command(plan), tmp_path)
            outcome = probegate.interpret_gate(plan, raw)
        assert outcome.ran and outcome.replan_after_survey
        assert _tests(probegate.plan_gate(root, SESS)) == [expected]
    finally:
        wsview.unbind(token)


def test_gate_refreshes_discovery_input_after_a_check_changes_it(tmp_path):
    if subprocess.run(["sh", "-c", "command -v npm && command -v node"], capture_output=True).returncode:
        pytest.skip("the project's own toolchain is not installed")
    _node_project(tmp_path)
    (tmp_path / "lookup.test.js").write_text(
        "const fs = require('fs'); const p = require('./package.json'); "
        "p.scripts.test = 'node changed.test.js'; fs.writeFileSync('package.json', JSON.stringify(p));\n")
    root, session = str(tmp_path), "known-manifest-post-check"
    view = wsview.View(root, session)
    token = wsview.bind(view)
    try:
        view.request_current_body(root + "/package.json")
        tree = subprocess.run(["sh", "-c", wsview.survey_command(session, cd=root)], capture_output=True, text=True).stdout
        assert wsview.apply_survey(view, wsview.strip_survey(tree)[1])
        assert view.read(root + "/package.json") is not None
        plan = probegate.plan_gate(root, session)
        assert _tests(plan) == ["npm run test"]
        raw = run_in_harness(plan.script, tmp_path, "sh")
        outcome = probegate.interpret_gate(plan, raw)
        while outcome.transport_pending:
            raw = run_in_harness(probegate.continue_transport_command(plan), tmp_path)
            outcome = probegate.interpret_gate(plan, raw)
        assert outcome.ran
        assert "node changed.test.js" in view.read_current_survey(root + "/package.json")
        # The next gate consumes the post-check manifest, rather than alternating
        # to a blind plan after the check changed it.
        next_plan = probegate.plan_gate(root, session)
        assert _tests(next_plan) == ["npm run test"]
        assert "package.json" not in next_plan.unanswered_reads
    finally:
        wsview.unbind(token)


def test_a_manifest_name_the_survey_reported_absent_is_not_queued_again_ahead_of_the_real_manifest():
    view = wsview.View("/w", "absent-names")
    view._surveyed, view._complete = True, False          # an incomplete listing: `isfile` is unknown for every name
    view._files["Rakefile"] = (10, 1.0)
    view._undeliverable["go.mod"] = -1                    # the survey's own answer: not there
    assert view.read("/w/go.mod") is None
    assert view.read("/w/Rakefile") is None
    assert wsview.pending("absent-names")[0] == ["Rakefile"]


def test_absence_is_proof_only_for_a_missing_file_and_only_until_the_tree_may_have_changed(tmp_path):
    (tmp_path / "locked").mkdir()
    (tmp_path / "Rakefile").write_text("x\n")
    script = wsview.survey_command("abs", cd=str(tmp_path))
    assert "FileNotFoundError, NotADirectoryError" in script                       # only ENOENT/ENOTDIR may say -1
    view = wsview.View("/w", "abs-fresh")
    view._surveyed, view._complete = True, False
    view._undeliverable["go.mod"] = wsview.UNSTATABLE                              # a stat error: not proof of anything
    assert view.read("/w/go.mod") is None and "go.mod" in wsview.pending("abs-fresh")[0]
    view._undeliverable["Cargo.toml"] = wsview.ABSENT
    view.note_unknown_mutation()                                                   # a command ran: absence is stale
    assert "Cargo.toml" not in view._undeliverable
    assert view.read("/w/Cargo.toml") is None and "Cargo.toml" in wsview.pending("abs-fresh")[0]
