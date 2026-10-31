"""A green check does not survive a later write; only a newer run of the same check clears a finding; stale quotes/notes are never present tense."""
import pytest

from cria import loop, probegate
from cria.probeparse import is_advisory
from gates_completion_helpers import (gates_completion_view, cand, coder_call, deliver, gate_turn, new_plan,  # noqa: F401
                                      sec, text_of)

RED_GO = sec(0, "cart.go:8:2: no required module provides package github.com/x/y", 1)


def write(path, cid="w"):
    """A landed edit_file: the call and its program's typed result."""
    return [*coder_call(cid, None, name="edit_file", args={"path": path, "old_string": "a", "new_string": "b"}),
            {"role": "tool", "tool_call_id": cid, "content": "Wrote it", "cria_result_outcome": "landed"}]


def notes(*later, plan=None):
    """The newest gate's block as the coder re-reads it after ``later`` messages happened."""
    plan = plan or deliver(new_plan("c" * 24, candidates=[cand(["go", "build", "./..."])]), RED_GO)
    out = probegate.clean_gate_results([*gate_turn("g", RED_GO, "c" * 24, probes=("go build ./...",)), *later], plan)
    return text_of(out)


def test_the_block_says_what_changed_after_it_ran_and_a_rerun_withdraws_the_demand():
    """cart-billing-go 1788230301: after `go mod download` the block asserted `missing go.sum entry` as present tense for 11
    calls, and after the coder's own `go build` it still demanded a re-run. Only a LANDED write or a write-capable command is
    a change; a probe re-run after the last change clears the demand (a command that also writes does not)."""
    landed_edit = write("go.mod")
    assert "ran BEFORE your edit to `go.mod` and have not been re-run since" in notes(*landed_edit)
    refused = [*write("go.mod")[:1], {"role": "tool", "tool_call_id": "w", "content": "⟦ctx:edit⟧ old_string is not an exact match"}]
    assert "BEFORE" not in notes(*refused)
    assert "BEFORE" not in notes(*coder_call("pre", "go build ./...", "ok"))        # a read-only command is no change
    assert "ran BEFORE a command you ran that can change the workspace" in notes(*coder_call("m", "go mod download x/y", "ok"))
    rerun = notes(*landed_edit, *coder_call("r", "go build ./...", "ok"))
    assert "re-run checks yourself since" in rerun and "have not been re-run since" not in rerun and "`go.mod`" in rerun
    both = notes(*landed_edit, *coder_call("r", "go build ./... && go mod download x/y", "ok"))
    assert "have not been re-run since" in both
    again = notes(*landed_edit, *coder_call("r", "go build ./...", "ok"), *write("cart.go", "w2"))    # a later edit voids the re-run
    assert "have not been re-run since" in again


def test_a_flagged_line_is_quoted_from_disk_only_while_the_file_has_not_moved(tmp_path):
    """mellum2 1786196176: the newest gate was re-annotated against yesterday's check with today's line - a self-contradicting
    anchor. After a landed write to the flagged file the finding keeps the checker's own line, unquoted."""
    (tmp_path / "t.py").write_text("import os\nmock = 1\n")
    raw = sec(0, "t.py:2:1: undefined name 'requests'", 1)
    plan = deliver(new_plan("d" * 24, workspace=str(tmp_path)), raw)
    fresh = text_of(probegate.clean_gate_results(gate_turn("g", raw, "d" * 24), plan))
    moved = text_of(probegate.clean_gate_results([*gate_turn("g", raw, "d" * 24), *write("t.py")], plan))
    assert "the flagged line on disk" in fresh and "mock = 1" in fresh
    assert "undefined name 'requests'" in moved and "the flagged line on disk" not in moved


def supersede(finding, coder_out, command="pytest -q", before_gate=False, then_write=False):
    checks = f"$ {command}\n{finding}"
    gate = gate_turn("g1", sec(0, finding, 1), probes=(command,))
    run = coder_call("c9", command, "Process exited with code 0\nOutput:\n" + coder_out)
    msgs = [*run, *gate] if before_gate else [*gate, *run, *(write("a.py") if then_write else [])]
    return loop._checks_superseded_by_coder_run(msgs, checks)


@pytest.mark.parametrize("finding,out,cmd,want", [
    ("error[E0432]: unresolved import `toml::Rows`", "test result: ok. 6 passed; 0 failed", "cargo test", "0f/6p"),
    ("Importer.java:31: error: cannot find symbol", "Tests run: 9, Failures: 0, Errors: 0, Skipped: 0", "mvn test", "0f/9p"),
    ("tests/test_a.py:44: AssertionError\n1 failed, 4 passed", "5 passed in 0.02s", "pytest -q", "0f/5p"),
    ("main.go:3: undefined: foo", "ok  \thandles/pkg\t0.2s", "go test ./...", ""),                       # plain `go test` prints no tally
    ("app.py:3:1: unused import os", "5 passed in 0.02s", "pytest -q", ""),                       # a lint finding is not a test finding
    ("tests/test_a.py:44: AssertionError", "2 failed, 3 passed in 0.02s", "pytest -q", ""),         # a red run clears nothing
], ids=["cargo-clears-compile", "junit-clears-javac", "pytest-clears-test", "go-no-tally", "pytest-keeps-lint", "red-clears-nothing"])
def test_only_a_newer_green_run_of_the_same_check_clears_a_cached_finding(finding, out, cmd, want):
    """qwen35/go 0034: the steer author read 'sum.Add is called with 2 args' as GROUND TRUTH after the coder's build passed.
    A compiled runner settles a compile finding too (cargo cannot say ok over an unresolved import); an interpreted one does not."""
    assert supersede(finding, out, cmd) == want


def test_a_run_before_the_gate_or_a_write_after_the_green_run_clears_nothing():
    """The green run must be NEWER than the gate and not followed by another write."""
    red = "t.py:4: AssertionError\n1 failed, 4 passed"
    assert supersede(red, "5 passed in 0.02s", before_gate=True) == ""
    assert supersede(red, "5 passed in 0.02s", then_write=True) == ""
    assert supersede(red, "5 passed in 0.02s") == "0f/5p"


@pytest.mark.parametrize("msg,advisory", [
    ("'os' imported but unused", True), ("./main.go:7:2: declared and not used: x", False),
])
def test_unused_is_advisory_only_where_the_program_still_runs(msg, advisory):
    """Go's unused variable/import is a COMPILE error and must still gate; the same English elsewhere is advisory."""
    assert is_advisory(msg) is advisory


def test_an_offline_fact_belongs_only_to_the_gate_that_measured_it():
    """Go L5: a later red gate left the earlier 'passed with the network taken away' in the confirmer's prompt."""
    plan = new_plan(offline_fact="The tests passed with the network taken away.")
    out = probegate.clean_gate_output(sec(0, "go.mod:5: usage: require module/path v1.2.3", 1), deliver(plan, sec(0, "go.mod:5: usage: require module/path v1.2.3", 1)))
    assert "go.mod:5" in out and plan.offline_fact == ""
