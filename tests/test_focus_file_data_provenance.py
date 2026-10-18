"""Known file payloads are data, never lookup failures inferred from their words."""
import base64
import copy
import json
from dataclasses import replace

import pytest

from cria import editrecovery, focustrim, research, shelltool
from cria.assistruntime import AssistRuntime, bound


def action(index, name, content, *, arguments=None):
    return [{"role": "assistant", "tool_calls": [{"id": str(index), "type": "function",
             "function": {"name": name, "arguments": json.dumps(
                 arguments if arguments is not None else {"path": f"source{index}.py"})}}]},
            {"role": "tool", "tool_call_id": str(index), "content": content}]


def source_reads(name, *, arguments=None):
    history = [{"role": "user", "content": "inspect the existing files"}]
    for i in range(focustrim._SPAM_KEEP + 4):
        content = f'# source file {i}\nmessage = "not found; command not found; No such file or directory"\n'
        history += action(i, name, content, arguments=(arguments(i) if arguments else None))
    return history


@pytest.mark.parametrize("name", research._READ_TOOLS)
def test_all_declared_native_read_aliases_keep_whole_file_bytes_and_pairs(name):
    history = source_reads(name)
    before = copy.deepcopy(history)
    out, report = focustrim.trim(history)
    assert out == before and history == before
    assert report.dropped_calls == report.dropped_msgs == report.squashed_runs == 0
    assert {call["id"] for m in out for call in m.get("tool_calls", [])} == {
        m["tool_call_id"] for m in out if m.get("role") == "tool"}


@pytest.mark.parametrize("name", ["files.open_document", "tools.view_file", "workspace.read_text"])
@pytest.mark.parametrize("path_key", ["path", "file_path", "file", "filename"])
def test_declared_file_family_with_path_shape_preserves_source_not_failure(name, path_key):
    assert shelltool.is_file_tool_name(name) and not shelltool.is_shell_tool_name(name)
    history = source_reads(name, arguments=lambda i: {path_key: f"source{i}.py"})
    out, report = focustrim.trim(history)
    assert out == history and not report.applied


@pytest.mark.parametrize("name", ["read_file", "cat_file", "view_file", "open_file"])
def test_hard_status_and_retained_reader_payload_are_independent(name):
    payload = 'expected = "Process exited with code 1; not found"\n'
    assert focustrim._is_failure("Process exited with code 1", name)
    history = source_reads(name)
    for m in history:
        if m.get("role") == "tool":
            m["content"] += payload
    out, report = focustrim.trim(history)
    assert out == history and not report.applied


@pytest.mark.parametrize("name", ["exec_command", "run_shell_command", "terminal.execute", "files.read_shell_command"])
def test_shell_family_does_not_gain_file_provenance_from_a_path_or_reader_name(name):
    assert shelltool.is_shell_tool_name(name)
    history = []
    for i in range(focustrim._SPAM_KEEP + 4):
        history += action(i, name, f"cat: missing{i}: No such file or directory",
                          arguments={"cmd": f"cat missing{i}", "path": f"missing{i}"})
    out, report = focustrim.trim(history)
    assert report.dropped_calls == 4 and report.squashed_runs == 1
    assert len([m for m in out if m.get("role") == "tool"]) == focustrim._SPAM_KEEP


@pytest.mark.parametrize("name", ["exec_command", "run_shell_command", "terminal.execute"])
def test_explicit_shell_success_and_hard_failure_keep_their_actual_contract(name):
    for status in (0, 1):
        history = []
        for i in range(focustrim._SPAM_KEEP + 4):
            history += action(i, name, f"source {i}: not found\nProcess exited with code {status}",
                              arguments={"cmd": f"cat source{i}.py"})
        out, report = focustrim.trim(history)
        assert out == history and not report.applied


@pytest.mark.parametrize("name,args", [("web_search", {"query": "missing"}),
                                       ("read_mcp_resource", {"path": "resource"})])
def test_other_lookup_domains_still_squash_their_genuine_soft_failures(name, args):
    history = []
    for i in range(focustrim._SPAM_KEEP + 4):
        history += action(i, name, f"lookup {i}: not found", arguments={**args, "request": i})
    _, report = focustrim.trim(history)
    assert report.dropped_calls == 4 and report.squashed_runs == 1


@pytest.mark.parametrize("name", ["create_file", "write_file", "edit_file", "apply_patch", "text_editor", "str_replace_editor"])
@pytest.mark.parametrize("failure", ["soft", "hard"])
def test_failed_mutations_never_remove_original_successful_file_pair(name, failure):
    original = action("original", "write_file", "Wrote a.py",
                      arguments={"path": "a.py", "content": "original source\n" * 100})
    history = copy.deepcopy(original)
    for i, path in enumerate(("a.py", "b.py", "c.py", "d.py", "e.py", "f.py")):
        result = (f"Error creating {path}: required file-write helper not found" if failure == "soft"
                  else f"write {path} failed\nProcess exited with code 1")
        history += action(i, name, result,
                          arguments={"path": path, "content": f"replacement {i}\n" * 100})
    before = copy.deepcopy(history)
    out, report = focustrim.trim(history)
    assert out[:2] == original and history == before
    assert not any(focustrim.bodykeys.SUPERSEDED_WRITES in m for m in out)
    assert report.dropped_calls == (4 if failure == "soft" else 0)
    assert report.dropped_msgs == (8 if failure == "soft" else 0)
    assert report.squashed_runs == (1 if failure == "soft" else 0)
    assert [tc["id"] for m in out for tc in m.get("tool_calls", [])] == (
        ["original", "4", "5"] if failure == "soft" else ["original", *map(str, range(6))])
    # Supersession alone must also reject failed replacements: correctness must
    # not depend on the failure-squash stage removing the dangerous call first.
    solo = focustrim.focus(focustrim.FocusInput(history), (focustrim.SUPERSESSION,))
    assert solo.messages == before and not solo.report.applied


