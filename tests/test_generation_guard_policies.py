"""Generation policy source cohort: fake byte streams/providers, no sockets or model.

These prove source stages and their transport boundary, not full driver selection.
The accepted legacy parity cases now use independent expected results: public
aliases and retired loop adapters are not independent policy oracles.
"""
import copy
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import bodykeys, generation, generationguards as guards, loop, prompts, upstream


class Log:
    phase = "coder"
    live_chars = 0
    def __init__(self):
        self.events = []
    def emit(self, name, **fields):
        self.events.append((name, fields))


def frame(delta=None, finish=None):
    return {"choices":[{"index":0, "delta":delta or {}, "finish_reason":finish}]}


def arg_delta(args, name="write_file"):
    return {"tool_calls":[{"index":0, "id":"w", "type":"function", "function":{"name":name, "arguments":args}}]}


def wire(frames):
    return [b"data: " + json.dumps(item, ensure_ascii=False).encode() + b"\n\n" for item in frames]


class Response:
    def __init__(self, frames):
        self.frames, self.closed, self.read = wire(frames), False, 0
    def __iter__(self):
        for raw in self.frames:
            self.read += 1
            yield raw
    def close(self):
        self.closed = True


def source_stream(frames, *, window=1000000, prompt=10, guessed=False, watch=None, elapsed=0):
    stream = guards.RUNAWAY.stream(guards.StreamInput(window, prompt, guessed, watch))
    response = Response(frames)
    content, reasoning, log = [], [], Log()
    try:
        for raw in response:
            value = json.loads(raw[5:])
            for choice in value.get("choices", []):
                delta = choice.get("delta") or {}
                content.append(delta.get("content") or "")
                reasoning.append(delta.get("reasoning_content") or delta.get("reasoning") or "")
            out = stream.feed(value, lambda:elapsed, lambda:"".join(reasoning), lambda:"".join(content), log)
            if out.status is guards.StreamStatus.ABORT:
                break
    finally:
        response.close()
    return stream, response, log


def transport_stream(frames, *, window=1000000, prompt=10, guessed=False, watch=None):
    response, log = Response(frames), Log()
    up = upstream.Upstream("http://not-used", context_window=window)
    up._window_guessed = guessed
    with patch.object(up, "_open_with_refit", return_value=(response, prompt, None)), \
         patch.object(up, "_resolve_window", return_value=window):
        completion = json.loads(up.chat_watched({"messages":[], "model":"fake"}, log, watch=watch))
    return completion, response, log


def abort_events(log):
    return [(name, {key:value for key,value in fields.items() if key not in ("assist_id", "family_id")})
            for name,fields in log.events if name == "rumination.abort"]


@pytest.mark.parametrize("kind", ["empty", "degenerate", "window", "reasoning", "content", "length"])
def test_stream_abort_authority(kind):
    watch = None
    window, prompt = 1000000, 10
    if kind == "empty":
        frames = [frame()] * (guards.DEAD_STREAM_CHUNKS + 10)
    elif kind == "degenerate":
        frames = [frame(arg_delta("0" * guards.DEGENERATE_RUN_CHARS))] * 2
    elif kind == "window":
        window, prompt = 110, 100
        frames = [frame({"unknown_parser_shape":"not counted as readable"})] * 15
    else:
        watch = guards.Detector(200).check
        key = "reasoning_content" if kind in ("reasoning", "length") else "content"
        text = "".join(f"analysis{i} " for i in range(120)) if kind == "length" else "actually wait hmm reconsider " * 20
        frames = [frame({key:text})] * 2
    state, response, log = source_stream(frames, window=window, prompt=prompt, watch=watch)
    old, old_response, old_log = transport_stream(frames, window=window, prompt=prompt, watch=watch)
    assert state.aborted == old[bodykeys.RUMINATION]
    assert abort_events(log) == abort_events(old_log)
    assert response.closed and old_response.closed
    assert response.read == old_response.read < len(frames)
    assert not old["choices"][0]["message"].get("tool_calls")
    assert all(fields["assist_id"] == guards.RUNAWAY.policy.id for _,fields in log.events)


