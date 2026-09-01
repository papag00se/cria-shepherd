"""`checks_are_stale` said "have not been re-run since — re-run them" to a coder who had just re-run.

Walked on cart-billing-go x nemotron-elastic 1788230301 (chunk10): last go.mod edit, then the
coder's own `go vet ./... && go build ./...`, then the re-shown gate block carrying "These checks
ran BEFORE your edit to `go.mod` and have not been re-run since … re-run them before concluding
your edit did not work" — over lines identical to that fresh run's output. A false fact (#5b) whose
instruction is the action it answers: obey → re-run → same label → a churn loop.

The re-run is recognised against the PLAN'S OWN discovered argv (never a command vocabulary, #20),
and when cria cannot tell, the existing sentence stands — today's behaviour, fail toward the known
state (#13). The sibling fix that made the note render at all (`go mod download` invisible to the
file ledger) is untouched: a command that writes still counts as a CHANGE, never as a re-run.
"""
import json
import tempfile
import unittest

from cria import probegate
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind


def cand(argv):
    return ProbeCandidate(kind=ProbeKind.BuildCheck, command=argv,
                          working_dir=tempfile.gettempdir(), confidence=90, expected_value=90,
                          cost=ProbeCost.Moderate, mutates_code=False, may_hang=False,
                          may_need_services=False, reason="t")


def plan(*argvs):
    return probegate.GatePlan(workspace=tempfile.gettempdir(), candidates=[cand(a) for a in argvs])


def shell(cmd):
    return {"role": "assistant", "tool_calls": [{"id": "s", "function": {
        "name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]}


def edit(path):
    return {"role": "assistant", "tool_calls": [{"id": "e", "function": {
        "name": "edit_file", "arguments": json.dumps(
            {"path": path, "old_string": "a", "new_string": "b"})}}]}


GATE = {"role": "tool", "content": "gate"}
P = plan(["go", "build", "./..."], ["go", "vet", "./..."])


class TheRerunIsRecognisedTests(unittest.TestCase):
    def test_probe_rerun_after_the_edit_is_seen(self):
        msgs = [GATE, edit("go.mod"), shell("go vet ./... && go build ./...")]
        self.assertTrue(probegate._probe_reran_after_last_change(msgs, 0, P))

    def test_a_probe_run_BEFORE_the_edit_is_not_a_rerun(self):
        msgs = [GATE, shell("go build ./..."), edit("go.mod")]
        self.assertFalse(probegate._probe_reran_after_last_change(msgs, 0, P))

    def test_a_command_that_also_writes_is_a_change_not_a_rerun(self):
        """`go build ./... && go mod download x` may not reflect its own change — the note stays."""
        msgs = [GATE, edit("go.mod"), shell("go build ./... && go mod download github.com/x/y")]
        self.assertFalse(probegate._probe_reran_after_last_change(msgs, 0, P))

    def test_no_plan_means_cria_cannot_tell_and_says_the_old_thing(self):
        msgs = [GATE, edit("go.mod"), shell("go build ./...")]
        self.assertFalse(probegate._probe_reran_after_last_change(msgs, 0, None))

    def test_an_unrelated_command_is_not_a_rerun(self):
        msgs = [GATE, edit("go.mod"), shell("ls -la && cat go.mod")]
        self.assertFalse(probegate._probe_reran_after_last_change(msgs, 0, P))


RAW_RED = "___CRIA_GATE_probe-0___\ncart.go:8:2: no required module provides package github.com/x/y\nEXIT:1\n"


class TheSentenceMatchesTheWorldTests(unittest.TestCase):
    def _out(self, reran):
        return probegate.clean_gate_output(RAW_RED, plan(["go", "build", "./..."]),
                                           changed_paths=frozenset({"go.mod"}),
                                           checks_reran=reran)

    def test_after_a_rerun_the_note_stops_demanding_one(self):
        out = self._out(True)
        self.assertNotIn("have not been re-run since", out)
        self.assertIn("re-run checks yourself since", out)
        self.assertIn("`go.mod`", out)

    def test_without_a_rerun_the_original_note_stands(self):
        out = self._out(False)
        self.assertIn("have not been re-run since", out)
        self.assertNotIn("re-run checks yourself since", out)


if __name__ == "__main__":
    unittest.main()
