"""Scenario: the model server refuses a coder reply (native protocol error), or the reply is a cut-off call. Real Loop.drive
over the plan-off path with a fake coder: the first refusals are answered with one bounded re-drive that tells the coder no
action ran; the bound ends in the error, not a silent hand-back; a cut call is never forwarded and the turn reports incomplete."""
import json
import pytest

from cria import generation
from cria.classify import Classification
from cria.loop import LoopStore
from cria.upstream import UpstreamProtocolError

from loop_main_helpers import drive_with_ops, Rlog, acting, body, completion, plan_off_loop, loop_main_local_view  # noqa: F401

CODING = Classification("task", "coding", "fixture")
REFUSED = {"type": generation.PROTOCOL_ERROR, "message": "invalid literal tool output"}


class Coder:
    def __init__(self, *script):
        self.script, self.bodies = list(script), []

    def __call__(self, b, rlog):
        self.bodies.append(b)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, BaseException):
            raise step
        return json.dumps(step).encode()


def refusal():
    return UpstreamProtocolError("invalid literal tool output", REFUSED)


def test_a_protocol_refused_reply_is_redriven_with_a_notice_then_bounded():
    coder, rlog = Coder(refusal(), acting()), Rlog()
    loop = plan_off_loop(coder, store=LoopStore())
    out = loop.drive(body(), "sid:r", CODING, rlog)
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "shell"
    assert len(coder.bodies) == 2 and "native protocol error" in json.dumps(coder.bodies[1]["messages"])
    assert "native protocol error" not in json.dumps(coder.bodies[0]["messages"])
    assert out[generation.EVIDENCE]["prior_protocol_errors"] == [REFUSED]
    refused = [f for k, f in rlog.events if k == "loop.protocol_refused"]
    assert [f["attempt"] for f in refused] == [1]
    stubborn, rlog = Coder(refusal()), Rlog()                      # never recovers: attempts 1 and 2, then the error stands
    with pytest.raises(UpstreamProtocolError):
        plan_off_loop(stubborn, store=LoopStore()).drive(body(), "sid:s", CODING, rlog)
    assert len(stubborn.bodies) == 3 and "loop.protocol_refusal_bound" in rlog.kinds()


def test_protocol_retry_keeps_user_and_real_tool_results_and_never_cria_s_own_calls(tmp_path):
    coder = Coder(refusal(), acting())
    driver = plan_off_loop(coder, store=LoopStore(), workspace_root=str(tmp_path), assists=True)
    request = body('Original task')
    history = list(request['messages'])
    for _ in range(3):
        response, history = drive_with_ops(driver, request, history, 'sid:private', CODING, Rlog(), cwd=tmp_path,
                                           harness=lambda call: 'private process failure')
        message = response['choices'][0]['message']
        call = message['tool_calls'][0]
        history += [message, {'role': 'tool', 'tool_call_id': call['id'], 'content': 'a real result'}]
        break
    real = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'real', 'type': 'function',
            'function': {'name': 'shell', 'arguments': json.dumps({'command': ['sh', '-c', 'true']})}}]}
    history += [real, {'role': 'tool', 'tool_call_id': 'real', 'content': 'actual tool voice'},
                {'role': 'user', 'content': 'Additional user instruction'}]
    drive_with_ops(driver, request, history, 'sid:private', CODING, Rlog(), cwd=tmp_path)
    assert len(coder.bodies) >= 2
    for sent in coder.bodies:
        text = json.dumps(sent['messages'])
        assert 'private process failure' not in text and 'ctx_' not in text
        assert 'Original task' in text


def test_a_real_call_that_reuses_the_id_of_one_cria_made_is_not_mistaken_for_it(tmp_path):
    coder = Coder(acting(), refusal(), acting())
    driver = plan_off_loop(coder, store=LoopStore(), workspace_root=str(tmp_path), assists=True)
    request = body('Original task')
    response, history = drive_with_ops(driver, request, request['messages'], 'sid:reuse', CODING, Rlog(), cwd=tmp_path)
    private = next(c['id'] for m in history if m.get('role') == 'assistant' for c in m.get('tool_calls') or ())
    assert private.startswith('ctx_')
    forged = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': private, 'type': 'function',
              'function': {'name': 'shell', 'arguments': json.dumps({'command': ['sh', '-c', 'echo real']})}}]}
    reused = request['messages'] + [forged, {'role': 'tool', 'tool_call_id': private, 'content': 'actual real output'},
                                    {'role': 'user', 'content': 'Keep this follow-up'}]
    driver.drive({**request, 'messages': reused}, 'sid:reuse', CODING, Rlog())
    for sent in coder.bodies[1:]:
        text = json.dumps(sent['messages'])
        assert 'actual real output' in text and 'Keep this follow-up' in text


def test_a_cut_off_call_is_never_forwarded_and_the_turn_reports_incomplete():
    cut = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "w", "type": "function", "function": {"name": "write_file", "arguments": '{"path":"x","content":"cut'}}]}}]}
    rlog = Rlog()
    out = plan_off_loop(Coder(cut), store=LoopStore()).drive(body(), "sid:c", CODING, rlog)
    assert generation.incomplete(out) and not out["choices"][0]["message"].get("tool_calls")
    assert out[generation.EVIDENCE]["call_prefixes"][0]["arguments"] == '{"path":"x","content":"cut'
    assert "loop.generation_incomplete" in rlog.kinds()
