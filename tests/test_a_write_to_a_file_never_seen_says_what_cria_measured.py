"""G4 — a write that names an EXISTING file the coder never read, and a call cria did not run, are SAID.

Incident: phi4 / feed-pipeline-java A2 (capture 20261010T230133-01a1298d-…), calls 0030/0031/0036/0037/
0042/0043. `pom.xml` (980 bytes) was never shown to the coder; every cycle it answered with a reply
whose first call was `write_file pom.xml` with placeholder content (`<content_of_pom.xml_with_added_
dependency>`). cria's fenced-call recovery refused it (a ```xml draft precedes the call: `prefix_fence`)
— but only as an event nobody reads, so the coder saw no result, no refusal and no fact, and
regenerated the same reply byte for byte. Had the draft fence been absent the recovery would have
promoted the call and the write would have replaced a real pom.xml with the placeholder.

Both halves are fixed on structure, never on the placeholder's spelling:
* a whole-file write naming an existing file with no recorded read/write is refused at the write
  lowering (the tool RESULT the coder reads) with what cria measured;
* a fenced call massage refuses to promote is said in the nudge that follows the call-less reply.
"""
import json
from pathlib import Path

import pytest

from cria import bodykeys, loop, massage, wsview
from cria.writeproxy import original_call, translate_outbound
from tests.test_loop import _Recorder, _Rlog, _ctx, _single_loop, _synth
from tests.wsfixture import survey

FIX = Path(__file__).parent / "fixtures" / "phi4_java_a2"
ROOT = "/home/jesse/suite-runs/suite-feed-pipeline-java_phi4_codex_poff_1791698490-30m9mppf"
JAVA = "src/main/java/pipeline/Importer.java"
REAL = json.loads((FIX / "0030-reply.json").read_text())
PLACEHOLDER = "<content_of_pom.xml_with_added_dependency>"
_CMD_SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}


@pytest.fixture
def view():
    v = wsview.View(ROOT, "g4")
    assert wsview.apply_survey(v, survey(
        f"D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\nF\t1\t4667\t{JAVA}\nF\t1\t980\tpom.xml",
        root=ROOT, complete=True))
    token = wsview.bind(v)
    yield v
    wsview.unbind(token)


def _completion(content, finish="stop"):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}


