"""Synthetic wire fixtures: native and recovered actions share terminal lowering."""
import json

import pytest

from cria import massage, writeproxy
from cria.shelltool import find_shell_tool


TOOLS = [{"type": "function", "function": {"name": "exec_command", "parameters": {
    "type": "object", "properties": {"cmd": {"type": "string"}}}}}]
WRITE = {"type": "function", "function": {"name": "write_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    "required": ["path", "content"]}}}


def run_stream(*, finish="tool_calls", native=False, textual=False, incomplete=False):
    literal = 'quotes " and unicode λ\nlast line without newline\\literal'
    args = json.dumps({"path": "a.txt", "content": literal}, ensure_ascii=False)
    chunks = [massage._sse({"role": "assistant"}, "fake"),
              massage._sse({"content": "prose stays live. " * 12}, "fake")]
    if textual:
        chunks.append(massage._sse({"content": '<tool_call>' + json.dumps({
            "name": "write_file", "arguments": json.loads(args)}) + '</tool_call>'}, "fake"))
    else:
        for index in range(2):
            chunks.append(massage._sse({"tool_calls": [{"index": index, "id": f"c{index}",
                "type": "function", "function": {"name": "write_file", "arguments": args[:17]}}]}, "fake"))
        for index in range(2):
            chunks.append(massage._sse({"tool_calls": [{"index": index,
                "function": {"arguments": args[17:]}}]}, "fake"))
    if finish == "error":
        chunks.append(b'data: {"error":{"message":"broken"}}\n\n')
    elif finish is not None:
        terminal = massage._sse({}, "fake", finish=finish)
        if incomplete:
            obj = json.loads(terminal[5:])
            obj['generation_evidence'] = {'incomplete': True}
            terminal = b'data: ' + json.dumps(obj).encode() + b'\n\n'
        chunks.append(terminal)
    chunks.append(b'data: [DONE]\n\n')
    posted = []
    def lower(completion):
        posted.append(completion)
        return writeproxy.translate_outbound(completion, find_shell_tool(TOOLS),
            injected=set() if native else {"write_file"})
    output = list(massage.massage_stream(iter(chunks), "fake", TOOLS + [WRITE], post=lower))
    calls = [tc for raw in output if (choice := massage._choice(raw))
             for tc in (choice.get("delta") or {}).get("tool_calls", [])]
    prose = ''.join((choice.get("delta") or {}).get("content", '') for raw in output
                    if (choice := massage._choice(raw)))
    return literal, posted, calls, prose, output


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("finish", ['stop', 'tool_calls'])
def test_fragmented_batch_lowered_once_after_admission(native, finish):
    literal, posted, calls, prose, _ = run_stream(native=native, finish=finish)
    assert len(posted) == 1
    assert [call['id'] for call in calls] == ['c0', 'c1']
    assert prose == 'prose stays live. ' * 12
    for call in calls:
        fn = call['function']
        if native:
            assert fn['name'] == 'write_file'
            assert json.loads(fn['arguments'])['content'] == literal
        else:
            assert fn['name'] == 'exec_command'
            command = json.loads(fn['arguments'])['cmd']
            assert writeproxy._b64(literal) in command
            original = writeproxy.original_call(command)
            assert original['name'] == 'write_file'
            assert json.loads(original['arguments'])['content'] == literal


@pytest.mark.parametrize("finish", ['length', 'error', None])
def test_unadmitted_structured_calls_never_reach_lowering(finish):
    _, posted, calls, prose, output = run_stream(finish=finish)
    assert posted == []
    assert calls == []
    assert prose == 'prose stays live. ' * 12
    assert any(b'error' in raw or b'incomplete' in raw for raw in output)


def test_authoritative_incomplete_evidence_overrides_successful_finish():
    _, posted, calls, prose, output = run_stream(incomplete=True)
    assert posted == []
    assert calls == []
    assert prose == 'prose stays live. ' * 12
    assert any(b'withheld_action_deltas' in raw for raw in output)


def test_textual_recovery_still_lowers_once():
    _, posted, calls, prose, _ = run_stream(finish='stop', textual=True)
    assert len(posted) == 1
    assert len(calls) == 1
    assert calls[0]['function']['name'] == 'exec_command'
    assert prose == 'prose stays live. ' * 12
