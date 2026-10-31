"""Regression coverage for whole reads after removal of the read-size guard.

Incident: ornith1.5_9b / Java overnight run 1 (capture 20261027T231856-01a18129-…, 1,342 calls, graded 35%). 54 of its
135 refused coder calls were whole reads of its OWN `src/main/java/pipeline/Importer.java` — 267 lines, 9,729 bytes —
answered "larger than can be returned in one read … start_line=1 end_line=217 fits". The cap was the fixed
`READ_INLINE_MAX` (9,000 bytes of RAW file), while the harness carries the read as a zlib record of 4,070 bytes and the
coder had 10–20k tokens of context left. The refusals also fed the 3-refusal guard: 31 of its 43 firings had a size
refusal in their window and 30 would not have reached 3 without one.

The former context allowance and read-size guard have since been removed. The captured reply is lowered by `translate_outbound`, executed against the real file, and read back through `represent_inbound`.
"""
import json
import os
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from cria import content_reduce, denial, filecommands, loop, prompts, resultpacket, tokenratio, webfetch, wsview, writeproxy
from cria.config import Role
from cria.loop import Loop, LoopContext
from cria.writeproxy import represent_inbound, translate_outbound
from tests.harnessenv import harness_env
from tests.wsfixture import survey

FIX = Path(__file__).parent / "fixtures" / "ornith_java_run1"
IMPORTER = "src/main/java/pipeline/Importer.java"
IMPORTER_BYTES = (FIX / "Importer.java").read_bytes()
REPLY_0093 = json.loads((FIX / "0093-reply.json").read_text())
MODEL = "ornith1.5_9b"
WINDOW, RESERVE = 49_152, 16_384                       # run 1's coder request: context.measured n_ctx / reserve
SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
FEED_MESSY = ("sku,description,quantity,unit_price\nSKU-0001,widget,5,10.00\nSKU-0002,gadget,,20.00\n"
              "SKU-0003,doohickey,3,$15.50\nSKU-0001,widget,5,10.00\nSKU-0004,thing,2,7.25\n"
              "SKU-0005,gizmo,not-a-number,3.00\nSKU-0006,,4,\nSKU-0007,\"widget, blue\",2,12.50\n")


class _Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def _coder_loop(window, guessed=False) -> Loop:
    def chat(body, rlog):
        return b""
    chat.upstream = SimpleNamespace(_resolve_window=lambda rlog: window, _window_guessed=guessed,
                                    loaded_model=lambda rlog: MODEL)
    ctx = LoopContext(planner=None, coder_chat=chat, reasoner_chat=chat,
                      reasoner_role=Role(name="reasoner", backend="local"), runs_dir="")
    return Loop(replace(ctx, coder_role=Role(name="coder", backend="local", output_reserve=RESERVE)))


@pytest.fixture(autouse=True)
def _run1_density():
    """The density run 1 had learned: call 0094 measured 22,732 real tokens for a 20,374-token estimate."""
    tokenratio.reset()
    for _ in range(40):
        tokenratio.record(MODEL, 22_732, 20_374)
    yield
    tokenratio.reset()


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "src/main/java/pipeline").mkdir(parents=True)
    (tmp_path / IMPORTER).write_bytes(IMPORTER_BYTES)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/feed_messy.csv").write_text(FEED_MESSY)
    (tmp_path / "data/feed.csv").write_text("".join(f"SKU-{i:05d},item {i},{i % 50},{i % 97}.25\n" for i in range(40_000)))
    view = wsview.View(str(tmp_path), "run1")
    listing = "\n".join(["D\tsrc", "D\tsrc/main", "D\tsrc/main/java", "D\tsrc/main/java/pipeline", "D\tdata"] +
                        [f"F\t1\t{(tmp_path / p).stat().st_size}\t{p}" for p in (IMPORTER, "data/feed_messy.csv", "data/feed.csv")])
    assert wsview.apply_survey(view, survey(listing, root=str(tmp_path), complete=True))
    token = wsview.bind(view)
    yield tmp_path
    wsview.unbind(token)


def _env(cwd):
    return harness_env(cwd)       # this interpreter as `python3`, never a PATH shim (tests/harnessenv.py)


def _cmd(tc):
    return json.loads(tc["function"]["arguments"])["cmd"]


def _execute(tc, cwd) -> tuple[str, str]:
    p = subprocess.run(["bash", "-c", _cmd(tc)], cwd=cwd, env=_env(cwd), capture_output=True, text=True)
    return p.stdout, (f"Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code {p.returncode}\n"
                      f"Original token count: 9\nOutput:\n{p.stdout}{p.stderr}")


