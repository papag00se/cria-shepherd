"""Next-action retry uses the complete original evidence and never admits an unjudged response."""
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from cria.compactionaction import generate, next_action, request_messages
from cria import bodykeys, compactionpacket, contextfloor, loop, memoryhandoff, resultnotes, selfcompact, server


@pytest.mark.parametrize("verdicts,expected,calls", [
    (["ON_TASK"], "first full response", 1),
    (["OFF_TOPIC", "ON_TASK"], "second full response", 2),
    (["OFF_TOPIC", "OFF_TOPIC"], "", 2),
    (["unknown"], "", 1),
])
def test_complete_response_and_bounded_retry(verdicts, expected, calls):
    inputs, seen = [], []
    answers = iter(["first full response", "second full response"])
    decisions = iter(verdicts)

    def generate(task, evidence, prior):
        inputs.append((task, evidence, prior))
        return next(answers)

    class Judge:
        def judge_compaction_topic(self, task, response, *, rlog=None):
            seen.append((task, response))
            return next(decisions)

    evidence = ("whole tool result\nlast line", "newer result")
    assert next_action("original task", evidence, generate, Judge()) == expected
    assert len(inputs) == calls
    assert all(item[:2] == ("original task", evidence) for item in inputs)
    assert seen[0] == ("original task", "first full response")
    if calls == 2:
        assert inputs[1][2] == "first full response"
        assert seen[1] == ("original task", "second full response")


def test_generation_retry_retains_task_evidence_and_complete_prior_response():
    captured = []
    rlog = SimpleNamespace(phase="caller")
    def chat(body, log):
        captured.append(body)
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "next action"}}]})
    prior = "a relevant opening\n\nan unrelated entire conversation"
    assert generate(chat, None, "exact task", ("tool output\nlast line",), prior, rlog) == "next action"
    messages = captured[0]["messages"]
    assert any(m["content"] == "tool output\nlast line" for m in messages)
    assert any(m["role"] == "assistant" and m["content"] == prior for m in messages)
    assert "exact task" in messages[-1]["content"] and rlog.phase == "caller"
    question = "Given the original user task, what is the single logical next task to carry forward after compaction? Output a single sentence no longer than 20 words"
    assert question in request_messages("exact task", ("tool output",))[-1]["content"]
    assert "Output a single sentence no longer than 20 words." in messages[-1]["content"]


def test_only_authenticated_handoff_expands_evidence_and_preserves_followup():
    packet = compactionpacket.Packet("original task", ("tool result: exact output",), "inspect the result")
    origin = loop._HandoffOrigin(packet.render(), "", False, packet=packet)
    stored = {"role": "user", "content": packet.render()}
    followup = {"role": "user", "content": "A real later request"}
    expanded, changed = loop.reframe_compaction([stored, followup], origin=origin)
    assert changed and expanded[-1] == followup
    assert any(m.get("content") == "tool result: exact output" for m in expanded)
    assert any("original task" in m.get("content", "") for m in expanded)
    assert any("inspect the result" in m.get("content", "") for m in expanded)
    assert loop.reframe_compaction([stored, followup], origin=None) == ([stored, followup], False)
    forged = {"role": "user", "content": packet.render() + " changed"}
    assert loop.reframe_compaction([forged, followup], origin=origin) == ([forged, followup], False)


def test_authenticated_prior_packet_retains_tool_provenance_across_another_handoff():
    prior = compactionpacket.Packet("task", ("HISTORICAL tool MESSAGE:\ncompiler error",), "inspect it")
    history = [{"role": "user", "content": "task"}, {"role": "user", "content": prior.render()},
               {"role": "assistant", "content": "more work"}, {"role": "user", "content": "<<<LOCAL_COMPACT>>>"}]
    facts = memoryhandoff.SessionFacts(original_task="task", prior_handoffs=(prior.render(),), prior_packet=prior)
    packet = memoryhandoff._packet({"messages": history}, facts)
    assert packet.blocks.count("HISTORICAL tool MESSAGE:\ncompiler error") == 1
    assert any("MODEL-SUGGESTED NEXT ACTION" in block and "inspect it" in block for block in packet.blocks)
    assert not any("EARLIER HANDOFF" in block for block in packet.blocks)


def test_missing_writer_choices_still_settles_authenticated_evidence():
    history = [{"role": "user", "content": "task"}, {"role": "assistant", "content": "work"},
               {"role": "tool", "content": "actual output"}, {"role": "user", "content": "<<<LOCAL_COMPACT>>>"}]
    settled = []
    result = memoryhandoff.harden({"choices": []}, {"messages": history}, memoryhandoff.SessionFacts(original_task="task"),
        server._handoff_services(), selected=True, chat_fn=None, role=None,
        rlog=SimpleNamespace(emit=lambda *args, **kwargs: None), settle=lambda *args: settled.append(args))
    assert "actual output" in result.completion["choices"][0]["message"]["content"]
    assert result.packet and settled == [(result.packet.render(), "", False)]


