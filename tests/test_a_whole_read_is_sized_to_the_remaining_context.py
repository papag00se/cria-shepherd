"""A whole read is sized to the coder's REMAINING context, not to a fixed 9,000 bytes.

Incident: ornith1.5_9b / Java overnight run 1 (capture 20261027T231856-01a18129-…, 1,342 calls, graded 35%). 54 of its
135 refused coder calls were whole reads of its OWN `src/main/java/pipeline/Importer.java` — 267 lines, 9,729 bytes —
answered "larger than can be returned in one read … start_line=1 end_line=217 fits". The cap was the fixed
`READ_INLINE_MAX` (9,000 bytes of RAW file), while the harness carries the read as a zlib record of 4,070 bytes and the
coder had 10–20k tokens of context left. The refusals also fed the 3-refusal guard: 31 of its 43 firings had a size
refusal in their window and 30 would not have reached 3 without one.

The limit is now `READ_ROOM_SHARE` (40%) of the context left after the coder request's measured prompt, its reply and the
reply reserve (operator design, 2026-10-28), split between the reply's whole reads, with:
* the old 9,000 bytes as a FLOOR — a full context never makes an ordinary read refuse (today's behaviour, unchanged);
* the harness's own cut as a CEILING on the record it carries — never a result the harness would cut;
* no known window or no measured prompt: the floor alone, exactly as before (#11b).
Nothing is ever truncated: anything over a bound gets the existing exact-window steer.

Executed end to end: the real run-1 reply is lowered by `translate_outbound` with the budget `Loop.read_budget_bytes`
computes from it, the commands run under bash against the real file, and `represent_inbound` reads the result.
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
    """Call 0093's reply (data/feed.csv lines 1-25, data/feed_messy.csv, Importer.java) at 21,773 measured prompt tokens:
    ~15.6 KB of room for its whole reads. Before: Importer.java was refused (call 0094)."""
    budget = _coder_loop(WINDOW).read_budget_bytes(REPLY_0093, _Log())
    assert budget is not None and budget > len(IMPORTER_BYTES)
    calls = _lower(REPLY_0093, ws, read_budget=budget)
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
        budget = _coder_loop(WINDOW).read_budget_bytes(comp, _Log())
        o, _ = _represented(_lower(comp, ws, read_budget=budget), ws)
        out += o
    assert loop._refusals_in_window(out)[0] == 0


# ── no room: the exact-window steer, never a cut ──────────────────────────────────────────────────────────────────────

def test_a_read_that_does_not_fit_the_remaining_context_gets_the_exact_window_steer(ws):
    """At 31,000 measured prompt tokens 40% of what is left is under the floor: the floor (9,000) rules, the 9,729-byte
    file is refused with the exact window, and that window really reads — one more line does not."""
    comp = _read(IMPORTER)
    comp["usage"]["prompt_tokens"] = 31_000
    budget = _coder_loop(WINDOW).read_budget_bytes(comp, _Log())
    assert budget < filecommands.READ_INLINE_MAX
    out, _ = _represented(_lower(comp, ws, read_budget=budget), ws)
    text = out[1]["content"]
    assert denial.refused(out[1]) and "is 267 lines, which is larger than can be returned in one read" in text
    fits = int(re.search(r"start_line=1 end_line=(\d+) fits", text).group(1))
    assert fits == 217                                                       # the same window run 1 was offered
    ok, _ = _represented(_lower(_read(IMPORTER, start_line=1, end_line=fits), ws), ws)
    over, _ = _represented(_lower(_read(IMPORTER, start_line=1, end_line=fits + 1), ws), ws)
    assert not denial.refused(ok[1]) and ok[1]["content"].startswith("1: package pipeline;")
    assert "larger than can be returned" in over[1]["content"]


def test_a_huge_output_file_is_still_steered_with_room_to_spare(ws):
    """Run 1's other refusals: 188 KB output dumps and the 1.2 MB feed. The room never stretches to them."""
    comp = _read("data/feed.csv")
    out, raw = _represented(_lower(comp, ws, read_budget=10 ** 7), ws)
    assert denial.refused(out[1]) and "is 40000 lines, which is larger than can be returned in one read" in out[1]["content"]
    assert "SKU-00500" not in raw["r1"]


def test_room_never_lifts_a_result_above_the_harness_ceiling(ws):
    """A file that fits the room but whose record would not fit the harness's cut is refused, not shortened."""
    noise = os.urandom(12_000)
    (ws / "blob.bin").write_bytes(noise)
    out, raw = _represented(_lower(_read("blob.bin"), ws, read_budget=10 ** 6), ws)
    assert denial.refused(out[1]) and "larger than can be returned in one read" in out[1]["content"]
    assert len(raw["r1"].encode()) < content_reduce.INLINE_RESULT_MAX_BYTES
    # …while compressible text of the same size, inside the same room, comes back whole and under the ceiling
    text = "".join(f"    total += row.quantity() * row.price(); // line {i}\n" for i in range(240)).encode()
    assert len(text) > 12_000
    (ws / "Loop.java").write_bytes(text)
    out, raw = _represented(_lower(_read("Loop.java"), ws, read_budget=10 ** 6), ws)
    assert out[1]["content"] == text.decode() and len(raw["r1"].encode()) <= content_reduce.INLINE_RESULT_MAX_BYTES


