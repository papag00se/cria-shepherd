"""Public producer witnesses for the selected harness-memory lifecycle.

Uses real server response methods and real session storage with scripted
in-process providers. No HTTP listener, model, executor, or reconstructed origin.
The two accepted source-oracle files retain their independent literal assertions.
"""
import copy
from dataclasses import replace

import pytest

from cria import assistruntime, memoryhandoff as memory, server
from cria.memoryeffects import Effect
from tests.test_harness_memory_boundaries import ResponseProvider, response_handler
from tests.test_harness_memory_source import Log, completion, history


def selected_root(definition=memory.DEFINITION, *, disabled=False, empty=False):
    definitions = () if empty else (definition,)
    return assistruntime.AssistRuntime.select(
        level=3, registrations=definitions,
        disabled=(definition.policy.id,) if disabled else ())


def setup_response(root, key):
    provider = ResponseProvider(completion("Initial upstream account"))
    handler, session = response_handler(provider, key)
    handler.server.pilot_runtime = root
    session.write_call_ids = ["w"]
    session.write_result_ids = set()
    return handler, session, provider


def produce(handler, body, log, key, stream):
    if stream:
        return b"".join(handler._produce_stream(body, log))
    return handler._produce_completion(body, log, key)[0]


@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "streaming"])
def test_exact_one_selected_definition_controls_recognition_framing_and_admitted_hardening(stream):
    events = []
    def recognize(body, **kwargs):
        assert kwargs["selected"] is True
        events.append("recognize")
        return True
    def frame(body, facts, services, *, selected):
        assert selected is True
        assert facts.original_task == "Implement all original deliverables"
        events.append("frame")
        return {**body, "messages": [{"role": "system", "content": "Selected handoff frame"},
                                      *body["messages"]]}
    def harden(comp, body, facts, services, **kwargs):
        assert kwargs["selected"] is True
        assert session.write_result_ids == {"w"}
        assert facts.original_task == "Implement all original deliverables"
        events.append("harden")
        result = completion("Selected retained handoff")
        kwargs["settle"]("Selected retained handoff", "", False)
        return memory.HandoffResult(result, Effect.DELIVERED, "Selected retained handoff", "")
    definition = replace(memory.DEFINITION, recognize=recognize, frame=frame, execute=harden)
    root = selected_root(definition)
    key = "sid:selected-handoff-" + str(stream)
    handler, session, provider = setup_response(root, key)
    body = {"messages": history()}
    original = copy.deepcopy(body)
    with assistruntime.bound(root):
        output = produce(handler, body, Log(), key, stream)
    calls = provider.stream_calls if stream else provider.calls
    assert calls[0]["messages"][0] == {"role": "system", "content": "Selected handoff frame"}
    assert events == (["recognize", "frame"] if stream else ["recognize", "frame", "harden"])
    assert len(calls) == 1  # replacements do not inherit the old recognizer or validator
    if stream:
        assert b"Initial upstream account" in output
        assert session.handoff_origin is None
    else:
        assert output["choices"][0]["message"]["content"] == "Selected retained handoff"
        assert session.handoff_origin.reply == "Selected retained handoff"
        assert session.handoff_origin.dropped is False
    assert body == original


@pytest.mark.parametrize("mode", ["empty", "disabled"])
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "streaming"])
def test_absent_selected_policy_is_lazy_but_required_write_result_observation_survives(monkeypatch, mode, stream):
    def forbidden(*args, **kwargs):
        raise AssertionError("absent optional lifecycle gathered evidence or executed")
    definition = replace(memory.DEFINITION, recognize=forbidden, frame=forbidden, execute=forbidden)
    root = selected_root(definition, disabled=mode == "disabled", empty=mode == "empty")
    key = "sid:absent-handoff-" + mode + str(stream)
    handler, session, provider = setup_response(root, key)
    for name in ("_workspace_listing", "_last_checks_note"):
        monkeypatch.setattr(server, name, forbidden)
    monkeypatch.setattr(server.groundtruth, "workspace_inventory", forbidden)
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    with assistruntime.bound(root):
        output = produce(handler, body, Log(), key, stream)
    assert session.write_result_ids == {"w"}
    assert session.handoff_origin is None
    calls = provider.stream_calls if stream else provider.calls
    assert len(calls) == 1
    assert calls[0]["messages"] == body["messages"][1:]  # ordinary proxy frame only
    if stream:
        assert b"Initial upstream account" in output
    else:
        assert output["choices"][0]["message"]["content"] == "Initial upstream account"


