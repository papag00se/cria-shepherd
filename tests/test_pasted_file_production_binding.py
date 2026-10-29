"""F16 public lifecycle binding: real drivers and translation, fake model transports."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from cria import assistruntime, config, loop, pastedfile as pf
from tests import test_text_write_recovery as tw
from test_loop import _Classification, _Rlog, _ctx, _enable_test_planning, _single_loop, _synth

SESSION = 'pasted-file-production'


def runtime(definition=pf.DEFINITION, *, disabled=False, synthetic=True, level=5):
    registrations = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id != definition.policy.id) + (definition,)
    return assistruntime.AssistRuntime.select(level=level, registrations=registrations,
        disabled=(definition.policy.id,) if disabled else (), experimental_planning=not synthetic)


def acting(cid='ordinary-followup'):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
        'content': None, 'tool_calls': [{'id': cid, 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': json.dumps({'path': tw.ROOT + '/' + tw.JAVA})}}]}}]}


@pytest.fixture
def production():
    holder = tw.TextWriteTests('test_the_a1_pasted_class_becomes_that_files_write_and_the_pom_excerpt_never_does')
    holder.setUp()
    text, tools, finish = tw._reply('a1_0022')
    pasted = {'choices': [{'finish_reason': finish, 'message': {'role': 'assistant', 'content': text}}]}
    try:
        yield holder, pasted, tools
    finally:
        holder.doCleanups()


def rig(production, selected, *, synthetic, replies=None, task=tw.TASK, text_write_answers=None):
    _, pasted, tools = production
    requests, judgments = [], []
    answers = iter(text_write_answers) if text_write_answers is not None else None
    responses = iter([pasted, acting()] if replies is None else replies)
    def coder(body, log):
        requests.append(deepcopy(body))
        value = next(responses)
        if isinstance(value, BaseException):
            raise value
        return json.dumps(value).encode()
    def reasoner(body, log):
        question = '\n'.join(str(m.get('content') or '') for m in body.get('messages', []))
        text_write = 'FILE NAMED BY THE ASSISTANT:' in question
        judgments.append((text_write, deepcopy(body)))
        answer = (next(answers) if answers is not None else 'WHOLE_FILE') if text_write else 'ON_TRACK'
        return json.dumps({'choices': [{'message': {'role': 'assistant',
            'content': answer}, 'finish_reason': 'stop'}]}).encode()
    if synthetic:
        driver = _single_loop(coder, reasoner_chat=reasoner,
            reasoner_role=config.Role(name='reasoner', backend='local'), workspace_root=tw.ROOT)
    else:
        ctx = _ctx(coder, reasoner, workspace_root=tw.ROOT)
        ctx.pilot_runtime = selected
        ctx.reasoner_role = config.Role(name='reasoner', backend='local')
        driver = loop.Loop(_enable_test_planning(ctx))
    driver._ctx.pilot_runtime = selected
    driver._ctx.assists = True
    driver._ctx.satisfaction_check_start = 0
    state = _synth()
    state.synthetic = state.plan_off = synthetic
    state.workspace_root, state.plan.task = tw.ROOT, task
    state.plan.items[0].text = task
    driver._store.put(SESSION, state)
    body = {'model': 'fixture', 'tools': deepcopy(tools), 'messages': [
        {'role': 'user', 'content': task},
        {'role': 'assistant', 'tool_calls': [{'id': 'rd', 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': json.dumps({'path': tw.ROOT + '/' + tw.JAVA})}}]},
        {'role': 'tool', 'tool_call_id': 'rd', 'content': 'package pipeline;'}]}
    return driver, state, body, requests, judgments


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_absent_pasted_policy_never_judges_or_promotes_the_recorded_draft(production, synthetic):
    driver, state, body, requests, judgments = rig(production, runtime(disabled=True, synthetic=synthetic), synthetic=synthetic)
    log = _Rlog()
    driver.drive(body, SESSION, _Classification(), log)
    assert requests and production[1]['choices'][0]['message']['content']
    assert not [request for is_text_write, request in judgments if is_text_write]
    assert not [fields for event, fields in log.events if event in ('massage.text_write_recovered', 'loop.unexecuted_write')]
    assert state.text_write_judged == {} and not state.pasted_block_other


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_exact_recovery_replacement_sees_original_draft_and_owns_its_completion(production, synthetic):
    seen = []
    replacement = acting('selected-recovery-result')
    def execute(source, state, *, enabled=True):
        seen.append((source, state, enabled))
        return pf.Result(pf.Status.UNCHANGED, completion=replacement)
    definition = replace(pf.DEFINITION, execute=execute)
    driver, state, body, requests, judgments = rig(production, runtime(definition, synthetic=synthetic), synthetic=synthetic)
    out = driver.drive(body, SESSION, _Classification(), _Rlog())
    assert len(seen) == 1 and seen[0][2] is True
    assert seen[0][0].completion['choices'][0]['message']['content'] == production[1]['choices'][0]['message']['content']
    assert out['choices'][0]['message']['tool_calls'] == replacement['choices'][0]['message']['tool_calls']
    assert len(requests) == 1 and not [request for is_text_write, request in judgments if is_text_write]


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_selected_redrive_replacement_owns_result_and_live_budget(production, synthetic):
    seen = []
    def execute(source, view, *, enabled=True):
        return pf.Result(pf.Status.UNCHANGED, source.completion)
    chosen = acting('selected-redrive-result')
    def redrive(source, view, *, enabled=True):
        seen.append((source, view, enabled))
        return pf.Result(pf.Status.UNCHANGED, chosen)
    definition = replace(pf.DEFINITION, execute=execute, redrive=redrive)
    driver, state, body, requests, judgments = rig(production, runtime(definition, synthetic=synthetic), synthetic=synthetic)
    out = driver.drive(body, SESSION, _Classification(), _Rlog())
    assert len(seen) == 1 and seen[0][0].budget is state and seen[0][2] is True
    assert state.unexecuted_nudges == 0 and len(requests) == 1
    assert out['choices'][0]['message']['tool_calls'] == chosen['choices'][0]['message']['tool_calls']
    assert not [r for is_text_write, r in judgments if is_text_write]


@pytest.mark.parametrize('synthetic', [False, True])
def test_new_other_ruling_suppresses_older_pending_pasted_write_redrive(production, synthetic):
    definition, seen = tracking()
    pasted = production[1]
    driver, state, body, requests, judgments = rig(production, runtime(definition, synthetic=synthetic),
        synthetic=synthetic, replies=[pasted, deepcopy(pasted), acting('after-other')],
        text_write_answers=['', 'OTHER'])
    driver.drive(body, SESSION, _Classification(), _Rlog())
    assert [entry[2].reason for entry in seen['execute'][:2]] == ['judge_unanswered', 'judged_other']
    assert list(state.text_write_judged.values()) == ['OTHER']
    assert len([request for text_write, request in judgments if text_write]) == 2
    assert [entry[2].status for entry in seen['redrive'][:2]] == [pf.Status.NUDGE, pf.Status.UNCHANGED]
    assert state.unexecuted_nudges == 1
    assert not state.pasted_block_other
    first_nudge = seen['redrive'][0][2].nudge
    assert len([entry for entry in seen['redrive'] if entry[2].status is pf.Status.NUDGE]) == 1
    # A successful consuming frame can acknowledge the old offer, but OTHER
    # cannot authorize another pasted-write prompt or admission.
    assert sum(entry[0][1] is first_nudge for entry in seen['nudge_delivered']) <= 1


def test_typed_other_revokes_authorization_without_credit_budget_or_unread_consumption():
    old = pf.Nudge('old instruction', 'old full reply', {'role': 'user', 'content': 'old instruction'}, 'old unread fact')
    state = pf.State(other=True, unread_fact='old unread fact', pending_nudge=old)
    budget = SimpleNamespace(unexecuted_nudges=2)
    def forbidden(*args):
        raise AssertionError('OTHER supersession inspected or judged draft again')
    evidence = SimpleNamespace(has_tool_calls=lambda completion: False,
        completion_text=forbidden, injected_texts=forbidden)
    result = pf.DEFINITION.redrive(pf.NudgeInput({}, [], evidence, budget, _Rlog(),
        defer_unread_consumption=True), state)
    assert result.status is pf.Status.UNCHANGED and state.pending_nudge is None and not state.other
    assert state.unread_fact == 'old unread fact' and budget.unexecuted_nudges == 2
    assert state.delivered_nudge is None
    assert pf.DEFINITION.nudge_delivered(state, old).status is pf.Status.UNCHANGED
    assert pf.DEFINITION.nudge_delivered(state, old, consumed=replace(old)).status is pf.Status.UNCHANGED
    assert state.delivered_nudge is None and state.unread_fact == 'old unread fact'
    acknowledged = pf.DEFINITION.nudge_delivered(state, old, consumed=old)
    assert acknowledged.status is pf.Status.FORWARDED and state.delivered_nudge is old
    assert not state.unread_fact and state.pending_nudge is None


def test_actual_old_consumption_does_not_clear_a_new_authorized_offer_or_its_unread_fact():
    old = pf.Nudge('old instruction', 'old reply', {}, 'old unread fact')
    current = pf.Nudge('new instruction', 'new reply', {}, 'new unread fact')
    state = pf.State(unread_fact='new unread fact', pending_nudge=current)
    result = pf.DEFINITION.nudge_delivered(state, old, consumed=old)
    assert result.status is pf.Status.FORWARDED and state.delivered_nudge is old
    assert state.pending_nudge is current and state.unread_fact == 'new unread fact'


@pytest.mark.parametrize('hook', ['execute', 'redrive', 'forwarded', 'settle', 'nudge_delivered', 'cancel'])
def test_runtime_rejects_malformed_pasted_lifecycle_hooks(hook):
    with pytest.raises(ValueError):
        runtime(replace(pf.DEFINITION, **{hook: None}))


def tracking(**overrides):
    seen = {name: [] for name in ('execute', 'redrive', 'forwarded', 'settle', 'nudge_delivered', 'cancel')}
    hooks = {}
    for name in seen:
        implementation = overrides.get(name, getattr(pf.DEFINITION, name))
        def invoke(*args, _name=name, _implementation=implementation, **kwargs):
            if _name == 'execute':
                seen['execute_inputs'].append(deepcopy(args[0].completion))
            result = _implementation(*args, **kwargs)
            seen[_name].append((args, kwargs, result))
            return result
        hooks[name] = invoke
    seen['execute_inputs'] = []
    return replace(pf.DEFINITION, **hooks), seen


def output_handler(driver, *, shell=False):
    from cria.server import CriaHandler
    handler = object.__new__(CriaHandler)
    from cria.multipart_bridge import Bridge
    handler.server = SimpleNamespace(multipart_bridge=Bridge(), loop=driver, loop_store=driver._store,
        pilot_runtime=driver._ctx.pilot_runtime, cfg=SimpleNamespace(safety=SimpleNamespace(external_dir_permission='none'),
            routing=SimpleNamespace(done_refusals=False, assists_enabled=False)))
    handler._shell_tool = ({'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
                           if shell else None)
    handler._synthetic, handler._workspace_root = {'write_file'}, tw.ROOT
    return handler


def translate(driver, completion, *, shell=False, handler=None):
    handler = output_handler(driver, shell=shell) if handler is None else handler
    final = handler._translate_out(completion, SESSION, _Rlog())
    handler._retain_pasted_output(final)
    return final


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_recovered_draft_is_forwarded_only_after_retained_server_output(production, synthetic):
    definition, seen = tracking()
    driver, state, body, requests, judgments = rig(production, runtime(definition, synthetic=synthetic), synthetic=synthetic)
    handler = output_handler(driver)
    out = driver.drive(body, SESSION, _Classification(), _Rlog(), pasted_delivery=handler._defer_pasted_delivery)
    assert len(seen['execute']) == 1 and len(requests) == 1
    source, view = seen['execute'][0][0]
    prepared = seen['execute'][0][2].prepared
    assert prepared is not None and view.prepared is prepared
    assert view.judged is state.text_write_judged and len(view.judged) == 1
    assert seen['execute_inputs'][0]['choices'][0]['message']['content'] == production[1]['choices'][0]['message']['content']
    assert seen['forwarded'] == seen['settle'] == [] and not view.deliveries
    # The final boundary may copy a reply; ID + actual payload authority, not dict identity.
    final = translate(driver, deepcopy(out), handler=handler)
    assert len(seen['forwarded']) == 1
    forwarded = seen['forwarded'][0]
    assert forwarded[0][0] is view and forwarded[0][1] is prepared
    assert forwarded[2].status is pf.Status.FORWARDED
    delivery = forwarded[2].delivery
    assert delivery.prepared is prepared and view.deliveries[delivery.call_ids[0]] is delivery
    args = json.loads(final['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    expected = production[1]['choices'][0]['message']['content'].split('```java\n', 1)[1].split('\n```', 1)[0] + '\n'
    assert args == {'path': tw.ROOT + '/' + tw.JAVA, 'content': expected}
    assert seen['settle'] == [] and not view.settlements
    assert len([r for is_text_write, r in judgments if is_text_write]) == 1


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('initial', [1, 2])
def test_public_redrive_uses_actual_shared_budget_and_full_carried_bytes(production, synthetic, initial):
    def unchanged(source, view, *, enabled=True):
        return pf.Result(pf.Status.UNCHANGED, source.completion)
    definition, seen = tracking(execute=unchanged)
    driver, state, body, requests, judgments = rig(production, runtime(definition, synthetic=synthetic), synthetic=synthetic)
    state.unexecuted_nudges = initial
    driver.drive(body, SESSION, _Classification(), _Rlog())
    assert seen['redrive']
    source, view = seen['redrive'][0][0]
    assert source.budget is state and source.defer_unread_consumption is True
    assert state.unexecuted_nudges == 2
    nudges = [entry[2].nudge for entry in seen['redrive'] if entry[2].status is pf.Status.NUDGE]
    if initial == 1:
        assert len(nudges) == 1 and len(seen['nudge_delivered']) == 1
        nudge = nudges[0]
        assert seen['nudge_delivered'][0][0][1] is nudge
        assert view.pending_nudge is None and view.delivered_nudge is nudge
        assert nudge.carried_reply == production[1]['choices'][0]['message']['content']
        assert len(requests) == 2
        assert any(m.get('role') == 'assistant' and m.get('content') == nudge.carried_reply for m in requests[1]['messages'])
        assert any(m.get('role') == 'user' and m.get('content') == nudge.user_turn['content'] for m in requests[1]['messages'])
    else:
        assert nudges == [] and seen['nudge_delivered'] == []
    assert not [r for is_text_write, r in judgments if is_text_write]


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('failure', ['provider', 'discard'])
def test_public_pending_nudge_is_retryable_without_credit_or_readmission(production, synthetic, failure, monkeypatch):
    def unchanged(source, view, *, enabled=True):
        if not source.evidence.has_tool_calls(source.completion):
            view.unread_fact = 'EXACT unread-target measurement'
        return pf.Result(pf.Status.UNCHANGED, source.completion)
    definition, seen = tracking(execute=unchanged)
    pasted = production[1]
    replies = [pasted, RuntimeError('provider interrupted'), acting('retry-consumed')] if failure == 'provider' else [pasted, acting('discarded'), acting('retry-consumed')]
    driver, state, body, requests, _ = rig(production, runtime(definition, synthetic=synthetic), synthetic=synthetic, replies=replies)
    state.unexecuted_nudges = 1
    method = '_drive_single_item' if synthetic else '_work'
    original, depth, dropping = getattr(driver, method), 0, failure == 'discard'
    def late(*args, **kwargs):
        nonlocal depth
        depth += 1
        try:
            out = original(*args, **kwargs)
        finally:
            depth -= 1
        return None if dropping and depth == 0 else out
    monkeypatch.setattr(driver, method, late)
    if failure == 'provider':
        with pytest.raises(RuntimeError, match='provider interrupted'):
            driver.drive(body, SESSION, _Classification(), _Rlog())
    else:
        assert driver.drive(body, SESSION, _Classification(), _Rlog()) is None
    nudge = next(entry[2].nudge for entry in seen['redrive'] if entry[2].status is pf.Status.NUDGE)
    view = seen['redrive'][0][0][1]
    assert seen['nudge_delivered'] == [] and view.pending_nudge is nudge and view.delivered_nudge is None
    assert view.unread_fact == 'EXACT unread-target measurement' and state.unexecuted_nudges == 2
    dropping = False
    out = driver.drive(body, SESSION, _Classification(), _Rlog())
    assert out['choices'][0]['message']['tool_calls'][0]['id'] == 'retry-consumed'
    assert len(seen['nudge_delivered']) == 1 and seen['nudge_delivered'][0][0][1] is nudge
    assert view.pending_nudge is None and view.delivered_nudge is nudge and not view.unread_fact
    assert state.unexecuted_nudges == 2 and len(requests) == 3
    assert any(m.get('content') == nudge.user_turn['content'] for m in requests[-1]['messages'])


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('kind,expected', [('denied', (False, False)), ('read-instead', (False, False)),
    ('wrote', (True, None)), ('opaque', (None, None)), ('exit-zero', (None, None))])
def test_public_settlement_uses_only_correlated_authoritative_result_facts(production, synthetic, kind, expected):
    from cria import bodykeys, denial
    definition, seen = tracking()
    driver, state, body, _, _ = rig(production, runtime(definition, synthetic=synthetic), synthetic=synthetic)
    out = driver.drive(body, SESSION, _Classification(), _Rlog())
    final = translate(driver, out)
    delivery = seen['forwarded'][0][2].delivery
    view = seen['execute'][0][0][1]
    raw = {'denied': denial.mark('the proposed mutation did not run'),
           'read-instead': denial.READ_INSTEAD_MARKER + '\noriginal file bytes',
           'wrote': 'Wrote notes.txt', 'opaque': 'ordinary returned content',
           'exit-zero': 'Process exited with code 0'}[kind]
    # cria's own refusal branches (a denial, a read-instead answer) are PROVEN by the producer; the others are not
    proven = ({bodykeys.RESULT_OUTCOME: denial.REFUSED} if kind in ('denied', 'read-instead')
              else {bodykeys.RESULT_OUTCOME: denial.LANDED} if kind == 'wrote' else {})   # the write program's own typed fact
    body['messages'] += [deepcopy(final['choices'][0]['message']),
        {'role': 'tool', 'tool_call_id': delivery.call_ids[0], 'content': raw, **proven}]
    driver.drive(body, SESSION, _Classification(), _Rlog())
    assert len(seen['settle']) == 1
    args, facts, result = seen['settle'][0]
    assert args[0] is view and args[1] is delivery and args[2] == delivery.call_ids[0]
    assert (facts['ran'], facts['changed']) == expected
    assert result.settlement.delivery is delivery
    assert (result.settlement.ran, result.settlement.changed) == expected
    assert view.settlements[delivery.call_ids[0]] is result.settlement


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_late_result_remains_with_older_delivery_and_duplicate_does_not_settle_twice(production, synthetic):
    definition, seen = tracking()
    pasted = production[1]
    driver, state, body, _, judgments = rig(production, runtime(definition, synthetic=synthetic),
        synthetic=synthetic, replies=[pasted, deepcopy(pasted), acting('after-old-result'), acting('duplicate-result')])
    first = translate(driver, driver.drive(body, SESSION, _Classification(), _Rlog()))
    d1 = seen['forwarded'][0][2].delivery
    second = translate(driver, driver.drive(body, SESSION, _Classification(), _Rlog()))
    d2 = seen['forwarded'][1][2].delivery
    assert d1 is not d2 and d1.call_ids != d2.call_ids
    view = seen['execute'][0][0][1]
    assert view.deliveries[d1.call_ids[0]] is d1 and view.deliveries[d2.call_ids[0]] is d2
    assert len([r for text_write, r in judgments if text_write]) == 1
    body['messages'] += [first['choices'][0]['message'], {'role': 'tool',
        'tool_call_id': d1.call_ids[0], 'content': 'opaque result for older draft'}]
    driver.drive(body, SESSION, _Classification(), _Rlog())
    assert len(seen['settle']) == 1 and seen['settle'][0][0][1] is d1
    assert d1.call_ids[0] in view.settlements and view.deliveries[d2.call_ids[0]] is d2
    driver.drive(body, SESSION, _Classification(), _Rlog())
    assert len(seen['settle']) == 1 and view.deliveries[d2.call_ids[0]] is d2
    assert second['choices'][0]['message']['tool_calls'][0]['id'] == d2.call_ids[0]


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('lowering', ['native', 'shell', 'refused', 'removed'])
def test_public_final_lowering_not_offered_ids_decides_recovered_write_delivery(production, synthetic, lowering):
    lines = ['import shutil', 'shutil.rmtree("/")'] if lowering == 'refused' else ['value = 1']
    lines += [f'value_{i} = {i}' for i in range(12)]
    code = '\n'.join(lines) + '\n'
    pasted = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
        'content': 'app.py\n```python\n' + code + '```'}}]}
    fixture = production[0], pasted, production[2]
    definition, seen = tracking()
    driver, state, body, _, _ = rig(fixture, runtime(definition, synthetic=synthetic),
        synthetic=synthetic, task='Create app.py.')
    handler = output_handler(driver, shell=lowering in ('shell', 'refused'))
    out = driver.drive(body, SESSION, _Classification(), _Rlog(), pasted_delivery=handler._defer_pasted_delivery)
    prepared = seen['execute'][0][2].prepared
    assert prepared is not None and prepared.content == code
    assert seen['forwarded'] == []
    view = seen['execute'][0][0][1]
    if lowering == 'removed':
        out = deepcopy(out)
        out['choices'][0]['message']['tool_calls'] = []
    final = translate(driver, out, handler=handler)
    if lowering in ('refused', 'removed'):
        assert not view.deliveries and not view.settlements and view.delivery is None
        assert not any(row[2].status is pf.Status.FORWARDED for row in seen['forwarded'])
        if lowering == 'refused':
            call = final['choices'][0]['message']['tool_calls'][0]
            assert call['id'] in prepared.call_ids and call['function']['name'] == 'exec_command'
    else:
        assert len(seen['forwarded']) == 1 and seen['forwarded'][0][2].status is pf.Status.FORWARDED
        delivery = seen['forwarded'][0][2].delivery
        assert delivery.prepared is prepared and delivery.call_ids == prepared.call_ids
        assert not view.settlements
        call = final['choices'][0]['message']['tool_calls'][0]
        assert call['function']['name'] == ('exec_command' if lowering == 'shell' else 'write_file')


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('stage', ['forwarded', 'settle', 'nudge_delivered'])
def test_public_selected_delivery_replacement_has_no_canonical_fallback(production, synthetic, stage):
    def decline(*args, **kwargs):
        return pf.Result(pf.Status.UNCHANGED, reason='selected decline')
    overrides = {stage: decline}
    if stage == 'nudge_delivered':
        overrides['execute'] = lambda source, view, **kwargs: pf.Result(pf.Status.UNCHANGED, source.completion)
    definition, seen = tracking(**overrides)
    driver, state, body, _, _ = rig(production, runtime(definition, synthetic=synthetic), synthetic=synthetic)
    out = driver.drive(body, SESSION, _Classification(), _Rlog())
    view = seen['execute'][0][0][1]
    if stage == 'settle':
        delivery = seen['forwarded'][0][2].delivery
        body['messages'] += [deepcopy(out['choices'][0]['message']), {'role': 'tool',
            'tool_call_id': delivery.call_ids[0], 'content': 'ordinary opaque tool return'}]
        driver.drive(body, SESSION, _Classification(), _Rlog())
        assert view.deliveries[delivery.call_ids[0]] is delivery and not view.settlements
    elif stage == 'forwarded':
        assert not view.deliveries and not view.settlements
    else:
        assert view.pending_nudge is not None and view.delivered_nudge is None
    assert len(seen[stage]) == 1 and seen[stage][0][2].reason == 'selected decline'


@pytest.mark.parametrize('synthetic', [False, True])
def test_step_cancel_preserves_memo_and_older_delivery_without_admitting_pending_offer(production, synthetic):
    from cria.plan import PlanItem
    definition, seen = tracking()
    pasted = production[1]
    driver, state, body, _, _ = rig(production, runtime(definition, synthetic=synthetic), synthetic=synthetic,
        replies=[pasted, deepcopy(pasted), acting('after-step-reset')])
    state.plan.items.append(PlanItem('Continue the remaining requested work.'))
    driver.drive(body, SESSION, _Classification(), _Rlog())
    old = seen['forwarded'][0][2].delivery
    view = seen['execute'][0][0][1]
    handler = output_handler(driver)
    pending = driver.drive(body, SESSION, _Classification(), _Rlog(), pasted_delivery=handler._defer_pasted_delivery)
    prepared = seen['execute'][-1][2].prepared
    assert prepared is not None and view.prepared is prepared
    memo = dict(state.text_write_judged)
    state.unexecuted_nudges = 2
    # This is the actual verified-step bridge, not a Source reset simulator.
    with assistruntime.bound(driver._ctx.pilot_runtime):
        driver._advance(state, SESSION, body, 1, 2, _Rlog())
    assert len(seen['cancel']) == 1 and seen['cancel'][0][0][0] is view
    assert state.unexecuted_nudges == 0 and state.text_write_judged == memo
    assert view.prepared is view.pending_nudge is view.delivered_nudge is None
    assert view.deliveries[old.call_ids[0]] is old and not view.settlements
    translate(driver, pending, handler=handler)
    assert all(delivery is old for delivery in view.deliveries.values())


@pytest.mark.parametrize('synthetic', [False, True])
def test_new_owner_does_not_inherit_prepared_nudge_or_delivery_and_restart_omits_transients(production, synthetic):
    definition, seen = tracking()
    driver, original, body, _, _ = rig(production, runtime(definition, synthetic=synthetic), synthetic=synthetic)
    out = driver.drive(body, SESSION, _Classification(), _Rlog())
    old_view = seen['execute'][0][0][1]
    old_delivery = seen['forwarded'][0][2].delivery
    serialized = loop._session_to_dict(original)
    restarted = loop._session_from_dict(serialized)
    assert restarted.text_write_judged == {} and not restarted.pasted_block_other
    replacement = _synth()
    replacement.synthetic = replacement.plan_off = synthetic
    replacement.workspace_root, replacement.plan.task = tw.ROOT, tw.TASK
    driver._store.put(SESSION, replacement)
    body['messages'] += [out['choices'][0]['message'], {'role': 'tool',
        'tool_call_id': old_delivery.call_ids[0], 'content': 'old-owner result'}]
    driver.drive(body, SESSION, _Classification(), _Rlog())
    new_view = seen['execute'][-1][0][1]
    assert new_view is not old_view and new_view.judged is replacement.text_write_judged
    assert not new_view.deliveries and not new_view.settlements
    assert new_view.prepared is new_view.pending_nudge is new_view.delivered_nudge is None
    assert seen['settle'] == [] and old_view.deliveries[old_delivery.call_ids[0]] is old_delivery


@pytest.mark.parametrize('synthetic', [False, True])
def test_old_finalization_callback_cannot_erase_or_forward_a_new_prepared_draft(production, synthetic):
    definition, seen = tracking()
    pasted = production[1]
    driver, state, body, _, _ = rig(production, runtime(definition, synthetic=synthetic),
        synthetic=synthetic, replies=[pasted, deepcopy(pasted)])
    finishes = []
    first = driver.drive(body, SESSION, _Classification(), _Rlog(), pasted_delivery=finishes.append)
    original_prepared = seen['execute'][0][2].prepared
    finishes[0](None)
    canceled = list(seen['forwarded'])
    assert not any(entry[2].status is pf.Status.FORWARDED for entry in canceled)
    second = driver.drive(body, SESSION, _Classification(), _Rlog(), pasted_delivery=finishes.append)
    current_prepared = seen['execute'][1][2].prepared
    view = seen['execute'][0][0][1]
    assert current_prepared is not original_prepared and view.prepared is current_prepared
    finishes[0](first)
    assert view.prepared is current_prepared and seen['forwarded'] == canceled and not view.deliveries
    finishes[1](second)
    assert len(seen['forwarded']) == len(canceled) + 1 and seen['forwarded'][-1][0][1] is current_prepared
    assert seen['forwarded'][-1][2].status is pf.Status.FORWARDED
    assert original_prepared.call_ids[0] not in view.deliveries


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('competitor', ['protocol', 'fenced', 'lost'])
def test_other_real_redrives_spend_same_budget_before_paste_admission(production, synthetic, competitor):
    from cria import generation
    from cria.upstream import UpstreamProtocolError
    if competitor == 'protocol':
        first = UpstreamProtocolError('typed malformed generation', response_error={
            'type': generation.PROTOCOL_ERROR, 'message': 'typed malformed generation'})
    elif competitor == 'fenced':
        first = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
            'content': '```json\n{"action":"deploy_prod","parameters":{"path":"x"}}\n```'}}]}
    else:
        first = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': None,
            'reasoning_content': "<|tool_call_start|>[deploy_prod(path='x')]<|tool_call_end|>"}}]}
    def unchanged(source, view, **kwargs):
        return pf.Result(pf.Status.UNCHANGED, source.completion)
    definition, seen = tracking(execute=unchanged)
    driver, state, body, requests, _ = rig(production, runtime(definition, synthetic=synthetic),
        synthetic=synthetic, replies=[first, production[1], acting('after-competition')])
    state.unexecuted_nudges = 1
    log = _Rlog()
    driver.drive(body, SESSION, _Classification(), log)
    assert state.unexecuted_nudges == 2 and len(requests) == 3
    event = {'protocol': 'loop.protocol_refused', 'fenced': 'loop.fenced_call_refused_said',
             'lost': 'loop.lost_call_offmenu'}[competitor]
    assert any(kind == event for kind, fields in log.events)
    assert not any(kind == 'loop.unexecuted_write' for kind, fields in log.events)
    assert not any(entry[2].status is pf.Status.NUDGE for entry in seen['redrive'])


def test_repeated_step_paste_spends_budget_without_ack_before_retention(production):
    def unchanged(source, view, *, enabled=True):
        view.unread_fact = 'EXACT unread fact still awaiting retained output'
        return pf.Result(pf.Status.UNCHANGED, source.completion)
    definition, seen = tracking(execute=unchanged)
    pasted = production[1]
    driver, state, body, requests, _ = rig(production, runtime(definition, synthetic=False),
        synthetic=False, replies=[pasted, deepcopy(pasted), acting('after-two-pastes')])
    handler = output_handler(driver)
    registrations = []
    def defer(retain):
        registrations.append(retain)
        handler._defer_pasted_delivery(retain)
    out = driver.drive(body, SESSION, _Classification(), _Rlog(), pasted_delivery=defer)
    assert len(registrations) == 1 and handler._pasted_retention is registrations[0]
    assert len(requests) == 3 and state.unexecuted_nudges == pf.MAX_NUDGES
    nudges = [entry[2].nudge for entry in seen['redrive'] if entry[2].status is pf.Status.NUDGE]
    assert len(nudges) == 2 and nudges[0] is not nudges[1]
    assert all(n.carried_reply == pasted['choices'][0]['message']['content'] for n in nudges)
    for request, nudge in zip(requests[1:], nudges, strict=True):
        assert nudge.user_turn in request['messages']
        assert {'role': 'assistant', 'content': nudge.carried_reply} in request['messages']
    assert state.pasted_pending_nudge is nudges[-1] and not seen['nudge_delivered']
    assert state.pasted_delivered_nudge is None and state.unread_target_fact
    assert out['choices'][0]['message']['tool_calls'][0]['id'] == 'after-two-pastes'
    translate(driver, out, handler=handler)
    assert len(seen['nudge_delivered']) == 1
    assert seen['nudge_delivered'][0][0][1] is nudges[-1]
    assert state.pasted_delivered_nudge is nudges[-1]
    assert state.pasted_pending_nudge is None and not state.unread_target_fact
    assert state.unexecuted_nudges == pf.MAX_NUDGES


def test_repeated_call_less_step_reaches_real_probe_at_shared_limit(production):
    def unchanged(source, view, *, enabled=True):
        return pf.Result(pf.Status.UNCHANGED, source.completion)
    definition, seen = tracking(execute=unchanged)
    selected = runtime(definition, synthetic=False)
    selected = replace(selected, ordered_stages=tuple(d for d in selected.ordered_stages
        if d.policy.id != 'completion-act-first'))
    pasted = production[1]
    driver, state, body, requests, _ = rig(production, selected, synthetic=False,
        replies=[pasted, deepcopy(pasted), deepcopy(pasted), acting('must-not-be-needed')])
    body['tools'].append({'type': 'function', 'function': {'name': 'exec_command',
        'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}})
    handler = output_handler(driver)
    out = driver.drive(body, SESSION, _Classification(), _Rlog(),
        pasted_delivery=handler._defer_pasted_delivery)
    assert len(requests) == pf.MAX_NUDGES + 1
    assert state.unexecuted_nudges == pf.MAX_NUDGES and state.awaiting_probe
    assert out['choices'][0]['message']['tool_calls'][0]['id'] == state.probe_call_id
    nudges = [entry[2].nudge for entry in seen['redrive'] if entry[2].status is pf.Status.NUDGE]
    assert len(nudges) == pf.MAX_NUDGES and not seen['nudge_delivered']
    assert state.pasted_pending_nudge is nudges[-1]
    translate(driver, out, handler=handler)
    # Retaining a required gate is not retaining the coder reply that consumed this nudge.
    assert not seen['nudge_delivered'] and state.pasted_pending_nudge is nudges[-1]
    assert state.pasted_delivered_nudge is None


def test_repeated_step_interruption_retries_latest_offer_without_new_spend(production):
    def unchanged(source, view, *, enabled=True):
        if not source.evidence.has_tool_calls(source.completion):
            view.unread_fact = 'EXACT interrupted unread fact'
        return pf.Result(pf.Status.UNCHANGED, source.completion)
    definition, seen = tracking(execute=unchanged)
    pasted = production[1]
    driver, state, body, requests, _ = rig(production, runtime(definition, synthetic=False),
        synthetic=False, replies=[pasted, deepcopy(pasted), RuntimeError('interrupted third frame'),
                                 acting('actual-resumed-reply')])
    with pytest.raises(RuntimeError, match='interrupted third frame'):
        driver.drive(body, SESSION, _Classification(), _Rlog())
    nudges = [entry[2].nudge for entry in seen['redrive'] if entry[2].status is pf.Status.NUDGE]
    assert state.unexecuted_nudges == pf.MAX_NUDGES and len(nudges) == pf.MAX_NUDGES
    assert nudges[0] is not nudges[-1] and state.pasted_pending_nudge is nudges[-1]
    assert not seen['nudge_delivered'] and state.unread_target_fact == 'EXACT interrupted unread fact'
    handler = output_handler(driver)
    out = driver.drive(body, SESSION, _Classification(), _Rlog(),
        pasted_delivery=handler._defer_pasted_delivery)
    assert len(requests) == 4 and nudges[-1].user_turn in requests[-1]['messages']
    assert state.unexecuted_nudges == pf.MAX_NUDGES and not seen['nudge_delivered']
    assert out['choices'][0]['message']['tool_calls'][0]['id'] == 'actual-resumed-reply'
    translate(driver, out, handler=handler)
    assert len(seen['nudge_delivered']) == 1 and seen['nudge_delivered'][0][0][1] is nudges[-1]
    assert state.pasted_pending_nudge is None and state.pasted_delivered_nudge is nudges[-1]
    assert not state.unread_target_fact and state.unexecuted_nudges == pf.MAX_NUDGES