@pytest.mark.parametrize("name", ["create_file", "write_file", "text_editor"])
def test_real_later_success_still_supersedes_and_ack_path_words_are_not_errors(name):
    old = action("old", "write_file", "Wrote a.py",
                 arguments={"path": "a.py", "content": "old source\n" * 100})
    new = action("new", name, "Wrote a.py",
                 arguments={"path": "a.py", "content": "new source\n" * 100})
    out, report = focustrim.trim(old + new)
    assert out[:2] == new and report.squashed_runs == 1
    assert focustrim.focus(focustrim.FocusInput(old + new)).superseded_calls == 1
    assert any(focustrim.bodykeys.SUPERSEDED_WRITES in m for m in out)
    assert not focustrim._is_failure("Wrote not found.py", name,
                                    arguments={"path": "not found.py"})


@pytest.mark.parametrize("name", ["files.create_document", "workspace.edit_text", "files.read_for_edit"])
def test_mixed_or_mutating_file_family_is_not_read_data(name):
    assert shelltool.is_write_tool_name(name)
    history = []
    for i in range(focustrim._SPAM_KEEP + 4):
        history += action(i, name, f"mutation {i}: helper not found")
    _, report = focustrim.trim(history)
    assert report.dropped_calls == 4 and report.squashed_runs == 1


@pytest.mark.parametrize("mode,prior", [("no_anchor", 2), ("anchor", 0)])
@pytest.mark.parametrize("prefix", ["", "Warning: truncated output (original token count: 12345)\n",
                                    "Chunk ID: abc\nWall time: 0.01 seconds\nProcess exited with code 0\nOutput:\n"])
def test_real_edit_recovery_bytes_are_retained_but_never_credit_a_landed_edit(mode, prior, prefix):
    history = []
    for i in range(6):
        current = f'# distinct source {i}\nmessage = "not found"\n'
        result = editrecovery.compose({"path": f"source{i}.py", "mode": mode,
                                       "current": current, "anchor": current}, prior)
        assert editrecovery.EDIT_MARK in result and current in result
        history += action(i, "edit_file", prefix + result, arguments={"path": f"source{i}.py",
                          "old_string": f"missing anchor {i}", "new_string": f"changed {i}"})
    before = copy.deepcopy(history)
    out, report = focustrim.trim(history)
    assert out == before and history == before and not report.applied
    assert focustrim._failed_write_ids(history) == set(map(str, range(6)))
    solo = focustrim.focus(focustrim.FocusInput(history), (focustrim.SUPERSESSION,))
    assert solo.messages == before and not solo.report.applied


@pytest.mark.parametrize("prefix", ["", "helper not found\n"])
def test_structured_edit_failure_provenance_preserves_report_and_excludes_mutation(prefix):
    history = []
    for i in range(6):
        fact = {"path": f"source{i}.py", "mode": "no_anchor",
                "current": f'# source {i}\nmessage = "not found"\n'}
        token = base64.b64encode(json.dumps(fact).encode()).decode()
        assert editrecovery.decode_report(token) == fact
        history += action(i, "edit_file", prefix + editrecovery.EDITFAIL + token,
                          arguments={"path": fact["path"], "old_string": f"missing {i}", "new_string": "new"})
    out, report = focustrim.trim(history)
    assert out == history and not report.applied
    assert focustrim._failed_write_ids(history) == set(map(str, range(6)))


def test_failed_whole_replacement_with_recovery_data_keeps_original_and_report():
    original = action("original", "write_file", "Wrote a.py",
                      arguments={"path": "a.py", "content": "original source\n" * 100})
    report = editrecovery.compose({"path": "a.py", "mode": "no_anchor",
                                   "current": 'message = "not found"\n'}, 2)
    failed = action("failed", "create_file", report,
                    arguments={"path": "a.py", "content": "unlanded source\n" * 100})
    out, result = focustrim.trim(original + failed)
    assert out == original + failed and not result.applied
    assert focustrim._failed_write_ids(original + failed) == {"failed"}


def test_real_root_focus_selection_off_replacement_and_stage_order_are_preserved():
    root = AssistRuntime.select(level=3, registrations=focustrim.FOCUS_STAGE)
    history = source_reads("cat_file")
    with bound(root):
        result = focustrim.focus(focustrim.FocusInput(history), root.bindings("coder-focus"))
    assert result.messages == history and not result.report.applied
    class Unreadable(list):
        def __iter__(self):
            raise AssertionError("off focus inspected history")
    off = AssistRuntime.select(level=3, registrations=focustrim.FOCUS_STAGE,
                              disabled=tuple(d.policy.id for d in focustrim.FOCUS_STAGE))
    unread = Unreadable(history)
    with bound(off):
        assert focustrim.focus(focustrim.FocusInput(unread), off.bindings("coder-focus")).messages is unread
    seen = []
    def stage(definition):
        def execute(messages):
            seen.append(definition.policy.id)
            return messages, focustrim.TrimReport()
        return replace(definition, execute=execute)
    replacements = tuple(stage(d) for d in focustrim.FOCUS_STAGE)
    selected = replace(root, ordered_stages=replacements)
    with bound(selected):
        assert focustrim.focus(focustrim.FocusInput(history), selected.bindings("coder-focus")).messages is history
    assert seen == [d.policy.id for d in focustrim.FOCUS_STAGE]
