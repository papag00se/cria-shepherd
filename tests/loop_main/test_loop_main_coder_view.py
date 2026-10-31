"""What the coder is handed: the framed history, cria's own marks kept out of it, and a harness compaction reattributed."""
import json

import pytest

from cria import prompts
from cria.loop import (TASK_COMPLETE_TOOL, _add_completion_tool, _completion_text, _frame_for_item, _has_tool_calls,
                       _history_root, _normalize_completion, reframe_compaction)
from cria.shelltool import shell_args
from cria.toolmenu import cheatsheet

from loop_main_helpers import SHELL, Rlog, loop_main_local_view  # noqa: F401

def comp(content=None, *calls):
    return {"choices": [{"message": {"content": content, "tool_calls": [
        {"id": "x", "type": "function", "function": {"name": n, "arguments": a}} for n, a in calls] or None}}]}


@pytest.mark.parametrize("reply,acting,text,names", [
    (comp(None, (TASK_COMPLETE_TOOL, '{"summary": "made hello.py"}')), False, "made hello.py", []),
    (comp(None, (TASK_COMPLETE_TOOL, '{"summary": "x"}'), ("write_file", '{"path": "a"}')), True, None, ["write_file"]),
    (comp(None, ("write_file", "{}")), True, None, ["write_file"]),
    (comp("all done"), False, "all done", []),
])
def test_task_complete_is_a_done_claim_for_the_gate_alone_and_is_dropped_beside_real_work(reply, acting, text, names):
    """A lone task_complete becomes a plain-text done (the SAME gate a bare done runs); beside real work the premature
    done is ignored; real tools and bare prose pass through. It is advertised once per coder turn and never forwarded."""
    out = _normalize_completion(reply, Rlog())
    assert _has_tool_calls(out) is acting
    if text is not None:
        assert _completion_text(out) == text
    assert [t["function"]["name"] for t in out["choices"][0]["message"].get("tool_calls") or []] == names
    menu = {"tools": [{"type": "function", "function": {"name": "shell"}}]}
    _add_completion_tool(menu)
    _add_completion_tool(menu)
    assert [t["function"]["name"] for t in menu["tools"]] == ["shell", TASK_COMPLETE_TOOL]


def test_the_plan_off_frame_is_the_raw_task_under_crias_coder_prompt_with_no_harness_prompt_or_banner():
    """server._direct_coder_body equivalent: cria's coder prompt (+ tool hint) leads, the harness system prompt and cria's
    own banner line are removed, the env preamble, raw task and work history stay, and the conversation root is unchanged
    (no step cage, no 'step 1/1'); the IGNORED step text of a synthetic item never reaches the model."""
    msgs = [{"role": "system", "content": "You are Codex, an autonomous agent."},
            {"role": "user", "content": "<env>cwd=/repo</env>"},
            {"role": "user", "content": "Add a --verbose flag to the CLI."},
            {"role": "assistant", "content": "⟦cria⟧ coder · gemma"},
            {"role": "tool", "content": "ok"}]
    out = _frame_for_item(msgs, "IGNORED-STEP", "IGNORED-SUMMARY", 1, 1, prior_work="", tools=[SHELL], synthetic=True)
    hint = cheatsheet([SHELL])
    assert out[0] == {"role": "system", "content": prompts.load("coder_system") + (f"\n\n{hint}" if hint else "")}
    assert out[1:] == [msgs[1], msgs[2], msgs[4]] and _history_root(out) == _history_root(msgs)
    blob = json.dumps(out)
    assert "IGNORED" not in blob and "step 1" not in blob.lower() and "You are Codex" not in blob


