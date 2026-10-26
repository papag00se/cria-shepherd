"""K3 — phi4 A4 CALL 0034: ONE reply carried nine `edit_file` calls to Importer.java; every one failed (the
file stayed byte-identical, 4543 B). cria then (1) answered them `failed to edit this file 1 … 9 times —
STOP editing it` inside a single turn (the escalation clock ran across results the coder had not yet seen),
and (2) counted the nine refused edits as "rewritten at least 5 times" (CALL 0039), starting a supervisor
that diagnosed a file nobody had changed.
"""
import base64
import json
from pathlib import Path

from cria import bodykeys, denial, editrecovery, loop
from cria.loop import GuardState, WHEEL_SPIN_WRITES, guard_track_write_streak


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append(kind)


A4 = json.loads((Path(__file__).parent / "fixtures" / "phi4_java_a4" / "0034-nine-edits-one-turn.json").read_text())["tool_calls"]
JAVA = [t for t in A4 if t["function"]["name"] == "edit_file" and t["function"]["arguments"].count("Importer.java")]
OTHER = {"id": "n1", "type": "function", "function": {"name": "write_file",
                                                      "arguments": json.dumps({"path": "REVIEW.md", "content": "x"})}}


def _completion(tcs):
    return {"choices": [{"message": {"role": "assistant", "tool_calls": tcs}}]}


def _results(tcs, body, outcome=None):
    """The history as `represent_inbound` hands it on: the calls, then their results; ``outcome`` is the
    PROVEN hint (cria's refusal ran / its edit program reported 'not applied'), never the wording."""
    hint = {bodykeys.RESULT_OUTCOME: outcome} if outcome else {}
    return [{"role": "assistant", "tool_calls": list(tcs)}] + [
        {"role": "tool", "tool_call_id": t["id"], "content": body(t), **hint} for t in tcs]


FAIL = lambda t: f"{editrecovery.EDIT_MARK} Importer.java — your old_string is not in the file (likely a stale copy)."
LANDED = lambda t: "Wrote Importer.java"


def test_the_real_batch_is_nine_edits_to_one_file():
    assert len(JAVA) == 9


def test_nine_refused_edits_in_one_turn_never_trip_the_spin_guard():
    gs, log = GuardState(), _Rlog()
    guard_track_write_streak(gs, _completion(JAVA), log, messages=[])
    assert not gs.spin_probe_due and "loop.wheel_spinning" not in log.events      # unknown yet: counted once
    guard_track_write_streak(gs, _completion([OTHER]), log, messages=_results(JAVA, FAIL, denial.UNAPPLIED))
    assert not gs.spin_probe_due and "loop.wheel_spinning" not in log.events
    assert gs.recent_writes.count(loop._write_path(JAVA[0]["function"])) == 0   # taken back


def test_the_same_batch_that_LANDED_trips_it_at_the_next_turn():
    gs, log = GuardState(), _Rlog()
    guard_track_write_streak(gs, _completion(JAVA), log, messages=[])
    assert not gs.spin_probe_due
    guard_track_write_streak(gs, _completion([OTHER]), log, messages=_results(JAVA, LANDED))
    assert gs.spin_probe_due and gs.spin_path.endswith("Importer.java")


def test_cria_own_refusals_are_not_rewrites_either():
    from cria import denial
    gs, log = GuardState(), _Rlog()
    guard_track_write_streak(gs, _completion(JAVA), log, messages=[])
    guard_track_write_streak(gs, _completion([OTHER]), log,
                             messages=_results(JAVA, lambda t: denial.mark("this write was not run"), denial.REFUSED))
    assert not gs.spin_probe_due


def test_one_per_turn_still_trips_on_the_fifth():
    gs, log = GuardState(), _Rlog()
    for i in range(WHEEL_SPIN_WRITES):
        tc = {**JAVA[0], "id": f"s{i}"}
        guard_track_write_streak(gs, _completion([tc]), log, messages=_results([{**JAVA[0], "id": f"s{j}"} for j in range(i)], LANDED))
    assert gs.spin_probe_due


# ── the escalation clock ────────────────────────────────────────────────────────────────────────

def _report(mode="no_anchor"):
    body = json.dumps({"mode": mode, "path": "Importer.java", "current": "package pipeline;\nclass Importer {}\n"})
    return editrecovery.EDITFAIL + base64.b64encode(body.encode()).decode()


def _answer_batch(out, n):
    """What represent_inbound does: results in order, each recovered against the messages before it."""
    out.append({"role": "assistant", "tool_calls": [{"id": f"b{k}"} for k in range(n)]})
    got = []
    for k in range(n):
        text = editrecovery.recover(_report(), out)
        out.append({"role": "tool", "tool_call_id": f"b{k}", "content": text, bodykeys.RESULT_OUTCOME: denial.UNAPPLIED})
        got.append(text)
    return got


def test_one_turn_of_nine_failed_edits_escalates_once_not_nine_times():
    got = _answer_batch([], 9)
    assert sum("STOP editing it." in t for t in got) == 1                 # was 9 (CALL 0036: 'failed … 1…9 times')
    assert "failed to edit this file 1 times" in got[0]                  # blind first touch: unchanged behaviour
    assert all("did not apply either" in t and "nothing from it reached the file" in t for t in got[1:])
    assert not any(f"failed to edit this file {n} times" in t for t in got[1:] for n in range(2, 10))


def test_the_clock_still_runs_across_turns():
    out = []
    for turn in range(3):
        _answer_batch(out, 2)                  # two failures per turn: the first of each is the counted attempt
    last = [m["content"] for m in out if m.get("role") == "tool"]
    assert any("failed to edit this file 3 times" in t for t in last)


def test_a_self_resolving_report_in_the_batch_is_not_swallowed():
    out = [{"role": "assistant", "tool_calls": [{"id": "a"}, {"id": "b"}]}]
    out.append({"role": "tool", "tool_call_id": "a", "content": editrecovery.recover(_report(), out),
                bodykeys.RESULT_OUTCOME: denial.UNAPPLIED})
    text = editrecovery.recover(_report("identical"), out)
    assert "identical" in text and "did not apply either" not in text


def test_the_escalation_event_is_emitted_once_per_batch():
    out, log = [{"role": "assistant", "tool_calls": [{"id": f"b{k}"} for k in range(9)]}], _Rlog()
    for k in range(9):
        out.append({"role": "tool", "tool_call_id": f"b{k}", "content": editrecovery.recover(_report(), out, log),
                    bodykeys.RESULT_OUTCOME: denial.UNAPPLIED})
    assert log.events.count("editrecovery.escalated") == 1
