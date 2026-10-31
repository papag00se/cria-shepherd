"""Repeats folded without destroying evidence: dedup.volatile_key / elide (one authoritative copy of cria's own
ledger) and focustrim.trim (identical call+result folded, refusals folded losslessly, failures never deleted
by wording)."""
import json

import pytest

from cria import bodykeys, dedup, denial, focustrim, toolwire, writeproxy
from cria.probegate import SECTION_PREFIX as GATE


@pytest.mark.parametrize("a,b", [
    ("url = <urllib.request.Request object at 0x7cd31c34ac60>\n3 failed, 1 passed in 0.36s",
     "url = <urllib.request.Request object at 0x740a465deed0>\n3 failed, 1 passed in 0.28s"),
    ("<MagicMock id='125997213614208'>", "<MagicMock id='125997213999999'>"),
    ("java.util.HashMap$KeyIterator@7f31245a", "java.util.HashMap$KeyIterator@14ae5a5"),
    ("ok  \ttick\t0.003s", "ok  \ttick\t0.921s"),
    ("Tests run: 4, Failures: 0, Time elapsed: 0.031 s", "Tests run: 4, Failures: 0, Time elapsed: 0.912 s"),
    ("Chunk ID: 939a6a\nWall time: 0.13 seconds\nOutput:\nhi", "Chunk ID: aaaaaa\nWall time: 9.90 seconds\nOutput:\nhi"),
    ("Run options: --seed 33602\n7 runs, 7 assertions, 0 failures\nFinished in 0.008s, 836.4 runs/s.",
     "Run options: --seed 62\n7 runs, 7 assertions, 0 failures\nFinished in 0.011s, 593.5 runs/s."),
])
def test_two_renderings_of_one_finding_share_a_key(a, b):
    """Object addresses, runner durations and seeds are per-run noise: otherwise four identical green runs sit
    in four groups and the repeat guard never fires (shipping-rates-rb / nemotron-elastic 1787432916)."""
    assert dedup.volatile_key(a) == dedup.volatile_key(b)


@pytest.mark.parametrize("a,b", [
    ("x.py:92: undefined name 'pytest'", "x.py:92: undefined name 'json'"),
    ("x.py:92: boom", "x.py:93: boom"),
    ("1 failed, 3 passed in 0.10s", "2 failed, 2 passed in 0.10s"),
    ("Benchmark complete.\nelapsed: 12.50 s", "Benchmark complete.\nelapsed: 3.10 s"),    # a program's own clock is content
    ("AssertionError: expected 30s", "AssertionError: expected 45s"),
    ("amount=125997213614208", "amount=125997213614209"),
])
def test_two_different_findings_never_share_a_key(a, b):
    """A wrong scrub silently MERGES two answers - truncation with extra steps ('make it 4x faster' printed
    elapsed 12.50 s then 3.10 s and focustrim folded them into one)."""
    assert dedup.volatile_key(a) != dedup.volatile_key(b)
    assert dedup.volatile_key("contact user@abcdef.com") == "contact user@abcdef.com"


FIELDS = ("  GET /handles/{handle} (replace in the URL path: {handle} = The Handle name) -> hex(string), name(string, "
          "e.g. my.handle), handle_type(string), holder(string, e.g. stake1uxxxxxxxx), rarity(string), "
          "resolved_addresses{ada(string)}, lovelace(integer), has_datum(boolean), updated_slot_number(integer)")
LEDGER = ("PAGES YOU HAVE ALREADY FETCHED - these SUCCEEDED:\n- https://api.handle.me/openapi.json -> HTTP 200; "
          "endpoints: /handles, /stats\n  fields each endpoint returns:\n" + FIELDS + "\n")
NOTE = "(shown in full once in the fetch-record block of this prompt - not repeated here)"


def test_a_ledger_copy_elsewhere_collapses_to_a_pointer_leaving_exactly_one_authoritative_copy():
    """maple walk: the fetch ledger rode up to THREE times in one prompt (anchor, compaction appendix, original
    page result). Byte-exact only, owner and non-user/tool roles never touched, copy-on-write, no-op identity."""
    units = dedup.ledger_units(LEDGER)
    msgs = [{"role": "system", "content": "sys " + FIELDS}, {"role": "user", "content": "⟦ctx:facts⟧ " + LEDGER},
            {"role": "user", "content": "⟦ctx:continuation⟧ summary: fixed.\n\n" + LEDGER},
            {"role": "tool", "content": "[response shape:\n" + FIELDS + "\n]"},
            {"role": "assistant", "content": FIELDS}]
    before = json.dumps(msgs)
    out, n = dedup.elide_from_messages(msgs, units, NOTE, skip_prefix="⟦ctx:facts⟧")
    assert n > 0 and json.dumps(msgs) == before
    assert [FIELDS in m["content"] for m in out] == [True, True, False, False, True]
    assert NOTE in out[2]["content"] and "PAGES YOU HAVE ALREADY FETCHED" in out[2]["content"] and "fixed." in out[2]["content"]
    assert dedup.elide_from_messages(msgs, [], NOTE, skip_prefix="⟦ctx:facts⟧") == (msgs, 0)
    assert dedup.elide_text("nothing overlaps", units, NOTE) == ("nothing overlaps", 0)


