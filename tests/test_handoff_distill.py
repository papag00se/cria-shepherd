"""Summary evidence too big for one request is distilled in pieces, never dropped or garbled.

Incidents (Ornith/Java L5-only run 1792480002): the first self-compaction briefings were rejected
or cut off (call 0051: 48,192 of 49,152 measured, 959 reply tokens) and for ~20 minutes the floor
dropped 45-85 coder turns per call instead. Port of codex-local's chunked compaction: one
extraction call per fitting piece, deterministic merge, recent turns and facts verbatim.
"""
import json
from types import SimpleNamespace

from cria import contextfloor, handoffdistill, memoryhandoff, selfcompact, server, tokenratio
from cria.content_reduce import est_tokens
from cria.loop import SUMMARIZE_MAX_TOKENS


class Log:
    session = "distill"
    phase = "proxy"

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def reply(content, finish="stop"):
    return json.dumps({"choices": [{"finish_reason": finish,
                                    "message": {"role": "assistant", "content": content}}]}).encode()


GOOD = json.dumps({"objective": "speed up importer", "errors": ["Importer.java:97 cannot find symbol"]})


import pytest


@pytest.fixture(autouse=True)
def _fresh_cache():
    handoffdistill.clear_cache()
    yield
    handoffdistill.clear_cache()


def test_extraction_contract_rejects_empty_wrong_or_object_shaped_replies():
    assert handoffdistill.valid_extraction({}) is None
    assert handoffdistill.valid_extraction({"summary": "x"}) is None
    assert handoffdistill.valid_extraction({"errors": [{"text": "E1"}]}) is None
    assert handoffdistill.valid_extraction({"objective": "", "errors": []}) is None
    assert handoffdistill.valid_extraction({"objective": "goal", "latest_plan": ["do x"]}) is None
    ok = handoffdistill.valid_extraction({"errors": "E1", "pending": ["write REVIEW.md"]})
    assert ok["errors"] == ["E1"] and ok["pending"] == ["write REVIEW.md"]


def test_merge_is_deterministic_union_newest_kept_in_order():
    state = handoffdistill.merge([
        {"objective": "old", "errors": ["E1", "E2"], "latest_plan": ["a"]},
        {"objective": "", "errors": ["e2", "E3"], "latest_plan": []},
        {"objective": "new", "errors": ["E4"], "latest_plan": ["b"]}])
    assert state.objective == "new" and state.latest_plan == ["b"]
    assert state.lists["errors"] == ["E1", "e2", "E3", "E4"]


def blocks(n, words=600):
    return [f"turn {i}: " + "detail " * words for i in range(n)]


def test_fit_is_decided_in_the_floors_currency_not_raw_chars():
    # Fits at chars/4, does not fit at the learned summary density: must distill.
    history = blocks(10, 300)
    raw = sum(est_tokens(b) for b in history)
    window = int(raw * 1.15) + handoffdistill.FRAME_TOKENS + 4000
    calls = []
    def chat(body, rlog):
        calls.append(body)
        return reply(GOOD)
    budget = handoffdistill.Budget(window=window, reply=4000, density=1.35)
    out = handoffdistill.distill(history, history_count=10, budget=budget,
                                 chat_fn=chat, apply_role=lambda b: None, rlog=Log())
    assert calls and out != history
    assert handoffdistill.Budget(window=window, reply=4000, density=1.0).fits(history)


