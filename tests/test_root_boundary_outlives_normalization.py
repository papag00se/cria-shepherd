"""The real source work boundary outlives gate cleanup and history reduction.

No-signal gate results/private command plumbing stay absent. An empty projection
of an actual assistant boundary carries structure, not an invented action.
"""
import copy
import json
from dataclasses import replace

import pytest

from cria import assistruntime, contextfloor, focustrim, loop, probegate, selfcompact, steppreparation
from cria.memoryeffects import Effect
from gatefixture import gate_page
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


def history(probes):
    first = {'role': 'user', 'content': 'Initial context may itself carry requirements.\r\n'}
    task = {'role': 'user', 'content': 'The actual task.\n'}
    command = probegate._gate_sentinel(probes) + '\n:'
    call = {'role': 'assistant', 'tool_calls': [{'id': 'g1', 'type': 'function', 'function': {
        'name': 'exec_command', 'arguments': json.dumps({'cmd': command})}}]}
    raw = 'Chunk ID: 1\n' + probegate.SECTION_PREFIX + 'git___\ndeadbeef\n'
    result = {'role': 'tool', 'tool_call_id': 'g1', 'content': gate_page(probegate.GatePlan(''), raw)}
    followup = {'role': 'user', 'content': 'A later followup, not root.'}
    return [first, task, call, result, followup, {'role': 'assistant', 'content': 'working'}]


def assemble(messages):
    services = steppreparation.BaseServices(loop._strip_cria_file_ops, loop._msg_text_content,
        loop.reframe_preamble, loop._is_serialized_plan_cursor, menu_note=None)
    return steppreparation.assemble_base(steppreparation.BaseInput(messages, services))


@pytest.mark.parametrize('probes', [[], ['pytest -q']])
def test_real_base_preserves_first_work_boundary_through_gate_normalization(probes):
    messages = history(probes)
    before = copy.deepcopy(messages)
    # The accepted gate policy really removes both the no-signal result and call.
    cleaned = probegate.clean_gate_results(loop._strip_cria_file_ops(messages))
    assert cleaned == [messages[0], messages[1], messages[4], messages[5]]
    base = assemble(messages)
    assert base.root_indices == (0, 1)
    assert messages == before
    assert loop._history_root(base.messages) == loop._history_root(messages)
    assert base.messages[1:] == [messages[0], messages[1], {'role': 'assistant', 'content': ''},
                                 messages[4], messages[5]]
    assert base.render() is base.messages  # final framing is idempotent, not another synthetic turn


def test_a_gate_call_with_a_retained_result_still_keeps_its_boundary_and_user_bytes():
    messages = history(['pytest -q'])
    messages[3]['content'] = 'Native diagnostic observation, not a no-signal gate page.'
    before = copy.deepcopy(messages)
    base = assemble(messages)
    assert base.root_indices == (0, 1)
    assert loop._history_root(base.messages) == loop._history_root(messages)
    assert base.messages.count(messages[3]) == 1
    assert messages == before


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('probes', [[], ['pytest -q']])
@pytest.mark.parametrize('drop_at', [None, 'rolling', 'focus'])
def test_common_path_keeps_root_and_followup_after_gate_cleanup_and_reducers(synthetic, probes, drop_at):
    driver, session, body = setup_driver()
    session.synthetic = session.plan_off = synthetic
    body['messages'] = history(probes)
    before = copy.deepcopy(body)
    first, task = body['messages'][:2]
    followup = body['messages'][4]
    seen = []
    def rolling(source, state):
        seen.append(('rolling', copy.deepcopy(source.messages)))
        messages = [followup] if drop_at == 'rolling' else source.messages
        return selfcompact.RollingResult(messages, state, Effect.REDUCED if drop_at == 'rolling' else Effect.NO_OP)
    def focus(messages):
        seen.append(('focus', copy.deepcopy(messages)))
        return ([followup] if drop_at == 'focus' else messages), focustrim.TrimReport()
    definitions = {selfcompact.DEFINITION.policy.id: replace(selfcompact.DEFINITION, execute=rolling),
                   focustrim.DUPLICATES.policy.id: replace(focustrim.DUPLICATES, execute=focus)}
    runtime = assistruntime.AssistRuntime.select(level=5)
    runtime = replace(runtime, ordered_stages=tuple(definitions.get(d.policy.id, d) for d in runtime.ordered_stages))
    driver._ctx.self_compact = driver._ctx.focus_trim = True
    with assistruntime.bound(runtime):
        out, _ = driver._prepare_coder_context(session, body, _Rlog(), synthetic=synthetic,
                                              index=1, total=1, item='step')
    assert [kind for kind, _ in seen] == ['rolling', 'focus']
    assert all(first not in messages and task not in messages and followup in messages for _, messages in seen)
    assert body == before
    messages = out['messages']
    pin = loop._history_root(body['messages'])[0]
    roots = selfcompact.root_user_indices(messages, pin)
    assert [messages[i] for i in roots] == [first, task]
    assert loop._history_root(messages) == loop._history_root(body['messages'])
    assert [message for message in messages if message == first or message == task or message == followup] == [first, task, followup]
    assert not any(message.get('tool_call_id') == 'g1' or message.get('tool_calls') for message in messages)
    assert probegate.SECTION_PREFIX not in json.dumps(messages)
    assert 'deadbeef' not in json.dumps(messages)
    # Real floor pressure must keep exactly the original root, not promote the
    # followup merely because the legitimate reducers removed all old work turns.
    pressured = messages + [{'role': 'assistant', 'content': 'old work ' * 100} for _ in range(30)]
    pressured += [{'role': 'user', 'content': 'Current request.'}]
    fitted, _, report = contextfloor.fit(pressured, None, window=1400, reserve=300, safety=1.0, pinned_task=pin)
    assert report.turns_dropped > 0
    assert first in fitted and task in fitted


@pytest.mark.parametrize('synthetic', [False, True])
def test_common_path_retains_real_native_result_without_inventing_gate_actions(synthetic):
    driver, session, body = setup_driver()
    session.synthetic = session.plan_off = synthetic
    body['messages'] = history(['pytest -q'])
    body['messages'][3]['content'] = 'Native diagnostic observation, not a no-signal gate page.'
    before = copy.deepcopy(body)
    out, _ = driver._prepare_coder_context(session, body, _Rlog(), synthetic=synthetic,
                                          index=1, total=1, item='step')
    assert loop._history_root(out['messages']) == loop._history_root(body['messages'])
    assert out['messages'].count(body['messages'][3]) == 1
    assert body == before


def test_native_first_tool_is_not_replaced_by_an_invented_assistant_boundary():
    messages = [history([])[0], {'role': 'tool', 'tool_call_id': 'native-orphan', 'content': 'native bytes\r\n'},
                {'role': 'user', 'content': 'Followup.'}]
    before = copy.deepcopy(messages)
    base = assemble(messages)
    assert base.messages[1:] == messages
    assert loop._history_root(base.messages) == loop._history_root(messages)
    assert messages == before