def asst(cid, name, args):
    return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": args}}]}


def res(cid, content):
    return {"role": "tool", "tool_call_id": cid, "content": content}


def ids(msgs):
    return [c["id"] for m in msgs if m["role"] == "assistant" for c in m.get("tool_calls") or []]


def test_only_calls_with_identical_arguments_and_output_collapse_keeping_the_last():
    """Key is (name, canonical args, RESULT): a rerun whose output differs (the file now exists) keeps both
    before/after; reordered JSON keys are the same call; no dupes -> the same list; no orphans."""
    msgs = [{"role": "user", "content": "go"},
            asst("A", "exec", '{"cmd": "cat x", "timeout": 5}'), res("A", "no such file"),
            asst("B", "exec", '{"timeout": 5, "cmd": "cat x"}'), res("B", "no such file"),
            asst("C", "exec", '{"cmd": "cat x", "timeout": 5}'), res("C", "def f(): ..."),
            asst("D", "exec", '{"cmd": "ls"}'), res("D", "a")]
    out, rep = focustrim.trim(msgs)
    assert (rep.dropped_calls, rep.dropped_msgs) == (1, 1) and ids(out) == ["B", "C", "D"]
    assert [m["tool_call_id"] for m in out if m["role"] == "tool"] == ["B", "C", "D"]
    assert focustrim.trim(out)[0] is out
    gate_args = json.dumps({"cmd": f"echo {GATE}probe-0___"})
    gates = [asst("g1", "exec", gate_args), res("g1", f"{GATE}probe-0___\nEXIT:1\nSyntaxError"),
             asst("g2", "exec", gate_args), res("g2", f"{GATE}probe-0___\nEXIT:1\nSyntaxError")]
    assert ids(focustrim.trim(gates)[0]) == ["g1", "g2"]       # a gate probe is ground truth, never a duplicate


def refused(cid, cmd):
    """A real authored refusal restored through the canonical inbound owner (nothing executes)."""
    args = json.dumps({"cmd": cmd})
    receipt = denial.receipt_for(cid, "exec_command", args)
    with denial.receipt_scope(receipt):
        stdout = denial.mark(f"Refused {cmd}\nObserved source detail for {cid}\n")
    call = toolwire._shell_call(cid, {"name": "exec_command", "parameters": {
        "type": "object", "properties": {"cmd": {"type": "string"}}}}, toolwire._sentinel("exec_command", args, receipt) + "\n:")
    return writeproxy.represent_inbound([{"role": "assistant", "tool_calls": [call]}, res(cid, stdout)])


def test_a_run_of_proven_refusals_folds_losslessly_and_the_newest_stay_whole():
    """Folding is allowed only for refusals cria itself authored, and the fold keeps every command and body
    verbatim (no clipping) while the newest pairs stay as real calls."""
    msgs = [{"role": "user", "content": "x"}]
    for i in range(6):
        msgs += refused(f"c{i}", f"python -m pytest tests/really/long/path/module_{i}/test_case_{i}.py")
    out, rep = focustrim.trim(msgs)
    assert (rep.squashed_runs, rep.dropped_calls) == (1, 4) and ids(out) == ["c4", "c5"] and out[-4:] == msgs[-4:]
    folded = "".join(m["content"] for m in out if m["role"] == "user")
    assert "…" not in folded
    for i in range(4):
        assert f"module_{i}/test_case_{i}.py" in folded and f"Observed source detail for c{i}" in folded


@pytest.mark.parametrize("shape", ["soft", "hard"])
def test_failures_are_kept_whole_not_deleted_by_their_wording(shape):
    """A hard failure (non-zero exit) carries the traceback the coder needs; native 'No such file' lookups
    are not authored refusals - neither is ever folded however many pile up (the exit-0 api.handle.me curl
    carried the route hint the old 'not found' rule threw away)."""
    msgs = [{"role": "user", "content": "fix it"}]
    for i in range(6):
        out = (f"cat {i}: No such file or directory" if shape == "soft"
               else f"tests/test_{i}.py FAILED\nAssertionError: expected 3 got {i}\nProcess exited with code 1")
        msgs += [asst(f"h{i}", "exec_command", json.dumps({"cmd": f"cmd {i}"})), res(f"h{i}", out)]
    out, rep = focustrim.trim(msgs)
    assert out == msgs and not rep.applied
    assert focustrim._is_failure("bash: x: command not found") and not focustrim._is_failure(
        '{"error":"route_not_found"}\nProcess exited with code 0')


@pytest.mark.parametrize("body", ["", "\n", "   "])
def test_an_empty_result_is_an_answer_not_a_failure(body):
    """orders-api-py / nemotron-elastic: an empty __init__.py read was classed a failure, so the repeat guard
    told the model its read 'failed the same way' 12 times and pushed it to view_image on a .py file."""
    call = [asst("c1", "read_file", '{"path":"orders/__init__.py"}'), res("c1", body)]
    assert not focustrim._repeat_failed(call, "c1")
    assert focustrim._repeat_failed([call[0], res("c1", "boom\nEXIT:1")], "c1")
