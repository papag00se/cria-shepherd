"""Summary evidence too big for one request is distilled in pieces, never dropped or garbled (Ornith / Java L5 run 1792480002: call 0051 was 48,192 of 49,152 tokens, then the floor dropped 45-85 coder turns per call for ~20 minutes)."""
import json
from types import SimpleNamespace

import pytest

from cria import contextfloor, handoffdistill as hd, memoryhandoff, server, tokenratio
from cria.content_reduce import est_tokens
from cria.loop import SUMMARIZE_MAX_TOKENS
from compaction_handoff_helpers import call, chat_reply, result

GOOD = json.dumps({"objective": "speed up importer", "errors": ["Importer.java:97 cannot find symbol"]})
LOG = SimpleNamespace(session="distill", phase="proxy", emit=lambda *a, **k: None)

@pytest.fixture(autouse=True)
def _fresh():
    hd.clear_cache()
    tokenratio.reset()
    yield
    hd.clear_cache()
    tokenratio.reset()

def blocks(n, words=600):
    return [f"turn {i}: " + "detail " * words for i in range(n)]

def test_an_extraction_must_have_the_contract_shape_and_the_merge_is_a_deterministic_newest_wins_union():
    """Extraction contract rejects empty/object-shaped replies; merge is a deterministic union that keeps the newest wording."""
    for bad in ({}, {"summary": "x"}, {"errors": [{"text": "E1"}]}, {"objective": "", "errors": []}, {"objective": "goal", "latest_plan": ["do x"]}):
        assert hd.valid_extraction(bad) is None
    assert hd.valid_extraction({"errors": "E1", "pending": ["write REVIEW.md"]})["pending"] == ["write REVIEW.md"]
    state = hd.merge([{"objective": "old", "errors": ["E1", "E2"], "latest_plan": ["a"]}, {"objective": "", "errors": ["e2", "E3"], "latest_plan": []},
                      {"objective": "new", "errors": ["E4"], "latest_plan": ["b"]}])
    assert state.objective == "new" and state.latest_plan == ["b"] and state.lists["errors"] == ["E1", "e2", "E3", "E4"]

def test_a_failed_piece_stays_verbatim_in_place_recent_turns_and_facts_are_untouched_and_each_request_fits():
    """A piece that fails to extract stays verbatim in its place; newest turns and facts are untouched; every request fits its window."""
    history, facts, sent = blocks(12), ["FILES ON DISK: Importer.java", "LAST CHECKS: Importer.java:97 cannot find symbol"], []

    def chat(body, rlog):
        sent.append(body)
        return chat_reply("{}" if len(sent) == 2 else GOOD)
    budget = hd.Budget(window=9000, reply=2000, density=1.0)
    out = hd.distill(history + facts, history_count=12, budget=budget, chat_fn=chat, apply_role=lambda b: None, rlog=LOG)
    failed = [m["content"] for m in sent[1]["messages"] if m["content"].startswith("turn ")]
    states = [i for i, b in enumerate(out) if b.startswith(hd.MARKER)]
    assert states[0] < out.index(failed[0]) < states[1]                          # the un-extractable piece keeps its chronological place
    assert out[-2:] == facts and out[-3] == history[-1]
    assert all(contextfloor._has_protect_marker({"role": "user", "content": out[i]}) for i in states)
    assert all(sum(est_tokens(m["content"]) for m in b["messages"]) + b["max_tokens"] <= 9000 for b in sent)
    n = len(sent)
    hd.distill(history, history_count=12, budget=budget, chat_fn=chat, apply_role=lambda b: None, rlog=LOG)
    assert len(sent) - n == 1                                                       # a retry over the same pieces re-asks only the one that failed
    other = blocks(12, 500)
    assert hd.distill(other, history_count=12, budget=budget, chat_fn=lambda b, r: chat_reply('{"summary": "nothing"}'), apply_role=lambda b: None, rlog=LOG) is other

def test_the_production_compaction_body_fits_through_the_real_floor_without_dropping_turns():
    """The real compaction body, distilled, passes the real floor with no turn dropped and the summary reply reserve intact."""
    tokenratio.record("m#summary", 135, 100)
    messages = [{"role": "user", "content": "Fix the importer. " + "Context. " * 20}]
    for n in range(60):
        messages += [call(f"c{n}", "exec_command", cmd=f"echo {n}"), result(f"c{n}", f"out {n} " + "x " * 400)]
    messages.append({"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize the session."})
    sent = []

    class Provider:                                       # a real bound .chat: the window is read off the provider that owns it
        _window_guessed = False

        def _resolve_window(self, rlog):
            return 24_576

        def chat(self, body, rlog):
            sent.append(body)
            return chat_reply(GOOD)
    provider = Provider()
    srv = SimpleNamespace(cfg=SimpleNamespace(routing=SimpleNamespace(roles={})))
    framed = server._compaction_body(server._proxy_body({"model": "m", "messages": messages}), definition=memoryhandoff.DEFINITION,
                                     facts=memoryhandoff.SessionFacts(), distill=server._handoff_distiller(provider, srv, LOG))
    assert sent and "⟦ctx:extracted⟧" in json.dumps(framed["messages"], ensure_ascii=False)
    _, _, report = contextfloor.fit(framed["messages"], None, window=24_576, reserve=contextfloor.reserve_for(framed), safety=tokenratio.observed_kind("summary"))
    assert report.turns_dropped == 0 and not report.over_budget and contextfloor.reserve_for(framed) == SUMMARIZE_MAX_TOKENS