def test_a_file_bigger_than_the_room_is_refused_even_when_its_record_would_fit(ws):
    """The room is a bound on what the MODEL reads, not only on what the harness carries."""
    (ws / "repeat.txt").write_text("ok\n" * 20_000)                          # 60 KB, compresses to almost nothing
    out, _ = _represented(_lower(_read("repeat.txt"), ws, read_budget=30_000), ws)
    assert denial.refused(out[1]) and "larger than can be returned" in out[1]["content"]


# ── the floor and the abstentions: exactly today's behaviour ─────────────────────────────────────────────────────────

def test_unknown_or_guessed_window_and_unmeasured_prompt_keep_todays_behaviour(ws):
    assert _coder_loop(None).read_budget_bytes(REPLY_0093, _Log()) is None
    assert _coder_loop(WINDOW, guessed=True).read_budget_bytes(REPLY_0093, _Log()) is None
    unmeasured = {k: v for k, v in REPLY_0093.items() if k != "usage"}
    assert _coder_loop(WINDOW).read_budget_bytes(unmeasured, _Log()) is None
    before = [_cmd(tc) for tc in _lower(REPLY_0093, ws)]
    assert [_cmd(tc) for tc in _lower(REPLY_0093, ws, read_budget=None)] == before
    out, _ = _represented(_lower(REPLY_0093, ws), ws)
    assert "is 267 lines, which is larger than can be returned in one read" in _importer_result(out)["content"]


def test_a_full_context_never_makes_an_ordinary_read_refuse(ws):
    """The floor: with no room at all a file at the old bound still comes back whole."""
    body = ("x" * 99 + "\n") * (filecommands.READ_INLINE_MAX // 100)
    (ws / "small.txt").write_text(body)
    out, _ = _represented(_lower(_read("small.txt"), ws, read_budget=0), ws)
    assert out[1]["content"] == body and not denial.refused(out[1])


def test_the_reply_shares_its_room_between_its_whole_reads():
    """Each read's room is the budget less what the OTHER whole reads bring back: a known size that fits, nothing for a
    file known to be too big (it will be steered), the floor when unknown. Ranged reads and other tools take no share."""
    sizes = {"a.java": 1_000, "b.csv": 2_000_000}
    calls = [{"function": {"name": "read_file", "arguments": json.dumps({"path": p})}} for p in ("big.java", "a.java", "b.csv", "c.txt")]
    calls += [{"function": {"name": "read_file", "arguments": json.dumps({"path": "a.java", "start_line": 1, "end_line": 5})}},
              {"function": {"name": "write_file", "arguments": json.dumps({"path": "w.txt", "content": "x"})}}]
    rooms = filecommands.whole_read_rooms(calls, 20_000, sizes.get)
    unknown = filecommands.READ_INLINE_MAX                      # big.java and c.txt: no size known
    assert rooms == {0: 20_000 - 1_000 - 0 - unknown,           # others: a.java, b.csv (steered), c.txt
                     1: 20_000 - unknown - 0 - unknown,         # others: big.java, b.csv, c.txt
                     2: 20_000 - unknown - 1_000 - unknown,     # others: big.java, a.java, c.txt
                     3: 20_000 - unknown - 1_000 - 0}           # others: big.java, a.java, b.csv
    assert filecommands.whole_read_rooms(calls, None, sizes.get) == {}


# ── unchanged neighbours ─────────────────────────────────────────────────────────────────────────────────────────────

def test_ranged_reads_keep_their_own_bound_whatever_the_room(ws):
    out, _ = _represented(_lower(_read(IMPORTER, start_line=1, end_line=267), ws, read_budget=10 ** 6), ws)
    assert "That line range of" in out[1]["content"] and denial.refused(out[1])


def test_a_spilled_document_keeps_the_floor_whatever_the_room(ws):
    spill = ws / webfetch.SPILL_DIR.lstrip("./")
    spill.mkdir(parents=True)
    (spill / "openapi.json").write_text('{"a": 1}\n' * 2_000)                # 18 KB, compressible
    rel = f"{webfetch.SPILL_DIR}/openapi.json"
    out, raw = _represented(_lower(_read(rel), ws, read_budget=10 ** 6), ws)
    assert denial.is_denied(raw["r1"]) and '{"a": 1}' not in raw["r1"]


def test_a_write_to_the_unread_importer_is_still_not_run(ws):
    """The whole-read-before-write requirement is untouched: a write naming the unread file does not run, whatever the
    room; once the whole read has come back, the hold lifts (it is a recorded whole read)."""
    write = {"choices": [{"message": {"tool_calls": [{"id": "w1", "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({"path": IMPORTER, "content": "class Importer {}\n"})}}]}}]}
    comp = json.loads(json.dumps(write))
    translate_outbound(comp, SHELL, injected={"write_file"}, workspace_root=str(ws), read_budget=10 ** 6,
                       unread_target=lambda p: f"{p} already exists on disk.")
    _represented(comp["choices"][0]["message"]["tool_calls"], ws)
    assert (ws / IMPORTER).read_bytes() == IMPORTER_BYTES                     # not written
    out, _ = _represented(_lower(_read(IMPORTER), ws, read_budget=_coder_loop(WINDOW).read_budget_bytes(_read(IMPORTER), _Log())), ws)
    assert IMPORTER in loop._extract_whole_reads(out)