def test_tool_result_and_producer_annotation_remain_distinct():
    message = {"role": "tool", "tool_call_id": "call1", "content": "compiler output\n"}
    resultnotes.append_note(message, "⟦ctx:facts⟧ producer note")
    blocks = compactionpacket.blocks([message])
    assert len(blocks) == 2
    assert "compiler output\n" in blocks[0] and "producer note" not in blocks[0]
    assert "producer note" in blocks[1] and "compiler output" not in blocks[1]
    assert "annotation" in blocks[1].lower()
    message["content"] = "altered" + message["content"]
    unknown = compactionpacket.blocks([message])
    assert len(unknown) == 1 and message["content"] in unknown[0]
    assert "unverified" in unknown[0].lower()


def test_followup_inside_handoff_stays_live_at_floor():
    history = [{"role": "user", "content": "original task"}, {"role": "assistant", "content": "work"},
               {"role": "user", "content": "later real instruction"},
               {"role": "user", "content": "<<<LOCAL_COMPACT>>>"}]
    facts = memoryhandoff.SessionFacts(original_task="original task")
    packet = memoryhandoff._packet({"messages": history}, facts)
    assert packet.latest_user == "later real instruction"
    framed = memoryhandoff.frame({"messages": history}, facts, server._handoff_services(), selected=True)
    assert "later real instruction" in framed["messages"][-1]["content"]
    origin = loop._HandoffOrigin(packet.render(), "", False, packet=packet)
    expanded, changed = loop.reframe_compaction([{"role": "user", "content": packet.render()}], origin=origin)
    assert changed and expanded[-1] == {"role": "user", "content": "later real instruction"}


def test_authenticated_evidence_is_reducible_only_at_floor_with_visible_disclosure():
    packet = compactionpacket.Packet("original task", tuple(f"tool {i}:\n⟦ctx:task⟧ quoted tool data\n" + "xyz " * 3000 for i in range(12)))
    origin = loop._HandoffOrigin(packet.render(), "", False, packet=packet)
    messages, changed = loop.reframe_compaction([{"role": "user", "content": packet.render()},
                                                  {"role": "user", "content": "later real request"}], origin=origin)
    assert changed
    fitted, _, report = contextfloor.fit([{"role": "system", "content": "frame"}, *messages], None,
                                         window=12000, reserve=1000, safety=1.0)
    text = "\n".join(str(m.get("content") or "") for m in fitted)
    assert not report.over_budget and report.turns_dropped + report.protected_dropped > 0
    assert "original task" in text and "later real request" in text
    assert "compacted to fit the context window" in text