def _call(name, args):
    return {"choices": [{"message": {"tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def _cmd(comp):
    args = json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    return args["cmd"]


# ── the incident reply, as massage sees it ─────────────────────────────────────────────────────

def test_the_incident_reply_is_refused_and_the_refusal_now_carries_what_it_was_about():
    comp = massage.apply(_completion(REAL["content"]), REAL["tools"], None)
    msg = comp["choices"][0]["message"]
    assert not msg.get("tool_calls")                                  # still refused: unchanged behaviour
    assert msg["content"] == REAL["content"]
    assert comp[bodykeys.FENCED_REFUSED] == {"reason": "prefix_fence", "tool": "write_file", "path": "pom.xml"}


def test_a_reply_with_no_fenced_call_carries_no_refusal_hint():
    comp = massage.apply(_completion("Here is my plan: read the file, then edit it."), REAL["tools"], None)
    assert bodykeys.FENCED_REFUSED not in comp


def test_a_recovered_call_carries_no_refusal_hint():
    reply = '```json\n{"name": "read_file", "arguments": {"path": "pom.xml"}}\n```'
    comp = massage.apply(_completion(reply), REAL["tools"], None)
    assert comp["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "read_file"
    assert bodykeys.FENCED_REFUSED not in comp


def test_the_hint_is_on_the_set_the_wire_strips():
    assert bodykeys.FENCED_REFUSED in bodykeys.ALL


# ── the refusal is SAID: the nudge after the call-less reply ─────────────────────────────────────

def _drive_plan_off(view, replies):
    from cria.loop import _plan_off_session, _synthetic_plan
    from tests.test_loop import _body
    coder = _Recorder(replies)
    lp = loop.Loop(_ctx(coder, None))
    sess = _plan_off_session(_synthetic_plan("fix the importer"), "")
    sess.workspace_root = ROOT
    lp._store.put("sid:g4", sess)
    body = _body()
    body["messages"].insert(0, {"role": "user", "content": f"Working environment — cwd: {ROOT}"})
    log = _Rlog()
    lp.drive(body, "sid:g4", None, log)
    return coder, sess, log


def test_the_next_coder_prompt_says_which_call_did_not_run_and_what_exists(view):
    read_it = {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": "r1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "pom.xml"}'}}]},
        "finish_reason": "tool_calls"}]}
    coder, sess, log = _drive_plan_off(view, [_completion(REAL["content"]), read_it])
    assert "loop.fenced_call_refused_said" in log.kinds()
    nudge = coder.bodies[1]["messages"][-1]["content"]
    assert "write_file" in nudge and "`pom.xml`" in nudge
    assert "it was not run" in nudge and "nothing happened" in nudge
    assert "a code block comes before the call" in nudge               # the rule that stopped it
    assert "pom.xml already exists on disk (980 bytes) and no read of it has been recorded this session, by a read tool or by a shell command naming it" in nudge
    assert "cria" not in nudge.lower().replace("⟦ctx:denied⟧", "")      # #17
    assert {"role": "assistant", "content": REAL["content"]} in coder.bodies[1]["messages"]   # what it refers to


def test_no_fact_about_a_file_that_does_not_exist_or_was_read(view):
    sess = _synth()
    lp = _single_loop(lambda b, r: b"{}", workspace_root=ROOT)
    msgs = [{"role": "user", "content": f"Working environment — cwd: {ROOT}"}]
    text = lp._refused_call_text(sess, {"messages": msgs}, {"reason": "nested", "tool": "write_file", "path": "NEW.md"})
    assert "already exists" not in text
    sess.read_files = {f"{ROOT}/pom.xml": (980, "28 lines")}
    text = lp._refused_call_text(sess, {"messages": msgs}, {"reason": "nested", "tool": "write_file", "path": "pom.xml"})
    assert "already exists" not in text and "sits inside a larger quoted block" in text


# ── the write lowering: a whole-file replacement of a file never seen ───────────────────────────

def _check(view, **seen):
    sess = _synth()
    sess.read_files = {f"{ROOT}/{p}": (1, "1 lines") for p in seen.get("read", ())}
    lp = _single_loop(lambda b, r: b"{}", workspace_root=ROOT)
    lp._store.put("sid:g4", sess)
    return lp.unread_target_check("sid:g4", seen.get("messages", []), ROOT)


def _run(cmd, cwd):
    import subprocess
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True)


A3 = json.loads((Path(__file__).parent / "fixtures" / "phi4_java_a3" / "0011-reply.json").read_text())
SEED_POM = "<project>\n  <modelVersion>4.0.0</modelVersion>\n  <artifactId>pipeline</artifactId>\n</project>\n"
SEED_JAVA = "package pipeline;\n\npublic class Importer {\n    public Summary summarize() { return null; }\n}\n"


def test_the_a3_unread_writes_are_answered_with_the_files_and_nothing_is_written(view, tmp_path):
    """CALL 0011: real write_file calls for pom.xml and Importer.java, files never read."""
    (tmp_path / "src/main/java/pipeline").mkdir(parents=True)
    (tmp_path / "pom.xml").write_text(SEED_POM)
    (tmp_path / JAVA).write_text(SEED_JAVA)
    comp = json.loads(json.dumps(A3))
    translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                       unread_target=_check(view))
    by_path = {}
    for tc in comp["choices"][0]["message"]["tool_calls"]:
        cmd = json.loads(tc["function"]["arguments"])["cmd"]
        orig = original_call(cmd)
        if orig is None:
            continue                                                    # the coder's own exec_command
        path = json.loads(orig["arguments"]).get("path")
        by_path[path] = (tc, cmd)
    assert "write_bytes" in by_path["REVIEW.md"][1]                      # a new file is written as before
    for path, seed in (("pom.xml", SEED_POM), (JAVA, SEED_JAVA)):
        tc, cmd = by_path[path]
        assert "write_bytes" not in cmd and "survey" not in cmd.lower().split("printf")[0]
        out = _run(cmd, tmp_path)
        assert out.returncode == 0
        assert (tmp_path / path).read_text() == seed                    # not written
        assert f"{path} already exists on disk" in out.stdout
        assert "This write_file call was not run" in out.stdout and "unchanged" in out.stdout
        head, _, payload = out.stdout.partition("⟦ctx:read-instead⟧\n")
        assert payload == seed                                          # the file, byte for byte
        # a later write_file for this path in the history is no longer held: it is a recorded read
        msgs = [{"role": "assistant", "tool_calls": [{"id": "w1", "type": "function", "function": {
                    "name": "write_file", "arguments": json.dumps({"path": path, "content": "x"})}}]},
                {"role": "tool", "tool_call_id": "w1", "content": out.stdout}]
        assert path in loop._extract_reads(msgs)
        sess = _synth()
        lp = _single_loop(lambda b, r: b"{}", workspace_root=ROOT)
        lp._store.put("sid:g4", sess)
        assert lp.unread_target_check("sid:g4", msgs, ROOT)(path) == ""
        again = _call("write_file", {"path": path, "content": "class A {}"})
        translate_outbound(again, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                           unread_target=lp.unread_target_check("sid:g4", msgs, ROOT))
        assert "write_bytes" in _cmd(again)


