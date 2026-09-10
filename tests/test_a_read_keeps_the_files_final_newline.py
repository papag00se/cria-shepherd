"""Whole reads may not replace surveyed sizes with newline-stripped file bodies.

Raw pre-representation Codex outputs in fixtures/raw_whole_reads_eof.json match
archived file bytes: Cargo.toml has no EOF newline, Importer.java has one, and
cart/item.2.go has three. This
pins the real harness convention rather than assuming envelope + payload.
Synthetic coverage adds two EOF newlines and guards unrelated tool behavior.
"""
import json
from pathlib import Path
import subprocess

import pytest

from cria import writeproxy, wsview


def assert_surveyed_roundtrip(tmp_path, path, payload, call, output):
    file = tmp_path / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(payload.encode())
    view = wsview.View(str(tmp_path))
    survey_run = subprocess.run(wsview.survey_command("fixture", cd=str(tmp_path)),
                                shell=True, capture_output=True, text=True, check=True)
    _, survey = wsview.strip_survey(survey_run.stdout)
    assert wsview.apply_survey(view, survey)
    assert view.surveyed
    assert view.size(str(file)) == file.stat().st_size
    history = [{"role": "assistant", "tool_calls": [call]},
               {"role": "tool", "tool_call_id": call["id"], "content": output}]
    token = wsview.bind(view)
    try:
        represented = writeproxy.represent_inbound(history)
        assert represented[-1]["content"] == payload
        assert view.read_bytes(str(file)) == payload.encode()
        assert view.size(str(file)) == file.stat().st_size
    finally:
        wsview.unbind(token)


@pytest.mark.parametrize("fixture", json.loads(
    (Path(__file__).parent / "fixtures/raw_whole_reads_eof.json").read_text()),
    ids=["raw-no-eof", "raw-one-eof", "raw-three-eof"])
def test_raw_ingress_preserves_surveyed_body_and_size(tmp_path, fixture):
    raw_call = fixture["call"]
    call = {"id": raw_call["call_id"], "type": "function", "function": {
        "name": raw_call["name"], "arguments": raw_call["arguments"]}}
    assert_surveyed_roundtrip(tmp_path, fixture["path"], fixture["expected"],
                             call, fixture["result"]["output"])


@pytest.mark.parametrize("payload", ["package pipeline;", "package pipeline;\n", "package pipeline;\n\n",
                                      "", "\n", "\n\n", "\npackage pipeline;\n"] )
def test_file_bytes_survive_the_read_envelope(tmp_path, payload):
    comp = {"choices": [{"message": {"tool_calls": [{"id": "r1", "type": "function",
        "function": {"name": "read_file", "arguments": json.dumps({"path": "source.txt"})}}]}}]}
    shell = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
    writeproxy.translate_outbound(comp, shell, injected={"read_file"})
    envelope = "Chunk ID: capture\nProcess exited with code 0\nOutput:\n" + payload
    assert_surveyed_roundtrip(tmp_path, "source.txt", payload,
                             comp["choices"][0]["message"]["tool_calls"][0], envelope)


def test_generic_envelope_cleanup_is_unchanged():
    assert writeproxy._strip_exec_envelope(
        "Chunk ID: c\nProcess exited with code 0\nOutput:\nlisting\n") == "listing"


@pytest.mark.parametrize("result", [
    "Process exited with code 1\nOutput:\ncat: read failed\n",
    "Process exited with code 0\nOutput:\nWarning: truncated output (original token count: 10000)\npartial\n",
    "Process exited with code 1\nOutput:\n⟦ctx:denied⟧ Nothing was read.\n",
])
def test_unsuccessful_whole_read_cannot_replace_known_file_bytes(result):
    fixture = json.loads((Path(__file__).parent / "fixtures/raw_whole_reads_eof.json").read_text())[0]
    call = fixture["call"]
    view = wsview.View("/project")
    view.note_written("Cargo.toml", "known body\n")
    token = wsview.bind(view)
    try:
        writeproxy.represent_inbound([
            {"role": "assistant", "tool_calls": [{"id": call["call_id"], "type": "function",
                "function": {"name": call["name"], "arguments": call["arguments"]}}]},
            {"role": "tool", "tool_call_id": call["call_id"], "content": result}])
        assert view.read_bytes("/project/Cargo.toml") == b"known body\n"
        assert view.size("/project/Cargo.toml") == len(b"known body\n")
    finally:
        wsview.unbind(token)
