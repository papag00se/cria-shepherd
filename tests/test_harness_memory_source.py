"""Independent handoff oracles; source execution is not production binding proof.

Synthetic inputs retain the empty/pseudo-call amnesia, cut-reply, unmarked-ask
ordering, original-task and rejected-handoff ledger scenarios. Expected replies
and transcript records are literal contracts, never another policy owner's output.
"""
import copy
import json
from dataclasses import replace

import pytest

from cria import memoryhandoff as memory
from cria import prompts, server
from cria.config import Role
from cria.loop import (SUMMARIZE_MAX_TOKENS, _drop_harness_frame,
                       _fetch_ground_truth, _briefing_disk_truth,
                       validate_compaction_briefing)
from cria.memoryeffects import Effect


class Log:
    def __init__(self):
        self.events = []

    def emit(self, name, **fields):
        self.events.append((name, fields))


def completion(text, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {
        "role": "assistant", "content": text}}]}


def history():
    return [
        {"role": "system", "content": "harness persona"},
        {"role": "user", "content": "Implement all original deliverables"},
        {"role": "assistant", "tool_calls": [{"id": "w", "type": "function",
         "function": {"name": "write_file", "arguments": json.dumps({"path": "a.py", "content": "x=1\n"})}}]},
        {"role": "tool", "tool_call_id": "w", "content": "Wrote a.py"},
        {"role": "user", "content": "Summarize with next steps for continuation"},
    ]


def services():
    return memory.EvidenceServices(
        _drop_harness_frame,
        lambda root: server.groundtruth.workspace_inventory(root, flavor="briefing"),
        server._workspace_listing, _fetch_ground_truth, _briefing_disk_truth,
        validate_compaction_briefing, server._proxy_body, SUMMARIZE_MAX_TOKENS)


class Provider:
    def __init__(self, retry="Retrospective account", verdict=True, broken=False):
        self.calls = []
        self.retry = retry
        self.verdict = verdict
        self.broken = broken

    def chat(self, body, log):
        self.calls.append(copy.deepcopy(body))
        system = body["messages"][0]["content"]
        if "PLAN or RETROSPECTIVE" in system:
            text = "RETROSPECTIVE" if self.verdict else "PLAN"
        elif "NARROWS or PRESERVES" in system:
            text = "PRESERVES" if self.verdict else "NARROWS"
        elif "UNFAITHFUL or FAITHFUL" in system:
            text = "FAITHFUL" if self.verdict else "UNFAITHFUL"
        else:
            if self.broken:
                raise RuntimeError("unavailable")
            text = self.retry
        return json.dumps(completion(text))


@pytest.mark.parametrize("initial,finish,retry,verdict,broken", [
    ("Historical work", "stop", "unused", True, False),
    ("Historical work", "stop", "unused", False, False),
    ("", "stop", "Historical retry", True, False),
    ("cut", "length", "Historical retry", True, False),
    ("", "stop", "", True, False),
    ("", "stop", "", True, True),
])
def test_source_matches_server(initial, finish, retry, verdict, broken):
    """Historical metadata symbol retained; oracle no longer calls/computes from server."""
    body = {"messages": history(), "max_tokens": None}
    original = completion(initial, finish)
    provider, log, settled = Provider(retry, verdict, broken), Log(), []
    actual = memory.harden(copy.deepcopy(original), copy.deepcopy(body),
                           memory.SessionFacts(original_task="Implement all original deliverables"),
                           services(), selected=True, chat_fn=provider.chat,
                           role=Role(name="reasoner", backend="local"), rlog=log,
                           settle=lambda *args: settled.append(args))
    needs_retry = not initial or finish == "length"
    candidate = retry if needs_retry else initial
    accepted = bool(candidate) and verdict and not broken
    expected_prose = candidate if accepted else ""
    expected_calls = (int(needs_retry) + (3 if accepted else 1 if candidate and not broken else 0))
    assert len(provider.calls) == expected_calls
    assert actual.effect is (Effect.DELIVERED if accepted else Effect.WITHHELD)
    assert actual.prose == expected_prose
    if accepted:
        assert actual.completion == completion(expected_prose)
        assert actual.ledger == ""
    else:
        assert actual.ledger.splitlines()[-1:] == ["- write_file a.py: confirmed written"]
        assert memory.completion_text(actual.completion) == memory.indicators.PROSE_DROPPED_MARKER + "\n" + actual.ledger
        assert "Historical work" not in memory.completion_text(actual.completion)
    assert settled == [(memory.completion_text(actual.completion), actual.ledger, not accepted)]
    events = [(name, fields) for name, fields in log.events
              if name.startswith(("route.compaction_", "context.compaction_validation"))]
    expected_names = (["route.compaction_retry"] if needs_retry else [])
    if broken:
        expected_names += ["route.compaction_retry_failed"]
    elif needs_retry and not retry:
        expected_names += ["route.compaction_no_briefing"]
    if candidate and not broken:
        expected_names += ["context.compaction_validation"]
        answers = {"retrospective": "RETROSPECTIVE", "scope": "PRESERVES", "fidelity": "FAITHFUL"} if accepted else {"retrospective": "PLAN"}
        assert events[-1][1] == {"reshape": "validate-rollup", "level": "info" if accepted else "warn",
                                "accepted": accepted, "answers": answers}
        lenses = provider.calls[int(needs_retry):]
        assert "Historical" in str(lenses[0]["messages"])
        if accepted:
            assert "Implement all original deliverables" in str(lenses[1]["messages"])
            assert "Wrote a.py" in str(lenses[2]["messages"])
            assert "Summarize with next steps" not in str(lenses)
    assert [name for name, _fields in events] == expected_names
    if needs_retry:
        assert provider.calls[0]["max_tokens"] == SUMMARIZE_MAX_TOKENS
        assert provider.calls[0]["chat_template_kwargs"]["enable_thinking"] is False
        assert_writer_request(provider.calls[0], reasoning_off=True)
        assert events[0][1] == {"level": "info", "had_leak": bool(initial),
                                "truncated": finish == "length", "max_tokens": SUMMARIZE_MAX_TOKENS}
    assert body["messages"] == history()
    assert original == completion(initial, finish)


