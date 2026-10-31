"""Evidence the operator reads: call captures, event log levels, tail, turn stats, claude CLI backend."""
import io
import json
import stat
from pathlib import Path
import types
from collections import Counter
from contextlib import redirect_stdout

import pytest

from cria import callcapture
from cria.claude_cli import ClaudeCliProvider
from cria.loop import LoopStore
from cria.events import BoundLog, EventLog
from cria.server import CriaHandler
from cria.tail import latest_log, main as tail_main
from cria.turnstats import StatsStore, TurnStats
from cria.upstream import UpstreamError


class Rlog:
    def __init__(self, session="01a02e27-1111-7000-8000-abcdefabcdef", phase=""):
        self.session, self._turn, self.phase, self.events = session, "t1", phase, []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


@pytest.fixture(autouse=True)
def fresh_capture_counter(monkeypatch):
    monkeypatch.setattr(callcapture, "_seq", {})


def test_capture_names_sort_in_call_order_and_hold_exact_body_prompt_and_response(tmp_path):
    """One folder per session (UUIDv7 ids get a sortable time prefix, others none), one numbered file per call, with the rendered prompt and response beside it."""
    sid = "019f5818-c99f-7911-a78e-79bbdb49625f"
    log, body = Rlog(sid), {"model": "q", "messages": [{"role": "user", "content": "hello"}], "temperature": 0.6}
    first = Path(callcapture.capture(body, log, calls_dir=tmp_path, phase="planner", rendered="<|user|>hello"))
    second = Path(callcapture.capture({"messages": []}, log, calls_dir=tmp_path, phase=None))
    resp = Path(callcapture.capture_response(str(first), json.dumps({"choices": [{"message": {"content": "ANSWER"}}]}).encode(), log))
    assert first.parent.name == callcapture.session_dirname(sid) and first.parent.name.startswith("20260712T")
    assert (first.name, second.name) == ("0001-planner.json", "0002-call.json")
    rec = json.loads(first.read_text())
    assert rec["body"] == body and rec["session"] == sid
    assert (first.parent / rec["rendered_prompt_file"]).read_text() == "<|user|>hello"
    assert resp.parent == first.parent and "ANSWER" in resp.read_text()
    assert callcapture.session_dirname("019f5900-0000-7000-8000-000000000000") > callcapture.session_dirname(
        "019f5818-0000-7000-8000-000000000000")
    assert callcapture.session_dirname("550e8400-e29b-41d4-a716-446655440000") == "550e8400-e29b-41d4-a716-446655440000"
    assert Path(callcapture.capture({}, Rlog(None), calls_dir=tmp_path, phase="proxy")).parent.name == "nosession"
    assert callcapture.capture_response(None, b"{}") is None


@pytest.mark.parametrize("seeded,first_name", [(0, "0001"), (9998, "9999"), (99998, "99999")])
def test_a_restart_never_overwrites_earlier_captures_and_the_count_continues(tmp_path, seeded, first_name):
    """cria restarts ~53x/day: the counter was memory-only so 274 captures were overwritten; it now resumes from disk, even across the 4->5 digit width."""
    log = Rlog()
    callcapture._seq[callcapture.session_dirname(log.session)] = seeded
    paths = [Path(callcapture.capture({"messages": []}, log, calls_dir=tmp_path, phase="coder-s1")) for _ in range(2)]
    paths[1].write_text("evidence")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    callcapture._seq.clear()  # the restart: disk stays, the counter is lost
    after = Path(callcapture.capture({"messages": []}, log, calls_dir=tmp_path, phase="compactor"))  # a new label must not reset it
    assert paths[0].name.startswith(first_name) and after.name == f"{int(first_name) + 2:04d}-compactor.json"
    assert all(p.read_bytes() == data for p, data in before.items())


def test_the_console_filters_by_level_but_an_unknown_level_is_loud_and_the_jsonl_is_never_filtered(tmp_path, capsys):
    """22 sites spelled 'warning'; the old table scored it as info and 828 records went quiet at `warn`: a typo may be louder, never silent."""
    log = EventLog(level="warn", dir=tmp_path, console=True)
    for level in ("debug", "info", "warn", "warning", "none"):
        log.emit(f"k.{level}", level=level)
    log.close()
    shown = capsys.readouterr().err
    assert [k for k in ("k.debug", "k.info", "k.warn", "k.warning", "k.none") if k in shown] == ["k.warn", "k.warning", "k.none"]
    assert len(open(log.path).read().splitlines()) == 5


RECS = [
    {"iso": "2026-07-07T00:00:00.100+00:00", "level": "info", "kind": "request.recv", "turn": "t1", "session": "s1", "n_messages": 2},
    {"iso": "2026-07-07T00:00:00.200+00:00", "level": "info", "kind": "decision", "turn": "t1", "decision": "engagement",
     "choice": "task", "reason": "write a handler", "task_type": "coding"},
    {"iso": "2026-07-07T00:00:00.300+00:00", "level": "warn", "kind": "route.skip", "turn": "t2", "role": "cloud.coder"},
    {"iso": "2026-07-07T00:00:00.400+00:00", "level": "debug", "kind": "http.access", "turn": "t2", "line": "GET /health"},
]


