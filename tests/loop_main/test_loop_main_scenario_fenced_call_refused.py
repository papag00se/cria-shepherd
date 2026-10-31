"""Scenario (phi4 A2: pom.xml, written seven times with placeholder content): the coder writes its call as a fenced JSON block for a tool
that is not on this turn's menu, naming a file that exists and that it never read. Real Loop.drive (plan-off) over a real directory, fake
coder: nothing runs, and the coder is told which call did not run, why, and the measured fact that the file exists unread."""
import json

from cria.classify import Classification
from cria.loop import LoopStore

from loop_main_helpers import Chat, Rlog, acting, body, completion, plan_off_loop, loop_main_local_view  # noqa: F401

CODING = Classification("task", "coding", "fixture")
FENCED = 'I will edit it:\n```json\n{"name": "edit_file", "arguments": {"path": "%s", "old_string": "a", "new_string": "b"}}\n```'


def test_a_fenced_call_that_was_not_run_is_said_with_its_reason_and_the_unread_files_measured_fact(tmp_path):
    (tmp_path / "pom.xml").write_text("<project>" + "x" * 970 + "</project>\n")
    pom = str(tmp_path / "pom.xml")
    fenced = FENCED % pom
    coder, rlog = Chat(completion(fenced), acting()), Rlog()
    out = plan_off_loop(coder, store=LoopStore(), workspace_root=str(tmp_path)).drive(body("fix the build"), "sid:f", CODING, rlog)
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "shell"
    retry = coder.bodies[1]["messages"]
    assert retry[-2] == {"role": "assistant", "content": fenced}                       # its own words are carried, not dropped
    said = retry[-1]["content"]
    assert retry[-1]["role"] == "user" and f"`edit_file` for `{pom}`" in said and "not one of this turn's tools" in said
    assert "already exists on disk (990 bytes)" in said.split("\n\n", 1)[1] and "cria" not in said.lower()       # the measured fact rides after the reason
    assert [f["reason"] for k, f in rlog.events if k == "loop.fenced_call_refused_said"] == ["off_menu"]
