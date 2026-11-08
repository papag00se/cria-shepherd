"""Summary evidence too big for one request is distilled in pieces, never dropped or garbled (Ornith / Java L5 run 1792480002: call 0051 was 48,192 of 49,152 tokens, then the floor dropped 45-85 coder turns per call for ~20 minutes)."""
import json
from types import SimpleNamespace

import pytest

from cria import contextfloor, handoffdistill as hd, memoryhandoff, server, tokenratio, selfcompact
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
    """Extraction contract rejects empty/mis-shaped replies; merge is a deterministic union that keeps the newest wording."""
    for bad in ({}, {"summary": "x"}, {"objective": "", "errors": []}, {"objective": "goal", "latest_plan": ["do x"]},
                {"errors": [{"text": "E1", "line": 3}]}, {"errors": [{"text": ["E1"]}]}, {"errors": [{}]}, {"errors": [["E1"]]},       # an entry that is not a string or an object of strings
                {"errors": [3]}, {"errors": [{"text": {"nested": "E1"}}]}):
        assert hd.valid_extraction(bad) is None
    # the model's own object rendering of a `"path — what"` entry (real replies: path/what, cmd/outcome, error/context, text/cmd, change/evidence)
    flat = hd.valid_extraction({"files_touched": [{"path": "Importer.java", "what": "edited: added the retry"}, "README.md — read"],
                                "commands_run": [{"cmd": "mvn test", "outcome": " exit 0 ", "note": ""}], "errors": [{"error": "E1", "command": "mvn -o compile"}]})
    assert flat["files_touched"] == ["Importer.java — edited: added the retry", "README.md — read"]
    assert flat["commands_run"] == ["mvn test — exit 0"] and flat["errors"] == ["E1 — mvn -o compile"]
    assert hd.valid_extraction({"errors": "E1", "pending": ["write REVIEW.md"]})["pending"] == ["write REVIEW.md"]
    state = hd.merge([{"objective": "old", "errors": ["E1", "E2"], "latest_plan": ["a"]}, {"objective": "", "errors": ["e2", "E3"], "latest_plan": []},
                      {"objective": "new", "errors": ["E4"], "latest_plan": ["b"]}])
    assert state.objective == "new" and state.lists["errors"] == ["E1", "e2", "E3", "E4"]

def test_a_failed_piece_stays_verbatim_in_place_recent_turns_and_facts_are_untouched_and_each_request_fits():
    """A piece that fails to extract stays verbatim in its place; newest turns and facts are untouched; every request fits its window."""
    history, facts, sent = blocks(12), ["FILES ON DISK: Importer.java", "LAST CHECKS: Importer.java:97 cannot find symbol"], []

    def chat(body, rlog):
        sent.append(body)
        return chat_reply("{}" if len(sent) == 2 else GOOD)
    budget = hd.Budget(window=9000, reply=2000, density=1.0)
    events = []
    rec = SimpleNamespace(session="distill", phase="proxy", emit=lambda kind, **f: events.append((kind, f)))
    out = hd.distill(history + facts, history_count=12, budget=budget, chat_fn=chat, apply_role=lambda b: None, rlog=rec)
    done = [f for k, f in events if k == "compaction.distilled"]
    assert len(done) == 1 and done[0]["pieces"] == len(sent) and done[0]["extracted"] == len(sent) - 1 and done[0]["kept_verbatim"] == 1
    assert done[0]["turns"] + done[0]["recent_verbatim"] == 12
    failed = [m["content"] for m in sent[1]["messages"] if m["content"].startswith("turn ")]
    states = [i for i, b in enumerate(out) if b.startswith(hd.MARKER)]
    assert done[0]["recent_verbatim"] == len([b for b in out if b.startswith("turn ")]) - len(failed) >= 1      # the counter is the tail actually kept verbatim
    assert states[0] < out.index(failed[0]) < states[1]                          # the un-extractable piece keeps its chronological place
    assert out[-2:] == facts and out[-3] == history[-1]
    assert all(contextfloor._has_protect_marker({"role": "user", "content": out[i]}) for i in states)
    assert all(sum(est_tokens(m["content"]) for m in b["messages"]) + b["max_tokens"] <= 9000 for b in sent)
    n = len(sent)
    hd.distill(history, history_count=12, budget=budget, chat_fn=chat, apply_role=lambda b: None, rlog=LOG)
    assert len(sent) - n == 1                                                       # a retry over the same pieces re-asks only the one that failed
    other, events[:] = blocks(12, 500), []
    assert hd.distill(other, history_count=12, budget=budget, chat_fn=lambda b, r: chat_reply('{"summary": "nothing"}'), apply_role=lambda b: None, rlog=rec) is other
    (all_failed,) = [f for k, f in events if k == "compaction.distilled"]
    assert all_failed["extracted"] == 0 and all_failed["kept_verbatim"] == all_failed["pieces"] > 1     # nothing extracted: every piece is counted as kept, none as read