def assert_writer_request(body, *, reasoning_off=False):
    # Prompt resources supply wording; ordered evidence is independently literal.
    system = prompts.load("selfcompact_summary")
    if reasoning_off:
        system += "\n\n" + prompts.load("nothink_directive")
    assert body["messages"] == [
        {"role": "system", "content": system},
        {"role": "user", "content": prompts.load("composed_evidence_intro")},
        {"role": "user", "content": "user: Implement all original deliverables"},
        {"role": "user", "content": 'assistant: write_file({"path": "a.py", "content": "x=1\\n"})'},
        {"role": "user", "content": "tool: Wrote a.py"},
        {"role": "user", "content": prompts.load("compact_closing_ask")},
    ]


def test_frame_keeps_full_correlated_evidence_and_excludes_unmarked_ask():
    body = {"messages": history(), "max_tokens": 123, "model": "fixture", "temperature": 0.3}
    actual = memory.frame(body, memory.SessionFacts(), services(), selected=True)
    assert_writer_request(actual)
    assert {k: v for k, v in actual.items() if k != "messages"} == {
        "max_tokens": 123, "model": "fixture", "temperature": 0.3}
    serialized = json.dumps(actual, ensure_ascii=False)
    assert "Summarize with next steps" not in serialized
    assert "a.py" in serialized and "x=1" in serialized
    assert body["messages"] == history()


def test_disabled_does_not_touch_evidence_judgment_or_state():
    def forbidden(*args, **kw):
        raise AssertionError("disabled policy executed")
    body, comp = {"messages": history()}, completion("keep raw")
    svc = memory.EvidenceServices(*(forbidden for _ in range(7)), summarize_max_tokens=1)
    assert memory.frame(body, memory.SessionFacts(), svc, selected=False) is body
    assert not memory.recognize(body, selected=False, context_fixes=True,
                                chat_fn=forbidden, role=object(), ask=forbidden, rlog=Log())
    result = memory.harden(comp, body, memory.SessionFacts(), svc, selected=False,
                           chat_fn=forbidden, role=object(), rlog=Log(), settle=forbidden)
    assert result.effect is Effect.NO_OP and result.completion is comp


def test_recognition_admission_and_unknown():
    calls = []
    def ask(*args, **kw):
        calls.append((args, kw))
        return "UNDECIDABLE"
    body = {"messages": history()}
    for modified, role, fixes in [(dict(body, tools=[{}]), object(), True),
                                  ({"messages": history()[:2]}, object(), True),
                                  (body, None, True), (body, object(), False)]:
        assert not memory.recognize(modified, selected=True, context_fixes=fixes,
                                    chat_fn=None, role=role, ask=ask, rlog=Log())
    assert calls == []
    assert not memory.recognize(body, selected=True, context_fixes=True,
                                chat_fn=None, role=object(), ask=ask, rlog=Log())
    assert len(calls) == 1
    body["messages"][-1]["content"] = memory.LOCAL_COMPACT_MARKER
    assert memory.recognize(body, selected=True, context_fixes=False,
                            chat_fn=None, role=None, ask=ask, rlog=Log())
    assert len(calls) == 1


