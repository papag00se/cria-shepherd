"""O8 live path (ornith1.5_9b / feed-pipeline-java B2, session 01a12fa9, 2026-10-12).

Two silent failures, both only reproducible on the REAL Codex shape (fixture = a trimmed copy of B2's
inbound request 083dc698, the one that first carried the opencsv pom):

* O2's readable-roots note was computed AFTER `_frame_for_item` dropped the caller-instruction
  messages -- the very messages that hold Codex's "The writable roots are `...`" -- so it was "" on
  every live request (the earlier test used a plain `system` message, which is never dropped).
* C40/O8 asked gather() once, at the request where pom.xml first named opencsv -- before the build had
  downloaded the jar -- recorded an abstain, and then did not look again for 20 requests.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cria import denial, depsurface, dirguard, loop, resultpacket, responses, wsview
from cria import writeproxy

FIX = Path(__file__).parent / "fixtures"
SESS = "sid:01a12fa9-86c5-7d42-8a56-d13c2449d6bd"
needs_javap = pytest.mark.skipif(not shutil.which("javap"), reason="javap not on PATH")


@pytest.fixture
def cell(tmp_path):
    install, ws = tmp_path / "install", tmp_path / "runs"
    install.mkdir(); ws.mkdir()
    for d in (depsurface._ANCHOR, depsurface._WITHHELD, depsurface._ABSTAINED):
        d.clear()
    raw = (FIX / "o8_b2_codex_inbound_083dc698.json").read_text()
    raw = raw.replace("@INSTALL@", str(install)).replace("@WORKSPACE@", str(ws))
    return install, ws, _as_the_current_producer_lowers_it(json.loads(raw))


def _as_the_current_producer_lowers_it(rbody):
    """The recorded request predates the typed result records: its lowered calls carry no receipt and their results no
    record, so today they are (correctly) UNKNOWN. Re-lower each recorded call with the real compiler and give its result the
    record its real program prints, so this test keeps pinning the Codex SHAPE, not the legacy proof."""
    calls = {i["call_id"]: i for i in rbody["input"] if i.get("type") == "function_call"}
    for cid, item in calls.items():
        orig = writeproxy.original_call(json.loads(item["arguments"])["cmd"])
        if orig is None or orig["name"] not in ("read_file", "edit_file"):
            continue
        comp = {"choices": [{"message": {"tool_calls": [{"id": cid, "type": "function", "function": {
            "name": orig["name"], "arguments": orig["arguments"]}}]}}]}
        writeproxy.translate_outbound(comp, {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}},
                                      injected={orig["name"]})
        cmd = comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        item["arguments"] = cmd
        receipt = writeproxy.receipt_of(json.loads(cmd)["cmd"], cid)
        for out in rbody["input"]:
            if out.get("type") == "function_call_output" and out.get("call_id") == cid:
                head, sep, body = out["output"].partition("Output:\n")
                if orig["name"] == "read_file":     # the read-once program's record: the file's bytes, length and digest
                    out["output"] = head + sep + resultpacket.line(receipt, denial.RAN, body=body.encode(), observe="whole")
                else:                                # a landed edit: the program's typed `landed` record, then its own lines
                    out["output"] = head + sep + resultpacket.line(receipt, denial.LANDED) + body
    return rbody


def put_jar(install):
    d = install / "m2" / "repository" / "com" / "opencsv" / "opencsv" / "5.9"
    d.mkdir(parents=True)
    shutil.copy(FIX / "o8_opencsv-5.9.jar", d / "opencsv-5.9.jar")


def inbound(rbody, ws):
    body = responses.to_chat_body(rbody)
    wsview.bind(wsview.View(str(ws), SESS))
    out = writeproxy.represent_inbound(body["messages"], workspace_root=str(ws), sess_key=SESS,
                                       tools_present=True)
    return body, out


def surface_notes(out):
    return [m["content"] for m in out if m.get("role") == "tool" and "THE VERSION OF" in str(m["content"])]


def test_the_real_codex_permission_text_yields_both_declared_roots(cell):
    install, ws, rbody = cell
    msgs = responses.to_chat_body(rbody)["messages"]
    assert dirguard.declared_roots(msgs) == (str(install), str(ws))


@needs_javap
def test_the_surface_note_carries_the_real_opencsv_classes(cell):
    install, ws, rbody = cell
    put_jar(install)
    _, out = inbound(rbody, ws)
    (note,) = surface_notes(out)
    assert "com.opencsv:opencsv:5.9" in note and "public class com.opencsv.CSVReader" in note
    assert "readNext()" in note


@needs_javap
def test_a_jar_that_lands_after_the_pom_is_found_on_the_next_request(cell):
    install, ws, rbody = cell
    _, out = inbound(rbody, ws)             # pom declared, build has not resolved it yet
    assert surface_notes(out) == []
    put_jar(install)                         # the build downloads it
    _, out = inbound(rbody, ws)              # very next request -- not 20 requests later
    assert len(surface_notes(out)) == 1


def test_the_coder_frame_tells_the_model_the_declared_root_is_readable(cell):
    install, ws, rbody = cell
    body = responses.to_chat_body(rbody)
    framed = loop._frame_for_item(body["messages"], "t", "", 0, 1, synthetic=True, workspace_root=str(ws))
    text = framed[0]['content']
    assert 'additional writable roots outside the project' in text
    assert 'active permissions remain authoritative' in text
    assert 'For dependency inspection, use read-only commands there' in text
    assert str(install) in text
