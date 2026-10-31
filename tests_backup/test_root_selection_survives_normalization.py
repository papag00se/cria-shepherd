"""Independent root-review incidents: exact pins and pre-normalization boundaries.

The raw role sequence owns root scope. Whitespace equivalence and a normalized
surviving message sequence cannot replace that authority.
"""
import copy
from dataclasses import replace

import pytest

from cria import assistruntime, bodykeys, contextfloor, focustrim, loop, selfcompact, steppreparation
from cria.memoryeffects import Effect
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


TASK = 'Implement the requested parser and preserve literal data.\n' * 32
BANNER = '<context>This may itself be a user requirement.</context>\r\n'


def u(text):
    return {'role': 'user', 'content': text}


def pressure(prelude):
    return ([u(text) for text in prelude]
            + [{'role': 'assistant', 'content': ('work block ' + str(i) + '\n') * 80} for i in range(35)]
            + [u('Continue the work now.')])


@pytest.mark.parametrize('boundary', [{'role': 'assistant'}, {'role': 'assistant', 'content': None},
    {'role': 'assistant', 'content': ''}, {'role': 'tool'}, {'role': 'tool', 'content': []}])
def test_dictionary_role_not_content_controls_root_stop(boundary):
    messages = [u(BANNER), u(TASK), boundary, u('followup')]
    assert selfcompact.root_user_indices(messages) == (0, 1)
    assert loop._history_root(messages)[0] == BANNER + '\n\n' + TASK


@pytest.mark.parametrize('source', list(bodykeys.AnnotationSource))
def test_every_enum_authority_excluded_but_string_lookalike_is_retained(source):
    known = {**u('producer context'), bodykeys.ANNOTATION_SOURCE: source}
    raw = {**u('literal requirement'), bodykeys.ANNOTATION_SOURCE: source.value}
    messages = [known, u(TASK), raw, {'role': 'assistant'}]
    assert selfcompact.root_user_indices(messages) == (1, 2)
    assert loop._history_root(messages)[0] == TASK + '\n\nliteral requirement'


@pytest.mark.parametrize('pin', ['', 'absent task'])
@pytest.mark.parametrize('headroom', [False, True])
def test_both_floor_reservation_paths_keep_whole_ordered_bundle_and_tail(pin, headroom):
    messages = pressure([BANNER, TASK])
    before = copy.deepcopy(messages)
    out, _, report = contextfloor.fit(messages, None, window=1400, reserve=600, safety=1.0,
                                      pinned_task=pin, headroom=headroom)
    assert report.turns_dropped > 0 and not report.over_budget
    assert out.index(u(BANNER)) < out.index(u(TASK)) < out.index(u('Continue the work now.'))
    assert sum(message == u(BANNER) for message in out) == sum(message == u(TASK) for message in out) == 1
    assert messages == before
    core = contextfloor._input_core(messages, pin)
    assert u(BANNER) in core and u(TASK) in core


@pytest.mark.parametrize('headroom', [False, True])
def test_exact_pin_selects_actual_exact_packet_not_earlier_whitespace_alias(headroom):
    alias = ' \r\n' + TASK + '\n '
    messages = pressure([alias, TASK])
    before = copy.deepcopy(messages)
    out, _, report = contextfloor.fit(messages, None, window=1400, reserve=600, safety=1.0,
                                      pinned_task=TASK, headroom=headroom)
    assert report.turns_dropped > 0 and u(TASK) in out
    assert selfcompact.root_user_indices(messages, TASK) == (1,)
    assert messages == before


@pytest.mark.parametrize('headroom', [False, True])
def test_unmatched_byte_exact_pin_does_not_discard_initial_context(headroom):
    messages = pressure([BANNER, TASK])
    pin = TASK.rstrip()
    assert all(message.get('content') != pin for message in messages)
    out, _, report = contextfloor.fit(messages, None, window=1400, reserve=600, safety=1.0,
                                      pinned_task=pin, headroom=headroom)
    assert report.turns_dropped > 0 and u(BANNER) in out and u(TASK) in out


def test_exact_joined_bundle_pin_does_not_drop_a_blank_but_real_user_packet():
    messages = pressure([TASK, ' \r\n'])
    pin = loop._history_root(messages)[0]
    assert pin == TASK + '\n\n \r\n'
    out, _, _ = contextfloor.fit(messages, None, window=1400, reserve=600, safety=1.0, pinned_task=pin)
    assert u(TASK) in out and u(' \r\n') in out
    assert selfcompact.root_user_indices(messages, pin) == (0, 1)


@pytest.mark.parametrize('boundary', [{'role': 'assistant', 'content': ''},
    {'role': 'assistant', 'content': '⟦cria⟧ status banner'}])
def test_public_base_assembly_keeps_raw_root_identity_before_history_normalization(boundary):
    messages = [u(TASK), boundary, u('later request'), {'role': 'assistant', 'content': 'working'}]
    before = copy.deepcopy(messages)
    services = steppreparation.BaseServices(loop._strip_cria_file_ops, loop._msg_text_content,
        loop.reframe_preamble, loop._is_serialized_plan_cursor, menu_note=None)
    base = steppreparation.assemble_base(steppreparation.BaseInput(messages, services))
    assert base.root_indices == (0,) and base.task_index == 0
    assert loop._history_root(base.messages) == loop._history_root(messages)
    assert base.messages[1] == messages[0] and base.messages[3] == messages[2]
    assert base.messages[2] == {'role': 'assistant', 'content': ''}
    assert messages == before
    # The caller-scoped boundary admission must not change ordinary scrubbing.
    assert loop._strip_cria_file_ops(messages) == [messages[0], messages[2], messages[3]]


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('boundary', [{'role': 'assistant', 'content': ''},
    {'role': 'assistant', 'content': '⟦cria⟧ status banner'}])
def test_real_common_preparation_keeps_only_raw_root_outside_both_reducers(synthetic, boundary):
    driver, session, body = setup_driver()
    session.synthetic = session.plan_off = synthetic
    raw_root = copy.deepcopy(body['messages'][0])
    followup = u('A later followup, not initial context.')
    body['messages'] += [boundary, followup, {'role': 'assistant', 'content': 'working'}]
    before = copy.deepcopy(body)
    observed = []
    def rolling(source, state):
        observed.append(('rolling', copy.deepcopy(source.messages)))
        return selfcompact.RollingResult(source.messages, state, Effect.NO_OP)
    def focus(messages):
        observed.append(('focus', copy.deepcopy(messages)))
        return messages, focustrim.TrimReport()
    definitions = {selfcompact.DEFINITION.policy.id: replace(selfcompact.DEFINITION, execute=rolling),
                   focustrim.DUPLICATES.policy.id: replace(focustrim.DUPLICATES, execute=focus)}
    runtime = assistruntime.AssistRuntime.select(level=5)
    runtime = replace(runtime, ordered_stages=tuple(definitions.get(d.policy.id, d) for d in runtime.ordered_stages))
    driver._ctx.self_compact = driver._ctx.focus_trim = True
    with assistruntime.bound(runtime):
        out, _ = driver._prepare_coder_context(session, body, _Rlog(), synthetic=synthetic,
                                              index=1, total=1, item='step')
    assert [kind for kind, _ in observed] == ['rolling', 'focus']
    assert loop._history_root(out['messages']) == loop._history_root(body['messages'])
    assert all(raw_root not in history and followup in history for _, history in observed)
    assert body == before