def test_rejection_carries_only_authenticated_ledger_and_settles_per_session():
    svc = replace(services(), validate=lambda *a, **k: False)
    records = [[], []]
    carried_record = memory.selfcompact.work_ledger([{
        "role": "assistant", "tool_calls": [{"id": "old", "type": "function",
        "function": {"name": "shell", "arguments": json.dumps({"cmd": "pwd"})}}]}])
    assert carried_record.splitlines()[-1] == "- issued (no result recorded; execution not established): pwd"
    for index, carried in enumerate((carried_record, "")):
        facts = memory.SessionFacts(carried_ledger=carried)
        result = memory.harden(completion("Untrusted account"), {"messages": history()},
                               facts, svc, selected=True, chat_fn=None, role=None,
                               rlog=Log(), settle=lambda *args: records[index].append(args))
        assert result.effect is Effect.WITHHELD and not result.prose
        assert "Untrusted account" not in memory.completion_text(result.completion)
        expected = (["- issued (no result recorded; execution not established): pwd"] if carried else [])
        assert [line for line in result.ledger.splitlines() if line.startswith("- ")] == [
            *expected, "- write_file a.py: confirmed written"]
    assert records[0] != records[1]


def test_definition_replacement_is_explicit_and_not_production_certification():
    # Exercise the declared hardening stage with the same request and services:
    # the replacement leaves the raw reply untouched, whereas the default
    # validates and withholds it when no judge is available.
    body, raw = {"messages": history()}, completion("unverified prose")
    facts, svc, settled = memory.SessionFacts(), services(), []
    kwargs = dict(selected=True, chat_fn=None, role=None, rlog=Log(),
                  settle=lambda *args: settled.append(args))
    default = memory.DEFINITION.execute(raw, body, facts, svc, **kwargs)
    assert default.effect is Effect.WITHHELD
    assert "unverified prose" not in memory.completion_text(default.completion)
    assert len(settled) == 1

    def replacement_stage(completion, body, facts, services, **kwargs):
        return memory.HandoffResult(completion, Effect.NO_OP)

    replacement = replace(memory.DEFINITION, execute=replacement_stage)
    result = replacement.execute(raw, body, facts, svc, **kwargs)
    assert result.completion is raw and result.effect is Effect.NO_OP
    assert len(settled) == 1  # no stale producer settlement from the replaced stage
    assert not memory.POLICY.migrated
    assert memory.POLICY.family_id == "F49"


@pytest.mark.parametrize("retry_text,retry_finish", [
    ('<tool_call>{"name":"write_file","arguments":{"path":"fake.py","content":"never written"}}</tool_call>', "stop"),
    ("cut retry cannot become memory", "length"),
])
def test_pseudo_call_or_cut_retry_is_withheld_instead_of_becoming_harness_memory(retry_text, retry_finish):
    # Synthetic version of the empty/pseudo-write briefing incident: neither a
    # second pseudo call nor a length-cut retry may become the harness's memory.
    calls, settled = [], []
    def chat(body, log):
        calls.append(copy.deepcopy(body))
        return json.dumps(completion(retry_text, retry_finish))
    first = completion('<tool_call>{"name":"write_file","arguments":{"path":"ghost.py","content":"x"}}</tool_call>')
    result = memory.harden(first, {"messages": history(), "max_tokens": None},
                           memory.SessionFacts(original_task="Implement all original deliverables"),
                           services(), selected=True, chat_fn=chat, role=None, rlog=Log(),
                           settle=lambda *args: settled.append(args))
    assert len(calls) == 1
    assert result.effect is Effect.WITHHELD and result.prose == ""
    assert result.ledger.splitlines()[-1] == "- write_file a.py: confirmed written"
    text = memory.completion_text(result.completion)
    assert "ghost.py" not in text and "fake.py" not in text and "cut retry" not in text
    assert text == memory.indicators.PROSE_DROPPED_MARKER + "\n" + result.ledger
    assert settled == [(text, result.ledger, True)]


