"""One correlated declaration serves both records; neither pairing nor position is relaxed."""
import copy
from unittest.mock import patch

import pytest

from cria import denial, resultpacket, toolwire, writeproxy

SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
BODY = b"original file\r\nwithout a final newline"
SURVEY = b"survey bytes\n"


def _exchange(declared=True):
    arguments = '{"path":"notes.txt"}'
    token = denial.receipt_for("read", "read_file", arguments)
    command = toolwire._sentinel("read_file", arguments, token, declared) + "\nprintf unused"
    call = toolwire._shell_call("read", SHELL, command)
    messages = [{"role": "assistant", "tool_calls": [call]},
                {"role": "tool", "tool_call_id": "read", "content": ""}]
    return messages, token, command


@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_both_records_share_one_real_receipt_validation_without_changing_payload(declared, eol):
    messages, token, command = _exchange(declared)
    first = resultpacket.line(token, denial.RAN, body=BODY, observe=resultpacket.WHOLE).replace("\n", eol)
    second = resultpacket.line(token, resultpacket.SURVEY, body=SURVEY).replace("\n", eol)
    tail = "opaque command output\n"
    messages[1]["content"] = first + second + tail
    original = copy.deepcopy(messages)
    # Wrap the real correlation owner: zero calls would bypass validation; two repeat the same proof.
    with patch.object(denial, "receipt_for", wraps=denial.receipt_for) as validate:
        proof = writeproxy._frame_proofs(messages)["read"]
    validate.assert_called_once_with("read", "read_file", '{"path":"notes.txt"}')
    assert proof.kind == denial.RAN and proof.text == BODY.decode() and not proof.exact
    assert proof.observe == resultpacket.WHOLE
    assert proof.survey == (SURVEY.decode() if declared else "")
    assert proof.content == BODY.decode() + ("" if declared else second) + tail
    assert messages == original
    assert toolwire.receipt_of(command, "read") == token


@pytest.mark.parametrize("second_kind", ["missing", "cut", "foreign", "not-adjacent"])
def test_a_valid_first_record_survives_without_searching_for_a_survey(second_kind):
    messages, token, _command = _exchange()
    first = resultpacket.line(token, denial.RAN, body=BODY, observe=resultpacket.WHOLE)
    second = resultpacket.line(token, resultpacket.SURVEY, body=SURVEY)
    tail = {"missing": "", "cut": second[:30],
            "foreign": resultpacket.line("foreign", resultpacket.SURVEY, body=SURVEY),
            "not-adjacent": "ordinary output\n" + second}[second_kind]
    messages[1]["content"] = first + tail
    proof = writeproxy._frame_proofs(messages)["read"]
    assert proof.kind == denial.RAN and proof.survey == ""
    assert proof.content == BODY.decode() + tail and proof.exact == (tail == "")


@pytest.mark.parametrize("invalid", ["foreign-declaration", "no-receipt", "nonleading-declaration",
                                    "nonleading-record", "duplicate-call", "duplicate-result", "out-of-order", "orphan"])
def test_reusing_a_declaration_does_not_relax_correlation_pairing_or_record_position(invalid):
    messages, token, command = _exchange()
    messages[1]["content"] = resultpacket.line(token, denial.RAN, body=BODY, observe=resultpacket.WHOLE)
    if invalid == "foreign-declaration":
        command = toolwire._sentinel("read_file", '{"path":"different.txt"}', token, True) + "\nprintf unused"
    elif invalid == "no-receipt":
        command = toolwire._sentinel("read_file", '{"path":"notes.txt"}') + "\nprintf unused"
    elif invalid == "nonleading-declaration":
        command = "ordinary command\n" + command
    elif invalid == "nonleading-record":
        messages[1]["content"] = "ordinary output\n" + messages[1]["content"]
    elif invalid == "duplicate-call":
        messages[0]["tool_calls"] *= 2
    elif invalid == "duplicate-result":
        messages.append(copy.deepcopy(messages[1]))
    elif invalid == "out-of-order":
        messages.reverse()
    elif invalid == "orphan":
        messages = messages[1:]
    if invalid in ("foreign-declaration", "no-receipt", "nonleading-declaration"):
        messages[0]["tool_calls"] = [toolwire._shell_call("read", SHELL, command)]
    original = copy.deepcopy(messages)
    assert writeproxy._frame_proofs(messages) == {}
    assert messages == original