def test_tail_filters_renders_decisions_with_their_reason_and_picks_the_newest_log(tmp_path):
    """cria-tail: --decisions shows choice+reason+extras, --turn/--kind/-n filter, debug hidden by default, the newest file wins, a missing file is rc 1."""
    (tmp_path / "cria-20260706.jsonl").write_text("")
    log = tmp_path / "cria-20260707.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in RECS) + "\n")
    assert latest_log(str(tmp_path)).endswith("cria-20260707.jsonl") and latest_log(str(tmp_path / "none")) is None

    def run(*args, rc=0):
        out = io.StringIO()
        with redirect_stdout(out):
            assert tail_main([str(log), *args]) == rc
        return out.getvalue()

    decisions = run("--decisions")
    assert "DECIDE" in decisions and "write a handler" in decisions and "task_type=coding" in decisions
    assert "request.recv" not in decisions
    t2 = run("--turn", "t2")
    assert "route.skip" in t2 and "request.recv" not in t2 and "http.access" not in run("--level", "info")
    assert json.loads(run("--kind", "decision", "--raw"))["decision"] == "engagement"
    assert run("-n", "1").count("\n") == 1 and "http.access" in run("-n", "1")
    assert tail_main(["/no/such/log.jsonl"]) == 1


def fires(*calls):
    """A real BoundLog, so the test sees what the fire sites declare rather than a mapping table."""
    lg = BoundLog(EventLog(console=False, jsonl=False), "s", "t")
    for kind, kw in calls:
        lg.emit(kind, **kw)
    return lg


def test_the_turn_summary_counts_model_calls_tokens_steers_and_reshapes_from_events():
    """'🧮 N calls' counts real model calls (not finalized responses) and steers/reshapes come from declared fires; plumbing events and clean gates are not interventions."""
    st = TurnStats()
    heavy = fires(*([("loop.periodic_gate", {"steer": "periodic-gate"})] * 3), ("loop.gate", {"blocked": True}),
                  *([("context.self_compact", {"reshape": "compact"})] * 22),
                  *([("massage.leaked_recovered", {"reshape": "massage"})] * 4),
                  *([("massage.text_from_reasoning", {"reshape": "massage"})] * 2), ("loop.gate", {"blocked": False}))
    st.observe(40.0, 1800, model_calls=1, events=heavy.events, ledger=heavy.ledger)
    st.observe(None, model_calls=0)
    st.observe(36.0, 1500, model_calls=3, events=Counter({"upstream.request": 5, "ctx.estimate": 5}))
    s = st.summary()
    assert s.startswith("⟦cria⟧ turn done") and "🧮 4 calls" in s and st.calls == 3
    assert "38.0 tok/s" in s and "🔢 3.3k tok" in s
    assert "periodic-gate×3" in s and "gate×1" in s and "gate×2" not in s
    assert "compact×22" in s and "massage×6" in s
    quiet = TurnStats()
    quiet.observe(50.0, 850, model_calls=1)
    assert "🔢 850 tok" in quiet.summary() and "🛡" not in quiet.summary() and "🧰" not in quiet.summary()


@pytest.mark.parametrize("content,reported", [("", False), ("done", True)])
def test_an_unshown_turn_summary_keeps_its_tally_and_a_shown_one_resets_it(content, reported):
    """Run 0728-m2: 1,711 real calls but two summaries totalling 86 because an empty answer discarded the tally; reset happens only after the summary is surfaced."""
    store = StatsStore()
    st = store.get("k")
    st.calls, st.model_calls = 5, 43
    st.observe(50.0, 100, 0)
    handler = CriaHandler.__new__(CriaHandler)
    handler.server = types.SimpleNamespace(
        cfg=types.SimpleNamespace(indicators=types.SimpleNamespace(enabled=True, stats=True, connect=False)),
        stats_store=store, loop_store=LoopStore())
    handler._decorate = lambda c: c
    log = types.SimpleNamespace(last_tok_per_s=None, gen_tokens=0, model_calls=0, events=None)
    comp = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    CriaHandler._finalize(handler, comp, "k", log)
    assert ("calls" in comp["choices"][0]["message"]["content"]) is reported
    assert (store.get("k").model_calls == 0) is reported


def _fake_claude(tmp_path):
    binary, args = tmp_path / "claude", tmp_path / "args.log"
    binary.write_text("#!/bin/sh\n" f'printf "%s\\n" "$*" >> "{args}"\n'
                      "printf '%s' '{\"result\":\"did the thing\",\"session_id\":\"S1\",\"usage\":{\"input_tokens\":10,\"output_tokens\":20}}'\n")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return str(binary), args


def test_the_claude_cli_backend_resumes_only_real_sessions_and_a_missing_binary_is_an_upstream_error(tmp_path):
    """Completions come back OpenAI-shaped; a second call of the same session resumes S1; sessionless calls never resume (two unrelated chats would bleed context)."""
    binary, args = _fake_claude(tmp_path)
    provider = ClaudeCliProvider(binary=binary)
    body = {"model": "m", "messages": [{"role": "user", "content": "step one"}]}
    done = json.loads(provider.chat(body, Rlog("sess-A")))
    assert done["choices"][0]["message"]["content"] == "did the thing" and done["usage"]["total_tokens"] == 30
    provider.chat(body, Rlog("sess-A"))
    provider.chat(body, Rlog(None))
    provider.chat(body, Rlog(None))
    lines = args.read_text().splitlines()
    assert ["--resume S1" in line for line in lines] == [False, True, False, False]
    streamed = b"".join(provider.stream_chat(body, Rlog(None)))
    assert b"did the thing" in streamed and streamed.endswith(b"data: [DONE]\n\n")
    with pytest.raises(UpstreamError):
        ClaudeCliProvider(binary="/no/such/claude").chat(body, Rlog(None))
