"""A held write is answered with a read of its file, carried out by cria through the harness `read` primitive: the real captured
incidents (tests/fixtures/unread_write), the receipt wording, and what the history readers (the loop's read ledger and unread-hold
hint) learn from the result. The earlier bridge's tests ported to the engine; the wording and the guard semantics did not change."""
import copy
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cria import bodykeys, denial, wsview
from write_edit_helpers import call, lower, represented, run, write_edit_workspace_view  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "unread_write"
ENVELOPE = "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code {rc}\nOriginal token count: 9\nOutput:\n"


def answered(tcs, workspace):
    """Run each lowered call as the harness does and present the turn as the model's history."""
    msgs = [{"role": "assistant", "tool_calls": tcs}]
    for tc in tcs:
        done = run(tc, workspace)
        msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": ENVELOPE.format(rc=done.returncode) + done.stdout + done.stderr})
    return represented(msgs, workspace_root=str(workspace))


def test_captured_ruby_batched_edits_hold_only_the_first_unread_readme_per_path_and_the_second_is_the_refusal_alone(tmp_path):
    """The batch of the 2026-11-09 Ruby run: two edits of one unread file: the first is answered with the file, the second with the
    refusal alone (the read answers for both); the model's own call arguments are restored to what it sent."""
    fixture = json.loads((FIXTURES / "ruby-batched-20261109.json").read_text())
    workspace = tmp_path / "workspace"
    shutil.copytree(REPO / "suite/tasks/shipping-rates-rb/seed", workspace)
    calls = [copy.deepcopy(c) for c in fixture["choices"][0]["message"]["tool_calls"]
             if c["function"]["name"] == "edit_file" and json.loads(c["function"]["arguments"])["path"] != "Gemfile"]
    tcs = lower(calls, injected=("edit_file",), root=str(workspace), unread_target=lambda p: "unread")
    commands = [json.loads(tc["function"]["arguments"])["cmd"] for tc in tcs]
    assert len(tcs) == len(calls) and all(tc["id"].startswith("ctx_") for tc in tcs)
    assert sum("python3 -I -S" in c for c in commands) == 2 and sum(c.lstrip().startswith("printf") for c in commands) == 3    # one read per held path, the rest only say so
    shown = answered(tcs, workspace)
    results = [m for m in shown if m["role"] == "tool"]
    delivered = set()
    for original, result in zip(calls, results):
        path = json.loads(original["function"]["arguments"])["path"]
        assert denial.refused(result) and "⟦ctx:read-unverified⟧" not in result["content"]
        if path not in delivered:
            assert denial.read_payload(result) == (workspace / path).read_text() and result["content"].endswith((workspace / path).read_text())
            delivered.add(path)
        else:
            assert denial.read_payload(result) is None and result["content"] == "⟦ctx:denied⟧ This edit_file call was not run.\n"
    assert all(set(json.loads(c["function"]["arguments"])) == {"path"} for m in shown if m.get("tool_calls") for c in m["tool_calls"])


@pytest.mark.parametrize("label,seed", [("node", "handles-cli-node"), ("nemotron", "handles-cli-node"), ("python-direct-replay", "orders-api-py")])
def test_incident_mutations_are_held_and_answered_with_the_file_through_the_engine(tmp_path, label, seed):
    """Campaign first replies (Node and Nemotron) and the separately labelled Python direct replay: every held mutation is answered with
    the exact bytes of its file, counts as the coder's read of it and sets the unread-hold hint for the next request only."""
    from cria import initial_inventory, loop
    workspace = tmp_path / "workspace"
    shutil.copytree(REPO / "suite" / "tasks" / seed / "seed", workspace)
    data = json.loads(subprocess.run(["bash", "-c", initial_inventory.command(str(workspace))], capture_output=True, text=True, check=True).stdout)
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir="", workspace_root=str(workspace), assists=True),
                       loop.LoopStore())
    driver._put_session("sid:incident", loop._plan_off_session(loop._synthetic_plan("task"), ""))
    fixture = json.loads((FIXTURES / (label + ".json")).read_text())
    assert fixture["calls"]
    for original in fixture["calls"]:
        args = json.loads(original["function"]["arguments"])
        path = workspace / args["path"]
        expected = path.read_text()
        name = original["function"]["name"]
        view = wsview.View(str(workspace), "sid:incident")
        assert view.apply_initial_inventory(data, str(workspace))
        token = wsview.bind(view)
        try:
            tcs = lower([copy.deepcopy(original)], injected=(name,), root=str(workspace),
                        unread_target=driver.unread_target_check("sid:incident", [], str(workspace)))
            assert tcs[0]["id"].startswith("ctx_")                                    # the harness is shown cria's primitive call, not a program
            shown = answered(tcs, workspace)
            result = next(m for m in shown if m.get("tool_call_id") == original["id"])
            assert denial.refused(result) and denial.read_payload(result) == expected and f"This {name} call was not run" in result["content"]
            assert args["path"] in loop._extract_reads(shown)
            assert loop._recent_unread_hold(shown) and not loop._recent_unread_hold(shown + [{"role": "assistant", "content": "next turn"}])
            assert path.read_text() == expected
        finally:
            wsview.unbind(token)


@pytest.mark.parametrize("name", ["write_file", "create_file", "edit_file", "str_replace", "apply_patch"])
@pytest.mark.parametrize("changed", [False, True])
def test_held_receipt_attributes_only_the_call_and_the_read_returns_the_file_as_it_is_when_read(tmp_path, name, changed):
    """README-overwrite guard semantics: the answer is the file's bytes as read (a file that changed before the read is returned as it is
    now), under the call's own receipt wording."""
    from cria import initial_inventory, loop
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "x.txt"
    path.write_text("old\n")
    data = json.loads(subprocess.run(["bash", "-c", initial_inventory.command(str(workspace))], capture_output=True, text=True, check=True).stdout)
    view = wsview.View(str(workspace), "sid:receipt")
    assert view.apply_initial_inventory(data, str(workspace))
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir="", workspace_root=str(workspace), assists=True),
                       loop.LoopStore())
    driver._put_session("sid:receipt", loop._plan_off_session(loop._synthetic_plan("task"), ""))
    args = ({"input": f"*** Begin Patch\n*** Update File: {path}\n@@\n-old\n+replacement\n*** End Patch\n"} if name == "apply_patch" else
            {"path": str(path), **({"content": "replacement"} if name in ("write_file", "create_file") else {"old_string": "old", "new_string": "replacement"})})
    original = {"id": "held", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    token = wsview.bind(view)
    try:
        tcs = lower([original], injected=(name,), root=str(workspace), unread_target=driver.unread_target_check("sid:receipt", [], str(workspace)))
        expected = "new external content\n" if changed else "old\n"
        if changed:
            path.write_text(expected)
        shown = answered(tcs, workspace)
        result = next(m for m in shown if m.get("tool_call_id") == "held")
        assert denial.refused(result) and denial.read_payload(result) == expected
        represented_call = next(m for m in shown if m.get("role") == "assistant")["tool_calls"][0]
        assert represented_call["function"]["name"] == name and json.loads(represented_call["function"]["arguments"]) == {"path": str(path)}
        assert "⟦ctx:rejected-candidate⟧" not in str(shown)
        assert f"This {name} call was not run" in result["content"].split("⟦ctx:read-instead⟧", 1)[0]
        assert "cria" not in result["content"].lower()
    finally:
        wsview.unbind(token)
