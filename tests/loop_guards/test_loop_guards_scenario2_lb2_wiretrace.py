"""What cria can say, from the wire and the disk, about files the coder touched: a lowered call is read as the call the coder made, a read is
checked against everything written after it, the disk facts handed to a steer author, the host a coder's own source names, and the notes
appended to a conversation — each stating only what was observed."""
import json
import subprocess

import pytest

from cria import assistruntime, loop, toolwire, wsview


def call(cid, name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def lowered(name, **args):
    return {"name": "exec_command", "arguments": json.dumps({"cmd": toolwire._sentinel(name, json.dumps(args)) + "\ntrue"})}


def survey_view(root):
    out = subprocess.run(["bash", "-lc", wsview.survey_command("lb2", cd=str(root))], capture_output=True, text=True).stdout
    view = wsview.View(str(root), "lb2")
    wsview.apply_survey(view, wsview.strip_survey(out)[1])
    return view


PATCH = "*** Begin Patch\n*** Update File: a.py\n*** Move to: b.py\n*** Delete File: c.py\n*** End Patch"


@pytest.mark.parametrize("fn,targets", [
    (lowered("write_file", path="x.py", content="1"), ["x.py"]),                                  # the lowering is read as the call the coder made
    (lowered("read_file", path="x.py"), []),
    ({"name": "apply_patch", "arguments": json.dumps({"input": PATCH})}, ["a.py", "b.py", "c.py"]),
    ({"name": "apply_patch", "arguments": PATCH.replace("\n", "\\n")}, ["a.py", "b.py", "c.py"]),  # a raw, escaped blob
    ({"name": "apply_patch", "arguments": json.dumps({"input": 5})}, loop._ANY_PATH),               # a patch naming nothing: any file may have changed
    ({"name": "exec_command", "arguments": '{"cmd": "tail -f'}, loop._ANY_PATH),                  # an undecodable fragment
    ({"name": "exec_command", "arguments": json.dumps({"cmd": "ls -la"})}, []),
    ({"name": "exec_command", "arguments": json.dumps({"cmd": "sed -i s/a/b/ x.py"})}, loop._ANY_PATH),
])
def test_a_calls_possible_mutations_are_read_from_the_call_the_coder_made(fn, targets):
    got = loop._mutation_targets(fn)
    assert got is targets if targets is loop._ANY_PATH else got == targets


def test_a_read_is_stale_only_when_a_later_write_could_have_touched_the_file_and_an_unlocatable_read_is_unknown():
    seen = [call("r", "read_file", path="a.py"), {"role": "tool", "tool_call_id": "r", "content": "x"},
            call("w1", "write_file", path="b.py", content="1"), call("w2", "write_file", path="/w/a.py", content="2")]
    assert loop._mutated_after_read(seen, 1, "a.py", "/w", seen) is True                       # the absolute spelling is the same file
    assert loop._mutated_after_read(seen[:3], 1, "a.py", "/w", seen[:3]) is False               # only b.py was written
    shell = seen[:2] + [call("s", "exec_command", cmd="sed -i s/a/b/ a.py")]
    assert loop._mutated_after_read(shell, 1, "a.py", "/w", shell) is True                      # a command of unknown effect
    accepted = [{"role": "user", "content": "task"}] + seen[:3]
    assert loop._mutated_after_read(seen, 1, "a.py", "/w", accepted) is False                   # located by call id in the accepted body
    assert loop._mutated_after_read(seen, 1, "a.py", "/w", accepted[:2]) is True                # the read is not in it: unknown is "may have changed"
    assert loop._mutated_after_read([{"role": "tool", "content": "x"}], 0, "a.py", "/w", [{"role": "tool"}]) is True


def test_disk_facts_for_a_steer_author_name_size_lines_and_absence_only_where_the_view_knows(tmp_path):
    (tmp_path / "a.py").write_text("x\ny\n")
    (tmp_path / "one.txt").write_text("single")
    (tmp_path / "empty.py").write_text("")
    root = str(tmp_path)
    token = wsview.bind(wsview.DirectView(root))
    try:
        facts = loop._fresh_disk_facts(root, ["a.py", "./a.py", "one.txt", "ghost.py"], "empty.py")
    finally:
        wsview.unbind(token)
    assert facts.splitlines() == ["FILE a.py — 4 bytes, 2 lines", "FILE one.txt — 6 bytes, 1 line", "FILE ghost.py — does NOT exist on disk",
                                  "FILE empty.py — 0 bytes, 0 lines"]
    token = wsview.bind(survey_view(tmp_path))                                                  # a survey lists sizes but holds no bodies
    try:
        assert loop._fresh_disk_facts(root, ["a.py", "ghost.py"], "") == "FILE a.py — 4 bytes\nFILE ghost.py — does NOT exist on disk"
    finally:
        wsview.unbind(token)
    assert loop._fresh_disk_facts(".", ["a.py"], "") == "" and loop._fresh_disk_facts(None, ["a.py"], "") == "" and loop._fresh_disk_facts(root, [], "") == ""


def test_a_host_is_the_coders_own_only_when_its_source_files_name_it(tmp_path):
    (tmp_path / "client.py").write_text("URL = 'https://api.handle.me/x'\n")
    (tmp_path / "notes.txt").write_text("api.other.io\n")
    (tmp_path / "bin.js").write_bytes(b"\xff\xfe")
    root = str(tmp_path)
    token = wsview.bind(wsview.DirectView(root))
    try:
        assert loop._host_in_workspace_code(root, "api.handle.me") is True
        assert loop._host_in_workspace_code(root, "api.other.io") is False                     # a note is not the coder's source
        assert loop._host_in_workspace_code(root, "nowhere.example") is False
        assert loop._host_in_workspace_code("", "api.handle.me") is False and loop._host_in_workspace_code(root, "") is False
        assert loop._host_in_workspace_code(str(tmp_path / "missing"), "api.handle.me") is False
    finally:
        wsview.unbind(token)


def test_a_refusal_note_reaches_the_next_turn_only_as_a_message_on_a_conversation_that_has_one():
    body = {"messages": [{"role": "user", "content": "task"}]}
    loop._refusal_turn(body, "your call was dropped")
    assert body["messages"][-1] == {"role": "user", "content": "your call was dropped"}
    loop._refusal_turn(body, "")
    loop._refusal_turn({"messages": "none"}, "x")
    loop._refusal_turn({}, "x")
    assert len(body["messages"]) == 2


def test_with_the_assists_off_the_wire_view_gets_no_restored_block_and_no_ledger_copy_is_elided():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    sess = type("S", (), {"fetched_pages": {}, "workspace_root": ""})()
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=0)):
        assert loop._restored_text_message(sess, msgs) == (None, {})
        assert loop._elide_ledger_copies(msgs, sess) is msgs
    assert loop._plan_off_tail(msgs, None, {"role": "user", "content": "F"})[-2:] == [msgs[-1], {"role": "user", "content": "F"}]
    block = {"role": "user", "content": "R"}
    assert loop._plan_off_tail(msgs[:1], block, {"role": "user", "content": "F"}) == [msgs[0], block, {"role": "user", "content": "F"}]