def test_replacement_distillation_cannot_fold_prior_or_newer_scopes_even_when_newer_is_oversized():
    prior = "EARLIER HANDOFF: old check failed\n" + "old " * 3000
    middle = ["MIDDLE BEING REPLACED: earlier work " + "x " * 3000 for _ in range(3)]
    newer = "NEWER RETAINED EVIDENCE: same check passed\n" + "new " * 10000
    task = "ORIGINAL TASK: retain both observations"
    seen = []
    def chat(body, rlog):
        seen.extend(m["content"] for m in body["messages"])
        return chat_reply(json.dumps({"errors": ["old check failed"]}))
    out = hd.distill([prior, *middle, newer, task], history_start=1, history_count=len(middle), history_scope="middle",
                     budget=hd.Budget(window=9000, reply=2000, density=1.0),
                     chat_fn=chat, apply_role=lambda b: None, rlog=LOG)
    assert seen and not any(prior in s or newer in s for s in seen)
    assert out[0] == prior and out[-2:] == [newer, task]
    extracted = [block for block in out[1:-2] if hd.MARKER in block]
    assert extracted and all(block.startswith("MIDDLE BEING REPLACED") for block in extracted)
    assert all(contextfloor._has_protect_marker({"role": "user", "content": block}) for block in extracted)

    # With no pressure nothing moves, and failed extraction leaves the same complete evidence.
    raw = [prior, *middle, newer, task]
    assert hd.distill(raw, history_start=1, history_count=3,
                      budget=hd.Budget(window=200000, reply=2000, density=1),
                      chat_fn=chat, apply_role=lambda b: None, rlog=LOG) is raw
    hd.clear_cache()
    assert hd.distill(raw, history_start=1, history_count=3,
                      budget=hd.Budget(window=9000, reply=2000, density=1),
                      chat_fn=lambda *a: chat_reply("{}"), apply_role=lambda b: None, rlog=LOG) == raw


def test_harness_writer_and_each_extractor_receive_the_actual_task_not_just_an_extracted_objective():
    task = "Keep Importer.summarize(path) compatible and report skipped rows."
    followup = "Also retain the existing output format."
    messages = [{"role": "user", "content": task}]
    for n in range(130):
        messages += [call(f"c{n}", "exec_command", cmd=f"echo {n}"), result(f"c{n}", f"out {n} " + "x " * 400)]
    messages += [{"role": "user", "content": followup}, {"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize."}]
    from cria.upstream import Upstream
    wire_owner = Upstream("http://unused", context_window=24_576)
    sent = []
    class Provider:
        _window_guessed = False
        def _resolve_window(self, rlog):
            return 24_576
        def chat(self, body, rlog):
            wire, _, _ = wire_owner._prep(body, False, rlog)
            sent.append(json.loads(wire))
            return chat_reply(GOOD)
    provider = Provider()
    srv = SimpleNamespace(cfg=SimpleNamespace(routing=SimpleNamespace(roles={})))
    framed = server._compaction_body(server._proxy_body({"model": "m", "messages": messages}),
        definition=memoryhandoff.DEFINITION, facts=memoryhandoff.SessionFacts(original_task=task),
        distill=server._handoff_distiller(provider, srv, LOG))
    assert len(sent) > 1 and all(task in json.dumps(b, ensure_ascii=False) for b in sent)
    wire, _, _ = wire_owner._prep(framed, False, LOG)
    rendered = wire.decode() if isinstance(wire, bytes) else wire
    assert task in rendered and followup in rendered
    _, _, report = contextfloor.fit(framed["messages"], None, window=24_576,
        reserve=contextfloor.reserve_for(framed), safety=tokenratio.observed_kind("summary"))
    assert report.turns_dropped == 0 and not report.over_budget


def test_extraction_cache_is_scoped_to_original_task_and_floor_keeps_the_task():
    group = ["old result " * 1200]
    bodies = []
    def chat(body, rlog):
        bodies.append(body)
        return chat_reply(GOOD)
    for task in ("Original task A", "Original task A", "Original task B"):
        assert hd.extract(group, chat, lambda b: None, LOG, task=task)
    assert len(bodies) == 2
    assert "Original task A" in json.dumps(bodies[0]) and "Original task B" in json.dumps(bodies[1])
    for body in bodies:
        fitted, _, _ = contextfloor.fit(body["messages"], None, window=9000, reserve=1000)
        assert any(selfcompact.TASK_MARKER in m.get("content", "") for m in fitted)


def test_authenticated_prior_handoff_is_not_promoted_into_original_task(monkeypatch):
    from cria.loop import _HandoffOrigin
    monkeypatch.setattr(server, "_session_cwd", lambda *a: "")
    monkeypatch.setattr(server, "_session_gate_plan", lambda *a: None)
    monkeypatch.setattr(server, "_last_gate_flag", lambda *a: "")
    monkeypatch.setattr(server, "_gate_age", lambda *a: 0)
    monkeypatch.setattr(server, "_last_checks_note", lambda *a: "")
    handoff = "⟦ctx:continuation⟧ False prior claim: all tests pass."
    owner = SimpleNamespace(handoff_origin=_HandoffOrigin("briefing", "", False, continuation=handoff),
                            plan=SimpleNamespace(task="Original actual task"))
    def facts(messages):
        return server._handoff_facts(None, "sid:case", {"messages": messages}, LOG, owner)
    root = {"role": "user", "content": "Original actual task"}
    prior = {"role": "user", "content": handoff}
    work = {"role": "assistant", "content": "work"}
    followup = {"role": "user", "content": "Real follow-up"}
    assert facts([root, prior, work, followup]).original_task == "Original actual task"
    assert facts([root, prior, followup, work]).original_task == "Original actual task"
    assert facts([prior, work, followup]).original_task == ""
    assert facts([{"role": "user", "content": "environment"}, prior, work, followup]).original_task == ""
    assert facts([root, work, followup]).original_task == "Original actual task"


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
