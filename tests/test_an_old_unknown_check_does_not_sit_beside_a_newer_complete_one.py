"""G3(c) — `⟦ctx:checks⟧ … the check result is UNKNOWN` next to a complete failing result.

Incident: phi4 / feed-pipeline-java A2 (capture 20261010T230133-01a1298d-…) calls 0031, 0037, 0043:
the coder read, one after the other, `⟦ctx:checks⟧ the automatic check evidence did not arrive
completely, so the check result is UNKNOWN. This is not a clean or passing result.` and then the full
maven failure of the NEXT gate.

Why: every paged gate is one transport, rendered at its first page's seat. When a harness compaction
dropped some pages of an OLDER transport, that transport can no longer be verified and
`clean_gate_results` rendered it UNKNOWN — beside a newer transport that verified completely. The
note is true of a run that has since been superseded and contradicts the run in front of it. Only the
NEWEST gate's unknown-ness is a fact about the repo's present state; an older unverifiable one is
silence (principle 3) — never clean (principle 13), just not stated over a newer reading.
"""
import base64
import hashlib
import json

from cria import probegate, prompts
from tests.gatefixture import bounds_field_for

UNKNOWN = prompts.load("probe_transport_unknown").strip()


def _page(transport_id: str, result: str, *, claim_total_extra: int = 0) -> str:
    data = result.encode()
    path = f"/tmp/.cria-gate-{transport_id}.wire"
    return "\n".join([
        probegate._transport_marker(transport_id),
        "path\t" + base64.b64encode(path.encode()).decode(),
        "offset\t0",
        f"total\t{len(data) + claim_total_extra}",
        "sha256\t" + hashlib.sha256(data).hexdigest(),
        *bounds_field_for(result),                      # the worker's declared extents and header offsets
        "data\t" + base64.b64encode(data).decode(),
        probegate._transport_marker(transport_id, end=True),
    ])


def _gate_turn(call_id: str, transport_id: str, result: str, **kw):
    command = "\n".join([
        probegate._gate_sentinel(["mvn -q compile"]),
        "__cria_gate_file=/tmp/.cria-gate-internal",
        "echo ___CRIA_SURVEY___",
        probegate._transport_reader('"/tmp/.cria-gate-internal"', 0, transport_id),
    ])
    return [
        {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": "exec_command", "arguments": json.dumps({"cmd": command})}}]},
        {"role": "tool", "tool_call_id": call_id, "content": _page(transport_id, result, **kw)},
    ]


FAIL = (f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
        "src/Importer.java:9: package org.apache.commons.csv does not exist\nEXIT:1\n")
OLD, NEW = "a" * 24, "b" * 24


def _clean(messages):
    return probegate.clean_gate_results(messages, linked_only=True)


def _text(msgs):
    return "\n".join(str(m.get("content") or "") for m in msgs)


def test_an_older_unverifiable_gate_is_not_stated_beside_a_newer_complete_one():
    msgs = [{"role": "user", "content": "fix it"},
            *_gate_turn("g-old", OLD, FAIL, claim_total_extra=40),     # pages missing: cannot verify
            {"role": "assistant", "content": "trying something"},
            *_gate_turn("g-new", NEW, FAIL)]
    out = _text(_clean(msgs))
    assert UNKNOWN not in out
    assert "package org.apache.commons.csv does not exist" in out      # the newer, complete result


def test_the_only_gate_being_unverifiable_is_still_unknown():
    msgs = [{"role": "user", "content": "fix it"},
            *_gate_turn("g-old", OLD, FAIL, claim_total_extra=40)]
    assert UNKNOWN in _text(_clean(msgs))


def test_a_newest_unverifiable_gate_after_a_complete_one_is_still_unknown():
    msgs = [{"role": "user", "content": "fix it"},
            *_gate_turn("g-old", OLD, FAIL),
            {"role": "assistant", "content": "edited"},
            *_gate_turn("g-new", NEW, FAIL, claim_total_extra=40)]
    out = _text(_clean(msgs))
    assert UNKNOWN in out                       # never reads as clean or silent about the NEWEST gate


def test_the_dropped_unknown_takes_no_orphan_with_it():
    msgs = [{"role": "user", "content": "fix it"},
            *_gate_turn("g-old", OLD, FAIL, claim_total_extra=40),
            *_gate_turn("g-new", NEW, FAIL)]
    out = _clean(msgs)
    called = {tc["id"] for m in out for tc in m.get("tool_calls") or []}
    answered = {m["tool_call_id"] for m in out if m.get("role") == "tool"}
    assert answered <= called
