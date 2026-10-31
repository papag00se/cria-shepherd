"""F13: missing/null fields cannot become destructive empty replacements.

Observe the actual lowered shell command, refusal, and final disk bytes. No
validator-shape/source-text assertions: these tests also work before extraction.
"""
import json
import subprocess

import pytest

from cria import denial
from cria.writeproxy import translate_outbound

SHELL = {"name":"exec_command", "schema":{"properties":{"cmd":{"type":"string"}}}}


def execute(tool, arguments, directory):
    comp = {"choices":[{"message":{"tool_calls":[{"id":"mutation", "type":"function", "function":{
        "name":tool, "arguments":json.dumps(arguments)}}]}}]}
    translate_outbound(comp, SHELL, injected={tool}, workspace_root=str(directory))
    call = comp["choices"][0]["message"]["tool_calls"][0]
    command = json.loads(call["function"]["arguments"])["cmd"]
    return subprocess.run(["bash","-c",command], cwd=directory, capture_output=True, text=True)


@pytest.mark.parametrize("tool", ["edit_file", "str_replace"])
@pytest.mark.parametrize("replacement", [None, "MISSING"])
def test_unusable_replacement_is_refused_not_deleted(tool, replacement, tmp_path):
    path = tmp_path / "data.txt"
    path.write_bytes(b"keep this text\n")
    arguments = {"path":str(path), "old_string":"this"}
    if replacement != "MISSING":
        arguments["new_string"] = replacement
    result = execute(tool, arguments, tmp_path)
    assert result.returncode != 0
    assert denial.is_denied(result.stdout + result.stderr)
    assert "new_string" in result.stdout + result.stderr
    assert path.read_bytes() == b"keep this text\n"


@pytest.mark.parametrize("tool", ["edit_file", "str_replace"])
def test_explicit_empty_replacement_still_deletes_exact_match(tool, tmp_path):
    path = tmp_path / "data.txt"
    path.write_bytes(b"keep this text\n")
    result = execute(tool, {"path":str(path), "old_string":"this ", "new_string":""}, tmp_path)
    assert result.returncode == 0 and path.read_bytes() == b"keep text\n"


@pytest.mark.parametrize("tool", ["edit_file", "str_replace"])
@pytest.mark.parametrize("replacement", [0, False])
def test_real_falsy_replacement_is_preserved_as_text_not_deletion(tool, replacement, tmp_path):
    path = tmp_path / "data.txt"
    path.write_bytes(b"value=original\n")
    result = execute(tool, {"path":str(path), "old_string":"original", "new_string":replacement}, tmp_path)
    assert result.returncode == 0 and path.read_text() == f"value={replacement}\n"


@pytest.mark.parametrize("tool", ["edit_file", "str_replace"])
@pytest.mark.parametrize("old", [0, False])
def test_real_falsy_anchor_names_its_text_not_an_empty_boundary(tool, old, tmp_path):
    path = tmp_path / "data.txt"
    path.write_text(f"value={old}\n")
    result = execute(tool, {"path":str(path), "old_string":old, "new_string":"changed"}, tmp_path)
    assert result.returncode == 0 and path.read_text() == "value=changed\n"


@pytest.mark.parametrize("tool", ["write_file", "create_file"])
@pytest.mark.parametrize("content", [None, "MISSING"])
def test_unusable_content_is_refused_not_empty_write(tool, content, tmp_path):
    path = tmp_path / "data.txt"
    path.write_bytes(b"keep all bytes\n")
    arguments = {"path":str(path)}
    if content != "MISSING":
        arguments["content"] = content
    result = execute(tool, arguments, tmp_path)
    assert result.returncode != 0 and denial.is_denied(result.stdout + result.stderr)
    assert path.read_bytes() == b"keep all bytes\n"


@pytest.mark.parametrize("tool", ["write_file", "create_file"])
@pytest.mark.parametrize("content", ["", 0, False])
def test_real_content_including_intentional_empty_is_preserved(tool, content, tmp_path):
    path = tmp_path / "data.txt"
    result = execute(tool, {"path":str(path), "content":content}, tmp_path)
    assert result.returncode == 0 and path.read_text() == str(content)


@pytest.mark.parametrize("tool", ["write_file", "create_file"])
def test_legacy_contents_alias_is_used_only_when_content_is_null(tool, tmp_path):
    path = tmp_path / "data.txt"
    result = execute(tool, {"path":str(path), "content":None, "contents":"alias bytes"}, tmp_path)
    assert result.returncode == 0 and path.read_text() == "alias bytes"
    result = execute(tool, {"path":str(path), "content":"", "contents":"not selected"}, tmp_path)
    assert result.returncode == 0 and path.read_bytes() == b""