@pytest.mark.parametrize("finalization", ["exception", "different-output", "inplace-content-mutation"])
def test_undelivered_or_replaced_buffered_output_cannot_publish_a_producer_record(finalization):
    root = selected_root()
    key = "sid:handoff-interruption-" + finalization
    handler, session, provider = setup_response(root, key)
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    def finalize(comp, *args):
        if finalization == "exception":
            raise RuntimeError("final delivery interrupted")
        if finalization == "inplace-content-mutation":
            comp["choices"][0]["message"]["content"] = "Unrelated returned output"
            return comp
        return completion("Unrelated returned output")
    handler._finalize = finalize
    with assistruntime.bound(root):
        if finalization == "exception":
            with pytest.raises(RuntimeError, match="final delivery interrupted"):
                handler._produce_completion(body, Log(), key)
        else:
            output = handler._produce_completion(body, Log(), key)[0]
            assert output["choices"][0]["message"]["content"] == "Unrelated returned output"
    assert session.handoff_origin is None
    assert session.write_result_ids == {"w"}
    assert len(provider.calls) == 2  # real rejected briefing, then the interrupted/replaced return


def test_selected_frame_replacement_is_also_used_by_real_buffered_retry():
    frames = []
    def selected_frame(body, facts, services, *, selected):
        frames.append(copy.deepcopy(body))
        framed = memory.frame(body, facts, services, selected=selected)
        framed["messages"][0] = {**framed["messages"][0], "content":
                                   "Selected frame used here\n\n" + framed["messages"][0]["content"]}
        return framed
    definition = replace(memory.DEFINITION, frame=selected_frame)
    root = selected_root(definition)
    key = "sid:selected-frame-retry"
    provider = ResponseProvider(completion(""))
    handler, session = response_handler(provider, key)
    handler.server.pilot_runtime = root
    body = {"messages": history(), "max_tokens": None}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    with assistruntime.bound(root):
        output = handler._produce_completion(body, Log(), key)[0]
    assert len(frames) == 2  # first writer AND the one bounded retry
    assert len(provider.calls) == 3  # writer, retry, rejecting retrospective judge
    for call in provider.calls[:2]:
        assert call["messages"][0]["content"].startswith("Selected frame used here\n\n")
    assert provider.calls[1]["max_tokens"] == 8192
    assert "Retrospective account" not in output["choices"][0]["message"]["content"]
    assert session.handoff_origin.dropped is True


def test_default_root_exposes_the_canonical_handoff_not_only_a_source_candidate():
    root = assistruntime.AssistRuntime.select(level=3)
    assert root.harness_memory_handoff is memory.DEFINITION
    assert root.bindings(memory.POLICY.stage) == (memory.DEFINITION,)


def test_projection_preserves_one_exact_lifecycle_and_rejects_partial_replacements():
    definition = replace(memory.DEFINITION, recognize=lambda *a, **k: False)
    assert memory.selected_definition((definition,)) is definition
    assert memory.selected_definition(()) is None
    for definitions in ((definition, definition),
                        (replace(definition, frame=None),),
                        (replace(definition, execute=None),),
                        (replace(definition, recognize=None),),
                        (replace(definition, policy=replace(definition.policy, default_level=2)),)):
        with pytest.raises(ValueError):
            memory.selected_definition(definitions)