def test_the_repeat_write_with_no_read_in_history_is_answered_again_never_passed(view):
    """The once-per-path pass (84c81ced) destroyed the seed files in A3: the hold lifts only on a read."""
    check = _check(view)
    for _ in range(3):
        comp = _call("write_file", {"path": "pom.xml", "content": PLACEHOLDER})
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT, unread_target=check)
        assert "write_bytes" not in _cmd(comp) and "cat " in _cmd(comp)


def test_the_answer_is_represented_as_the_coders_write_call_and_records_the_read(view, tmp_path):
    from cria.writeproxy import represent_inbound
    (tmp_path / "pom.xml").write_text(SEED_POM)
    comp = _call("write_file", {"path": "pom.xml", "content": PLACEHOLDER})
    translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT, unread_target=_check(view))
    tc = comp["choices"][0]["message"]["tool_calls"][0]
    out = _run(_cmd(comp), tmp_path).stdout
    envelope = f"Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOriginal token count: 9\nOutput:\n{out}"
    msgs = represent_inbound([{"role": "assistant", "tool_calls": [tc]},
                              {"role": "tool", "tool_call_id": "c1", "content": envelope}])
    assert msgs[0]["tool_calls"][0]["function"]["name"] == "write_file"
    assert msgs[1]["content"] == out and msgs[1]["content"].endswith(SEED_POM)
    assert "Chunk ID" not in msgs[1]["content"]
    assert "pom.xml" in loop._extract_reads(msgs)