def _lower(completion, root, **kw):
    comp = json.loads(json.dumps(completion))
    translate_outbound(comp, SHELL, injected={"read_file", "write_file"}, workspace_root=str(root), **kw)
    return comp["choices"][0]["message"]["tool_calls"]


def _represented(calls, root):
    msgs, raw = [{"role": "assistant", "tool_calls": calls}], {}
    for tc in calls:
        stdout, envelope = _execute(tc, root)
        raw[tc["id"]] = stdout
        msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": envelope})
    return represent_inbound(msgs, workspace_root=str(root)), raw


def _read(path, cid="r1", **rng):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function",
            "function": {"name": "read_file", "arguments": json.dumps({"path": path, **rng})}}]}}],
            "usage": {"prompt_tokens": 12_000, "completion_tokens": 40}}


def _importer_result(out):
    ids = {tc["id"]: json.loads(tc["function"]["arguments"]).get("path") for m in out
           if m.get("role") == "assistant" for tc in m.get("tool_calls") or []}
    return next(m for m in out if m.get("role") == "tool" and ids.get(m["tool_call_id"]) == IMPORTER)


# ── the incident: the real 267-line Importer.java, with the room run 1 actually had ───────────────────────────────────

def test_the_run1_importer_read_comes_back_whole_with_the_room_that_request_had(ws):
    """Call 0093's multi-read reply includes Importer.java, refused in call 0094 under the former fixed cap."""
    calls = _lower(REPLY_0093, ws)
    out, raw = _represented(calls, ws)
    result = _importer_result(out)
    assert result["content"] == IMPORTER_BYTES.decode()                     # the whole file, byte for byte
    assert denial.proof(result) == denial.RAN and not denial.refused(result)
    assert "larger than can be returned" not in result["content"]
    assert IMPORTER in loop._extract_whole_reads(out)                       # a whole read: the write hold lifts
    assert denial.refused_call_ids(out) == set()                            # nothing for the refusal guard to count
    importer_raw = raw[next(tc["id"] for tc in calls if IMPORTER in tc["function"]["arguments"])]
    assert len(importer_raw.encode()) <= content_reduce.INLINE_RESULT_MAX_BYTES   # under the harness's cut


def test_three_whole_reads_of_it_no_longer_trip_the_refusal_guard(ws):
    """Run 1 23:14-08:16: three refused Importer reads in a window fired the guard (probe + reasoner redirect)."""
    out = []
    for n in range(3):
        comp = _read(IMPORTER, cid=f"r{n}")
        o, _ = _represented(_lower(comp, ws), ws)
        out += o
    assert loop._refusals_in_window(out)[0] == 0


# ── formerly size-refused reads now return their complete requested content ───────────────────────────────────────────

def test_high_prompt_usage_does_not_refuse_whole_or_ranged_read(ws):
    """The former allowance refused this incident file at 31,000 prompt tokens and offered a prefix."""
    comp = _read(IMPORTER)
    comp["usage"]["prompt_tokens"] = 31_000
    out, _ = _represented(_lower(comp, ws), ws)
    assert not denial.refused(out[1]) and out[1]["content"] == IMPORTER_BYTES.decode()
    ranged, _ = _represented(_lower(_read(IMPORTER, start_line=1, end_line=217), ws), ws)
    expected = ''.join(f'{i}: {line}\n' for i, line in enumerate(IMPORTER_BYTES.decode().split('\n')[:217], 1))
    assert not denial.refused(ranged[1]) and ranged[1]["content"] == expected


def test_a_huge_output_file_offers_a_working_transport_window(ws):
    """Run 1 also saw size refusals for 188 KB output dumps and the 1.2 MB feed."""
    out, raw = _represented(_lower(_read("data/feed.csv"), ws), ws)
    assert denial.refused(out[1]) and denial.read_payload(out[1]) is None
    assert len(raw['r1'].encode()) <= filecommands.READ_TRANSPORT_STDOUT_BYTES
    args = json.loads(out[1]['content'].split('Next read_file arguments: ', 1)[1])
    assert args['path'] == 'data/feed.csv' and args['start_line'] == 1 and args['end_line'] < 40_000
    retry, _ = _represented(_lower(_read(**args), ws), ws)
    lines = (ws / 'data/feed.csv').read_text().splitlines()
    expected = ''.join(f'{i}: {line}\n' for i, line in enumerate(lines[:args['end_line']], 1))
    assert not denial.refused(retry[1]) and denial.read_payload(retry[1]) == expected


