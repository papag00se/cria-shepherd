"""Which file a call writes, decided from the call: the progress and truncation-steer owners read these."""
import json

import pytest

from cria import probegate, writeproxy
from cria.loop import _is_write_tool, _shell_write_target, _truncated_write_path, _write_path

PATCH = "*** Begin Patch\n*** Update File: handler.py\n-a\n+b\n*** End Patch"
CUT_PATCH = '{"input": "*** Begin Patch\\n*** Update File: handler.py\\n-a\\n+b'
EXAMPLE_IN_CONTENT = '{"content": "How to patch:\\n*** Update File: src/parser.py\\n+fixed line\\nthen run te'


def fn(name, args):
    return {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}


def sh(cmd):
    return fn("shell", {"command": ["bash", "-lc", cmd]})


@pytest.mark.parametrize("call,path", [
    (fn("write_file", {"path": "config.json", "content": "{}"}), "config.json"),     # not rstrip-mangled to config.jso
    (fn("write_file", {"file_path": "a.py", "content": "x"}), "a.py"),     # alias key
    (fn("apply_patch", {"input": PATCH}), "handler.py"),
    (fn("apply_patch", CUT_PATCH), "handler.py"),                    # escaped \n in a cut blob ends the path
    (fn("write_file", EXAMPLE_IN_CONTENT), None),                    # a patch header typed INTO content is no target
    (sh("echo x > handler.py"), "handler.py"),
    (sh("pytest -q | tee out.log"), "out.log"),
    (sh("cat handler.py"), None),
    (sh("pytest -q 2>/dev/null"), None),
])
def test_a_calls_write_target_is_read_from_the_call_and_reads_and_quoted_arrows_are_not_writes(call, path):
    """Progress tracking and the incremental-write steer name a file only when the call really writes it."""
    assert _write_path(call) == path


@pytest.mark.parametrize("args,is_write", [
    (json.dumps({"command": ["bash", "-lc", "echo done > out.txt"], "justification": "don't skip"}), True),
    (json.dumps({"command": ["bash", "-lc", "cat a.py"], "justification": "we can't miss Bob's edge > case"}), False),
    ('{"command": ["bash", "-lc", "echo x > f.py"]', True),          # cut-off JSON still escape-encoded
    ('{"command": ["bash", "-lc", "pytest -q > /dev/null 2>&1"]', False),
    ("grep 'count > 1' src/module.py", False),                       # bare shell text, quotes are real
    (json.dumps({"shell_command": "echo done > result.txt"}), True), # another harness's field name
    (json.dumps({"script": "sort", "input": "line a\nc > d"}), False),   # stdin data is not the program
    (json.dumps({"script": "generate.sh > reports/out.txt", "input": "dataset-a"}), True),
])
def test_a_shell_write_is_judged_on_the_command_text_only_whatever_shape_the_arguments_arrive_in(args, is_write):
    """Round 3-5 reviews: an apostrophe in a prose field unbalanced the quote mask, a truncated blob masked its whole
    command away, and stdin data containing '>' read as a phantom write. Only COMMAND fields are scanned."""
    assert (_shell_write_target(args) is not None) is is_write


def test_a_truncated_write_names_its_file_through_any_alias_and_write_stdin_is_not_a_write_tool():
    """A cut-off write with a `file_path` alias still gets the incremental-write steer; write_stdin was mis-classed."""
    cut = {"choices": [{"message": {"tool_calls": [{"function": {
        "name": "write_file", "arguments": '{"file_path": "big.py", "content": "xxx'}}]}}]}
    assert _truncated_write_path(cut) == "big.py"
    example = {"choices": [{"message": {"tool_calls": [{"function": {"name": "write_file", "arguments": EXAMPLE_IN_CONTENT}}]}}]}
    assert _truncated_write_path(example) is None
    assert (_is_write_tool("write_stdin"), _is_write_tool("write_file"), _is_write_tool("edit_file")) == (False, True, True)


@pytest.mark.parametrize("name,args,path", [("write_file", {"path": "a.py", "content": "x = 1\n"}, "a.py"),
                                            ("edit_file", {"path": "b.py", "old_string": "x", "new_string": "y"}, "b.py"),
                                            ("list_dir", {"path": "."}, None)])
def test_a_call_cria_lowered_to_a_shell_program_is_judged_by_what_the_coder_asked_for_and_not_by_crias_own_text(name, args, path):
    """feed-pipeline-java x nemotron-elastic 1787346816: the survey program riding on a lowered write contains
    `if len(files) > FOLD_AT:`; the redirect matcher read that `>` as a write and told the coder `FILE FOLD_AT — does NOT
    exist`. The sentinel holds the call actually made, so the path comes from it; cria's own gate script writes nothing."""
    comp = {"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {
        "name": name, "arguments": json.dumps(args)}}]}}]}
    shell = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
    writeproxy.translate_outbound(comp, shell, injected={name}, workspace_root="/w")
    assert _write_path(comp["choices"][0]["message"]["tool_calls"][0]["function"]) == path
    assert _write_path(sh(probegate._gate_sentinel(["pytest -q"]) + "\nif len(files) > FOLD_AT:\n  echo hi > out.txt")) is None
