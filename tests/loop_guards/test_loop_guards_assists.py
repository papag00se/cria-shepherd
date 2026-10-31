"""Loop-side assists that keep a derailed small model on the task without writing for it or hiding its work."""
import json

import pytest

from cria import bodykeys, completedwork as cw, loop, prompts, selfcompact, windowcaps, wsview
from cria.assistruntime import AssistRuntime
from cria.config import Role
from cria.plan import Plan, PlanItem
from loop_guards_helpers import Log

DICTATION = ("UNSTUCK You are stuck because pytest is warning about an unknown mark named live. 1. Register "
             'the mark in resolve_handle.py: pytest.register_pytest_mark("live")')
QUOTE = ("Two bugs each named by the check: resolve_handles.py line 14 has data=response.json() where one "
         "mock's json is a dict, not callable; fix the mock so it matches how line 14 uses it.")


@pytest.mark.parametrize("directive,answer,dictates", [
    # run 20260801T232511 call 0132: an invented API call sat inline in prose and reached the coder
    (DICTATION, "DICTATES", True),
    (QUOTE, "DESCRIBES", False),             # quoting what IS is allowed; the old regex ate this steer
    (QUOTE, "`describes`", False),           # a model's decoration does not change its ruling
    (DICTATION, "I think it depends", True), # unreadable: the pre-filter's verdict stands (only ever delivers more)
    (DICTATION, None, True),                 # no reasoner at all: the same safe direction
    ("Read the file before you rewrite it.", None, False),
])
def test_a_steer_is_dropped_as_dictation_only_when_code_shaped_and_not_ruled_a_description(directive, answer, dictates):
    asked = []

    def ask(system, user=""):
        asked.append(system)
        return answer

    assert loop._dictates_code(directive, None if answer is None else ask) is dictates
    if answer is not None and directive != "Read the file before you rewrite it.":
        assert directive in asked[0] and "DIRECTIVE:" not in asked[0]        # a bare label was answered INSTEAD of a verdict
        assert asked[0].rstrip().endswith("DICTATES or DESCRIBES.")
    elif directive.startswith("Read"):
        assert not asked                                                      # a plain steer never costs a question


PASTED = "Here is the script:\n\n```python\n" + "\n".join(f"line_{i} = {i}" for i in range(20)) + "\n```\n"


