"""Call capture is evidence, so it must be exact and must never break the request: restart-stable numbering that never overwrites, receipts
that sit beside (not inside) the body, native records in their own counter, the inbound receipt that never advances the call sequence, and
every unwritable / unserialisable case answered with None instead of an exception."""
import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from cria import callcapture

SID = "019f5900-0000-7000-8000-000000000000"


class Rlog:
    def __init__(self, session=SID, turn="t7"):
        self.session, self._turn, self.events = session, turn, []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


@pytest.fixture(autouse=True)
def fresh_counter(monkeypatch):
    monkeypatch.setattr(callcapture, "_seq", {})


def test_numbering_resumes_after_a_restart_past_the_highest_existing_file_at_any_width(tmp_path):
    """A restart empties the in-memory counter; the folder is the truth: the next capture is one past the highest `NNNN-` already there (a
    5-digit name counts, a non-numbered file does not), so capture 0001 is never overwritten."""
    rlog = Rlog()
    first = Path(callcapture.capture({"messages": []}, rlog, calls_dir=tmp_path, phase="coder"))
    folder = first.parent
    (folder / "10000-old.json").write_text("{}")
    (folder / "notes.txt").write_text("x")
    callcapture._seq.clear()                                   # the restart
    assert Path(callcapture.capture({"messages": []}, rlog, calls_dir=tmp_path, phase="coder")).name == "10001-coder.json"
    assert first.read_text() and json.loads(first.read_text())["seq"] == 1


def test_a_capture_carries_its_receipts_beside_the_exact_body(tmp_path):
    """The body is exactly what was sent; the preframe receipt, the assist selection, the url and the stats sit next to it, never inside; the
    rendered prompt is a sibling file with its size recorded; the event reports whether a rendering exists."""
    rlog, body = Rlog(), {"messages": [{"role": "user", "content": "hi"}], "tools": [{"type": "function"}]}
    path = Path(callcapture.capture(body, rlog, calls_dir=tmp_path, phase="co der/1", url="http://u/v1", rendered="<|user|>hi",
                                    coder_preframe={"sha": "abc"}, assist_selection={"level": 3}))
    record = json.loads(path.read_text())
    assert path.name == "0001-co-der-1.json" and record["body"] == body and record["url"] == "http://u/v1" and record["turn"] == "t7"
    assert record["coder_preframe"] == {"sha": "abc"} and record["assist_selection"] == {"level": 3}
    assert (path.parent / record["rendered_prompt_file"]).read_text() == "<|user|>hi" and record["stats"]["rendered_chars"] == 10
    assert record["stats"]["n_messages"] == 1 and record["stats"]["n_tools"] == 1 and record["stats"]["tool_tokens"] > 0
    bare = json.loads(Path(callcapture.capture({"messages": []}, rlog, calls_dir=tmp_path)).read_text())
    assert not {"coder_preframe", "assist_selection", "rendered_prompt_file"} & set(bare) and bare["phase"] is None
    kinds = [(k, e["rendered"]) for k, e in rlog.events]
    assert kinds == [("upstream.dump", True), ("upstream.dump", False)]


def test_a_native_record_never_overwrites_a_file_another_process_wrote_and_has_its_own_counter(tmp_path):
    """The exclusive create skips a name another process took in the meantime; native records neither shift nor are counted by the upstream
    sequence."""
    rlog = Rlog()
    up = Path(callcapture.capture({"messages": []}, rlog, calls_dir=tmp_path, phase="coder"))
    native = tmp_path / callcapture.session_dirname(SID) / "system1"
    native.mkdir()
    (native / "0001-system1-dictation.json").write_text("TAKEN")
    callcapture._seq[f"{callcapture.session_dirname(SID)}/system1"] = 0       # this process has not seen the other one's file: its counter says 1
    got = Path(callcapture.capture_native({"x": 1}, {"label": "A"}, rlog, calls_dir=tmp_path, namespace="system1", phase="system1-dictation"))
    assert got.name == "0002-system1-dictation.json" and (native / "0001-system1-dictation.json").read_text() == "TAKEN"
    assert json.loads(got.read_text())["seq"] == 2 and json.loads(got.read_text())["request"] == {"x": 1}
    nxt = Path(callcapture.capture({"messages": []}, rlog, calls_dir=tmp_path, phase="coder"))
    assert up.name == "0001-coder.json" and nxt.name == "0002-coder.json" and not [f for f in up.parent.glob("*.json") if "system1" in f.name]