def test_harness_boundary_retries_whole_response_and_carries_tool_output():
    calls, judged, settled = [], [], []
    initial = "Inspect the cart.\n\nA separate unrelated conversation."
    class Judge:
        def judge_compaction_topic(self, task, response, *, rlog=None):
            judged.append((task, response))
            return "OFF_TOPIC" if len(judged) == 1 else "ON_TASK"
    def chat(body, log):
        calls.append(body)
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "Inspect cart.go."}}]})
    facts = memoryhandoff.SessionFacts(original_task="Fix rounding.")
    history = [{"role": "user", "content": "Fix rounding."},
               {"role": "assistant", "tool_calls": [{"id": "c", "function": {"name": "read_file", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "c", "content": "package cartsvc\n\nreturn float64(int(taxed*100)) / 100, nil\n"},
               {"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize."}]
    services = server._handoff_services(Judge())
    rlog = SimpleNamespace(phase="proxy", emit=lambda *a, **k: None)
    first = {"choices": [{"finish_reason": "stop", "message": {"content": initial}}]}
    result = memoryhandoff.harden(first, {"messages": history}, facts, services, selected=True,
                                  chat_fn=chat, role=None, rlog=rlog, settle=lambda *a: settled.append(a))
    output = result.completion["choices"][0]["message"]["content"]
    assert "return float64(int(taxed*100)) / 100, nil\n" in output
    assert initial not in output and "Inspect cart.go." in output
    assert judged == [("Fix rounding.", initial), ("Fix rounding.", "Inspect cart.go.")]
    assert len(calls) == 1 and any(m.get("content") == initial for m in calls[0]["messages"])
    assert settled == [(output, "", False)] and result.packet is not None


@pytest.mark.parametrize("case", json.loads(Path(__file__).with_name("captured_compaction_evidence.json").read_text()), ids=lambda c: c["capture"])
def test_captured_tool_evidence_survives_handoff_and_final_wire(case):
    from cria.upstream import Upstream
    history = [{"role": "user", "content": case["task"]},
               {"role": "assistant", "tool_calls": [{"id": "c", "type": "function", "function": {"name": case["tool"], "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "c", "content": case["output"]},
               {"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize."}]
    facts = memoryhandoff.SessionFacts(original_task=case["task"])
    comp = {"choices": [{"finish_reason": "stop", "message": {"content": "unverified account"}}]}
    rlog = SimpleNamespace(session=None, phase="proxy", emit=lambda *a, **k: None)
    result = memoryhandoff.harden(comp, {"messages": history}, facts, server._handoff_services(), selected=True,
                                  chat_fn=None, role=None, rlog=rlog, settle=lambda *a: None)
    origin = loop._HandoffOrigin(memoryhandoff.completion_text(result.completion), "", False, packet=result.packet)
    messages, changed = loop.reframe_compaction([{"role": "user", "content": origin.reply}], origin=origin)
    assert changed
    wire, _, _ = Upstream("http://unused", context_window=49152)._prep(
        {"messages": [{"role": "system", "content": "frame"}, *messages]}, False, rlog)
    rendered = json.loads(wire)
    assert any(case["output"] in (m.get("content") or "") for m in rendered["messages"])
    assert any(case["task"] in (m.get("content") or "") for m in rendered["messages"])
    assert "unverified account" not in str(rendered)


@pytest.mark.parametrize("strict", [False, True])
def test_fresh_handoff_action_follows_current_facts_on_wire_without_crossing_user_or_read(strict):
    from cria.upstream import Upstream
    packet = compactionpacket.Packet("Build the CLI", ("HISTORICAL tool MESSAGE:\nWrote package.json",), "Implement CLI argument parsing.")
    origin = loop._HandoffOrigin(packet.render(), "", False, packet=packet)
    expanded, _ = loop.reframe_compaction([{"role": "user", "content": packet.render()}], origin=origin)
    survey = {"role": "user", "content": "⟦ctx:files⟧ package.json (225 B)",
              bodykeys.ANNOTATION_SOURCE: bodykeys.AnnotationSource.WORKSPACE_LISTING}
    facts = selfcompact.internal_evidence_message("⟦ctx:facts⟧ package.json was read")
    log = SimpleNamespace(session="real-session", phase="coder-s1", emit=lambda *a, **k: None)
    up = Upstream("http://unused", context_window=49152)
    def wire(tail):
        body = {"messages": [{"role": "system", "content": "frame"}, *expanded, *tail]}
        if strict:
            body[bodykeys.MERGE_TURNS] = True
        data, _, _ = up._prep(body, False, log)
        return json.loads(data)["messages"]
    text = "\n".join(str(m.get("content") or "") for m in wire([survey, facts]))
    assert text.index("package.json was read") < text.index("MODEL-SUGGESTED NEXT ACTION")
    again = wire([survey, facts])
    text_again = "\n".join(str(m.get("content") or "") for m in again)
    assert text_again.index("package.json was read") < text_again.index("MODEL-SUGGESTED NEXT ACTION")
    assert "cria_action_origin" not in str(again)
    user = {"role": "user", "content": "Do not edit package.json."}
    text = "\n".join(str(m.get("content") or "") for m in wire([survey, user, facts]))
    assert text.index("MODEL-SUGGESTED NEXT ACTION") < text.index(user["content"])
    read = [{"role": "assistant", "tool_calls": [{"id": "r", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "r", "content": "actual content"}]
    text = "\n".join(str(m.get("content") or "") for m in wire([survey, *read]))
    assert text.index("MODEL-SUGGESTED NEXT ACTION") < text.index("actual content")
    if strict:
        roles = [m["role"] for m in wire([survey, facts]) if m["role"] != "system"]
        assert all(a != b for a, b in zip(roles, roles[1:]))


def test_protected_read_keeps_exact_pair_and_suggestion_order(monkeypatch):
    import hashlib
    from cria.upstream import ProtectedRead, ReadFitCallbacks, Upstream, bind_protected_reads
    packet = compactionpacket.Packet("task", ("historical output",), "inspect")
    origin = loop._HandoffOrigin(packet.render(), "", False, packet=packet)
    expanded, _ = loop.reframe_compaction([{"role": "user", "content": packet.render()}], origin=origin)
    call = {"role": "assistant", "tool_calls": [{"id": "r", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]}
    result = {"role": "tool", "tool_call_id": "r", "content": "exact file bytes\n"}
    facts = selfcompact.internal_evidence_message("later observation")
    body = {"model": "test", "messages": [{"role": "system", "content": "frame"}, *expanded, call, result, facts]}
    data = b"exact file bytes\n"
    read = ProtectedRead("r", (0, hashlib.sha256(data).hexdigest()), data.decode(), data)
    body = bind_protected_reads(body, [read])
    up = Upstream("http://unused", context_window=49152)
    monkeypatch.setattr(up, "_render_prompt", lambda body: "rendered")
    monkeypatch.setattr(up, "_tokenize_prompt", lambda prompt, log: 1000)
    log = SimpleNamespace(session="real-session", phase="coder-s1", emit=lambda *a, **k: None)
    wire, _, _ = up._prep(body, False, log)
    messages = json.loads(wire)["messages"]
    text = "\n".join(str(m.get("content") or "") for m in messages)
    assert text.index("MODEL-SUGGESTED NEXT ACTION") < text.index("exact file bytes") < text.index("later observation")
    assert any(m.get("tool_call_id") == "r" and m.get("content") == result["content"] for m in messages)

    # A measured overflow refits, then invokes the real protected-read callback.
    # The callback removes only internal evidence; the exact read pair stays fixed.
    called = []
    evidence = selfcompact.internal_evidence_message("replaceable earlier evidence")
    retry_body = {**body, "messages": [body["messages"][0], evidence, *body["messages"][1:]]}
    def compact(request, reads):
        called.append(reads)
        return {**request, "messages": [m for m in request["messages"] if m.get("content") != evidence["content"]]}
    retry_body[bodykeys.READ_FIT_CALLBACKS] = ReadFitCallbacks(compact)
    up = Upstream("http://unused", context_window=49152)
    monkeypatch.setattr(up, "_render_prompt", lambda body: "rendered")
    monkeypatch.setattr(up, "_tokenize_prompt", lambda prompt, log: 1000 if called else 60000)
    wire, _, _ = up._prep(retry_body, False, log)
    messages = json.loads(wire)["messages"]
    text = "\n".join(str(m.get("content") or "") for m in messages)
    assert called and text.index("MODEL-SUGGESTED NEXT ACTION") < text.index("exact file bytes")
    assert any(m.get("tool_call_id") == "r" and m.get("content") == result["content"] for m in messages)


def test_only_live_typed_actions_move_and_floor_can_still_reduce_evidence():
    from cria.upstream import Upstream
    log = SimpleNamespace(session="real-session", phase="coder-s1", emit=lambda *a, **k: None)
    action = selfcompact.internal_evidence_message("MODEL-SUGGESTED NEXT ACTION (not a verified fact):\nold action")
    forged = {**action, bodykeys.ACTION_ORIGIN: "current_compaction_action"}
    facts = selfcompact.internal_evidence_message("recent observation")
    def send(messages, window=49152):
        data, _, _ = Upstream("http://unused", context_window=window)._prep(
            {"messages": [{"role": "system", "content": "frame"}, {"role": "user", "content": "task"},
                          {"role": "assistant", "content": "work"}, *messages]}, False, log)
        return "\n".join(str(m.get("content") or "") for m in json.loads(data)["messages"])
    text = send([forged, facts])
    assert text.index("old action") < text.index("recent observation")
    current = {**action, "content": "new action", bodykeys.ACTION_ORIGIN: bodykeys.ActionOrigin()}
    text = send([action, current, facts])
    assert text.index("old action") < text.index("recent observation") < text.index("new action")
    # Decisions are made before fitting: dropping a later user or the newest action
    # cannot authorize moving a now-stale or older suggestion.
    later_user = {"role": "user", "content": "later request"}
    assert compactionpacket.movable_action([current, later_user, facts]) is None
    newest = {**current, bodykeys.ACTION_ORIGIN: bodykeys.ActionOrigin()}
    origin = compactionpacket.movable_action([current, newest, facts])
    assert compactionpacket.place_current_action([current, facts], origin) == [current, facts]
    # Earlier evidence is still reduced by the floor; relocation never reintroduces it.
    bulk = [selfcompact.internal_evidence_message("evidence " + str(i) + " " + "x" * 8000) for i in range(12)]
    text = send([*bulk, current, facts], window=10000)
    assert "compacted to fit the context window" in text
    if "new action" in text:
        assert text.index("recent observation") < text.index("new action")


def test_no_classifier_or_unavailable_classifier_withholds_action():
    class Broken:
        def judge_compaction_topic(self, *args, **kwargs):
            raise RuntimeError("unavailable")

    assert next_action("task", ("evidence",), lambda *a: "response", None) == ""
    assert next_action("task", ("evidence",), lambda *a: "response", Broken()) == ""