@pytest.mark.parametrize("reject_lens,answer,expected_calls", [
    ("retrospective", "UNDECIDABLE", 1),
    ("scope", "NARROWS", 2),
    ("fidelity", "UNFAITHFUL", 3),
])
def test_each_independent_lens_can_withhold_without_changing_original_task(reject_lens, answer, expected_calls):
    calls = []
    systems = {prompts.load("compaction_validate_retrospective"): "retrospective",
               prompts.load("compaction_validate_scope"): "scope",
               prompts.load("compaction_validate"): "fidelity"}
    def chat(body, log):
        calls.append(copy.deepcopy(body))
        lens = next(name for prompt, name in systems.items() if body["messages"][0]["content"].startswith(prompt))
        positive = {"retrospective": "RETROSPECTIVE", "scope": "PRESERVES", "fidelity": "FAITHFUL"}
        return json.dumps(completion(answer if lens == reject_lens else positive[lens]))
    result = memory.harden(completion("Claimed work"), {"messages": history()},
                           memory.SessionFacts(original_task="Implement all original deliverables"),
                           services(), selected=True, chat_fn=chat,
                           role=Role(name="reasoner", backend="fixture"), rlog=Log(),
                           settle=lambda *args: None)
    assert len(calls) == expected_calls
    assert result.effect is Effect.WITHHELD and result.prose == ""
    assert "Claimed work" not in memory.completion_text(result.completion)
    assert result.ledger.splitlines()[-1] == "- write_file a.py: confirmed written"
    if expected_calls >= 2:
        assert "Implement all original deliverables" in str(calls[1]["messages"])
    if expected_calls == 3:
        assert "Wrote a.py" in str(calls[2]["messages"])
        assert "Summarize with next steps" not in str(calls[2]["messages"])


def test_rejected_handoff_ledger_correlates_results_by_id_not_result_order():
    from cria import denial
    calls = [{"id": name, "type": "function", "function": {"name": "write_file",
              "arguments": json.dumps({"path": name + ".py", "content": name + "=1\n"})}}
             for name in ("a", "b", "c", "d")]
    messages = [
        {"role": "user", "content": "Implement all original deliverables"},
        {"role": "assistant", "tool_calls": calls},
        {"role": "tool", "tool_call_id": "b", "content": denial.mark("not run")},
        {"role": "tool", "tool_call_id": "c", "content": "opaque acknowledgement"},
        {"role": "tool", "tool_call_id": "a", "content": "Wrote a.py"},
        {"role": "user", "content": "Summarize with next steps for continuation"},
    ]
    before, settled = copy.deepcopy(messages), []
    result = memory.harden(completion("Unsupported success account"), {"messages": messages},
                           memory.SessionFacts(), services(), selected=True, chat_fn=None,
                           role=None, rlog=Log(), settle=lambda *args: settled.append(args))
    assert result.effect is Effect.WITHHELD and result.prose == ""
    assert [line for line in result.ledger.splitlines() if line.startswith("- ")] == [
        "- write_file a.py: confirmed written",
        "- write_file b.py: refused, not written",
        "- write_file c.py: no confirmation recorded",
        "- write_file d.py: no result recorded",
    ]
    assert "Unsupported success account" not in memory.completion_text(result.completion)
    assert settled == [(memory.completion_text(result.completion), result.ledger, True)]
    assert messages == before


@pytest.mark.parametrize("prose", [
    "Historical account ",
    "\n\tHistorical account  \t\n",
    "\n".join(f"Historical observation {i}: " + "old " * 12 for i in range(110)),
], ids=["trailing-space", "leading-and-trailing", "historical-C21-shape"])
def test_retained_prose_authority_matches_exact_unchanged_completion_bytes(prose):
    # The real C21 historical-record shape ends in one space. Validation reads
    # normalized working text, but that must not become a false statement about
    # the exact completion which the caller actually retains and authenticates.
    original = completion(prose)
    before = copy.deepcopy(original)
    provider, settled = Provider(), []
    result = memory.harden(original, {"messages": history()},
                           memory.SessionFacts(original_task="Implement all original deliverables"),
                           services(), selected=True, chat_fn=provider.chat,
                           role=Role(name="reasoner", backend="fixture"), rlog=Log(),
                           settle=lambda *args: settled.append(args))
    assert result.effect is Effect.DELIVERED and result.ledger == ""
    assert result.completion is original and original == before
    assert memory.completion_text(result.completion).encode() == prose.encode()
    assert result.prose.encode() == prose.encode()
    assert settled == [(prose, "", False)]
    assert len(provider.calls) == 3


def test_retained_prose_authority_matches_exact_successful_retry_bytes():
    prose = "\nHistorical retry account \t\n"
    provider, settled = Provider(retry=prose), []
    result = memory.harden(completion(""), {"messages": history()},
                           memory.SessionFacts(original_task="Implement all original deliverables"),
                           services(), selected=True, chat_fn=provider.chat,
                           role=Role(name="reasoner", backend="fixture"), rlog=Log(),
                           settle=lambda *args: settled.append(args))
    assert result.effect is Effect.DELIVERED and result.ledger == ""
    assert memory.completion_text(result.completion).encode() == prose.encode()
    assert result.prose.encode() == prose.encode()
    assert settled == [(prose, "", False)]
    assert len(provider.calls) == 4