def test_explicit_none_helpers_do_not_resurrect_an_active_root_or_hide_required_write_facts(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("explicit None resurrected selected lifecycle")
    definition = replace(memory.DEFINITION, recognize=forbidden, frame=forbidden, execute=forbidden)
    root = selected_root(definition)
    key = "sid:explicit-none-handoff"
    handler, session, provider = setup_response(root, key)
    monkeypatch.setattr(server.groundtruth, "workspace_inventory", forbidden)
    monkeypatch.setattr(server, "_workspace_listing", forbidden)
    body = {"messages": history()}
    raw = completion("Leave this answer intact")
    with assistruntime.bound(root):
        assert not server._recognize_compaction(body, handler.server, Log(), definition=None)
        body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
        assert server._recognize_compaction(body, handler.server, Log(), definition=None)
        assert server._compaction_body(body, definition=None) is body
        assert server._harden_compaction_reply(raw, body, provider, handler.server, Log(), key,
                                               definition=None) is raw
    assert session.write_result_ids == {"w"}
    assert session.handoff_origin is None
    assert provider.calls == []


@pytest.mark.parametrize("bad_settlement", ["wrong-reply", "wrong-ledger", "wrong-dropped", "missing", "duplicate", "wrong-prose", "noop-with-credit"])
def test_replacement_settlement_must_match_its_actual_typed_output(bad_settlement):
    def harden(comp, body, facts, services, **kwargs):
        reply, ledger, dropped = "Selected retained handoff", "", False
        if bad_settlement == "wrong-reply":
            reply = "A different attempted reply"
        elif bad_settlement == "wrong-ledger":
            ledger = "Invented ledger"
        elif bad_settlement == "wrong-dropped":
            dropped = True
        if bad_settlement != "missing":
            kwargs["settle"](reply, ledger, dropped)
            if bad_settlement == "duplicate":
                kwargs["settle"](reply, ledger, dropped)
        if bad_settlement == "noop-with-credit":
            return memory.HandoffResult(completion("Selected retained handoff"), Effect.NO_OP)
        return memory.HandoffResult(completion("Selected retained handoff"), Effect.DELIVERED,
                                     "Different prose" if bad_settlement == "wrong-prose" else "Selected retained handoff", "")
    definition = replace(memory.DEFINITION, execute=harden)
    root = selected_root(definition)
    key = "sid:invalid-source-settlement-" + bad_settlement
    handler, session, provider = setup_response(root, key)
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    with assistruntime.bound(root):
        try:
            handler._produce_completion(body, Log(), key)
        except ValueError:
            pass  # contract rejection may fail the request; it must never publish authority
    assert session.handoff_origin is None
    assert session.write_result_ids == {"w"}
    assert len(provider.calls) == 1


def test_noop_replacement_without_settlement_does_not_create_a_producer_record():
    def harden(comp, body, facts, services, **kwargs):
        return memory.HandoffResult(comp, Effect.NO_OP)
    root = selected_root(replace(memory.DEFINITION, execute=harden))
    key = "sid:noop-handoff"
    handler, session, provider = setup_response(root, key)
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    with assistruntime.bound(root):
        output = handler._produce_completion(body, Log(), key)[0]
    assert output["choices"][0]["message"]["content"] == "Initial upstream account"
    assert session.handoff_origin is None
    assert session.write_result_ids == {"w"}
    assert len(provider.calls) == 1


def test_session_replacement_during_return_cannot_receive_the_previous_session_producer_record():
    root = selected_root()
    key = "sid:session-replaced-on-return"
    handler, session, provider = setup_response(root, key)
    replacement_sessions = []
    def finalize(comp, *args):
        from cria.loop import PlanSession
        # The shared key now addresses a distinct real session, not the one
        # whose transcript and carried ledger were supplied to the hardener.
        replacement = PlanSession(plan=session.plan)
        handler.server.loop._store.put(key, replacement)
        replacement_sessions.append(replacement)
        return comp
    handler._finalize = finalize
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    with assistruntime.bound(root):
        handler._produce_completion(body, Log(), key)
    assert session.handoff_origin is None
    assert replacement_sessions[0].handoff_origin is None
    assert session.write_result_ids == {"w"}
    assert len(provider.calls) == 2


def test_source_retry_framer_bridge_uses_the_supplied_callable_without_extra_inference():
    from tests.test_harness_memory_source import services
    frames = []
    def selected_frame(body, facts, evidence, *, selected):
        frames.append(body)
        result = memory.frame(body, facts, evidence, selected=selected)
        result["messages"][0] = {**result["messages"][0], "content": "Selected retry frame"}
        return result
    provider, settled = ResponseProvider(completion("")), []
    result = memory.harden(completion(""), {"messages": history()}, memory.SessionFacts(),
                           services(), selected=True, chat_fn=provider.chat, role=None, rlog=Log(),
                           frame_hook=selected_frame, settle=lambda *args: settled.append(args))
    assert len(frames) == 1 and len(provider.calls) == 1
    assert provider.calls[0]["messages"][0] == {"role": "system", "content": "Selected retry frame"}
    assert result.effect is Effect.WITHHELD
    assert settled == [(memory.completion_text(result.completion), result.ledger, True)]


def test_interrupted_stream_cannot_publish_a_buffered_handoff_origin():
    root = selected_root()
    key = "sid:interrupted-stream"
    class BrokenStream(ResponseProvider):
        def stream_chat(self, body, log):
            iterator = super().stream_chat(body, log)
            yield next(iterator)
            raise RuntimeError("stream transport interrupted")
    provider = BrokenStream(completion("Partial reply"))
    handler, session = response_handler(provider, key)
    handler.server.pilot_runtime = root
    session.write_call_ids = ["w"]
    session.write_result_ids = set()
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    log = Log()
    with assistruntime.bound(root):
        wire = b"".join(handler._produce_stream(body, log))
    assert b"stream transport interrupted" in wire
    assert any(name == "response.error" for name, _fields in log.events)
    assert session.handoff_origin is None
    assert session.write_result_ids == {"w"}
    assert len(provider.stream_calls) == 1 and provider.calls == []


def test_equal_content_final_copy_retains_authentic_producer_and_restart_abstains():
    from cria import loop
    root = selected_root()
    key = "sid:lossless-final-copy"
    handler, session, provider = setup_response(root, key)
    handler._finalize = lambda comp, *args: copy.deepcopy(comp)
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    with assistruntime.bound(root):
        output = handler._produce_completion(body, Log(), key)[0]
    text = output["choices"][0]["message"]["content"]
    origin = session.handoff_origin
    assert origin.reply == text and origin.dropped is True
    assert origin.ledger.splitlines()[-1] == "- write_file a.py: confirmed written"
    stored = {"role": "user", "content": loop._COMPACTION_MARKER + "\n" + loop._COMPACTION_BOUNDARY + "\n" + text}
    assert server._carried_ledger([stored], origin=origin) == origin.ledger
    assert server._carried_ledger([stored]) == ""  # restart cannot invent producer authority
    following, changed = loop.reframe_compaction([
        {"role": "user", "content": "Implement all original deliverables"}, stored], origin=origin)
    assert changed
    assert server._carried_ledger(following, origin=origin) == origin.ledger
    assert len(provider.calls) == 2


def test_provider_interruption_keeps_prior_real_producer_and_shared_result_facts():
    root = selected_root()
    key = "sid:followup-provider-interruption"
    handler, session, provider = setup_response(root, key)
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    with assistruntime.bound(root):
        first = handler._produce_completion(body, Log(), key)[0]
    origin = session.handoff_origin
    assert origin.reply == first["choices"][0]["message"]["content"]
    session.write_call_ids.append("new")
    followup = copy.deepcopy(body)
    followup["messages"].insert(-1, {"role": "assistant", "tool_calls": [{
        "id": "new", "type": "function", "function": {"name": "write_file",
        "arguments": '{"path":"new.py","content":"new=1\\n"}'}}]})
    followup["messages"].insert(-1, {"role": "tool", "tool_call_id": "new", "content": "Wrote new.py"})
    class InterruptedProvider(ResponseProvider):
        def chat(self, body, log):
            self.calls.append(copy.deepcopy(body))
            raise RuntimeError("provider interrupted")
    broken = InterruptedProvider(completion("unreached"))
    handler._route = lambda *args: (broken, server.Indicator(False, False, "fixture"))
    with assistruntime.bound(root):
        with pytest.raises(RuntimeError, match="provider interrupted"):
            handler._produce_completion(followup, Log(), key)
    assert session.handoff_origin is origin
    assert session.write_result_ids == {"w", "new"}
    assert len(broken.calls) == 1


def test_accepted_whitespace_payload_is_returned_and_authenticated_without_normalizing_bytes():
    root = selected_root()
    key = "sid:accepted-raw-whitespace-payload"
    raw_prose = "\nHistorical account remains exactly as emitted \t\n"
    provider = ResponseProvider(completion(raw_prose))
    provider.verdict = True
    handler, session = response_handler(provider, key)
    handler.server.pilot_runtime = root
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    with assistruntime.bound(root):
        output = handler._produce_completion(body, Log(), key)[0]
    assert output["choices"][0]["message"]["content"].encode() == raw_prose.encode()
    assert session.handoff_origin.reply.encode() == raw_prose.encode()
    assert session.handoff_origin.ledger == "" and session.handoff_origin.dropped is False
    assert len(provider.calls) == 6  # writer, three-lens validation, the change-claim lens and the build-state lens
