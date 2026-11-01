"""Recovery after an aborted or cut-off turn, through loop.guard_rumination / guard_truncation.

Only the coder provider is faked. Notices must say what actually happened, appear once, never
repeat a byte-identical retry, and never release a call that was cut off.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from cria import bodykeys, generation, generationguards as g, loop, massage
from loop_guards_helpers import Chat, Log, reply

BODY = lambda: {"messages": [{"role": "user", "content": "task"}], "tools": []}


def aborted(**verdict):
    comp = reply("", finish="rumination")
    comp[bodykeys.RUMINATION] = verdict
    return comp


def last_user(chat):
    return [b["messages"][-1]["content"] for b in chat.bodies]


@pytest.mark.parametrize("verdict,has,lacks", [
    (dict(hits=8, reasoning_tokens=900, arm="second_guessing"), ["hit 8 second-guessing", "~900"], []),
    (dict(hits=0, reasoning_tokens=4096, arm="length"), ["about 4096 tokens"], ["second-guessing"]),
    # cycle 4 (nemotron-elastic): four aborts at 0.7-2.5 markers/1k were all told "you hit N phrases"
    (dict(dead_stream=True, chunks=400), ["produced nothing"], ["second-guessing", "repeating"]),
    (dict(degenerate=True, chars=2048), ["repeating over and over"], ["second-guessing"]),
    (dict(window_exhausted=True, room=1000, frames=920), ["92%", "discarded, not truncated"], ["too big"]),
])
def test_each_abort_arm_is_told_what_actually_happened(verdict, has, lacks):
    """Rule 5b: a notice never names a behaviour that did not happen, never claims a continuity that was
    destroyed, never forbids looking something up, and the model never reads the shim's name."""
    chat = Chat(reply("next real answer"))
    body = BODY()
    out = loop.guard_rumination(aborted(**verdict), body, chat, Log())
    notice = last_user(chat)[0]
    assert all(s in notice for s in has) and not any(s in notice for s in lacks)
    assert "cria" not in notice.lower() and "continue from what you already know" not in notice
    assert "do not revisit" not in notice.lower()
    assert "survive" in notice or verdict.get("window_exhausted")
    assert chat.bodies[0]["messages"][0] == {"role": "user", "content": "task"}
    assert body["messages"] == [{"role": "user", "content": "task"}]          # the caller's body is untouched
    assert out["choices"][0]["message"]["content"] == "next real answer"
    assert bodykeys.RUMINATION not in out
    assert "reasoning loop detected — aborted and refocused (1×)" in out[bodykeys.NOTES]


def test_the_guard_notice_is_replaced_not_stacked_and_an_identical_retry_is_withheld():
    """shipping-rates-rb x ternary-bonsai: three retries stacked three copies of the notice (a longer
    prompt each time); replacing it then re-sent a byte-identical prompt 8.7% of the time."""
    same = Chat(aborted(dead_stream=True, chunks=400))
    out = loop.guard_rumination(aborted(dead_stream=True, chunks=400), BODY(), same, Log())
    assert len(same.bodies) == 1                      # the same arm on the same conversation is not re-asked
    assert generation.incomplete(out) and bodykeys.RUMINATION not in out   # still quarantined, never "stop"

    changing = Chat(aborted(window_exhausted=True), aborted(degenerate=True), aborted(dead_stream=True))
    loop.guard_rumination(aborted(hits=8, reasoning_tokens=900), BODY(), changing, Log())
    assert len(changing.bodies) == g.MAX_RUMINATION_RETRIES
    for sent in changing.bodies:                      # a changed arm is a different prompt: still tried
        assert len(sent["messages"]) == 2 and sent["messages"][1]["content"].startswith("[")
    assert len({json.dumps(b["messages"]) for b in changing.bodies}) == len(changing.bodies)


@pytest.mark.parametrize("role_reasoning,forced_off", [("on", True), ("off", False), (None, False)])
def test_the_retry_alone_runs_with_reasoning_off(role_reasoning, forced_off):
    """feed-pipeline-java x ornith1.5_9b: replayed 8x each, a reasoning-ON retry produced a tool call 1/8,
    reasoning-OFF 7/8. The flip lands on the retry copy only: the caller's body keeps the role's reasoning."""
    role = SimpleNamespace(reasoning=role_reasoning, think_protocol="chat_template") if role_reasoning else None
    body = {**BODY(), "chat_template_kwargs": {"enable_thinking": True}}
    chat = Chat(reply("ok"))
    loop.guard_rumination(aborted(hits=10, reasoning_tokens=2048), body, chat, Log(), coder_role=role)
    assert chat.bodies[0]["chat_template_kwargs"]["enable_thinking"] is (not forced_off)
    assert body["chat_template_kwargs"]["enable_thinking"] is True


