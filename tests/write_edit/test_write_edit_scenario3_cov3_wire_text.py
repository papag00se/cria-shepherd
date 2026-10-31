"""What the model is finally shown of a landed edit, of a binary or coloured result, and of a result carrying a credential: the edit echo from the executor's typed report (and what a damaged
report leaves), the binary stand-in that names the format, and secret redaction that keeps a payload boundary true."""
import base64
import json

import pytest

from cria import bodykeys, payloadboundary, prompts, writeproxy

PATH = "src/App.java"
PLAIN = writeproxy.render_edit_echo(PATH)
ENV = "Chunk ID: 1\nWall time: 0.1 seconds\nProcess exited with code 0\nOutput:\n"
PNG = "\x89PNG\r\n\x1a\n" + "\x00\x01\x02" * 50


def echo(**report):
    return writeproxy.render_edit_echo(PATH, {"ev": base64.b64encode(json.dumps(report).encode()).decode()})


def test_a_landed_edit_echoes_the_window_the_executor_reported_and_a_damaged_report_says_less():
    """The plain confirmation names the path; a report adds the real post-edit lines with their numbers (one window that covers the edit says so, several say the span is omitted,
    a removal says removed); a repeated-block hint and the flexible-match / omitted flags add their notes; a corrupt dup field drops only the hint; an unreadable token or a
    late batch-order flag never invents a window."""
    assert PATH in PLAIN and "10:" not in PLAIN
    whole = echo(first=10, last=11, total=40, segs=[[10, "int a;\nint b;"]])
    assert PLAIN in whole and "10: int a;" in whole and "11: int b;" in whole and "10: int a;\n11: int b;" in whole
    spans = echo(first=1, last=50, total=60, segs=[[1, "head"], [50, "tail"]])
    assert "1: head" in spans and "50: tail" in spans and whole.split("\n")[1] != spans.split("\n")[1]
    assert prompts.render("edit_echo_removed", path=PATH, total=40, a=10) in echo(first=10, last=10, total=40, segs=[], empty=True)
    noted = echo(first=10, last=11, total=40, segs=[[10, "x\ny"]], dup=[3, 4, 7, 8, 2, 2], flex=True, omitted=True)
    assert prompts.render("edit_echo_repeat", a=3, b=4, x=7, y=8, old=2, new=2) in noted
    assert prompts.load("edit_echo_flexible") in noted and prompts.load("edit_echo_omitted") in noted
    damaged_dup = echo(first=10, last=11, total=40, segs=[[10, "x\ny"]], dup=["a", "b"])
    assert damaged_dup == echo(first=10, last=11, total=40, segs=[[10, "x\ny"]])
    assert writeproxy.render_edit_echo(PATH, {"ev": "!!!not-a-report"}) == PLAIN
    assert writeproxy.render_edit_echo(PATH, {"ev": base64.b64encode(b'{"first": 1}').decode()}) == PLAIN
    late = writeproxy.render_edit_echo(PATH, {"late": True})
    assert prompts.load("edit_order_late") in late and "1:" not in late


def test_colour_is_stripped_and_binary_is_replaced_by_a_line_that_names_what_it_was_keeping_the_run_record():
    """Colour alone never costs a result (every Maven error in a six-language battery was once thrown away for it); a binary blob becomes ONE fact line with its size and, when the
    magic bytes are readable, its format; the harness's exec envelope is the record of the run and is kept; undecodable heads are sized only; text passes untouched."""
    assert writeproxy._debinarized("\x1b[31mred\x1b[0m ok") == "red ok" and writeproxy._debinarized("") == ""
    assert writeproxy._debinarized(ENV + "plain text\n") == ENV + "plain text\n"
    named = writeproxy._debinarized(PNG)
    assert named.startswith("[binary content: 159 bytes, PNG image") and "\x00" not in named
    assert writeproxy._debinarized(ENV + PNG) == ENV + named
    unnamed = writeproxy._debinarized("\u6f22\u5b57" + "\x00\x01\x02" * 50)
    assert unnamed.startswith("[binary content: 156 bytes") and "PNG" not in unnamed


KEY = "BSAnwLmCmt454A0U3WnT7fzIVFRAKM2"


def test_redaction_keeps_the_payload_boundary_true_over_the_scrubbed_bytes():
    """A result whose tool payload carries a credential (and a cria annotation after it that also does): both are scrubbed, the stamped boundary is re-stamped over the REDACTED
    payload so provenance readers still verify it; a boundary that never verified stays as it was and the whole text is scrubbed; the input list is not mutated."""
    payload, note = f"token={KEY}\nbody", f"\n⟦ctx:note⟧ saw {KEY}"
    stamped = {"role": "tool", "tool_call_id": "c", "content": payload + note, bodykeys.PAYLOAD_BOUNDARY: (len(payload), payloadboundary.digest(payload))}
    broken = {"role": "tool", "tool_call_id": "d", "content": payload + note, bodykeys.PAYLOAD_BOUNDARY: (len(payload), "0" * 64)}
    out = writeproxy.redact_secrets([stamped, broken], [KEY])
    clean = out[0]
    assert KEY not in json.dumps(out) and clean["content"] == "token=***\nbody\n⟦ctx:note⟧ saw ***"
    assert payloadboundary.payload_of(clean, clean["content"]) == "token=***\nbody"
    assert out[1][bodykeys.PAYLOAD_BOUNDARY] == (len(payload), "0" * 64) and payloadboundary.payload_of(out[1], out[1]["content"]) is None
    assert KEY in stamped["content"] and stamped[bodykeys.PAYLOAD_BOUNDARY] == (len(payload), payloadboundary.digest(payload))