def test_a_step_frame_keeps_the_task_as_history_and_hides_cria_plumbing_from_the_coder():
    """A genuine step keeps the whole task as background and the step as the ask; cria's own plan-file write and its
    banner lines (which a coder parrots back) never reach the model, while its real calls and prose do."""
    msgs = [{"role": "user", "content": "Write a handler and a README."},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "exec_command", "arguments": '{"cmd": "mkdir -p .cria && printf %s YWJj | base64 -d > .cria/x.md"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "wrote .cria/x.md"},
            {"role": "assistant", "content": "⟦cria⟧ planned 5 steps\n⟦cria⟧ update_plan: [...]"},
            {"role": "assistant", "content": "⟦cria⟧ coder · m\nActually reading handler.py now."},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c2", "type": "function", "function": {
                "name": "exec_command", "arguments": '{"cmd": "cat handler.py"}'}}]}]
    framed = _frame_for_item(msgs, "Create handler.py", "", 2, 3, tools=[SHELL])
    blob = json.dumps(framed)
    assert ".cria" not in blob and "⟦cria⟧" not in blob
    assert "cat handler.py" in blob and "Actually reading handler.py now." in blob and "README" in blob
    assert framed[-1]["role"] == "user" and "Create handler.py" in framed[-1]["content"] and "README" not in framed[-1]["content"]


MARKER = ("Another language model started to solve this problem and produced a summary of its thinking process. "
          "You also have access to the state of the tools that were used by that language model. Use this to build on "
          "the work that has already been done and avoid duplicating work. Here is the summary produced by the other "
          "language model, use the information in this summary to assist with your own analysis:\n")


def env(cwd):
    return {"role": "user", "content": f"<environment_context><cwd>{cwd}</cwd></environment_context>"}


@pytest.mark.parametrize("shape", ["reattributed", "list_parts", "drifted_boundary", "empty_workspace", "populated",
                                   "validator_dropped_briefing"])
def test_a_harness_compaction_turn_is_reattributed_without_granting_authority_and_never_over_a_false_claim(shape, tmp_path):
    """Codex's VS Code compaction appends 'Another language model started to solve this problem…', misattributing the
    model's own summary. The root does not change, so only this reframe repairs it. Over an EMPTY cwd the 'build on
    existing files, do NOT recreate' claim is false and is inverted; a briefing the validator dropped claims no account."""
    summary = "Built handler.py + tests; live test still failing."
    (tmp_path / "w").mkdir()
    if shape == "populated":
        (tmp_path / "w" / "handler.py").write_text("x = 1\n")
    content = {"drifted_boundary": "Another language model started to solve this problem and did a bunch.\n" + summary,
               "validator_dropped_briefing": MARKER}.get(shape, MARKER + summary)
    if shape == "list_parts":
        content = [{"type": "text", "text": content}]
    msgs = [{"role": "user", "content": "task: build the lambda"}, {"role": "user", "content": content}]
    if shape in ("empty_workspace", "populated"):
        msgs.insert(0, env(tmp_path / "w"))
    out, hit = reframe_compaction(msgs)
    new = out[-1]["content"]
    assert hit and "Another language model" not in str(new) and out[-2] is msgs[-2]
    if shape == "validator_dropped_briefing":
        assert "ungrounded account" not in new and "did not survive" in new
    else:
        assert summary in str(new)
    if shape == "empty_workspace":
        assert "EMPTY" in new and "Start fresh in this workspace" in new and "do NOT recreate" not in new
    elif shape != "validator_dropped_briefing":
        assert "ungrounded account" in str(new)
    again, hit_again = reframe_compaction(out)                           # idempotent: already reframed
    assert not hit_again and again is out
    plain = [{"role": "user", "content": "just a normal task"}]
    assert reframe_compaction(plain) == (plain, False) and reframe_compaction(plain)[0] is plain


@pytest.mark.parametrize("tool,field", [({"name": "shell", "schema": {"properties": {"command": {"type": "array"}}}}, "command"),
                                        ({"name": "exec_command", "schema": {"properties": {
                                            "cmd": {"type": "string"}, "justification": {"type": "string"}},
                                            "required": ["cmd"]}}, "cmd")])
def test_a_shell_call_is_written_into_the_field_the_harness_tools_schema_names(tool, field):
    """Codex's exec_command carries the command in `cmd`; producing `command` stalled the plan loop ('missing cmd field')."""
    args = shell_args(tool, "ls")
    assert list(args) == [field] and "ls" in str(args[field])
