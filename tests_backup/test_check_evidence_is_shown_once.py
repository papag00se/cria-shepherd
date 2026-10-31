"""G1 — the SAME checker evidence reaches the model ONCE per body.

Incident: phi4 / feed-pipeline-java A2 (capture 20261010T230133-01a1298d-…), coder call 0042: nine
messages, est_total 15,439 tokens of a 16,384 window, and the line
`package org.apache.commons.csv does not exist` 24 times in the one body — the gate's findings
rendered by three owners that never see each other (the compaction continuation that froze them, the
`⟦ctx:checks⟧` result carrying maven's raw output, and the trailing `⟦ctx:steer⟧`), plus maven's own
repeats inside the result. Near-full windows are what made Codex compact every cycle; the coder never
reached pom.xml.

The fixtures are the exact messages of calls 0042 / 0043 (system prompt kept separately).
"""
import json
from pathlib import Path

from cria import contextfloor, dedup, loop, modelview, probegate, prompts

FIX = Path(__file__).parent / "fixtures" / "phi4_java_a2"
DIAG = "package org.apache.commons.csv does not exist"
NOTE = prompts.load("repeated_message_note").strip()


def _fx(n):
    return json.loads((FIX / f"{n}-coder-s1.messages.json").read_text())


def _text(msgs):
    return "\n".join(str(m.get("content") or "") for m in msgs)


def _units(msgs):
    out = set()
    for m in msgs:
        if m.get("role") in ("user", "tool") and isinstance(m.get("content"), str):
            out.update(u.rstrip() for u in dedup._units(m["content"]))
    return out


def test_the_incident_body_carried_the_diagnostic_many_times_and_now_carries_it_a_few():
    fx = _fx("0042")
    before = _text(fx["messages"]).count(DIAG)
    shown = modelview.fold_evidence(fx["messages"])
    after = _text(shown).count(DIAG)
    assert before == 24            # the supervisor-verified figure
    assert after <= 10 and after < before / 2


def test_the_incident_window_shrinks_by_a_fifth():
    fx = _fx("0042")
    before = contextfloor.est_total(fx["messages"], fx["tools"])
    after = modelview.visible_tokens(fx["messages"], fx["tools"], fold=True)
    assert after <= before * 0.82
    # …and the usage the harness is told is the same smaller number the wire carries (#24)
    assert after == contextfloor.est_total(modelview.fold_evidence(modelview.wire_messages(fx["messages"])), fx["tools"])
    # L0-L2 report the unfolded size (no context surgery there)
    assert modelview.visible_tokens(fx["messages"], fx["tools"]) == before


def test_nothing_is_lost_every_distinct_line_still_in_the_body():
    for n in ("0042", "0043"):
        fx = _fx(n)
        shown = modelview.fold_evidence(fx["messages"])
        missing = {u for u in _units(fx["messages"]) if u not in _units(shown)}
        assert missing == set()


def test_the_trailing_steer_is_the_whole_copy_and_the_continuation_points_at_it():
    fx = _fx("0042")
    shown = modelview.fold_evidence(fx["messages"])
    steer = [m for m in shown if str(m.get("content")).startswith("⟦ctx:steer⟧ not done yet")][0]
    orig = [m for m in fx["messages"] if str(m.get("content")).startswith("⟦ctx:steer⟧ not done yet")][0]
    assert "[GROUND TRUTH — the repo's own checks fail]" in steer["content"]
    assert "A test YOU wrote earlier" in steer["content"]       # the newest copy keeps its rule whole
    cont = [m for m in shown if str(m.get("content")).startswith("⟦ctx:continuation⟧")][0]
    assert NOTE in cont["content"]
    assert "Establish current state from it" in cont["content"]  # the continuation's own frame stays
    assert DIAG not in cont["content"]
    assert len(steer["content"]) < len(orig["content"])


def test_the_tool_result_form_of_the_checks_carrier_folds_the_same_way():
    fx = _fx("0043")                                             # the checks result is a `tool` message
    assert any(m["role"] == "tool" for m in fx["messages"])
    shown = modelview.fold_evidence(fx["messages"])
    assert _text(shown).count(DIAG) < _text(fx["messages"]).count(DIAG) / 2
    assert [m["role"] for m in shown] == [m["role"] for m in fx["messages"]]   # roles / pairing intact
    assert [m.get("tool_call_id") for m in shown] == [m.get("tool_call_id") for m in fx["messages"]]


def test_the_task_the_assistant_and_the_system_are_never_rewritten():
    fx = _fx("0042")
    shown = modelview.fold_evidence(fx["messages"])
    for a, b in zip(fx["messages"], shown):
        if not str(a.get("content")).startswith(modelview.EVIDENCE_CARRIERS):
            assert a == b


def test_a_body_with_no_repeated_evidence_is_the_same_list():
    msgs = [{"role": "user", "content": "the task " * 200},
            {"role": "user", "content": "⟦ctx:steer⟧ " + "one failure line that is long enough. " * 3}]
    assert modelview.fold_evidence(msgs) is msgs


def test_a_short_shared_run_is_not_folded():
    """Two failing tests share an assertion line (the 2026-07 nemotron incident, probegate's
    CONSECUTIVE-ONLY comment): a short common run must stay in BOTH blocks."""
    shared = "E   AssertionError: unexpectedly None\n    self.assertIsNotNone(result['x'])\n"
    a = "⟦ctx:checks⟧ test_goose FAILED\n" + shared + "test_goose.py:24: AssertionError\n"
    b = "⟦ctx:steer⟧ test_papagoose FAILED\n" + shared + "test_papagoose.py:31: AssertionError\n"
    msgs = [{"role": "user", "content": a}, {"role": "user", "content": b}]
    out, n = dedup.fold_repeated_runs(msgs, NOTE, prefixes=modelview.EVIDENCE_CARRIERS)
    assert n == 0 and out is msgs


def test_a_run_never_splices_two_messages():
    block = "".join(f"[ERROR] /w/src/Main.java:[{i},3] cannot find symbol number {i}\n" for i in range(30))
    msgs = [{"role": "user", "content": "⟦ctx:checks⟧ first\n" + block},
            {"role": "user", "content": "⟦ctx:steer⟧ tail\n" + block}]
    out, n = dedup.fold_repeated_runs(msgs, NOTE, prefixes=modelview.EVIDENCE_CARRIERS)
    assert n == 1
    assert out[0]["content"].startswith("⟦ctx:checks⟧ first\n" + NOTE)
    assert out[1]["content"] == msgs[1]["content"]                # the newest copy is whole


def test_an_assistant_turn_is_never_folded_into_a_pointer():
    block = "".join(f"[ERROR] /w/src/Main.java:[{i},3] cannot find symbol number {i}\n" for i in range(30))
    msgs = [{"role": "assistant", "content": "⟦ctx:checks⟧ " + block},
            {"role": "user", "content": "⟦ctx:steer⟧ " + block}]
    out, n = dedup.fold_repeated_runs(msgs, NOTE, prefixes=modelview.EVIDENCE_CARRIERS)
    assert n == 0 and out is msgs


def test_the_carrier_prefixes_name_the_markers_their_owners_write():
    assert modelview.EVIDENCE_CARRIERS[0] == loop.CONTINUATION_MARKER
    assert modelview.EVIDENCE_CARRIERS[1] == probegate.CHECKS_MARKER
    assert prompts.load("gate_fail_steer").startswith("not done yet")   # rides under ⟦ctx:steer⟧