def test_failed_piece_stays_verbatim_in_order_and_condensation_is_floor_protected():
    history = blocks(12)
    facts = ["FILES ON DISK: Importer.java", "LAST CHECKS: Importer.java:97 cannot find symbol"]
    sent = []
    def chat(body, rlog):
        sent.append(body)
        return reply("{}") if len(sent) == 2 else reply(GOOD)
    budget = handoffdistill.Budget(window=9000, reply=2000, density=1.0)
    out = handoffdistill.distill(history + facts, history_count=12, budget=budget,
                                 chat_fn=chat, apply_role=lambda b: None, rlog=Log())
    failed = [m["content"] for m in sent[1]["messages"] if m["content"].startswith("turn ")]
    states = [i for i, b in enumerate(out) if b.startswith(handoffdistill.MARKER)]
    first_raw = out.index(failed[0])
    assert states[0] < first_raw < states[1]                    # chronological position kept
    assert out[-2:] == facts and out[-3] == history[-1]
    assert all(contextfloor._has_protect_marker({"role": "user", "content": out[i]}) for i in states)
    for body in sent:                                            # each piece fits with its reply
        assert len([m for m in body["messages"] if m["content"].startswith("turn ")]) >= 1
        assert sum(est_tokens(m["content"]) for m in body["messages"]) + body["max_tokens"] <= 9000


def test_all_pieces_failing_returns_the_original_evidence():
    history = blocks(12)
    out = handoffdistill.distill(history, history_count=12,
        budget=handoffdistill.Budget(window=9000, reply=2000, density=1.0),
        chat_fn=lambda b, r: reply('{"summary": "nothing"}'), apply_role=lambda b: None, rlog=Log())
    assert out is history


def history_messages(turns, size=400):
    messages = [{"role": "user", "content": "Fix the importer. " + "Context. " * 20}]
    for n in range(turns):
        messages += [
            {"role": "assistant", "content": f"Step {n}.", "tool_calls": [{"id": f"c{n}", "type": "function",
             "function": {"name": "exec_command", "arguments": json.dumps({"cmd": f"echo {n}"})}}]},
            {"role": "tool", "tool_call_id": f"c{n}", "content": f"out {n} " + "x " * size}]
    messages.append({"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize the session."})
    return messages


class Provider:
    def __init__(self, window):
        self.window, self._window_guessed, self.sent = window, False, []

    def _resolve_window(self, rlog):
        return self.window

    def chat(self, body, rlog):
        self.sent.append(body)
        return reply(GOOD)


def test_production_compaction_body_fits_through_the_real_floor_without_dropping_turns():
    tokenratio.reset()
    try:
        tokenratio.record("m#summary", 135, 100)                  # learned summary density 1.35+
        provider = Provider(24_576)
        srv = SimpleNamespace(cfg=SimpleNamespace(routing=SimpleNamespace(roles={})))
        log = Log()
        framed = server._compaction_body(server._proxy_body({"model": "m", "messages": history_messages(60)}),
            definition=memoryhandoff.DEFINITION, facts=memoryhandoff.SessionFacts(),
            distill=server._handoff_distiller(provider, srv, log))
        assert provider.sent and "⟦ctx:extracted⟧" in json.dumps(framed["messages"], ensure_ascii=False)
        _, _, rep = contextfloor.fit(framed["messages"], None, window=24_576,
            reserve=contextfloor.reserve_for(framed), safety=tokenratio.observed_kind("summary"))
        assert rep.turns_dropped == 0 and not rep.over_budget
        assert contextfloor.reserve_for(framed) == SUMMARIZE_MAX_TOKENS
    finally:
        tokenratio.reset()


def test_briefing_retry_reframes_with_distillation_too():
    seen = []
    def distill(blocks, count):
        seen.append(count)
        return blocks
    services = server._handoff_services()
    services = memoryhandoff.EvidenceServices(*[getattr(services, f) for f in (
        "drop_harness_frame", "inventory", "listing", "fetch_facts", "disk_truth", "validate",
        "proxy_body", "summarize_max_tokens")], distill=distill)
    body = {"model": "m", "messages": history_messages(3)}
    cut = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "Brief"}}]}
    memoryhandoff.harden(cut, body, memoryhandoff.SessionFacts(), services, selected=True,
        chat_fn=lambda b, r: reply("A complete briefing."), role=None, rlog=Log(),
        settle=lambda *a: None)
    assert seen, "the retry framing must also distill"


ROOM = 16_384          # a view room these 60 x 1,200-word fixtures overflow


