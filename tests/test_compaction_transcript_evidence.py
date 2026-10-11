"""F3 — the harness-compaction transcript must not feed empty or result-less turns to the writer.

Incident: phi4 / feed-pipeline-java CALL 0006 (capture 20261010T083620-01a12675-…). The briefing
writer's evidence held six blocks that were literally `assistant: ` (cria's ⟦cria⟧ status messages,
blanked by `strip_history`) and `assistant: exec_command({"cmd": "mvn -q compile\\nmvn test", …})`
with no output — cria's OWN gate launch, whose raw result is excluded as an anchor, rendered as a
coder action nobody saw the result of. The writer said "the results are not provided" and the scope
validator returned NARROWS, so the harness's whole remembered past was empty.
"""
import json
from pathlib import Path

from cria import indicators, probegate, responses, selfcompact, server

FIX = Path(__file__).parent / "fixtures" / "phi4_java_loop"


def _incident_messages():
    rbody = json.loads((FIX / "inbound-e6c63812-responses.json").read_text())
    body = responses.to_chat_body(rbody)
    msgs, _ = indicators.strip_history(body["messages"])
    return server._compaction_messages(msgs)


def test_the_captured_call_0006_input_had_the_defect():
    prompt = (FIX / "call0006-proxy.prompt.txt").read_text()
    # rendered phi4 template: each evidence block is its own user turn
    assert prompt.count("<|im_sep|>assistant: <|im_end|>") + prompt.count("assistant: <|im_end|>") >= 6
    assert '<|im_sep|>assistant: exec_command({"cmd": "mvn -q compile\\nmvn test"' in prompt


def test_the_real_incident_transcript_has_no_empty_turn_and_no_resultless_gate_call():
    messages = _incident_messages()
    # the defect inputs are really present: blanked status turns, and cria's stamped gate calls
    assert sum(1 for m in messages if m["role"] == "assistant" and not m.get("tool_calls")
               and not (m.get("content") or "").strip()) >= 6
    gate_ids = probegate.gate_call_ids(messages)
    assert gate_ids and not any(m.get("tool_call_id") in gate_ids for m in messages)  # results anchor-filtered

    parts = selfcompact.compaction_request_parts(messages)
    assert all(p.split(":", 1)[1].strip() for p in parts)         # no `role: ` with nothing after it
    assert not any("exec_command(" in p or "mvn -q compile" in p or "ctx:gate" in p for p in parts)
    assert parts[0].startswith("user: Working environment")          # the real evidence is intact, in order
    assert parts[1].startswith("user: Fix these three problems in the supplier feed importer")
    assert len(parts) == 2
    # the legacy single-string composer reads the same owner
    flat = selfcompact.compaction_request(messages)
    assert "assistant: \n" not in flat and "exec_command(" not in flat


def test_every_consumer_reads_the_one_evidence_owner():
    messages = _incident_messages()
    blocks = [m["content"] for m in selfcompact.compaction_request_messages(messages)]
    assert not any(b.strip() == "assistant:" for b in blocks)
    assert not any("exec_command(" in b for b in blocks)


def test_the_coders_own_calls_and_their_results_are_untouched():
    msgs = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "exec_command",
                                                          "arguments": json.dumps({"cmd": "ls src"})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "Output:\nFeed.java"},
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "I read the directory."},
    ]
    parts = selfcompact.compaction_request_parts(msgs)
    assert parts == ['user: task', 'assistant: exec_command({"cmd": "ls src"})',
                     'tool: Output:\nFeed.java', 'assistant: I read the directory.']


def test_a_gate_call_whose_result_is_present_is_left_to_the_cleaner():
    messages = _incident_messages()
    gate_ids = probegate.gate_call_ids(messages)
    answered = messages + [{"role": "tool", "tool_call_id": next(iter(gate_ids)), "content": "x"}]
    # an ANSWERED gate call is not dropped by the unanswered-call rule
    kept = selfcompact._drop_unanswered_gate_calls(answered)
    ids = {tc["id"] for m in kept for tc in m.get("tool_calls") or []}
    assert next(iter(gate_ids)) in ids
    assert len(ids) == 1                       # only that one: the unanswered siblings are gone


def test_an_empty_coder_tool_result_is_evidence_and_still_renders():
    """Review of d37f8b32: a quiet command's empty result is a real `tool: ` line, not a blank turn."""
    msgs = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "shell",
                                                          "arguments": json.dumps({"cmd": "touch a.txt"})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": ""},
        {"role": "assistant", "content": "done"},
        {"role": "assistant", "content": ""},
    ]
    assert selfcompact.compaction_request_parts(msgs) == [
        "user: task", 'assistant: shell({"cmd": "touch a.txt"})', "tool: ", "assistant: done"]