def test_an_oversize_file_is_not_dumped_and_records_no_read(view, tmp_path):
    from cria import writeproxy
    (tmp_path / "pom.xml").write_text("<a/>\n" * (writeproxy.READ_INLINE_MAX // 5 + 10))
    comp = _call("write_file", {"path": "pom.xml", "content": PLACEHOLDER})
    translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT, unread_target=_check(view))
    out = _run(_cmd(comp), tmp_path).stdout
    assert "This write_file call was not run" in out and "⟦ctx:read-instead⟧" not in out
    assert out.count("<a/>") == 0                                       # paged through the read owner's steer
    msgs = [{"role": "assistant", "tool_calls": [{"id": "w1", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": "pom.xml", "content": "x"})}}]},
            {"role": "tool", "tool_call_id": "w1", "content": out}]
    assert loop._extract_reads(msgs) == {}


def test_a_write_the_harness_ran_is_not_recorded_as_a_read(view):
    msgs = [{"role": "assistant", "tool_calls": [{"id": "w1", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": "pom.xml", "content": "x"})}}]},
            {"role": "tool", "tool_call_id": "w1", "content": "Wrote pom.xml"}]
    assert loop._extract_reads(msgs) == {}


def test_any_content_is_answered_not_a_spelling_of_one(view):
    for content in ("<project/>", "your_updated_pom_xml_content_here", "x" * 4000):
        comp = _call("write_file", {"path": "pom.xml", "content": content})
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                           unread_target=_check(view))
        assert "write_bytes" not in _cmd(comp) and content not in _cmd(comp)


def test_the_hold_is_per_path(view):
    check = _check(view)
    other = _call("write_file", {"path": JAVA, "content": "class A {}"})
    translate_outbound(other, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT, unread_target=check)
    assert "write_bytes" not in _cmd(other) and f"{JAVA} already exists" in _cmd(other)
    fresh = _call("write_file", {"path": "NEW.md", "content": "n"})
    translate_outbound(fresh, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT, unread_target=check)
    assert "write_bytes" in _cmd(fresh)


def _shell_read(command, result="<project>\n</project>", call_id="s1"):
    return [{"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"cmd": command})}}]},
            {"role": "tool", "tool_call_id": call_id, "content": result}]


def test_a_shell_command_naming_the_file_may_have_read_it_so_no_hold(view):
    for command in ("cat pom.xml", f"sed -n 1,40p {ROOT}/pom.xml", "head -50 ./pom.xml && echo done"):
        comp = _call("write_file", {"path": "pom.xml", "content": "<project/>"})
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                           unread_target=_check(view, messages=_shell_read(command)))
        assert "write_bytes" in _cmd(comp), command


def test_a_shell_command_naming_a_different_file_is_not_a_read_of_this_one(view):
    for command in ("cat pom.xml.bak", "cat my-pom.xml", "ls -la", "mvn -q compile"):
        comp = _call("write_file", {"path": "pom.xml", "content": "<project/>"})
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                           unread_target=_check(view, messages=_shell_read(command)))
        assert "write_bytes" not in _cmd(comp), command


def test_a_refused_or_empty_shell_result_is_not_a_read(view):
    from cria import denial
    for result in (denial.mark("that command cannot run here"), "   "):
        comp = _call("write_file", {"path": "pom.xml", "content": "<project/>"})
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                           unread_target=_check(view, messages=_shell_read("cat pom.xml", result)))
        assert "write_bytes" not in _cmd(comp)


def test_a_file_the_coder_read_may_be_rewritten(view):
    comp = _call("write_file", {"path": "pom.xml", "content": "<project/>"})
    translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                       unread_target=_check(view, read=["pom.xml"]))
    assert "write_bytes" in _cmd(comp)


def test_a_file_the_coder_read_in_this_conversation_may_be_rewritten(view):
    msgs = [{"role": "assistant", "tool_calls": [{"id": "r1", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": "pom.xml"})}}]},
            {"role": "tool", "tool_call_id": "r1", "content": "<project>\n</project>"}]
    comp = _call("write_file", {"path": "pom.xml", "content": "<project/>"})
    translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                       unread_target=_check(view, messages=msgs))
    assert "write_bytes" in _cmd(comp)


def test_a_new_file_is_never_refused(view):
    comp = _call("write_file", {"path": "REVIEW.md", "content": "# review\n"})
    translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                       unread_target=_check(view))
    assert "write_bytes" in _cmd(comp)


def test_an_unsurveyed_workspace_says_nothing(view):
    fresh = wsview.View(ROOT, "g4-unsurveyed")
    token = wsview.bind(fresh)
    try:
        comp = _call("write_file", {"path": "pom.xml", "content": "<project/>"})
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                           unread_target=_check(fresh))
        assert "write_bytes" in _cmd(comp)               # unknown is not "exists" (#11b)
    finally:
        wsview.unbind(token)


def test_a_session_that_does_not_keep_the_record_makes_no_claim(view):
    lp = _single_loop(lambda b, r: b"{}", workspace_root=ROOT)
    lp._ctx.assists = False
    assert lp.unread_target_check("sid:g4", [], ROOT) is None


def test_the_lowering_without_the_check_is_unchanged(view):
    comp = _call("write_file", {"path": "pom.xml", "content": "<project/>"})
    translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT)
    assert "write_bytes" in _cmd(comp)


# ── the pasted-file recovery's own refusal ───────────────────────────────────────────────────────

def test_the_pasted_file_recovery_refusal_reaches_the_nudge(view):
    from tests.test_text_write_recovery import FIX as TW, TextWriteTests
    t = TextWriteTests("test_the_a1_pasted_class_becomes_that_files_write_and_the_pom_excerpt_never_does")
    t.setUp()
    try:
        content = TW["replies"]["a1_0022"]["content"]
        tools = TW["menus"][TW["replies"]["a1_0022"]["menu"]]
        sess = _synth()
        # the java file was never read in this session: the recovery refuses unread_existing_file …
        _ch, calls, _asked, log, sess = t.turn(content, tools, read=False, sess=sess)
        assert calls == [] and log.get("loop.text_write_refused")["reason"] == "unread_existing_file"
        # … and the fact it refused on rides on the nudge that follows, once.
        lp = _single_loop(lambda b, r: b"{}", workspace_root=t.view.root)
        nudge = lp._unexecuted_nudge_text(sess)
        assert "already exists on disk" in nudge and "no read of it has been recorded" in nudge
        assert lp._unexecuted_nudge_text(sess) == loop.prompts.load("unexecuted_write_nudge")
    finally:
        t.doCleanups()
