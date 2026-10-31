"""Composed gate histories through the real public readers: clean_gate_results / check_evidence_messages over multi-turn conversations built from real paged transports
(complete, lost page, continued after the final page, older beside newer), and ingest_transport over every page a harness can mangle, with the producer's declared extents,
sections and write marks read as data."""
import base64
import json

import pytest

from cria import completionmarks, probegate
from test_gates_completion_staleness import notes, write
from gates_completion_helpers import coder_call, deliver, gate_turn, gates_completion_view, new_plan, page, sec  # noqa: F401  (autouse fixture)

T1, T2, T3 = "1" * 24, "2" * 24, "3" * 24
FAIL = sec(0, "x" * 70 + "\nsrc/a.py:9: boom", 1) + sec(1, "3 passed")
USER = {"role": "user", "content": "go"}
B64 = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731


def shape(messages):
    return [m["role"] + (":" + ",".join(c["id"] for c in m["tool_calls"]) if m.get("tool_calls") else "") + (":" + m["tool_call_id"] if m.get("tool_call_id") else "")
            for m in messages]


def result_text(messages, call_id):
    return next(m["content"] for m in messages if m.get("tool_call_id") == call_id)


def pages(tid, raw, call_ids, size=40):
    """One gate paged over several harness turns, one call per page."""
    out = []
    for n, call_id in enumerate(call_ids):
        last = n == len(call_ids) - 1
        out += gate_turn(call_id, raw, tid, offset=n * size, size=None if last else size)
    return out


HISTORIES = [  # (what happened, history, shape of the cleaned history, the call whose result is checked, what that result says, what it must NOT say)
    ("one paged gate is one piece of evidence on its first seat", [USER, *pages(T1, FAIL, ["a1", "a2", "a3"])], ["user", "assistant:a1", "tool:a1"],
     "a1", ["src/a.py:9: boom"], ["offset", "sha256", probegate.TRANSPORT_PREFIX]),
    ("an older verified gate stays whole beside the newer one", [USER, *gate_turn("o", FAIL, T1), *gate_turn("n", sec(0, "ok"), T2)],
     ["user", "assistant:o", "tool:o", "assistant:n", "tool:n"], "o", ["src/a.py:9: boom"], ["UNKNOWN"]),
    ("an older gate whose pages were lost is SILENT beside a newer verified one (no stale UNKNOWN contradicting it)",
     [USER, *gate_turn("o", FAIL, T1, offset=0, size=40), *gate_turn("n", FAIL, T2)], ["user", "assistant:n", "tool:n"], "n", ["src/a.py:9: boom"], ["UNKNOWN"]),
    ("the newest gate with a lost page is UNKNOWN, never green", [USER, *gate_turn("o", FAIL, T1, offset=0, size=40)], ["user", "assistant:o", "tool:o"],
     "o", ["UNKNOWN"], ["3 passed", "no error-class problems"]),
    ("a page arriving after the transport's final page makes it UNKNOWN", [USER, *pages(T1, FAIL, ["a1"], size=10**6), *gate_turn("a2", FAIL, T1)],
     ["user", "assistant:a1", "tool:a1"], "a1", ["UNKNOWN"], ["3 passed"]),
    ("a check that could not run (exit 127) carries no signal: result AND its call are dropped", [USER, *gate_turn("a1", sec(0, "sh: pytest: not found", 127), T1)],
     ["user"], None, [], []),
    ("repeats of one stamped finding keep only the latest full copy",
     [USER, *gate_turn("a1", sec(0, "x.py:9: boom\n3 failed in 0.36s", 1), T1), *gate_turn("a2", sec(0, "other.py:1: bad", 1), T2),
      *gate_turn("a3", sec(0, "x.py:9: boom\n3 failed in 0.28s", 1), T3)], ["user", "assistant:a1", "tool:a1", "assistant:a2", "tool:a2", "assistant:a3", "tool:a3"],
     "a1", [probegate.CHECKS_REPEAT_NOTE], ["boom"]),
]


@pytest.mark.parametrize("what,history,expected,call_id,says,never", HISTORIES, ids=[h[0][:40] for h in HISTORIES])
def test_a_gate_history_reads_as_one_truthful_piece_of_evidence_per_check(what, history, expected, call_id, says, never):
    """Every shape a real session produced: per-page turns collapse onto the first seat, verified older evidence survives, a lost page is silent beside a newer verified gate
    and UNKNOWN when it is the newest, and a no-signal check vanishes with its call (no orphan tool message). Stamped repeats collapse; the output is idempotent."""
    cleaned = probegate.clean_gate_results(history, linked_only=True)
    assert shape(cleaned) == expected, what
    if call_id:
        text = result_text(cleaned, call_id)
        assert all(s in text for s in says) and not any(s in text for s in never)
    assert probegate.clean_gate_results(cleaned, linked_only=True) == cleaned


