"""Scenario: recorded gate streams (per-probe EXIT sentinels, as a harness pages them home) walk through `clean_gate_output`
and come out as the ONE honest state the coder reads: located error-class findings (with counted delimiter facts and the
flagged line quoted from the workspace), a failure with no location, a timeout that names its command, a launch failure that
is no signal, a clean run that says what it covered, or an offline re-run that proves itself only when the counts agree."""
import pytest

from cria import probegate
from cria.probediscovery import ProbeKind as K
from gates_completion_helpers import P, S, cand, clean, gates_completion_view, new_plan, sec  # noqa: F401  (autouse view fixture)

SRC = "x = (1 + 2))\nimport os\n\ndef f(): pass\ndef f(): pass\n"
NO_SIGNAL = "the automatic checks produced no usable result — no signal either way."
OFFLINE = lambda body, code: f"{P}offline{S}\n{body}\nEXIT:{code}\n"          # noqa: E731


@pytest.mark.parametrize("raw,cands,must,mustnt", [
    (sec(0, "sh: pytest: not found", 127), [cand(["pytest"])], [NO_SIGNAL], ["not found"]),
    (f"{P}git{S}\nabc123\n", [], [NO_SIGNAL], []),                                             # a git-only gate ran NO check
    (f"{P}probe-0{S}\nhello\n", [cand(["pytest"])], ["a check did not finish (timed out)", "printed this before it was stopped:\nhello"], []),
    (sec(0, "collecting...", 124), [cand(["pytest", "-q"])], ["`pytest -q` did not finish (timed out)", "collecting..."], []),
    (sec(0, "", 124), [cand(["pytest", "-q"])], ["`pytest -q` did not finish (timed out) — no verdict either way."], ["printed this"]),
    (sec(0, "", 1), [cand(["pytest"])], ["FAILED but printed no parseable location"], []),
    (sec(0, "a.py:1:1: F401 'os' imported but unused", 1), [cand(["pytest"], K.Test)], ["FAILED but printed no parseable location"], []),   # a test exit is hard
    (sec(0, "a.py:1:1: F401 'os' imported but unused", 1), [cand(["ruff"], K.Lint)],
     ["[1 advisory line(s) from this check are not shown"], ["FAILED", "F401"]),                  # a lint exit is advisory
    (sec(0, "a.py:3: error: boom\na.py:3: error: boom", 1) + sec(1, "", 124), [cand(["mypy"], K.BuildCheck), cand(["pytest"], K.Test)],
     ["Native checker diagnostics:\na.py:3: error: boom\n`pytest` did not finish"], ["boom\na.py:3: error: boom"]),      # a consecutive repeat collapses
    (sec(0, "no tests ran in 0.01s", 5), [cand(["pytest"], K.Test)], ["pytest — exit 5\nno tests ran in 0.01s"], ["FAILED"]),
], ids=["launch-failure", "git-only", "no-exit-sentinel", "timeout-with-output", "timeout-silent", "failed-no-detail", "hard-kind-advisory-only",
        "lint-advisory-only", "findings-plus-timeout", "zero-tests"])
def test_each_gate_stream_reads_as_one_honest_state(raw, cands, must, mustnt):
    out = clean(raw, new_plan(candidates=cands))
    assert out.startswith("⟦ctx:checks⟧")
    for text in must:
        assert text in out
    for text in mustnt:
        assert text not in out


def test_staleness_is_stated_for_findings_and_a_clean_run_says_what_it_covered(tmp_path):
    findings = sec(0, "a.py:3: error: boom", 1)
    plan = lambda: new_plan(candidates=[cand(["mypy"], K.BuildCheck)])      # noqa: E731
    changed = frozenset({"a.py"})
    stale, rerun = clean(findings, plan(), changed_paths=changed), clean(findings, plan(), changed_paths=changed, checks_reran=True)
    assert "`a.py`" in stale and "`a.py`" in rerun
    assert clean(findings, plan(), changed_paths=changed) != clean(findings, plan(), changed_paths=changed, checks_reran=True)
    assert clean(findings, plan(), a_command_ran_since=True) != clean(findings, plan())
    cands = [cand(["mypy"], K.BuildCheck), cand(["ruff"], K.Lint), cand(["python3", "-m", "compileall", "."], K.SyntaxCheck)]
    p = new_plan(candidates=cands, untested=["No test files were found."], ran_in="sub")
    out = clean(sec(0, "ok") + sec(1, "fine") + sec(2, "compiled"), p)
    assert "mypy — exit 0\nok" in out and "cover syntax, lint and build only — no test command was composed" in out
    assert "had to be run inside `sub`" in out and out.split("\nThese checks use the original workspace")[0].rstrip().endswith("No test files were found.")


