"""The steer author end to end with only the reasoner faked: `loop.author_steer` over a real session, on both paths (a plain asked
reply and the tool-using path a surveyed workspace selects). Every kind of reply the reasoner can give is a row - delivered, on track,
cut, ruminating, reasoning-only, structurally refused, echoed tool arguments, role-play - with what the coder is (not) told and the
event that records why. A second table walks each rejection reason of the steer funnel (`loop._vet_steer`) with its logged event."""
import json

import pytest

from cria import loop, wsview
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401

SESSION = [{"role": "user", "content": "Resolve a handle."},
           {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "exec_command", "arguments": '{"cmd": "python live_test.py"}'}}]},
           {"role": "tool", "tool_call_id": "c1", "content": "Chunk ID: 1\nWall time: 0.0 seconds\nProcess exited with code 127\nOriginal token count: 12\nOutput:\n/bin/bash: python: command not found"}]
FIX = "Install python3 or use python3 in the command."
LOOPING = "The coder keeps retrying the same thing. " * 60

# (reply message, finish_reason, the directive delivered or None, the event that records why)
REPLIES = [({"content": FIX}, "stop", FIX, "loop.steer_outcome"),
           ({"content": "ON_TRACK"}, "stop", None, "loop.steer_on_track"),
           ({"content": "ON_TRACK", "reasoning_content": "the coder is fine"}, "stop", None, "loop.steer_on_track"),
           ({"content": LOOPING}, "stop", None, "loop.steer_degenerate"),
           ({"content": "", "reasoning_content": "Thinking... the coder should run `python3 live_test.py` instead of python."}, "stop", None, "massage.reasoning_text_recovered"),
           ({"content": "Read the file first. Then rewrite the handler."}, "stop", None, "loop.steer_multiple_actions"),
           ({"content": 'assistant: run exec_command({"cmd":"x"})'}, "stop", None, "loop.steer_roleplay_dropped"),
           ({"content": '{"path":"a.py","content":"x"}'}, "stop", None, None),
           ({"content": ""}, "stop", None, None)]


def author(reply, finish, root=None):
    sent = []

    def chat(body, rlog):
        sent.append(body)
        return json.dumps({"choices": [{"message": reply, "finish_reason": finish}]}).encode()
    log = Rlog()
    out = loop.author_steer(chat, None, root, loop.GuardState(), {"messages": SESSION, "tools": []}, log, condition="wheel_spin")
    return out, log.kinds(), len(sent)


@pytest.fixture
def surveyed_root(tmp_path):
    view = wsview.View(str(tmp_path), "au")
    P, S = wsview._SEC_PREFIX, wsview._SEC_SUFFIX
    assert wsview.apply_survey(view, "\n".join([f"{P}meta{S}", f"root\t{tmp_path}", f"{P}tree{S}", "F\t1\t2\ta.py", f"{P}blob{S}", f"{P}outside{S}",
                                                f"{P}progs{S}", f"{P}done{S}", "entries\t1", "complete\t1", wsview.SURVEY_CLOSE]))
    token = wsview.bind(view)
    yield str(tmp_path)
    wsview.unbind(token)


@pytest.mark.parametrize("reply,finish,directive,event", REPLIES)
def test_every_kind_of_reasoner_reply_is_delivered_or_withheld_with_its_reason_on_the_plain_path(loop_rest_local_view, reply, finish, directive, event):
    out, kinds, _calls = author(reply, finish)
    assert out == directive and (event is None or event in kinds)


@pytest.mark.parametrize("reply,finish,directive,event", REPLIES + [({"content": "Run the"}, "length", None, "loop.steer_truncated")])
def test_the_same_replies_get_the_same_answer_on_the_tool_using_path_a_surveyed_workspace_selects(surveyed_root, reply, finish, directive, event):
    out, kinds, calls = author(reply, finish, surveyed_root)
    assert out == directive and (event is None or event in kinds) and calls == 1


def test_a_reply_cut_by_the_token_limit_is_asked_again_once_and_then_withheld(loop_rest_local_view):
    out, kinds, calls = author({"content": "Run the"}, "length")
    assert out is None and calls == 2 and kinds.count("summarize.truncated") == 2


def vet(directive, evidence="", ask=None, flag="", messages=None):
    class Sess:
        fetched_pages, last_gate_flag = {}, flag
    log = Rlog()
    return loop._vet_steer(directive, evidence, log, ask, Sess() if flag or ask else None, [] if messages is None else messages, None), log.kinds()


WRITE = [{"role": "assistant", "tool_calls": [{"id": "w", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "go.mod", "content": "x"})}}]},
         {"role": "tool", "tool_call_id": "w", "content": "Wrote go.mod"}]
FLAGGED = "Use the pinned version in go.mod."


@pytest.mark.parametrize("args,expected,event", [
    ({"directive": ""}, (None, "empty"), None),
    ({"directive": "assistant: I will do it"}, (None, "roleplay"), "loop.steer_roleplay_dropped"),
    ({"directive": '{"path": "a.py", "content": "x"}'}, (None, "argument_blob"), "loop.steer_argument_blob"),
    ({"directive": "Fetch https://nowhere.example/spec.json and read it.", "evidence": "ev"}, (None, "ungrounded_url"), "loop.steer_ungrounded"),
    ({"directive": "I will write the parser now. Read a.py."}, ("I will write the parser now. Read a.py.", ""), "loop.steer_roleplay_firstperson"),
    ({"directive": FLAGGED, "flag": "go.mod:5: bad version", "ask": lambda s, u="": "SUPPORTED", "messages": WRITE}, (None, "diagnostic_stale"), "loop.steer_diagnostic_stale"),
    ({"directive": FLAGGED, "flag": "go.mod:5: bad version", "ask": lambda s, u="": "CONTRADICTED"}, (None, "diagnostic_contradicted"), "loop.steer_diagnostic_action"),
    ({"directive": FLAGGED, "flag": "go.mod:5: bad version", "ask": lambda s, u="": "UNSUPPORTED."}, (None, "diagnostic_unsupported"), "loop.steer_diagnostic_action"),
    ({"directive": FLAGGED, "flag": "go.mod:5: bad version", "ask": lambda s, u="": "unrelated"}, (None, "diagnostic_unrelated"), "loop.steer_diagnostic_action"),
    ({"directive": FLAGGED, "flag": "go.mod:5: bad version", "ask": lambda s, u="": "hmm, maybe"}, (None, "diagnostic_undecidable"), "loop.steer_diagnostic_action"),
    ({"directive": FLAGGED, "flag": "go.mod:5: bad version", "ask": lambda s, u="": "SUPPORTED"}, (FLAGGED, ""), "loop.steer_diagnostic_action"),
    ({"directive": "call foo.bar(x) then baz(y) here", "ask": lambda s, u="": "maybe"}, ("call foo.bar(x) then baz(y) here", ""), "loop.dictates_verdict_unreadable"),
])
def test_each_rejection_reason_of_the_steer_funnel_names_its_guard_and_logs_it(args, expected, event):
    got, kinds = vet(**args)
    assert got == expected and (event is None or event in kinds)