def test_an_inbound_receipt_is_the_exact_bytes_named_by_turn_and_api_and_never_advances_the_call_sequence(tmp_path):
    rlog = Rlog(turn="t 9")
    raw = b'{"model":"m","input":[]}  \n'
    path = Path(callcapture.capture_inbound(raw, rlog, calls_dir=tmp_path, api="responses/v1"))
    assert path.name == "inbound-t-9-responses-v1.json" and path.read_bytes() == raw
    assert rlog.events[0][0] == "inbound.dump" and rlog.events[0][1]["bytes"] == len(raw)
    assert Path(callcapture.capture({"messages": []}, rlog, calls_dir=tmp_path)).name == "0001-call.json"
    assert Path(callcapture.capture_inbound(raw, Rlog(turn=None), calls_dir=tmp_path, api="chat")).name == "inbound-noturn-chat.json"


def test_a_response_capture_keeps_valid_json_as_parsed_and_wraps_invalid_bytes_as_raw_text(tmp_path):
    rlog = Rlog()
    req = callcapture.capture({"messages": []}, rlog, calls_dir=tmp_path, phase="coder")
    good = Path(callcapture.capture_response(req, b'{"choices": []}', rlog))
    assert good.name == "0001-coder.response.json" and json.loads(good.read_text()) == {"choices": []}
    junk = Path(callcapture.capture_response(req, b"data: {not json\xff", rlog))
    assert json.loads(junk.read_text()) == {"raw": "data: {not json\ufffd"}
    assert json.loads(Path(callcapture.capture_response(req, {"a": 1}, None)).read_text()) == {"a": 1}


def test_every_unwritable_or_unserialisable_capture_answers_none_and_never_raises(tmp_path):
    """Capture is best-effort: a calls dir that is a file, a body JSON cannot encode, a request path inside nothing — each returns None."""
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    rlog = Rlog()
    assert callcapture.capture({"messages": []}, rlog, calls_dir=blocker) is None
    assert callcapture.capture({"messages": [], (1, 2): "tuple key"}, rlog, calls_dir=tmp_path / "ok") is None
    assert callcapture.capture_native({"x": 1}, {"y": 2}, rlog, calls_dir=blocker, namespace="n", phase="p") is None
    assert callcapture.capture_native({(1,): 1}, {}, rlog, calls_dir=tmp_path / "ok", namespace="n", phase="p") is None
    assert callcapture.capture_inbound(b"{}", rlog, calls_dir=blocker, api="chat") is None
    assert callcapture.capture_inbound("not bytes", rlog, calls_dir=tmp_path / "ok", api="chat") is None
    assert callcapture.capture_response(str(tmp_path / "missing-dir" / "0001-x.json"), b"{}") is None
    assert callcapture.capture_response(str(tmp_path / "0001-x.json"), {(1,): 1}) is None
    assert rlog.events == []                                    # nothing was reported as written


def test_the_capture_folder_time_is_decoded_from_a_v7_session_id_and_a_non_v7_id_has_none():
    ms = 0x019f59000000                                         # the 48-bit prefix of SID
    assert callcapture.uuid7_epoch(SID) == ms / 1000.0
    assert callcapture.session_dirname(SID) == datetime.fromtimestamp(ms / 1000).strftime("%Y%m%dT%H%M%S") + "-" + SID
    for sid in ("550e8400-e29b-41d4-a716-446655440000", "", None, "019F5900-0000-4000-8000-000000000000"):
        assert callcapture.uuid7_epoch(sid) is None
    assert callcapture.session_dirname("a b/c") == "a_b_c" and callcapture.session_dirname(None) == "nosession"
    huge = "ffffffff-ffff-7000-8000-000000000000"                # a stamp the platform cannot format is no stamp, not a crash
    assert callcapture.session_dirname(huge) == huge and callcapture.uuid7_epoch(huge) == 0xffffffffffff / 1000.0