def test_incompressible_single_line_refusal_names_a_usable_byte_route(ws):
    import random
    rng = random.Random(123)
    text = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(20_000))
    (ws / "source.txt").write_text(text)
    out, raw = _represented(_lower(_read("source.txt"), ws), ws)
    assert denial.refused(out[1]) and denial.read_payload(out[1]) is None
    assert 'byte-oriented shell command' in out[1]['content']
    assert 'Next read_file arguments:' not in out[1]['content']
    assert len(raw['r1'].encode()) <= filecommands.READ_TRANSPORT_STDOUT_BYTES
    p = subprocess.run(['bash', '-c', 'head -c 1000 source.txt'], cwd=ws, capture_output=True, text=True, check=True)
    assert p.stdout == text[:1000]


def test_compressible_file_is_returned_whole(ws):
    """Previously the model-text allowance refused this even when the encoded record fit."""
    (ws / "repeat.txt").write_text("ok\n" * 20_000)
    out, _ = _represented(_lower(_read("repeat.txt"), ws), ws)
    assert not denial.refused(out[1]) and out[1]["content"] == "ok\n" * 20_000


# Usage does not impose a read guard.

def test_unknown_or_guessed_window_and_unmeasured_prompt_keep_todays_behaviour(ws):
    unmeasured = {k: v for k, v in REPLY_0093.items() if k != "usage"}
    assert [_cmd(tc) for tc in _lower(unmeasured, ws)] == [_cmd(tc) for tc in _lower(REPLY_0093, ws)]
    out, _ = _represented(_lower(REPLY_0093, ws), ws)
    assert _importer_result(out)["content"] == IMPORTER_BYTES.decode()


def test_zero_legacy_allowance_does_not_refuse_a_read(ws):
    """The former guard refused even a small file when its computed allowance was zero."""
    body = ("x" * 99 + "\n") * 90
    (ws / "small.txt").write_text(body)
    comp = _read("small.txt")
    comp["usage"]["prompt_tokens"] = WINDOW
    out, _ = _represented(_lower(comp, ws), ws)
    assert not denial.refused(out[1]) and out[1]["content"] == body


def test_multiple_whole_and_ranged_reads_return_independently(ws):
    """Whole and ranged reads once shared a computed allowance; neither should suppress another."""
    calls = _read(IMPORTER)['choices'][0]['message']['tool_calls']
    calls += _read('data/feed_messy.csv', cid='r2')['choices'][0]['message']['tool_calls']
    calls += _read(IMPORTER, cid='r3', start_line=1, end_line=1)['choices'][0]['message']['tool_calls']
    out, _ = _represented(_lower({'choices': [{'message': {'tool_calls': calls}}]}, ws), ws)
    assert out[1]['content'] == IMPORTER_BYTES.decode()
    assert out[2]['content'] == FEED_MESSY
    assert out[3]['content'] == '1: package pipeline;\n'
    assert not denial.refused_call_ids(out)


# ── unchanged neighbours ─────────────────────────────────────────────────────────────────────────────────────────────

def test_ranged_reads_return_the_requested_lines(ws):
    out, _ = _represented(_lower(_read(IMPORTER, start_line=1, end_line=267), ws), ws)
    assert out[1]["content"].startswith("1: package pipeline;") and not denial.refused(out[1])


def test_a_spilled_document_returns_whole(ws):
    spill = ws / webfetch.SPILL_DIR.lstrip("./")
    spill.mkdir(parents=True)
    (spill / "openapi.json").write_text('{"a": 1}\n' * 2_000)                # 18 KB, compressible
    rel = f"{webfetch.SPILL_DIR}/openapi.json"
    out, raw = _represented(_lower(_read(rel), ws), ws)
    assert out[1]["content"] == '{"a": 1}\n' * 2_000


def test_a_write_to_the_unread_importer_is_still_not_run(ws):
    """The whole-read-before-write requirement is untouched: a write naming the unread file does not run, whatever the
    room; once the whole read has come back, the hold lifts (it is a recorded whole read)."""
    write = {"choices": [{"message": {"tool_calls": [{"id": "w1", "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({"path": IMPORTER, "content": "class Importer {}\n"})}}]}}]}
    comp = json.loads(json.dumps(write))
    translate_outbound(comp, SHELL, injected={"write_file"}, workspace_root=str(ws),
                       unread_target=lambda p: f"{p} already exists on disk.")
    _represented(comp["choices"][0]["message"]["tool_calls"], ws)
    assert (ws / IMPORTER).read_bytes() == IMPORTER_BYTES                     # not written
    out, _ = _represented(_lower(_read(IMPORTER), ws), ws)
    assert IMPORTER in loop._extract_whole_reads(out)