def test_a_repeat_collapse_keeps_the_latest_copy_whole_and_leaves_other_findings_alone():
    """Of three stamped results, the first and third are the same finding (volatile time differs): only the earlier loses its text; the different finding and the latest keep every line."""
    history = HISTORIES[-1][1]
    cleaned = probegate.clean_gate_results(history, linked_only=True)
    assert "other.py:1: bad" in result_text(cleaned, "a2") and "x.py:9: boom" in result_text(cleaned, "a3") and "boom" not in result_text(cleaned, "a1")
    assert "boom" in result_text(probegate.clean_gate_results(history), "a1")            # without provenance linking nothing is collapsed


def test_an_unframed_raw_gate_result_claims_nothing_and_a_refused_private_script_is_dropped_on_request():
    """Pre-transport (unframed) results have no declared boundary, so they stay VISIBLE byte for byte, no-signal or not; the call cria composed whole is still removed from the coder's
    history (it never made it); a private bootstrap the harness REFUSED (no markers at all) is removed with `drop_private_results` and otherwise left for the reader to see."""
    sentinel = lambda *probes: probegate._gate_sentinel(list(probes)) + "\nscript"                  # noqa: E731
    raw_none = [USER, *coder_call("g", sentinel("pytest -q"), sec(0, "", 127))]
    kept = probegate.clean_gate_results(raw_none, linked_only=True)
    assert shape(kept) == ["user", "assistant:g", "tool:g"] and kept[2] == raw_none[2] and json.loads(kept[1]["tool_calls"][0]["function"]["arguments"]) == {"cmd": "pytest -q"}
    whole = probegate.clean_gate_results([USER, *coder_call("g", sentinel(""), FAIL)], linked_only=True)
    assert shape(whole) == ["user", "tool:g"] and whole[1]["content"] == FAIL
    refused = [USER, *coder_call("g", sentinel(""), 'Rejected("rm -f style commands are not permitted")')]
    assert shape(probegate.clean_gate_results(refused, drop_private_results=True)) == ["user"]
    assert shape(probegate.clean_gate_results(refused)) == ["user", "tool:g"]


def test_check_evidence_keeps_who_requested_a_check_through_list_commands_and_mixed_turns():
    """A reasoner is shown automatic checks as observations even when the harness spells the command as an argv list, when the assistant turn also spoke, and when it also made a
    call of its own; unreadable arguments and non-message entries are never mistaken for a gate."""
    stamp = probegate._gate_sentinel(["mvn -q test"])
    gate_call = {"id": "auto", "type": "function", "function": {"name": "shell", "arguments": json.dumps({"command": ["bash", "-lc", stamp, "mvn -q test"]})}}
    own_call = {"id": "own", "type": "function", "function": {"name": "shell", "arguments": json.dumps({"cmd": "ls"})}}
    broken = {"id": "bad", "type": "function", "function": {"name": "shell", "arguments": "{not json"}}
    listed = {"id": "arr", "type": "function", "function": {"name": "shell", "arguments": json.dumps(["not", "a", "dict"])}}
    history = [USER, {"role": "assistant", "content": "checking", "tool_calls": [gate_call, own_call, broken, listed]},
               {"role": "tool", "tool_call_id": "auto", "content": page(new_plan(T1), sec(0, "A.java:3: boom", 1))},
               {"role": "tool", "tool_call_id": "own", "content": "files"}]
    assert probegate.gate_call_ids([*history[:1], "stray", None, *history[1:]]) == {"auto"}
    cleaned = probegate.check_evidence_messages(history)
    assert [m["role"] for m in cleaned] == ["user", "assistant", "observation", "assistant", "assistant", "assistant", "observation", "tool"]
    assert cleaned[2]["content"].startswith("Automatic check requested") and "mvn -q test" in cleaned[2]["content"] and "bash" not in cleaned[2]["content"].replace("mvn", "")
    assert "A.java:3: boom" in cleaned[-2]["content"] and cleaned[-1]["content"] == "files" and cleaned[1]["tool_calls"] == []


