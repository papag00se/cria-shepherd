"""Scenario2 (LA2): the edges of the judge seats and the workspace readers around them - a verdict declared as a TOOL call, a tool call
with garbage arguments, a judge that leaks a tool nobody offered, no reasoner / no task / no runtime arm, the confirm brake's skip rule,
the workspace-subject resolver, and the footer listing that keeps the last action last. Real functions, real temp workspaces; only the
reasoner reply is scripted."""
import json

import pytest

from cria import assistruntime, loop, selfcompact, verifytools, wsview
from cria.config import Role
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401
from test_loop_rest_judge_protocol import ROLE, completion, scripted


def call(name, arguments):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": arguments}}


def judge(replies, root, **kw):
    chat, bodies = scripted(replies)
    log = Rlog()
    comp = loop._judge_completion(chat, None, "sys", "q", log, phase="t", workspace_root=str(root), **kw)
    return comp, bodies, log


@pytest.mark.parametrize("arguments,approved", [('{"done": true, "reason": "r"}', True), ('{"done": false}', False)])
def test_a_verdict_declared_as_a_tool_call_is_the_answer_even_beside_an_inspection_call(tmp_path, arguments, approved):
    comp, bodies, log = judge([completion("", calls=[call("list_dir", '{"path": "."}'), call("verdict", arguments)])], tmp_path,
                              verdict_key="done")
    assert json.loads(comp["choices"][0]["message"]["content"])["done"] is approved and len(bodies) == 1
    assert "loop.verdict_by_tool" in log.kinds() and "loop.verify_inspect" not in log.kinds()


def test_a_verdict_call_missing_its_key_or_unparseable_is_just_another_inspection_round_and_garbage_arguments_are_answered(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    replies = [completion("", calls=[call("verdict", "{not json")]), completion("", calls=[call("read_file", "nope")]),
               completion("", calls=[call("verdict", '{"other": 1}')]), completion("final words")]
    comp, bodies, log = judge(replies, tmp_path, verdict_key="done")
    assert comp["choices"][0]["message"]["content"] == "final words" and len(bodies) == 4
    answers = [m["content"] for b in bodies[1:] for m in b["messages"] if m["role"] == "tool"]
    assert "[unparseable tool arguments — call again with valid JSON]" in answers
    assert log.kinds().count("loop.verify_inspect") == 3 and "loop.verdict_by_tool" not in log.kinds()


def test_a_judge_that_keeps_leaking_unrunnable_calls_is_asked_twice_then_the_simple_shape_and_the_answer_is_kept(tmp_path):
    leak = completion("", calls=[call("list_dir", '{"path": "."}')])
    bare = {**leak, "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "<function=satisfied>"}}]}
    comp, bodies, log = judge([bare, bare, completion("CONSISTENT")], tmp_path, verdict_key="consistent", allow_inspection=False,
                              answer_now="NORMAL ASK", answer_now_simple="ONE WORD")
    assert comp["choices"][0]["message"]["content"] == "CONSISTENT" and len(bodies) == 3
    assert bodies[1]["messages"][-1]["content"].endswith("NORMAL ASK") and bodies[2]["messages"][-1]["content"] == "ONE WORD"
    assert "loop.verdict_simplified" in log.kinds()


def test_a_satisfaction_judge_that_answers_with_a_tool_nobody_offered_is_named_and_still_fails_closed():
    leaked = completion("<|tool_call>call:exec_command")
    chat, bodies = scripted([leaked, leaked, completion("nothing readable")])
    log = Rlog()
    verdict = loop._satisfaction_verdict("judge", "task", chat, ROLE, log, reasoning_off=False)
    assert verdict is None and [e["tool"] for e in log.of("loop.judge_phantom_tool")] == ["exec_command"]


def test_the_seats_without_a_reasoner_a_task_or_a_rehunt_policy_decline_without_asking():
    chat, bodies = scripted([completion("{}")])
    assert loop.judge_satisfaction("   ", "evidence", chat, ROLE, Rlog()) == (False, "no task text to judge", "")
    assert loop.reassess_remaining(chat, None, "task", "done", "left", "evidence", Rlog()) is None
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=3)):
        assert assistruntime.current().rehunt is None
        assert loop.judge_rehunt(chat, ROLE, "task", "new query", "old query", Rlog()) is False
    assert bodies == []


@pytest.mark.parametrize("claim,red,gate_red,answer,applies", [
    ("write app.py", "", False, "NO", False), ("write app.py", "", False, "No - it only reads.", False),
    ("write app.py", "", False, "YES", True), ("write app.py", "", False, "", True), ("write app.py", "", False, "perhaps", True),
    ("write app.py", "  FAILED test_x ", False, "NO", True), ("write app.py", "", True, "NO", True), ("write app.py", "", False, None, True)])
def test_the_confirm_brake_is_skipped_only_when_nothing_is_red_and_the_judge_says_no_artifact(claim, red, gate_red, answer, applies):
    log, asked = Rlog(), []
    ask = None if answer is None else (lambda question: asked.append(question) or answer)
    assert loop._confirm_applies(claim, red, gate_red=gate_red, ask=ask, rlog=log) is applies
    assert bool(log.of("loop.confirm_skipped_no_artifact")) is (not applies)
    assert bool(asked) is (answer is not None and not red.strip() and not gate_red)


def test_the_workspace_subject_resolver_names_a_unique_file_anywhere_and_never_turns_doubt_into_absence(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "feed.csv").write_text("a,b\n")
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "twin.py").write_text("1")
    (tmp_path / "y").mkdir()
    (tmp_path / "y" / "twin.py").write_text("2")
    (tmp_path / "top.py").write_text("print(1)\n")
    root = str(tmp_path)
    assert loop._workspace_subject("", "top.py") == loop._workspace_subject(root, "") == ("", None, None)
    assert loop._workspace_subject(root, "../escape.py") == ("", None, None)
    assert loop._workspace_subject(root, "top.py") == ("top.py", True, "print(1)\n")
    assert loop._workspace_subject(root, "feed.csv") == ("data/feed.csv", True, "a,b\n")        # basename found in a subdirectory
    assert loop._workspace_subject(root, "twin.py") == ("", None, None)                         # ambiguous: unknown, not absent
    assert loop._workspace_subject(root, "ghost.py") == ("ghost.py", False, None)               # complete listing, genuinely absent
    assert loop._workspace_basename_matches(root, "") is None and loop._workspace_basename_matches("", "a") is None
    assert loop._workspace_basename_matches(root, "sub/feed.csv") == ["data/feed.csv"]


def test_the_fresh_listing_rides_alone_when_only_a_stale_one_was_there_and_just_above_the_last_message_otherwise(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    stale = {"role": "user", "content": selfcompact.FILES_MARKER + "\n- old.py"}
    alone = loop._ground_coder_view([stale], str(tmp_path))
    assert len(alone) == 1 and "app.py" in alone[0]["content"] and "old.py" not in alone[0]["content"]
    task, last = {"role": "user", "content": "build it"}, {"role": "user", "content": "keep going"}
    view = loop._ground_coder_view([task, stale, last], str(tmp_path))
    assert [m["content"] for m in view][0] == "build it" and view[-1] is last
    assert sum("app.py" in m["content"] for m in view) == 1 and loop._ground_coder_view([task], "") == [task]
