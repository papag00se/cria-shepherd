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
from cria.writeproxy import translate_outbound
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


def test_the_placeholder_write_is_refused_with_the_measured_fact_and_nothing_is_lowered(view):
    comp = _call("write_file", {"path": "pom.xml", "content": PLACEHOLDER})
    translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                       unread_target=_check(view))
    cmd = _cmd(comp)
    assert "pom.xml already exists on disk (980 bytes) and no read of it has been recorded this session, by a read tool or by a shell command naming it" in cmd
    assert "This write_file call was not run, so nothing was written and the file is unchanged." in cmd
    assert "Once a read of it is recorded this no longer applies" in cmd     # what changes the fact
    assert "the same write sent again is not held" in cmd
    assert "write_bytes" not in cmd and PLACEHOLDER not in cmd
    assert "⟦ctx:denied⟧" in cmd                                         # the one refusal owner marks it


def test_any_content_is_refused_not_a_spelling_of_one(view):
    for content in ("<project/>", "your_updated_pom_xml_content_here", "x" * 4000):
        comp = _call("write_file", {"path": "pom.xml", "content": content})
        translate_outbound(comp, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT,
                           unread_target=_check(view))     # a fresh session each time: the first attempt
        assert "write_bytes" not in _cmd(comp)


def test_the_hold_is_made_once_per_path_and_the_second_attempt_passes(view):
    check = _check(view)
    first = _call("write_file", {"path": "pom.xml", "content": PLACEHOLDER})
    translate_outbound(first, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT, unread_target=check)
    assert "write_bytes" not in _cmd(first) and "already exists on disk" in _cmd(first)
    again = _call("write_file", {"path": "pom.xml", "content": PLACEHOLDER})
    translate_outbound(again, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT, unread_target=check)
    assert "write_bytes" in _cmd(again)                        # held once, never trapped
    # …and ./pom.xml / the absolute spelling is the SAME path (normalised through the view)
    abs_again = _call("write_file", {"path": f"{ROOT}/pom.xml", "content": "<project/>"})
    translate_outbound(abs_again, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT, unread_target=check)
    assert "write_bytes" in _cmd(abs_again)


def test_the_hold_is_per_path(view):
    check = _check(view)
    translate_outbound(_call("write_file", {"path": "pom.xml", "content": "x"}), _CMD_SHELL,
                       injected={"write_file"}, workspace_root=ROOT, unread_target=check)
    other = _call("write_file", {"path": JAVA, "content": "class A {}"})
    translate_outbound(other, _CMD_SHELL, injected={"write_file"}, workspace_root=ROOT, unread_target=check)
    assert "write_bytes" not in _cmd(other) and f"{JAVA} already exists" in _cmd(other)


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