def test_an_aborted_reply_never_releases_its_calls_even_if_its_marker_is_stripped():
    """Quarantine is required protocol integrity: an injected provider cannot free a cut-off call by
    clearing the local marker, and the exact prefix stays evidence."""
    args = '{"path":"x","content":"literal"}'
    comp = reply("", finish="stop", tool_calls=[{"id": "w", "type": "function",
                                                  "function": {"name": "write_file", "arguments": args}}])
    comp[bodykeys.RUMINATION] = {"dead_stream": True}
    chat = Chat()
    out = loop.guard_rumination(comp, BODY(), chat, Log())
    assert not chat.bodies
    assert not out["choices"][0]["message"].get("tool_calls") and generation.incomplete(out)
    assert out[generation.EVIDENCE]["call_prefixes"][0]["arguments"] == args


def test_disabled_guards_still_quarantine_cut_calls_and_never_coach():
    """Optional recovery off: no retry, no refusal text — but a cut call is still never forwarded."""
    selected = g.SelectedGuards(None, None)
    cut = reply("", finish="length", tool_calls=[{"id": "w", "type": "function", "function": {
        "name": "write_file", "arguments": '{"path":"x","content":"cut'}}])
    body, log = BODY(), Log()
    forbidden = lambda *a: pytest.fail("a disabled guard was invoked")
    services = g.RetryServices(forbidden, forbidden, forbidden, log)
    out = selected.recover(g.RecoveryInput(cut, body), services, forbidden, forbidden)
    assert out.runaway is None and out.truncation is None
    assert not out.completion["choices"][0]["message"].get("tool_calls")
    assert body == BODY() and not log.events


def cut_write(args, finish="tool_calls", name="write_file"):
    return reply("", finish=finish, tool_calls=[{"id": "w", "type": "function",
                                                  "function": {"name": name, "arguments": args}}])


CUT = '{"path":"x.txt","content":"cut'
WHOLE = '{"path":"x.txt","content":"whole"}'


@pytest.mark.parametrize("first,retries,sends,survives,refusal", [
    # length-cut whole-file write: steered to small pieces, the retry's complete call ships
    (cut_write(CUT, "length"), [cut_write(WHOLE)], 1, True, None),
    # ended early on its own (finish=tool_calls, arguments cut): a different notice, still recovered
    (cut_write(CUT), [cut_write(WHOLE)], 1, True, None),
    # every retry cut again: the retry budget is bounded and the final call is refused, never run
    (cut_write(CUT), [cut_write(CUT)] * 3, 3, False, "WRITE WAS REFUSED"),
    # a cut call that is no file write: refused outright, no retry to coach a path we cannot name
    (cut_write('{"cmd":"cut', name="exec_command"), [], 0, False, "TOOL CALL WAS REFUSED"),
    (cut_write('{"cmd":"cut', "length", "exec_command"), [], 0, False, "incomplete terminal status"),
    # a whole call that merely reached the limit is not a cut-off write: it is told what was withheld
    (cut_write(WHOLE, "length"), [reply("next answer")], 1, False, None),
])
def test_truncation_recovery_retries_with_the_true_reason_then_refuses_the_cut_call(
        first, retries, sends, survives, refusal):
    """A cut-off call never executes; the refusal reaches the model (call_refused), the retry cap holds."""
    chat, body, log = Chat(*retries), BODY(), Log()
    out = loop.guard_truncation(first, body, chat, log)
    assert len(chat.bodies) == sends
    assert bool(out["choices"][0]["message"].get("tool_calls")) is survives
    if survives:
        assert out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == WHOLE
    if sends:
        assert "x.txt" in last_user(chat)[0] or "withheld" in last_user(chat)[0]
    if refusal:
        assert refusal in body["messages"][-1]["content"] and body["messages"][-1]["role"] == "user"
        assert "cria" not in body["messages"][-1]["content"].lower()


OTHER = '{"path":"other.txt","old_string":"old","new_string":"new"}'


@pytest.mark.parametrize("name,args,small_pieces", [
    ("write_file", '{"path":"x","content":"cut', True),                 # a whole-file write cut mid-content: the build-in-pieces advice is TRUE here
    ("edit_file", '{"path":"x","old_string":"old","new_string":"cut', False),
    ("exec_command", '{"cmd":"cut', False)])                            # ...and false for every other cut call
def test_the_final_cut_call_chooses_the_wording_and_the_other_calls_in_the_reply_are_named_as_withheld(name, args, small_pieces):
    """C14 D1 (a COMPLETE 1.4K edit_file was told its whole-file write was cut): the retry notice describes the call that was actually cut, and a
    complete call beside it is said to be withheld and NOT run - it must not silently vanish from the coder's picture of the repo."""
    first = reply("", finish="length", tool_calls=[
        {"id": "a", "type": "function", "function": {"name": "edit_file", "arguments": OTHER}},
        {"id": "b", "type": "function", "function": {"name": name, "arguments": args}}])
    chat = Chat(reply("next answer"))
    out = loop.guard_truncation(first, BODY(), chat, Log())
    notice = last_user(chat)[0]
    assert "`edit_file` on `other.txt`" in notice and f"({len(OTHER)} characters, arguments complete)" in notice and "NOT run" in notice
    assert ("SMALL pieces" in notice) is small_pieces and "cria" not in notice.lower()
    if not small_pieces:
        assert f"`{name}`" in notice and f"({len(args)} characters, arguments cut off at the limit)" in notice
    assert not out["choices"][0]["message"].get("tool_calls")      # the retry answered in prose: nothing from the cut reply ran


