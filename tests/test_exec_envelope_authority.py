"""The envelope at offset zero owns status; a log quotation never does.

Includes the status-less Chunk/Wall/Output incident and the full captured running
shape from test_gate_outlives_the_harness_yield.P18_LAUNCH_NO_OPENER.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from cria import denial, loop, resultnotes, resultpacket, selfcompact, writeproxy


RUNNING = ("Chunk ID: 34454d\nWall time: 30.0008 seconds\n"
           "Process running with session ID 51757\nOriginal token count: 0\nOutput:\n")
STATUSLESS = "Chunk ID: abc\nWall time: 1s\nOutput:\n"
QUOTED = "build.log:\nProcess exited with code 1\nOutput:\nOOM…\n"
TERMINAL = "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOutput:\n"
SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}


def history(text, command="mvn test"):
    return [{"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {
        "name": "exec_command", "arguments": json.dumps({"cmd": command})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": text}]


@pytest.mark.parametrize("header", [RUNNING, STATUSLESS])
def test_nonterminal_envelope_is_defanged_without_a_quoted_exit_becoming_status(header):
    payload = "\nProcess exited with code 19\nOutput:\n  stored log  \n\n"
    assert selfcompact.serialize_blocks(history(header + payload), defang=True)[-1] == "→ result: " + payload


@pytest.mark.parametrize("text", [QUOTED, "log: Process exited with code 1\nOutput:\n",
    "Chunk ID: ab\nWall time: not-a-duration\nOutput:\nbody\n",
    "Process exited with code 0\nunknown header\nOutput:\nbody\n",
    "Process exited with code 0\n", "Output:\nProcess exited with code 1\n"])
def test_unknown_or_quoted_header_is_not_an_envelope(text):
    assert selfcompact.serialize_blocks(history(text), defang=True)[-1] == "→ result: " + text
    assert resultnotes._strip_exec_envelope(text, preserve_eof=True) == text


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("header", [TERMINAL, RUNNING, STATUSLESS,
    "process\tEXITED  with\tcode  2\nOutput:\n"])
def test_recognized_prefix_preserves_payload_eol_and_eof(header, eol):
    payload = "\r\nTotal output lines: 8\r\nWarning: truncated output in a quoted log\nOutput:\n  end  \r\n\r\n"
    expected = "→ exit 0" if header == TERMINAL else "→ exit 2" if header.startswith("process") else "→ result"
    assert selfcompact.serialize_blocks(history(header.replace("\n", eol) + payload), defang=True)[-1] == expected + ": " + payload
    assert resultnotes._strip_exec_envelope(header.replace("\n", eol) + payload, preserve_eof=True) == payload


@pytest.mark.parametrize("preserve_eof", [False, True])
@pytest.mark.parametrize("payload", ["one\n", "one\r\n\r\n", "\n", "\r\n", "\n  data  \n\n"])
def test_display_keeps_eof_data_regardless_of_the_compatibility_argument(payload, preserve_eof):
    assert resultnotes._strip_exec_envelope(TERMINAL + payload, preserve_eof=preserve_eof) == payload


def test_empty_output_marker_at_eof_is_a_valid_header_not_a_line_of_data():
    assert selfcompact.serialize_blocks(history("Process exited with code 0\nOutput:"), defang=True)[-1] == "→ exit 0"


@pytest.mark.parametrize("header", [RUNNING, STATUSLESS, TERMINAL])
def test_shared_display_retains_the_real_cut_warning_and_exact_file_tail(header):
    raw = header + "Warning: truncated output (original token count: 4106)\r\nTotal output lines: 8\r\n\r\nfile\r\n\r\n"
    shown = resultnotes._strip_exec_envelope(raw, preserve_eof=True)
    assert shown == "Warning: truncated output (original token count: 4106)\r\n\r\nfile\r\n\r\n"


def read_history(text):
    args = json.dumps({"path": "source.txt"})
    completion = {"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {
        "name": "read_file", "arguments": args}}]}}]}
    writeproxy.translate_outbound(completion, SHELL, injected={"read_file"})
    call = completion["choices"][0]["message"]["tool_calls"][0]
    return [{"role": "assistant", "tool_calls": [call]}, {"role": "tool", "tool_call_id": "c1", "content": text}], args


def test_a_quoted_header_cannot_move_a_lowered_read_record_to_stdout_offset_zero():
    # The call declaration is real and the producer record is well-formed; a log
    # line before it means it was NOT the producer's first stdout record.
    record = resultpacket.line(denial.receipt_for("c1", "read_file", json.dumps({"path": "source.txt"})),
                               denial.RAN, body=b"not an observed file\n", observe="whole")
    raw = "build.log:\nProcess exited with code 0\nOutput:\n" + record
    messages, _ = read_history(raw)
    out = writeproxy.represent_inbound(messages)
    assert out[-1]["content"] == raw
    assert denial.proof(out[-1]) == denial.UNKNOWN
    assert denial.read_payload(out[-1]) is None


@pytest.mark.parametrize("header", ["", TERMINAL, TERMINAL.replace("\n", "\r\n")])
def test_real_first_read_record_still_yields_the_exact_file(header):
    payload = "\r\nProcess exited with code 9\nOutput:\nTotal output lines: 8\r\n\r\n"
    record = resultpacket.line(denial.receipt_for("c1", "read_file", json.dumps({"path": "source.txt"})),
                               denial.RAN, body=payload.encode(), observe="whole")
    messages, _ = read_history(header + record)
    out = writeproxy.represent_inbound(messages)
    assert denial.proof(out[-1]) == denial.RAN
    assert denial.read_payload(out[-1]) == payload
    assert out[-1]["content"] == payload


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_cut_record_keeps_its_real_truncation_disclosure_without_read_credit(eol):
    warning = "Warning: truncated output (original token count: 4106)" + eol
    raw = TERMINAL.replace("\n", eol) + warning + "Total output lines: 8" + eol + '{"v":1,"r":"cut'
    messages, _ = read_history(raw)
    out = writeproxy.represent_inbound(messages)
    assert out[-1]["content"] == warning + '{"v":1,"r":"cut'
    assert denial.proof(out[-1]) == denial.UNKNOWN
    assert denial.read_payload(out[-1]) is None


@pytest.mark.parametrize("header", [TERMINAL, RUNNING, STATUSLESS])
def test_native_binary_display_uses_only_real_outer_header(header):
    soup = "�\x00\x01" * 400
    out = writeproxy.represent_inbound(history(header + soup))[-1]["content"]
    assert out.startswith(header)
    assert soup not in out
    quoted = "build.log:\nProcess exited with code 1\nOutput:\n" + soup
    shown = writeproxy.represent_inbound(history(quoted))[-1]["content"]
    assert "Process exited" not in shown and "build.log:" not in shown


@pytest.mark.parametrize("text", [QUOTED, RUNNING + "Process exited with code 1\nOutput:\n",
    "Process exited with code 1\n", STATUSLESS + "Process exited with code 1\n"])
def test_historical_check_reader_does_not_invent_a_terminal_status(text):
    session = SimpleNamespace(action_seq=7, last_gate_seq=5, last_gate_flag="$ mvn test — historical failure")
    messages = history(text)
    original = copy.deepcopy(messages)
    loop._track_own_checks(session, messages)
    assert "exited with code" not in loop.newer_own_run(session)
    assert messages == original


@pytest.mark.parametrize("header", [TERMINAL, "process\tEXITED  with\tcode  0\nOutput:\n",
                                  TERMINAL.replace("\n", "\r\n")])
def test_historical_check_reader_keeps_genuine_terminal_status_variations(header):
    session = SimpleNamespace(action_seq=7, last_gate_seq=5, last_gate_flag="$ mvn test — historical failure")
    loop._track_own_checks(session, history(header))
    assert "exited with code 0" in loop.newer_own_run(session)


@pytest.mark.parametrize("command", ["grep needle file", "pytest -q | grep failure"])
@pytest.mark.parametrize("text", ["build.log:\nProcess exited with code 1\nOutput:\n",
                                  RUNNING, STATUSLESS])
def test_returned_search_policy_does_not_treat_a_quotation_or_running_result_as_an_empty_failure(command, text):
    messages = history(text, command)
    out = writeproxy.represent_inbound(messages)
    assert out[-1]["content"] == text