def test_clock_and_wire_timeouts_have_their_own_facts():
    state, response, log = source_stream([frame()] * 3, elapsed=181.25)
    assert state.aborted == {"dead_stream":True, "chunks":1, "seconds":181.2}
    assert response.read == 1
    fresh = guards.StreamGuard(guards.StreamInput(None, 0, True))
    out = fresh.wire_timeout(420.55, "read deadline", log)
    assert out.verdict == {"dead_stream":True, "chunks":0, "seconds":420.6, "wire":True}
    assert log.events[-1][1]["error"] == "read deadline"


def test_guessed_window_does_not_cap_legitimate_literal_arguments():
    args = json.dumps({"path":"snow.txt", "content":"".join(f"line {i}: 雪 \\\n" for i in range(1200))}, ensure_ascii=False)
    pieces = [args[i:i+70] for i in range(0,len(args),70)]
    frames = [frame(arg_delta(piece)) for piece in pieces]
    frames[-1]["choices"][0]["finish_reason"] = "tool_calls"
    watched = []
    def scanner(text, tokens):
        watched.append(text)
        return None
    state, response, log = source_stream(frames, window=20, prompt=10, guessed=True, watch=scanner)
    old, _, _ = transport_stream(frames, window=20, prompt=10, guessed=True, watch=scanner)
    assert state.aborted is None
    assert response.read == len(frames)
    assert not watched, "literal tool arguments must never enter the reasoning scanner"
    assert old["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == args
    assert not abort_events(log)


@pytest.mark.parametrize("budget,rate,text,tokens,hits,expected", [
    (1000,3,"actually wait " * 30,600,60, {"hits":60,"reasoning_tokens":600,"arm":"second_guessing"}),
    (1000,3,"actually wait",100,2,None),
    (8192,6,"no markers",9000,0,{"hits":0,"reasoning_tokens":9000,"arm":"length"}),
    (16384,10,"actually " * 10,8254,10,None),
    (0,3,"actually waiting factually reconsideration",100,1,None),
])
def test_detector_parity(budget, rate, text, tokens, hits, expected):
    # rumination is now a direct alias, so comparing it would test the same owner twice.
    assert guards.Detector(budget, rate).check(text, tokens) == expected
    assert guards.count_markers(text) == hits


def test_wide_tail_and_stream_reset_match_original_detector():
    unit = "".join(f"line {i}: calculate({i})\n" for i in range(300))
    repeated = "an unrelated prefix" + unit * 4
    assert guards.degenerate_wide(repeated) is True
    state, response, log = source_stream([frame(arg_delta(repeated))] * 2)
    assert state.aborted == {"degenerate":True, "chars":min(len(repeated), guards.WIDE_RUN_CHARS)}
    assert log.events[-1][1]["wide"] is True
    fresh, _, _ = source_stream([frame({"content":"a new independent turn"}, "stop")])
    assert fresh.aborted is None and fresh.frames == 1
    assert fresh.chars == len("a new independent turn")


def completion(name=None, args="", *, finish="tool_calls", abort=None, content=""):
    message = {"role":"assistant", "content":content}
    if name:
        message["tool_calls"] = [{"id":"w", "type":"function", "function":{"name":name, "arguments":args}}]
    value = {"choices":[{"message":message,"finish_reason":finish}]}
    if abort:
        value[bodykeys.RUMINATION] = abort
    return value


def aborted(verdict):
    return completion(finish="rumination", abort=verdict)


def retry_services(replies, *, role=None):
    replies = iter(copy.deepcopy(replies))
    bodies, log = [], Log()
    def chat(body, rlog):
        bodies.append(copy.deepcopy(body))
        return json.dumps(next(replies), ensure_ascii=False).encode()
    return guards.RetryServices(chat, loop._parse_completion, loop._add_note, log, role), bodies


def clean_events(log):
    return [(name,{key:value for key,value in fields.items() if key not in ("assist_id", "family_id")}) for name,fields in log.events]


@pytest.mark.parametrize("verdict,prompt,fill,event", [
    ({"hits":8,"reasoning_tokens":900,"arm":"second_guessing"}, "rumination_guard",
     {"hits":8,"tokens":900}, {"guard":"rumination","hits":8,"reasoning_tokens":900}),
    ({"hits":0,"reasoning_tokens":4096,"arm":"length"}, "rumination_guard_length",
     {"tokens":4096}, {"guard":"rumination","hits":0,"reasoning_tokens":4096}),
    ({"dead_stream":True,"chunks":400}, "rumination_guard_dead_stream", {}, {"guard":"dead_stream","chunks":400}),
    ({"degenerate":True,"chars":2048}, "rumination_guard_degenerate", {}, {"guard":"degenerate","chars":2048}),
    ({"window_exhausted":True,"room":1000,"frames":920}, "rumination_guard_window",
     {"percent":92}, {"guard":"window_exhausted","room":1000,"frames":920}),
])
def test_runaway_recovery_parity(verdict, prompt, fill, event):
    body = {"messages":[{"role":"user","content":"task"}], "tools":[]}
    replies = [completion(content="next real answer", finish="stop")]
    services, sent = retry_services(replies)
    result = guards.RUNAWAY.execute(guards.RecoveryInput(aborted(verdict), copy.deepcopy(body)), services, None)
    expected = copy.deepcopy(replies[0])
    expected[bodykeys.NOTES] = ["reasoning loop detected — aborted and refocused (1×)"]
    assert result.completion == expected
    assert result.status is guards.RecoveryStatus.RECOVERED and result.attempts == 1
    assert sent == [{"tools":[], "messages":body["messages"] + [
        {"role":"user", "content":prompts.render(prompt, **fill)}]}]
    assert services.log.events == [("loop.rumination", {
        "assist_id":"generation-runaway-guard", "family_id":"F48", "step":None, "attempt":1, **event})]
    assert body["messages"] == [{"role":"user","content":"task"}]


def test_identical_retry_suppression_and_reasoning_isolation():
    role = SimpleNamespace(reasoning="on", think_protocol="chat_template")
    value = aborted({"dead_stream":True,"chunks":400})
    body = {"messages":[{"role":"user","content":"task"}], "tools":[{"type":"function","function":{"name":"read_file"}}],
            "chat_template_kwargs":{"enable_thinking":True,"other":"literal"}}
    original = copy.deepcopy(body)
    services, sent = retry_services([value], role=role)
    result = guards.recover_runaway(guards.RecoveryInput(value,body), services)
    assert result.status is guards.RecoveryStatus.IDENTICAL
    assert len(sent) == 1 and result.attempts == 2
    assert len(sent[0]["messages"]) == 2
    assert sent[0]["chat_template_kwargs"]["enable_thinking"] is False
    assert body == original


def test_quarantined_exhaustion_keeps_original_reply_and_event_bytes():
    body = {"messages":[{"role":"user","content":"task"}],"tools":[]}
    value = generation.safe_completion(aborted({"dead_stream":True,"chunks":400}))
    services, sent = retry_services([value])
    result = guards.recover_runaway(guards.RecoveryInput(copy.deepcopy(value),copy.deepcopy(body)), services)
    expected = copy.deepcopy(value)
    expected.pop(bodykeys.RUMINATION)
    expected["choices"][0]["finish_reason"] = "stop"
    expected[bodykeys.NOTES] = ["reasoning loop detected — aborted and refocused (2×)"]
    assert result.completion == expected
    assert result.status is guards.RecoveryStatus.IDENTICAL and result.attempts == 2
    assert sent == [{"tools":[], "messages":body["messages"] + [
        {"role":"user", "content":prompts.load("rumination_guard_dead_stream")}]}]
    assert clean_events(services.log) == [
        ("loop.rumination", {"step":None,"attempt":1,"guard":"dead_stream","chunks":400}),
        ("loop.rumination", {"step":None,"attempt":2,"guard":"dead_stream","chunks":400}),
        ("loop.rumination_retry_identical", {"level":"warn","attempt":2,"arm":""})]
    assert generation.incomplete(result.completion)
    # Stage cleanup cannot release the retained reply. Required final quarantine
    # restores its incomplete finish without changing the original wire evidence.
    guards.required_quarantine(result.completion)
    expected["choices"][0]["finish_reason"] = "length"
    assert result.completion == expected


def test_changing_arms_exhausts_only_the_original_retry_cap():
    services, sent = retry_services([aborted({"window_exhausted":True}), aborted({"degenerate":True}), aborted({"dead_stream":True})])
    result = guards.recover_runaway(guards.RecoveryInput(aborted({"hits":8,"reasoning_tokens":900}), {"messages":[]}), services)
    assert result.status is guards.RecoveryStatus.EXHAUSTED
    assert result.attempts == len(sent) == guards.MAX_RUMINATION_RETRIES
    assert all(len(body["messages"]) == 1 for body in sent)
    assert bodykeys.RUMINATION not in result.completion


def cuts():
    return guards.CutServices(frozenset(loop._WRITE_TOOLS), frozenset(loop.writeproxy_names), loop._path_of_args)


@pytest.mark.parametrize("first,replies,case", [
    (completion("write_file", '{"path":"x.txt","content":"cut', finish="length"),
     [completion("write_file", '{"path":"x.txt","content":"whole 雪\\n"}')], "length_write"),
    (completion("write_file", '{"path":"x.txt","content":"cut'),
     [completion("write_file", '{"path":"x.txt","content":"whole"}')], "selfcut_write"),
    (completion("exec_command", '{"cmd":"cut'), [], "unknown_command"),
    (completion("edit_file", '{"path":"x.txt","old_string":"x","new_string":"cut', finish="length"),
     [completion("exec_command", '{"cmd":"cut')], "edit_then_command"),
    (completion("write_file", '{"path":"x.txt","content":"cut'),
     [completion("write_file", '{"path":"x.txt","content":"cut')] * 3, "exhausted_write"),
    (completion("write_file", '{"path":"x.txt","content":"whole"}', finish="length"),
     [completion(content="next answer",finish="stop")], "complete_args_at_limit"),
])
def test_truncation_recovery_parity(first, replies, case):
    # The old bodies are retired. These accepted cases independently retain every
    # request, caller-conversation mutation, result, notice and event assertion.
    body = {"messages":[{"role":"user","content":"task"}],"tools":[]}
    original = copy.deepcopy(body)
    services, sent = retry_services(replies)
    result = guards.TRUNCATION.execute(guards.RecoveryInput(copy.deepcopy(first), body), services, cuts())
    withheld = prompts.load_map("truncation_withheld")
    selfcut = prompts.render("truncation_guard_selfcut", path="x.txt", also="")
    edit_size = len('{"path":"x.txt","old_string":"x","new_string":"cut')
    whole_size = len('{"path":"x.txt","content":"whole"}')
    notices = {
        "length_write": [prompts.render("truncation_guard", path="x.txt", limit="the output-token limit",
                                          tool="write_file", also="")],
        "selfcut_write": [selfcut],
        "unknown_command": [],
        "edit_then_command": [prompts.fill(withheld["withheld"], used="the output-token limit", prose=0,
            calls=f"`edit_file` on `x.txt` ({edit_size} characters, arguments cut off at the limit)")],
        "exhausted_write": [selfcut] * 3,
        "complete_args_at_limit": [prompts.fill(withheld["withheld"], used="the output-token limit", prose=0,
            calls=f"`write_file` on `x.txt` ({whole_size} characters, arguments complete)")],
    }[case]
    status, refusal, note, trace = {
        "length_write": (guards.RecoveryStatus.RECOVERED, None, "steered to incremental writes (1×)", [(1,"x.txt",False)]),
        "selfcut_write": (guards.RecoveryStatus.RECOVERED, None, "steered to incremental writes (1×)", [(1,"x.txt",True)]),
        "unknown_command": (guards.RecoveryStatus.REFUSED, "incomplete_args",
            "tool call was cut off mid-arguments — partial call refused", []),
        "edit_then_command": (guards.RecoveryStatus.REFUSED, "truncated_call",
            "output ended before the call was complete — partial call refused", [(1,"x.txt",False),(2,None,True)]),
        "exhausted_write": (guards.RecoveryStatus.EXHAUSTED, "selfcut_write",
            "output stopped early mid-write — partial write refused (retry in smaller pieces)",
            [(1,"x.txt",True),(2,"x.txt",True),(3,"x.txt",True)]),
        "complete_args_at_limit": (guards.RecoveryStatus.RECOVERED, None,
            "steered to incremental writes (1×)", [(1,"x.txt",False)]),
    }[case]
    expected = copy.deepcopy(replies[-1] if replies else first)
    if refusal:
        expected["choices"][0]["message"].pop("tool_calls", None)
    expected[bodykeys.NOTES] = [note]
    assert result.completion == expected
    assert result.status is status and result.attempts == len(notices)
    expected_body = copy.deepcopy(original)
    if refusal:
        expected_body["messages"].append({"role":"user", "content":prompts.load_map("call_refused")[refusal]})
    assert body == expected_body
    assert sent == [{**original, "messages":original["messages"] + [
        {"role":"user", "content":notice} for notice in notices[:i + 1]]} for i in range(len(notices))]
    events = [("loop.truncated", {"steer":"truncation", "step":None, "attempt":i,
                                 "path":path, "output_tokens":None, "selfcut":selfcut}) for i,path,selfcut in trace]
    if case == "unknown_command":
        events = [("loop.incomplete_tool_call_dropped", {"step":None})]
    elif refusal:
        events += [("loop.truncated_dropped", {"step":None}),
                   ("loop.truncated_refused", {"step":None,"wording":refusal,"classification":refusal,
                                               "was_write":case == "exhausted_write"})]
    assert clean_events(services.log) == events
    assert all(fields["assist_id"] == "generation-cut-output-recovery" and fields["family_id"] == "F09"
               for _,fields in services.log.events)
    if refusal:
        assert not result.completion["choices"][0]["message"].get("tool_calls")


@pytest.mark.parametrize("later_write", [False, True])
def test_grounded_notice_uses_only_checker_read_and_mutation_facts(later_write):
    from tests.test_a_check_no_edit_followed_says_what_cria_saw import read_msgs, FLAG, REL
    root = "/w"
    messages = read_msgs(REL, start=203, end=204)
    if later_write:
        messages.append({"role":"assistant", "tool_calls":[{"id":"later", "function":{
            "name":"edit_file", "arguments":json.dumps({"path":REL,"old_string":"x","new_string":"y"})}}]})
    lines = []
    for raw in FLAG.splitlines():
        match = loop._CHECK_FILE_LINE.search(raw)
        if match:
            lines.append((raw,match.group("path"),int(match.group("line"))))
    facts = guards.GroundedNoticeServices(
        lambda:True, lambda:lines,
        lambda conv:[guards.ReadResult(idx,path,start,end,text) for idx,_tid,path,start,end,text in loop._read_results_ordered(conv)],
        loop._read_span, lambda a,b:loop._same_workspace_file(a,b,root),
        lambda conv,idx,path:any(value is loop._ANY_PATH or loop._same_workspace_file(value,path,root)
                                 for value in loop._write_paths_after(conv,idx,root)))
    out = guards.grounded_next_step(messages, facts)
    assert bool(out) is not later_write
    expected = "" if later_write else prompts.render(
        "rumination_next_step_grounded", finding=lines[0][0].strip(), path=f"`{REL}`", line=203)
    assert out == expected
    if out:
        assert "203" in out and REL in out


@pytest.mark.parametrize("name,args,path,whole", [
    ("write_file", '{"path":"x","content":"cut', "x", True),
    ("edit_file", '{"path":"x","old_string":"old","new_string":"cut', "x", False),
    ("exec_command", '{"cmd":"cut', None, False),
])
def test_final_cut_call_controls_wording_and_other_calls_remain_evidence(name, args, path, whole):
    first = completion("edit_file", json.dumps({"path":"other.txt","old_string":"old","new_string":"new"}))
    first["choices"][0]["message"]["tool_calls"] += completion(name, args)["choices"][0]["message"]["tool_calls"]
    assert guards.cut_target(first,cuts()) == (name, args, path, False, 1)
    other_args = json.dumps({"path":"other.txt","old_string":"old","new_string":"new"})
    other = f"`edit_file` on `other.txt` ({len(other_args)} characters, arguments complete)"
    also = prompts.fill(prompts.load_map("truncation_withheld")["also"], others=other)
    assert guards.also_withheld(first,cuts()) == also
    assert "other.txt" in also
    calls = other + "; " + f"`{name}`" + (f" on `{path}`" if path else "") + f" ({len(args)} characters, arguments cut off at the limit)"
    expected = (prompts.render("truncation_guard", path="x", limit="123 tokens", tool="write_file", also=also)
                if whole else prompts.fill(prompts.load_map("truncation_withheld")["withheld"],
                                                          used="123 tokens", prose=0, calls=calls))
    assert guards.length_cut_notice(first,"x",123,cuts()) == expected


def test_protocol_error_from_retry_is_not_recovered_or_downgraded():
    services, _ = retry_services([])
    calls = []
    def failed(body, log):
        calls.append(body)
        raise upstream.UpstreamProtocolError("invalid literal tool output", {"type":generation.PROTOCOL_ERROR})
    services = replace(services, chat=failed)
    with pytest.raises(upstream.UpstreamProtocolError):
        guards.recover_runaway(guards.RecoveryInput(aborted({"dead_stream":True}),{"messages":[]}),services)
    assert len(calls) == 1


def test_truncation_exhaustion_refuses_the_final_reply_without_synthetic_success():
    value = completion("write_file", '{"path":"x.txt","content":"cut')
    services, bodies = retry_services([value] * guards.MAX_TRUNCATION_RETRIES)
    body = {"messages":[]}
    out = guards.recover_truncation(guards.RecoveryInput(value,body),services,cuts())
    assert out.status is guards.RecoveryStatus.EXHAUSTED
    assert out.attempts == len(bodies) == guards.MAX_TRUNCATION_RETRIES
    assert not out.completion["choices"][0]["message"].get("tool_calls")
    assert body["messages"][-1]["role"] == "user"
    assert services.log.events[-1][0] == "loop.truncated_refused"


def test_clearing_an_injected_abort_marker_cannot_release_its_actions():
    value = completion("write_file", '{"path":"x","content":"literal"}', finish="stop", abort={"dead_stream":True})
    services, sent = retry_services([])
    out = guards.recover_runaway(guards.RecoveryInput(value,{"messages":[]}),services)
    assert not sent
    assert not out.completion["choices"][0]["message"].get("tool_calls")
    assert generation.incomplete(out.completion)
    assert out.completion[generation.EVIDENCE]["call_prefixes"][0]["arguments"] == '{"path":"x","content":"literal"}'


def test_disabled_recovery_still_quarantines_actions():
    def forbidden(*args):
        raise AssertionError("disabled source was invoked")
    selected = guards.SelectedGuards(None, None)
    assert selected.stream(forbidden) is None
    services = guards.RetryServices(forbidden, forbidden, forbidden, Log())
    body = {"messages":[{"role":"user","content":"unchanged"}]}
    original = copy.deepcopy(body)
    for value in (completion("write_file", '{"path":"x","content":"cut'),
                  completion("write_file", '{"path":"x","content":"whole"}', finish="length"),
                  aborted({"dead_stream":True})):
        out = selected.recover(guards.RecoveryInput(value,body), services, forbidden, forbidden)
        assert out.runaway is None and out.truncation is None
        assert not out.completion["choices"][0]["message"].get("tool_calls")
    assert body == original
    assert not services.log.events


def test_selected_replacements_are_called_in_order_and_keep_distinct_results():
    calls = []
    def runaway(source, services, grounding):
        calls.append("runaway")
        return guards.RecoveryResult(source.completion, guards.RecoveryStatus.EXHAUSTED, 3)
    def truncation(source, services, cut_services):
        calls.append("truncation")
        return guards.RecoveryResult(source.completion, guards.RecoveryStatus.UNCHANGED)
    new_stream = object()
    runaway_definition = replace(guards.RUNAWAY, execute=runaway, stream=lambda source:new_stream)
    truncation_definition = replace(guards.TRUNCATION, execute=truncation)
    selected = guards.SelectedGuards(runaway_definition, truncation_definition)
    assert selected.stream(lambda:guards.StreamInput(None,0,True)) is new_stream
    services, _ = retry_services([])
    out = selected.recover(guards.RecoveryInput(completion(finish="stop"),{}), services, cuts)
    assert calls == ["runaway","truncation"]
    assert out.runaway.status is guards.RecoveryStatus.EXHAUSTED
    assert out.truncation.status is guards.RecoveryStatus.UNCHANGED


def test_required_wire_quarantine_never_releases_eof_fragments_when_optional_guards_are_disabled():
    raw = wire([frame(arg_delta('{"path":"x","content":"cut'))])
    released = list(generation.quarantine_stream(raw))
    frames = [json.loads(item[5:]) for item in released]
    assert not any((choice.get("delta") or {}).get("tool_calls") for item in frames for choice in item.get("choices", []))
    assert frames[-1]["error"]["type"] == generation.INCOMPLETE_STREAM_ERROR
    assert frames[-1]["error"][generation.EVIDENCE]["withheld_action_deltas"], "retain the exact prefix as evidence, never a live call"