GATE_RESULT = f"{loop.probegate.SECTION_PREFIX}probe-0{loop.probegate.SECTION_SUFFIX}\nFAILED tests/test_a.py::t - assert 1 == 2\nEXIT:1\n"


def test_the_judge_is_shown_the_task_and_the_session_without_the_harness_frame_or_the_gate_scaffolding():
    gate_cmd = loop.probegate._gate_sentinel(["pytest -q"]) + "\ntrue\n"
    msgs = [{"role": "system", "content": "HARNESS FRAME"}, {"role": "user", "content": "Fix the cart total."},
            call("g1", "exec_command", cmd=gate_cmd), {"role": "tool", "tool_call_id": "g1", "content": GATE_RESULT}]
    task, session = loop._periodic_judgment_evidence(loop.GuardState(), {"messages": msgs})
    assert task == "Fix the cart total." and "HARNESS FRAME" not in session
    assert session.startswith('user: Fix the cart total.\nassistant: exec_command({"cmd": "pytest -q"})\ntool: ')
    assert "FAILED tests/test_a.py::t" in session and loop.probegate.GATE_SENTINEL not in session


@pytest.mark.parametrize("level", [0, 3])
def test_without_the_repository_check_assist_a_probe_result_is_still_recorded_as_fact_and_never_forwarded(level):
    """Required factual settlement is not optional: the result is read and recorded, the pending flags clear, and no steer is produced."""
    body = {"messages": [{"role": "user", "content": "t"}, {"role": "tool", "tool_call_id": "p", "content": "output"}]}
    log = type("L", (), {"events": [], "emit": lambda s, k, **kw: s.events.append(k)})()
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=level)):
        periodic = loop.GuardState()
        periodic.periodic_probe = periodic.awaiting_probe = True
        periodic.probe_call_id, periodic.gate_fresh = "p", False
        assert loop.guard_periodic_result(periodic, body, log) is None
        assert (periodic.periodic_probe, periodic.awaiting_probe, periodic.gate_fresh) == (False, False, False)   # freshness is the clock's, not the reading's
        verdict = loop.GuardState()
        verdict.probe_call_id, verdict.gate_fresh = "p", False
        assert loop.guard_gate_verdict(verdict, body, log) is None and verdict.gate_fresh is True and verdict.last_gate_ran is False
        idle = loop.GuardState()
        idle.awaiting_probe, idle.probe_call_id = True, "p"                                                   # a completion probe is pending, not a periodic one
        assert loop.guard_periodic_result(idle, body, log) is None and idle.awaiting_probe is True
    assert log.events == []                                                                                    # nothing ran, so nothing is logged as a result
