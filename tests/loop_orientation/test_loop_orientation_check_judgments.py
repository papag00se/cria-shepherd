"""A failed declared runner / Go test gets ONE definitive judgment per distinct facts; unknown answers never settle it
and an unknown workspace fact is stated as unknown."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from cria import modulestate as ms, probediscovery as pd, proberun, runnercontract as rc
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401

def failed(eco, command, *, declared=False, code=1):
    cand = pd.ProbeCandidate(pd.ProbeKind.Test, command.split(), Path("."), 90, 90, pd.ProbeCost.Moderate, False, False,
                             False, "fixture", ecosystem=eco, declared_interface=declared)
    return SimpleNamespace(report=proberun.ProbeReport([], [cand], [SimpleNamespace(command=command, exit_code=code)]))

class Judge:
    """Drives either policy through its real entry point with a scripted closed-question answer."""
    def __init__(self, kind):
        self.kind, self.state, self.asked, self.log = kind, (rc.RunnerState() if kind == "runner" else ms.ModuleState()), [], Log()
        self.outcome = (failed(pd.Ecosystem.JsTs, "npm test", declared=True) if kind == "runner"
                        else failed(pd.Ecosystem.Go, "go test ./..."))

    def __call__(self, answer, checks="checker bytes", outcome=None, node_modules=None):
        def ask(question, **_):
            self.asked.append(question)
            if isinstance(answer, Exception):
                raise answer
            return answer
        outcome = outcome or self.outcome
        if self.kind == "runner":
            return rc.judge_runner_contract(rc.RunnerInput(outcome, lambda: checks, lambda: node_modules,
                                                           lambda: ("the task", "session"), ask, self.log), self.state)
        return ms.judge_module_state(ms.ModuleInput(outcome, lambda: checks, lambda: ("the task", "session"),
                                                    ask, self.log), self.state)

def label(result):
    return (getattr(result, "status", None) or result.judgment).value

@pytest.mark.parametrize("kind,reset,silent", [("runner", "RESET", "ON_TRACK"), ("module", "REANCHOR", "ON_TRACK")])
def test_one_judgment_per_distinct_failure_facts_and_unreadable_answers_never_settle(kind, reset, silent):
    judge = Judge(kind)
    for unreadable in ("?", "", RuntimeError("provider down")):
        try:
            assert label(judge(unreadable)) == "withheld"
        except RuntimeError:
            assert isinstance(unreadable, RuntimeError)                       # a failing provider settles nothing either
    assert len(judge.asked) == 3 and not judge.state.signature            # nothing was remembered: it is asked again
    verdict = judge(reset)
    assert (verdict.steer or "").strip() and "checker bytes" in verdict.steer      # the guidance carries the exact checks
    n = len(judge.asked)
    assert judge(reset).steer is None and len(judge.asked) == n                 # identical facts: remembered, not re-asked
    judge(silent, checks="different checker bytes")
    assert len(judge.asked) == n + 1                                            # changed facts re-judge
    for code in (0, None):                                                      # green, or no exit status at all
        ok = failed(pd.Ecosystem.JsTs if kind == "runner" else pd.Ecosystem.Go, "x", declared=True, code=code)
        assert label(judge(reset, outcome=ok)) == "not-applicable" and len(judge.asked) == n + 1   # nothing failed: no question

def test_an_unknown_node_modules_is_stated_as_unknown_never_as_absent():
    for present, words in ((True, "is present"), (False, "is absent"), (None, "is not known")):
        judge = Judge("runner")
        judge("ON_TRACK", node_modules=present)
        assert words in judge.asked[0]
