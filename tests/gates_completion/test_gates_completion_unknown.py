"""An UNKNOWN check says why (the harness's own last line), vetoes completion only boundedly, and never sits beside a newer reading."""
import base64

from cria import loop, probegate, prompts, repositorychecks as checks
from gates_completion_helpers import Log, gates_completion_view, gate_turn, new_plan, sec, text_of  # noqa: F401

LAST = "OSError: [Errno 30] Read-only file system: '.gate-private-b52133be8bb213a65ba610ee'"
TRACE = f'Traceback (most recent call last):\n  File "<string>", line 7, in <module>\n{LAST}'
UNKNOWN = prompts.load("probe_transport_unknown").strip()


def error_result(plan, detail=TRACE):
    m = probegate._transport_marker
    return f"Output:\n{m(plan.transport_id)}\nerror\t{base64.b64encode(detail.encode()).decode()}\n{m(plan.transport_id, end=True)}\n"


def completion_check(state, plan, raw, log, read=None):
    """The real completion path: repositorychecks.completion_result over the loop's own readers."""
    state.gate_plan, state.probe_call_id = plan, "probe"
    src = checks.Input({"messages": [{"role": "tool", "tool_call_id": "probe", "content": raw}]}, log, engagement=5)
    ev = checks.EvidenceServices(loop._read_tool_result, read or loop.read_gate, loop.gate_error_text,
                                 lambda findings, messages: loop.track_gate_progress(state, findings, messages))
    return checks.completion_result(src, state, ev)


def test_the_unknown_notice_carries_the_harness_last_line_verbatim_and_cria_adds_none_of_its_own():
    """Codex with TMPDIR unset: the page reader's `error` envelope ended in `OSError ... Read-only file system`; the coder
    saw only the fixed UNKNOWN notice 184 times. The notice now quotes the harness's own last line (selected, not the dump)."""
    plan = new_plan("b52133be8bb213a65ba610ee")
    out = probegate.interpret_gate(plan, error_result(plan))
    text = loop.gate_error_text(out)
    assert out.transport_unknown and out.transport_reported == LAST
    assert text.startswith(UNKNOWN) and LAST in text and "Traceback" not in text
    own = new_plan()          # a failure cria diagnosed itself (a cut page) quotes nothing
    cut = probegate.interpret_gate(own, probegate._transport_marker(own.transport_id) + "\ncut")
    assert cut.transport_reported == "" and loop.gate_error_text(cut) == prompts.load("probe_transport_unknown")


def test_the_same_unknown_vetoes_completion_only_up_to_the_bound_then_stops_and_other_readings_restart_the_count():
    """MAX_COMPLETION_CHECKS identical UNKNOWN notices veto; the next ones are silent (a task the coder cannot finish still
    ends). A non-UNKNOWN reading or a DIFFERENT reported reason restarts the count."""
    state, log, results = loop.GuardState(), Log(), []
    for i in range(loop.MAX_COMPLETION_CHECKS + 3):
        plan = new_plan(f"{i:024x}")                 # a fresh private token every gate, as in the real run
        results.append(completion_check(state, plan, error_result(plan), log))
    held = [r for r in results if r.status is checks.Status.OBSERVED]
    assert len(held) == loop.MAX_COMPLETION_CHECKS and all("Read-only file system" in r.text for r in held)
    assert [r.status for r in results[len(held):]] == [checks.Status.SILENT] * 3
    assert len([e for e in log.events if e[0] == "loop.done_unverified"]) == 3

    other = new_plan("e" * 24)
    res = completion_check(state, other, error_result(other, "PermissionError: [Errno 13] Permission denied"), log)
    assert res.status is checks.Status.OBSERVED and "PermissionError: [Errno 13]" in res.text
    ran_nothing = lambda plan, raw, rlog: probegate.GateOutcome(ran=False)           # noqa: E731
    assert completion_check(state, new_plan("d" * 24), "", log, read=ran_nothing).status is checks.Status.SILENT
    again = new_plan("f" * 24)
    assert completion_check(state, again, error_result(again), log).status is checks.Status.OBSERVED


FAIL = sec(0, "src/Importer.java:9: package org.apache.commons.csv does not exist", 1)


def clean(msgs):
    return text_of(probegate.clean_gate_results(msgs, linked_only=True))


def test_only_the_newest_gates_unknownness_is_stated():
    """phi4 / feed-pipeline-java A2 calls 0031/0037/0043: pages of an OLDER transport were lost to compaction, so it rendered
    UNKNOWN beside the NEXT gate's complete failure. Older unverifiable = silence; a newest unverifiable = still UNKNOWN."""
    lost = dict(total=str(len(FAIL.encode()) + 40))             # declares more bytes than ever arrive
    user = {"role": "user", "content": "fix it"}
    stale = [user, *gate_turn("old", FAIL, "a" * 24, **lost), *gate_turn("new", FAIL, "b" * 24)]
    out = probegate.clean_gate_results(stale, linked_only=True)
    assert UNKNOWN not in text_of(out) and "package org.apache.commons.csv does not exist" in text_of(out)
    calls = {tc["id"] for m in out for tc in m.get("tool_calls") or []}
    assert {m["tool_call_id"] for m in out if m.get("role") == "tool"} <= calls          # the dropped unknown took no orphan
    assert UNKNOWN in clean([user, *gate_turn("only", FAIL, "a" * 24, **lost)])
    assert UNKNOWN in clean([user, *gate_turn("old", FAIL, "a" * 24), *gate_turn("new", FAIL, "b" * 24, **lost)])
