"""The completion gate's page transport survives a login shell that prints around every page (mise, direnv, a noisy profile).

Real gate script, real `bash -lc` on a real PTY, the pinned Codex's head/tail cut (`chatty_shell`). Before the fix a page cut in the
middle ended the transport terminally UNKNOWN: with 3 KB of noise the very first page was cut, so the gate never read and was composed
again (and cut again) until the run's wall clock ran out.
"""
import subprocess
import sys

import pytest
from chatty_shell import chatty_pty, codex_result
from gates_completion_helpers import harness_dir  # noqa: F401  (also provides the autouse view fixture)
from gates_completion_helpers import gates_completion_view  # noqa: F401

from cria import probegate, proberun
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind

CHECKER = ("import hashlib,sys\nfor i in range(900): print('noise-%04d-'%i+hashlib.sha256(str(i).encode()).hexdigest())\n"
           "print('src/middle.py:73: MIDDLE_FAILURE'); print('FINAL_TALLY: 1 failed'); sys.exit(1)")


def gate_through_noise(tmp_path, monkeypatch, before, after):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "source.txt").write_text("source\n")
    candidate = ProbeCandidate(ProbeKind.BuildCheck, [sys.executable, "-c", CHECKER], tmp_path, 100, 100,
                               ProbeCost.Cheap, False, False, False, "fixture", composed_by_cria=True)
    monkeypatch.setattr(proberun, "select_completion_probes", lambda root: [candidate])
    plan = probegate.plan_gate(str(tmp_path))
    command, results, plan.stalled = plan.script, [], 0
    while len(results) < 60:
        raw, code = chatty_pty(command, str(tmp_path), before, after=after, env={"TMPDIR": str(harness_dir(tmp_path))})
        results.append(codex_result(raw, code))
        had = len(plan.transport_data)
        outcome = probegate.interpret_gate(plan, results[-1])
        plan.stalled += outcome.transport_pending and len(plan.transport_data) == had     # a result that moved the read nowhere
        if not outcome.transport_pending:
            return plan, outcome, results
        command = probegate.continue_transport_command(plan)
    raise AssertionError("the transport never ended")


@pytest.mark.parametrize("before,after", [(0, 0), (1000, 0), (7000, 0), (12000, 0), (3000, 3000), (0, 7000), (1000, 12000)])
def test_every_byte_of_the_gate_arrives_verified_whatever_the_shell_prints_around_the_pages(tmp_path, monkeypatch, before, after):
    plan, outcome, results = gate_through_noise(tmp_path, monkeypatch, before, after)
    assert outcome.ran and not outcome.transport_unknown, plan.transport_error
    full = probegate.transported_result(plan)
    assert "noise-0000" in full and "MIDDLE_FAILURE" in full and "FINAL_TALLY" in full and len(full.encode()) == plan.transport_total
    assert any("middle.py" in f.file for f in outcome.report.results[0].findings)
    assert plan.stalled <= 1              # at most the first (unmeasured) page is wasted: later pages are sized to the measured noise
    if before + after >= 3000:
        assert len(results) > 7           # the pages really were narrowed beside the noise (7 pages when the shell is quiet)


def test_noise_on_both_sides_that_leaves_no_page_a_place_in_the_result_is_unknown_never_a_clean_gate(tmp_path, monkeypatch):
    """7 KB before AND 7 KB after: the harness keeps 5 KB of each end, so no page of any size survives. After the three narrower
    probes the transport is terminally UNKNOWN (the checker was never read), not clean."""
    plan, outcome, results = gate_through_noise(tmp_path, monkeypatch, 7000, 7000)
    assert outcome.transport_unknown and not outcome.ran and len(results) == 1 + len(probegate.TRANSPORT_REFETCH_BUDGETS)
    assert "does not fit beside what the shell prints" in plan.transport_error and not plan.transport_complete