def test_when_several_calls_are_cut_the_last_one_chooses_the_notice():
    """The output limit ends the LAST call; an earlier malformed one must not decide which advice the coder reads."""
    first = reply("", finish="length", tool_calls=[
        {"id": "a", "type": "function", "function": {"name": "edit_file", "arguments": '{"path":"first.txt","old_string":"o","new_string":"cut'}},
        {"id": "b", "type": "function", "function": {"name": "write_file", "arguments": '{"path":"last.txt","content":"cut'}}])
    chat = Chat(reply("next answer"))
    loop.guard_truncation(first, BODY(), chat, Log())
    assert "SMALL pieces" in last_user(chat)[0] and "`last.txt`" in last_user(chat)[0]


def test_a_protocol_error_from_the_retry_is_not_recovered_or_downgraded():
    from cria import upstream
    calls = []

    def failing(body, rlog):
        calls.append(body)
        raise upstream.UpstreamProtocolError("invalid literal tool output", {"type": generation.PROTOCOL_ERROR})

    with pytest.raises(upstream.UpstreamProtocolError):
        loop.guard_rumination(aborted(dead_stream=True), BODY(), failing, Log())
    assert len(calls) == 1


def _turn(finish, **extra):
    call = {"id": "c1", "type": "function", "function": {"name": "write_file", "arguments": '{"path": "a.py", "content": "x'}}
    return {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": "", "tool_calls": [call]}}], **extra}


@pytest.mark.parametrize("extra,finish,reason", [
    ({}, "length", "generation_limit"),                                              # the server hit its length cap mid-call
    ({bodykeys.RUMINATION: {"why": "loop"}}, "stop", "generation_aborted"),            # cria cut a ruminating generation itself
])
def test_an_incomplete_turn_ships_no_call_and_keeps_every_withheld_call_as_evidence(extra, finish, reason):
    """A cut-off write call must never reach the harness as an executable call; its complete prefix is evidence, not an action.
    Mutation survivors: dropping `withheld_choices`, or keeping the first record when a turn is hardened twice, failed no test."""
    turn = _turn(finish, **extra)
    original = copy.deepcopy(turn["choices"])
    shipped = generation.safe_completion(turn)
    message = shipped["choices"][0]["message"]
    assert "tool_calls" not in message and shipped["choices"][0]["finish_reason"] == ("rumination" if extra else "length")
    evidence = shipped[generation.EVIDENCE]
    assert evidence["incomplete"] is True and evidence["withheld_choices"] == original
    assert evidence["call_prefixes"] == [{"name": "write_file", "arguments": '{"path": "a.py", "content": "x', "id": "c1"}]
    assert evidence["wire_finish_reason"] == ("rumination" if extra else "length")
    assert ("local_abort" in evidence) is bool(extra) and generation.incomplete_reason(shipped) == reason
    assert not generation.may_recover(shipped)
    again = generation.safe_completion(shipped)                  # hardened twice (retry paths): the first record stands
    assert again[generation.EVIDENCE]["withheld_choices"] == original


def test_a_complete_turn_is_shipped_untouched_and_only_the_two_generation_errors_are_generation_errors():
    turn = _turn("tool_calls")
    assert generation.safe_completion(turn) is turn and "tool_calls" in turn["choices"][0]["message"] and generation.may_recover(turn)
    kinds = {generation.PROTOCOL_ERROR: True, generation.INCOMPLETE_STREAM_ERROR: True, "rate_limit_error": False}
    assert {k: generation.is_generation_error({"type": k}) for k in kinds} == kinds
    assert not generation.is_generation_error(None) and not generation.is_generation_error("incomplete_stream_error")
    assert not generation.is_protocol_error({"type": generation.INCOMPLETE_STREAM_ERROR})


@pytest.mark.parametrize("raw", [
    '{"path": "main.go", "content": "package main\\n\\nfunc main() {}\\n\\nfunc other() {',      # cut after the empty brace pair of the code being written
    "{\"cmd\": \"awk '{}' f; echo $",                                                          # `awk '{}'` inside a cut shell program
    "prose with {} in it and no call at all",
])
def test_an_empty_object_found_inside_a_cut_argument_string_never_replaces_what_the_model_wrote(raw):
    """Four real write_file calls (6,026 / 6,277 / 6,893 / 28,571 chars, one a whole test file) had their arguments replaced by `{}` because the
    first brace-balanced span that parses is the empty pair of the code being written (`func main() {}`, `awk '{}'`, `${}`): the substitution
    deleted the call. The raw text stays exactly as written and the refusal is logged, so the harness's parse error is true of the model's output."""
    events = []
    call = {"id": "c", "type": "function", "function": {"name": "write_file", "arguments": raw}}
    out = massage.repair_tool_args({"choices": [{"message": {"tool_calls": [call]}}]},
                                   SimpleNamespace(emit=lambda kind, **fields: events.append((kind, fields))))
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == raw
    assert events == [("massage.args_recovery_refused", {"tool": "write_file", "raw_chars": len(raw)})]