@pytest.mark.parametrize("finish,carried", [("stop", True), ("length", False)])
def test_the_unexecuted_write_nudge_shows_the_model_the_reply_it_is_about_unless_it_was_cut_off(finish, carried):
    """nemotron-nano 1786243834 call 0073: the nudge said "send that same content again" but the re-framed
    history never held the internal prose turn; ordered to resend text it could not see, the model re-read the
    spec a 7th time and the run died. A reply cut at the cap is the worse lie, so it is not carried."""
    seen = {}

    def coder_turn(sess, framed, body, step, rlog, **kwargs):
        seen["messages"] = framed["messages"]
        return {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "write_file", "arguments": "{}"}}]}}]}

    lp = loop.Loop(loop.LoopContext(None, None, None))
    lp._coder_turn = coder_turn
    sess = loop.PlanSession(plan=Plan(id="x", task="t", created="c", items=[PlanItem("write the script")]))
    comp = {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": PASTED}}]}
    lp._pasted_redrive(sess, comp, {"messages": []}, Log(), plan_off=True)
    lp._gate_single_done(sess, comp, {"messages": [{"role": "user", "content": "do it"}]}, {"messages": []},
                         "k1", Log(), completion_act_first=AssistRuntime.select().completion_act_first)
    roles = [(m["role"], m.get("content")) for m in seen["messages"]]
    assert (("assistant", PASTED) in roles) is carried                      # verbatim, never clipped
    assert "your last message" in seen["messages"][-1]["content"] and sess.nudge_reply == ""


ROOT, JAVA = "/w/feed-run", "src/main/java/pipeline/Importer.java"
CLASS = "package pipeline;\n\npublic class Importer {\n" + "".join(f"    int f{i}() {{ return {i}; }}\n" for i in range(60)) + "}"
REPLY = ("1. Add to `pom.xml`:\n\n```xml\n<dependency>\n  <artifactId>commons-csv</artifactId>\n</dependency>\n```\n\n"
         f"2. **Refactor `Importer.java`**:\n\n```java\n{CLASS}\n```\n\nThen create REVIEW.md.\n")
WRITE = [{"type": "function", "function": {"name": "write_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    "required": ["path", "content"]}}}]


def text_write_turn(judge, *, read=True):
    """phi4 / Java A1 (capture 20261010T212733 call 0022): a pom excerpt, then the COMPLETE Importer.java, then pseudo-actions."""
    view = wsview.View(ROOT, "text-write")
    tree = f"D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\nF\t1\t4543\t{JAVA}\nF\t1\t980\tpom.xml"
    survey = "\n".join([f"{wsview._SEC_PREFIX}meta{wsview._SEC_SUFFIX}", f"root\t{ROOT}",
                        f"{wsview._SEC_PREFIX}tree{wsview._SEC_SUFFIX}", tree,
                        *(f"{wsview._SEC_PREFIX}{n}{wsview._SEC_SUFFIX}" for n in ("blob", "outside", "progs")),
                        f"{wsview._SEC_PREFIX}done{wsview._SEC_SUFFIX}", f"entries\t{wsview.tree_entries(tree)}",
                        "complete\t1", wsview.SURVEY_CLOSE])
    assert wsview.apply_survey(view, survey)
    asked, log = [], Log()
    ruling = lambda body, rlog: asked.append(body["messages"][0]["content"]) or json.dumps(
        {"choices": [{"message": {"content": judge}}]}).encode()
    coder = lambda body, rlog: json.dumps({"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": REPLY}}]}).encode()
    lp = loop.Loop(loop.LoopContext(planner=None, coder_chat=coder, reasoner_chat=ruling, planner_enabled=False,
                                    reasoner_role=Role(name="reasoner", backend="local"), runs_dir="", workspace_root=ROOT))
    sess = loop.PlanSession(plan=Plan(id="x", task="Fix the importer; add `REVIEW.md`.", created="c", items=[PlanItem("s")]),
                            synthetic=True)
    sess.workspace_root = ROOT
    history = [{"role": "assistant", "tool_calls": [{"id": "rd", "type": "function", "function": {
        "name": "read_file", "arguments": json.dumps({"path": f"{ROOT}/{JAVA}"})}}]},
        {"role": "tool", "tool_call_id": "rd", "content": "package pipeline;"}] if read else []
    token = wsview.bind(view)
    try:
        comp = lp._coder_turn(sess, {"messages": [], "tools": WRITE}, {"messages": history}, step=1, rlog=log)
    finally:
        wsview.unbind(token)
    return comp["choices"][0], asked, log


def test_a_whole_file_typed_into_chat_becomes_that_files_write_only_when_judged_whole_and_already_read():
    """The pom excerpt never becomes a write; only the exact positive word converts; anything else leaves the reply as it came."""
    ch, asked, log = text_write_turn("WHOLE_FILE\n\nThe assistant presents the block as the complete file.")
    (call,) = ch["message"]["tool_calls"]
    args = json.loads(call["function"]["arguments"])
    assert (call["function"]["name"], args["path"], args["content"]) == ("write_file", f"{ROOT}/{JAVA}", CLASS + "\n")
    assert len(asked) == 1 and "pom.xml" not in asked[0].split("FILE NAMED BY THE ASSISTANT:")[1].split("WORKSPACE FACT")[0]
    assert ch["finish_reason"] == "tool_calls" and "REVIEW.md" not in ch["message"]["content"].split("Refactor")[1]
    assert log.first("massage.text_write_recovered")["dropped_chars"] > 0          # disclosed, not silent
    for answer in ("OTHER", "NOT_WHOLE_FILE", "whole file", ""):
        ch, _, log = text_write_turn(answer)
        assert not ch["message"].get("tool_calls") and ch["message"]["content"] == REPLY
        assert "loop.text_write_refused" in log.names()
    ch, _, _ = text_write_turn("WHOLE_FILE", read=False)                      # an existing file the coder never read
    assert not ch["message"].get("tool_calls") and ch["message"]["content"] == REPLY


def test_the_completed_work_briefing_is_carried_only_from_the_assistants_own_closed_block():
    block = f"{cw.BRIEFING_OPEN}\nClaimed finished work\n{cw.BRIEFING_CLOSE}"
    absent = cw.HistoryStatus.ABSENT
    for role in ("user", "tool", "system", "developer"):
        assert cw.read_history([{"role": role, "content": block}]).status is absent
    for content in ("Quoted inline: " + block, "> " + block, [{"type": "text", "text": block}],
                    f"{cw.BRIEFING_CLOSE}\n{cw.BRIEFING_OPEN}\nUnclosed claim"):
        assert cw.read_history([{"role": "assistant", "content": content}]).status is absent
    earlier = {"role": "assistant", "content": f"{cw.BRIEFING_OPEN}\nEarlier\n{cw.BRIEFING_CLOSE}"}
    latest = {"role": "assistant", "content": f"{cw.BRIEFING_OPEN}\n Latest facts \n{cw.BRIEFING_CLOSE}"}
    blank = {"role": "assistant", "content": f"{cw.BRIEFING_OPEN}\n \n{cw.BRIEFING_CLOSE}"}
    assert cw.read_history([earlier, latest]).text == "Latest facts"
    assert cw.read_history([earlier, blank]).status is cw.HistoryStatus.EMPTY   # an emptied block does not resurrect older memory


def test_every_window_scaled_cap_is_its_old_value_at_the_reference_window_and_never_small_when_unknown():
    """A bound tuned on a 49,152-token window was the WHOLE window of a 16K model (a compaction lens reserved
    its whole 16,384-token reply cap, and the floor swapped 53-215 evidence turns for a digest)."""
    assert windowcaps.JUDGE_REPLY == 16384 and windowcaps.SELFCOMPACT_REFOLD == 6000
    for name in windowcaps.NAMES:
        cap = getattr(windowcaps, name.upper())
        low, high = windowcaps._SPECS[name][1:]
        sizes = [windowcaps.scaled(cap, w) for w in (1, 8192, 16384, 49152, 131072, 10**7)]
        assert windowcaps.scaled(cap, 49152) == int(cap) and sizes == sorted(sizes) and (sizes[0], sizes[-1]) == (low, high)
        assert all(windowcaps.scaled(cap, unknown) == int(cap) for unknown in (None, 0, -1, True))
    assert windowcaps.scaled(windowcaps.JUDGE_REPLY, 16384) <= 16384 * 0.4
    assert windowcaps.resolve(16384, 8192) == 16384                          # an operator's explicit value is never rescaled


def test_the_compaction_ask_comes_last_and_superseded_file_bodies_do_not_reach_the_summarizer():
    """ada-handles/mellum2: a transcript ending on the coder's own "Do ONLY this step" made the compactor
    obey it and fabricate a file; nemotron orders-api-py: the briefing described two versions of db.py as current."""
    ask = prompts.load("compact_closing_ask")
    out = selfcompact.compaction_request([{"role": "user", "content": "do ONLY this step, then stop: write the file"}])
    assert out.endswith(ask) and out.index("write the file") < out.index(ask)
    assert "no tool call" in ask.lower() and "no code" in ask.lower()
    old, new = "OLD_CONTENT_" * 40, "NEW_CONTENT_" * 40

    def write(cid, body):
        return [{"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": "app.py", "content": body})}}]},
            {"role": "tool", "tool_call_id": cid, "content": prompts.render("write_confirm", path="app.py"),
             bodykeys.RESULT_OUTCOME: "landed"}]

    request = selfcompact.compaction_request([{"role": "user", "content": "write app.py"}, *write("c1", old), *write("c2", new)])
    assert old not in request and new in request