def OVERFLOWS(view):
    """Every view this test offers overflows the coder window (no summary is ever accepted)."""
    return True


def test_floor_pressure_summarizes_through_the_rejection_throttle():
    msgs = [{"role": "system", "content": "sys"}] + [
        {"role": "user" if i % 2 else "assistant", "content": f"m{i} " + "w " * 1200} for i in range(60)]
    asked = []
    def summarize(mm, **kw):
        asked.append(len(mm))
        return ""                                                # rejected again
    state = selfcompact.CompactState()
    first = selfcompact.DEFINITION.execute(selfcompact.RollingInput(msgs, summarize, room_tokens=ROOM), state)
    again = selfcompact.DEFINITION.execute(selfcompact.RollingInput(msgs, summarize, room_tokens=ROOM), first.state)
    assert len(asked) == 1                                       # identical evidence is not re-asked
    grown = msgs + [{"role": "assistant", "content": f"g{i} " + "w " * 1200} for i in range(3)]
    later = selfcompact.DEFINITION.execute(selfcompact.RollingInput(grown, summarize, room_tokens=ROOM), again.state)
    assert len(asked) == 1                                       # under 4000 new tokens: throttled
    selfcompact.DEFINITION.execute(selfcompact.RollingInput(grown, summarize, room_tokens=ROOM, floor_pressure=OVERFLOWS),
                                   later.state)
    assert len(asked) == 2                                       # floor pressure: fold, don't drop
    for n in range(5):                                           # still rejected, still pressured:
        grown = grown + [{"role": "assistant", "content": f"h{n} " + "w " * 1200}]
        selfcompact.DEFINITION.execute(selfcompact.RollingInput(grown, summarize, room_tokens=ROOM, floor_pressure=OVERFLOWS),
                                       later.state if n == 0 else state_n)
        state_n = selfcompact.DEFINITION.execute(
            selfcompact.RollingInput(grown, summarize, room_tokens=ROOM, floor_pressure=OVERFLOWS),
            later.state if n == 0 else state_n).state
    assert len(asked) <= 4      # one pressure retry per rejection run, not one per coder turn


def test_retry_over_the_same_pieces_reuses_accepted_extractions():
    history = blocks(12)
    sent = []
    def chat(body, rlog):
        sent.append(body)
        return reply(GOOD)
    budget = handoffdistill.Budget(window=9000, reply=2000, density=1.0)
    for _ in range(2):
        handoffdistill.distill(history, history_count=12, budget=budget,
                               chat_fn=chat, apply_role=lambda b: None, rlog=Log())
    pieces = len(handoffdistill.chunk(history[:-1], 9000 - handoffdistill.EXTRACT_REPLY_TOKENS
                                      - 2 * handoffdistill.FRAME_TOKENS, 1.0))
    assert len(sent) <= pieces


def test_coder_floor_prediction_uses_the_coders_own_density_and_frame():
    from cria import loop as loopmod
    tokenratio.reset()
    try:
        for _ in range(40):                                      # learned (falls slowly from 1.8)
            tokenratio.record("ornith", 100, 100)                # coder density ~1.0
            tokenratio.record("ornith#summary", 200, 100)        # summary density much higher
        up = SimpleNamespace(_resolve_window=lambda rlog: 10_000, _window_guessed=False,
                             loaded_model=lambda rlog: "ornith")
        def coder_chat(body, rlog):
            return b""
        coder_chat.upstream = up
        driver = loopmod.Loop.__new__(loopmod.Loop)
        driver._ctx = SimpleNamespace(coder_chat=coder_chat, coder_role=SimpleNamespace(output_reserve=2000))
        msgs = [{"role": "user", "content": "w " * 12_000}]       # ~6,000 estimated tokens
        assert not driver._floor_would_drop(msgs, Log())          # 6,000 x 1.0 + 2,000 fits 10,000
        assert driver._floor_would_drop(msgs, Log(), frame_tokens=2_500)   # frame counted
    finally:
        tokenratio.reset()