@pytest.mark.parametrize("mangle,reason", [
    (lambda p: p.replace("sha256\t", "sha256\t0\nsha256\t"), "malformed or duplicate fields"),
    (lambda p: p.replace("\nsha256\t", "\nno-tab-here\nsha256\t"), "malformed or duplicate fields"),
    (lambda p: page(new_plan(), FAIL, data=B64("z" * (probegate.TRANSPORT_CHUNK_BYTES + 1))), "undecodable fields"),
    (lambda p: page(new_plan(), FAIL, data=B64("not a zlib stream"), enc="zlib"), "undecodable fields"),
    (lambda p: page(new_plan(), FAIL, path=B64("/tmp/.cria-gate-" + "a" * 24 + ".x\nevil")), "path or hash is invalid"),
    (lambda p: page(new_plan(), FAIL, sha256="NOT-HEX"), "path or hash is invalid"),
    (lambda p: page(new_plan(), FAIL, total="-1"), "inconsistent"),
], ids=["duplicate-field", "no-tab", "oversize-payload", "bad-zlib", "newline-in-path", "non-hex-digest", "negative-total"])
def test_every_mangled_page_is_terminal_unknown_with_its_own_reason_and_no_bytes_kept(mangle, reason):
    """The reason names what was wrong with the page, no byte of it becomes evidence, and a later perfect page cannot revive the plan."""
    plan = new_plan()
    assert probegate.ingest_transport(plan, mangle(page(plan, FAIL))) == "unknown"
    assert reason in plan.transport_error and not plan.transport_data and not plan.transport_complete
    assert probegate.ingest_transport(plan, page(plan, FAIL)) == "unknown"


def test_the_readers_typed_envelopes_and_a_foreign_hash_are_classified_not_trusted():
    """`error` carries the harness's own words (last line kept as reported; unreadable base64 is still a failure), a `running` envelope's path is validated like a page's, a raw
    marker page from before the transport is legacy, and a hash that changes between pages is UNKNOWN."""
    env = lambda plan, *fields: "\n".join([probegate._transport_marker(plan.transport_id), *fields, probegate._transport_marker(plan.transport_id, end=True)])  # noqa: E731
    plan = new_plan()
    assert probegate.ingest_transport(plan, env(plan, "error\t" + B64("Traceback...\nOSError: spool vanished\n"))) == "unknown"
    assert plan.transport_reported == "OSError: spool vanished" and "OSError: spool vanished" in plan.transport_error
    broken = new_plan()
    assert probegate.ingest_transport(broken, env(broken, "error\t!!!not-base64")) == "unknown"
    assert broken.transport_error == "harness-side page reader failed" and broken.transport_reported == ""
    for path in ("!!!", B64("/tmp/a\nb")):
        bad = new_plan()
        assert probegate.ingest_transport(bad, env(bad, "path\t" + path, "running\t1.0")) == "unknown"
        assert "undecodable" in bad.transport_error or "invalid" in bad.transport_error
    legacy = new_plan()
    assert probegate.ingest_transport(legacy, FAIL) == "legacy" and legacy.transport_error == ""
    plan = new_plan()
    assert probegate.ingest_transport(plan, page(plan, FAIL, 0, 40)) == "pending"
    assert probegate.ingest_transport(plan, page(plan, FAIL, 40, sha256="f" * 64)) == "unknown" and "hash changed" in plan.transport_error


def declared(**fields):
    return B64(json.dumps(fields))


GOOD_MARK = "ab" * 8
SECTIONS_OK = {"probe-0": 0, "probe-1": 12}
EXTENTS = len(FAIL.encode())


@pytest.mark.parametrize("bounds,expected", [
    (declared(checker_end=10, report_end=20, total=EXTENTS, sections=SECTIONS_OK, marks={}), ((10, 20), SECTIONS_OK, {})),
    ("!!!not-base64", (None, None, None)),
    (B64("[1, 2]"), (None, None, None)),
    (declared(marks={}), (None, None, {})),                                                               # extents and sections absent: only what is declared is known
    (declared(checker_end=10, report_end=20, total=5, sections=SECTIONS_OK), (None, SECTIONS_OK, None)),    # a total that is not this spool's
    (declared(checker_end=True, report_end=20, total=EXTENTS), (None, None, None)),
    (declared(checker_end=30, report_end=20, total=EXTENTS), (None, None, None)),
    (declared(checker_end=1, report_end=2, total=EXTENTS, sections={"probe-0": 0, "probe-1": -1}), ((1, 2), {"probe-0": 0}, None)),   # -1: a name declared twice
    (declared(checker_end=1, report_end=2, total=EXTENTS, sections={"probe-0": "0"}), ((1, 2), None, None)),
    (declared(marks={GOOD_MARK: ["landed", "c" * 64, 1], "cd" * 8: ["did_not_run", "", 0]}), (None, None, {GOOD_MARK: ("landed", "c" * 64, 1), "cd" * 8: ("did_not_run", "", 0)})),
    (declared(marks={GOOD_MARK: ["landed", "", 1]}), (None, None, None)),                                  # landed needs the digest
    (declared(marks={GOOD_MARK: ["uncertain", "c" * 64, 1]}), (None, None, None)),                          # a non-landed state carries none
    (declared(marks={"short": ["landed", "c" * 64, 1]}), (None, None, None)),
    (declared(marks={GOOD_MARK: ["landed", "c" * 64, 2]}), (None, None, None)),
    (declared(marks={GOOD_MARK: ["exploded", "", 0]}), (None, None, None)),
    (declared(marks={f"{i:016x}": ["incomplete", "", 0] for i in range(completionmarks.MAX_OUTSTANDING + 1)}), (None, None, None)),
], ids=["all-declared", "garbage", "not-an-object", "marks-only", "foreign-total", "bool-extent", "inverted-extents", "duplicate-section", "string-offset", "marks-ok",
        "landed-no-digest", "digest-on-uncertain", "short-receipt", "bad-flag", "bad-state", "too-many-marks"])