def test_a_diagnostic_is_followed_by_counted_facts_and_the_flagged_line_read_from_the_workspace(tmp_path):
    (tmp_path / "a.py").write_text(SRC)
    raw = sec(0, f"{tmp_path}/a.py:1:12: error: unmatched ')'\n  continues\n{tmp_path}/a.py:4:1: error: undefined name\n"
                 f"{tmp_path}/a.py:5:1: ValueError: x\n{tmp_path}/a.py:9:1: error: past the end\n/etc/hosts:1:1: error: outside\n", 1)
    out = clean(raw, new_plan(candidates=[cand(["mypy"], K.BuildCheck)], workspace=str(tmp_path)))
    assert ("unmatched ')'\n  continues\n  counted fact: line 1 on disk is `x = (1 + 2))` — it contains 1 '(' and 2 ')'.\n") in out
    assert "undefined name\n  the flagged line on disk — line 4: `def f(): pass`" in out
    assert "ValueError: x\n  the flagged line" not in out and "past the end\n  the flagged" not in out and "outside\n  the flagged" not in out
    quiet = clean(raw, new_plan(candidates=[cand(["mypy"], K.BuildCheck)], workspace=str(tmp_path)), annotate=False)
    assert "counted fact" in quiet and "the flagged line on disk" not in quiet
    moved = clean(raw, new_plan(candidates=[cand(["mypy"], K.BuildCheck)], workspace=str(tmp_path)), changed_paths=frozenset({"a.py"}))
    assert "the flagged line on disk" not in moved
    (tmp_path / "b.py").write_text("x = (1 + 2)\n")
    balanced = clean(sec(0, f"{tmp_path}/b.py:1:5: error: unmatched ')'", 1), new_plan(candidates=[cand(["mypy"], K.BuildCheck)], workspace=str(tmp_path)))
    assert "counted fact" not in balanced


def test_an_f811_shadow_of_a_def_is_a_real_finding_but_an_import_rebinding_is_advisory(tmp_path):
    (tmp_path / "a.py").write_text(SRC)
    raw = sec(0, "a.py:5:1: F811 redefinition of unused 'f' from line 4\na.py:2:8: F811 redefinition of unused 'os' from line 1", 1)
    out = clean(raw, new_plan(candidates=[cand(["pyflakes"], K.Lint)], workspace=str(tmp_path)))
    assert "a.py:5:1: F811 redefinition of unused 'f'" in out and "a.py:2:8" not in out and "[1 advisory line(s)" in out


@pytest.mark.parametrize("online,offline,sentence", [
    ("3 passed in 0.1s", "3 passed in 0.1s", "The same tests (0f/3p) pass with the network switched off"),
    ("3 passed in 0.1s", "3 passed, 1 skipped in 0.1s", None),                    # same tally but a test stepped aside: no claim
    ("ok", "ok", "only that none of them failed"),                                 # uncounted: only what the exit code showed
    ("ok", "ok (1 skipped)", None),
], ids=["equal-counts", "skipped-offline", "uncounted", "uncounted-skip"])
def test_the_offline_rerun_claims_only_what_both_readings_establish(online, offline, sentence):
    plan = new_plan(candidates=[cand(["pytest"], K.Test)])
    out = clean(sec(0, online) + OFFLINE(offline, 0), plan)
    assert (sentence in out and sentence in plan.offline_fact) if sentence else (plan.offline_fact == "" and "network" not in out)
    failing = new_plan(candidates=[cand(["pytest"], K.Test)])
    clean(sec(0, online) + OFFLINE("boom", 1), failing)
    assert failing.offline_fact == ""
    assert probegate._offline_fact({"offline": offline}, plan) == "" and probegate._offline_fact({"offline": "x", "probe-0": "y\nEXIT:0"}, None) == ""