def test_the_producers_declared_extents_sections_and_marks_are_read_as_data_or_not_at_all(bounds, expected):
    """A page's `bounds` field is the producer's declaration: each part is accepted only when self-consistent with the spool, else it is None (never inferred or searched for)."""
    plan = new_plan()
    assert probegate.ingest_transport(plan, page(plan, FAIL, bounds=bounds)) == "complete"
    assert (plan.transport_bounds, plan.transport_sections, plan.transport_marks) == expected
    if expected[0] is None:
        assert probegate.transported_parts(plan) is None
    else:
        assert "".join(probegate.transported_parts(plan)) == FAIL


def test_unsettled_writes_are_those_the_gate_could_not_establish_as_landed_before_its_checks():
    """A watched write is settled only by a mark that was final BEFORE the checks started (or a witnessed did_not_run): no declaration, an incomplete one and a late one stay open."""
    marks = {"a" * 16: "a.py", "b" * 16: "b.py", "c" * 16: "c.py", "d" * 16: "d.py", "e" * 16: "e.py"}
    plan = new_plan(marks_paths=marks)
    assert probegate.unsettled_writes(new_plan()) == [] and [r for r, _, _ in probegate.unsettled_writes(plan)] == list(marks)
    plan.transport_marks = {"a" * 16: ("landed", "f" * 64, 1), "b" * 16: ("landed", "f" * 64, 0), "c" * 16: ("did_not_run", "", 0), "d" * 16: ("incomplete", "", 0)}
    assert probegate.unsettled_writes(plan) == [("b" * 16, "b.py", "landed"), ("d" * 16, "d.py", "incomplete"), ("e" * 16, "e.py", "incomplete")]


UNREADABLE = [  # what follows the newest gate without ever being a workspace change
    [{"role": "assistant", "tool_calls": [{"id": "bad", "type": "function", "function": {"name": "exec_command", "arguments": "{not json"}}]}],
    coder_call("empty", None, name="exec_command", args={}),
    coder_call("web", "rm -rf build && go mod download x/y", name="web_search"),            # a write-shaped string in a tool that is not a shell
    [{"role": "assistant", "tool_calls": [{"id": "bw", "type": "function", "function": {"name": "edit_file", "arguments": "{not json"}}]}, {"role": "tool", "tool_call_id": "bw", "content": "Wrote it"}],
]


@pytest.mark.parametrize("later", UNREADABLE, ids=["bad-json-shell", "empty-shell", "non-shell-tool", "bad-json-edit"])
def test_what_cannot_be_read_as_a_workspace_change_never_makes_a_finding_stale_nor_withdraws_a_rerun_demand(later):
    """A later call with unparseable arguments, no command, or a tool that is not a shell is not evidence the files moved: the newest block keeps asserting its findings as current
    (no `BEFORE` note), and after a REAL landed edit the demand to re-run stays whatever such noise follows."""
    assert "BEFORE" not in notes(*later)
    assert "have not been re-run since" in notes(*write("go.mod"), *later)


def test_an_unframed_raw_gate_result_is_cleaned_through_the_plan_that_declared_its_transport():
    """A raw (un-paged) result in the history is cleaned only through a plan whose completed transport declared its extents: a no-signal one is dropped WITH its call; one whose
    command cria composed whole leaves its findings as a plain user message (nothing for the model to answer)."""
    plan = deliver(new_plan("c" * 24), FAIL)
    sentinel = lambda *probes: probegate._gate_sentinel(list(probes)) + "\nscript"                  # noqa: E731
    silent = probegate.clean_gate_results([USER, *coder_call("g", sentinel("pytest -q"), sec(0, "", 127))], deliver(new_plan("e" * 24), sec(0, "", 127)), linked_only=True)
    assert shape(silent) == ["user"]
    whole = probegate.clean_gate_results([USER, *coder_call("g", sentinel(""), FAIL)], plan, linked_only=True)
    assert shape(whole) == ["user", "user"] and "src/a.py:9: boom" in whole[1]["content"] and probegate.SECTION_PREFIX not in whole[1]["content"]
