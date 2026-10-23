"""F44 exact selection at real public drivers; fake transports, no executed probes."""
from copy import deepcopy
from dataclasses import replace
import io
import json

import pytest

from cria import assistruntime, config, groundedaction as ga, loop, probegate, repositorychecks, stalledwork as sw
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog

SESSION = 'driver-fixture'


def runtime(definition=sw.DEFINITION, *, disabled=False, level=5):
    registrations = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id != sw.DEFINITION.policy.id) + (definition,)
    return assistruntime.AssistRuntime.select(level=level, registrations=registrations,
        disabled=(sw.DEFINITION.policy.id,) if disabled else ())


def acting(cid='next', name='read_file', args=None):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
        'tool_calls': [{'id': cid, 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps({'path': 'next.txt'} if args is None else args)}}]}}]}


def refused_history():
    history = []
    for i in range(3):
        history += [acting(str(i))['choices'][0]['message'],
                    {'role': 'tool', 'tool_call_id': str(i), 'content': '⟦ctx:denied⟧ request did not run'}]
    return history


def rig(monkeypatch, root, *, synthetic=True, replies=None):
    driver, state, body = setup_driver()
    state.synthetic = state.plan_off = synthetic
    driver._ctx.pilot_runtime = root
    driver._ctx.assists = True
    posted = []
    answers = iter([acting()] if replies is None else replies)
    def transport(request, **options):
        if request.full_url.endswith('/v1/chat/completions'):
            posted.append(json.loads(request.data))
            reply = next(answers)
            if isinstance(reply, BaseException):
                raise reply
            return io.BytesIO(json.dumps(reply).encode())
        if request.full_url.endswith('/tokenize'):
            return io.BytesIO(b'{"tokens":[1,2,3]}')
        return io.BytesIO(b'{"data":[]}')
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
    return driver, state, body, posted


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_disabled_selection_does_not_arm_legacy_refusal_or_spin(monkeypatch, synthetic):
    driver, state, body, posted = rig(monkeypatch, runtime(disabled=True), synthetic=synthetic)
    body['messages'] += refused_history()
    out = driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1 and out['choices'][0]['message']['tool_calls'] == acting()['choices'][0]['message']['tool_calls']
    assert not state.redirect_due and not state.spin_probe_due
    assert state.action_seq == 1 and state.blocked_fired_seq == -10000


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_exact_observation_replacement_owns_the_only_detection(monkeypatch, synthetic):
    seen = []
    def observe(source, state, *, enabled=True):
        seen.append((source, state, enabled))
        return sw.Result(sw.Status.WITHHELD)
    chosen = replace(sw.DEFINITION, execute=observe)
    driver, state, body, posted = rig(monkeypatch, runtime(chosen), synthetic=synthetic)
    body['messages'] += refused_history()
    driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1 and len(seen) == 1
    assert isinstance(seen[0][0], sw.ObservationInput) and seen[0][2]
    assert not state.redirect_due and state.action_seq == 1


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_absence_keeps_required_write_result_and_unlanded_ids(monkeypatch, synthetic):
    reply = acting('next-write', 'write_file', {'path': 'a.py', 'content': 'next source\n'})
    driver, state, body, posted = rig(monkeypatch, runtime(disabled=True), synthetic=synthetic, replies=[reply])
    state.write_call_ids = ['prior-write']
    body['messages'] += [acting('prior-write', 'write_file', {'path': 'a.py', 'content': 'old\n'})['choices'][0]['message'],
                         {'role': 'tool', 'tool_call_id': 'prior-write', 'content': 'Wrote a.py'}]
    driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1
    assert state.write_tracking and state.write_call_ids == ['prior-write', 'next-write']
    assert state.write_result_ids == {'prior-write'}
    assert not state.recent_writes and not state.recent_write_ids


@pytest.mark.parametrize('mode', ['absent', 'noop'])
def test_public_required_clock_records_first_act_and_prevents_extra_leg0_without_f44(monkeypatch, mode):
    chosen = replace(sw.DEFINITION, execute=lambda *a, **k: sw.Result(sw.Status.NO_OP))
    root = runtime(chosen, disabled=mode == 'absent')
    done = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'done'}}]}
    driver, state, body, posted = rig(monkeypatch, root,
        replies=[acting('actual-first'), done, acting('unnecessary-leg0')])
    first = driver.drive(body, SESSION, None, _Rlog())
    first_clock = state.action_seq
    body['messages'] += [first['choices'][0]['message'],
                         {'role': 'tool', 'tool_call_id': 'actual-first', 'content': 'actual result'}]
    driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 2 and not state.leg0_nudged, 'a genuine retained act must satisfy required act-first authority'
    assert first_clock == 1


@pytest.mark.parametrize('mode', ['absent', 'noop'])
def test_public_required_clock_dates_later_own_check_facts_without_f44(monkeypatch, mode):
    chosen = replace(sw.DEFINITION, execute=lambda *a, **k: sw.Result(sw.Status.NO_OP))
    driver, state, body, posted = rig(monkeypatch, runtime(chosen, disabled=mode == 'absent'),
        replies=[acting('own-check', 'exec_command', {'cmd': 'pytest -q'}), acting('next')])
    body['tools'].append({'type': 'function', 'function': {'name': 'exec_command', 'parameters': {
        'type': 'object', 'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}})
    state.last_gate_flag, state.last_gate_seq = '$ pytest -q\nprior exact failure', 0
    first = driver.drive(body, SESSION, None, _Rlog())
    body['messages'] += [first['choices'][0]['message'], {'role': 'tool', 'tool_call_id': 'own-check',
        'content': 'Process exited with code 0\nOutput:\nactual passing result'}]
    driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 2
    assert state.own_check_runs == [(1, ['pytest -q'], 0)]
    assert state.action_seq == 2 and 'pytest -q' in loop.newer_own_run(state)


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('start,blocked,end,triggered', [(49, 38, 51, 50), (24, 14, 26, 26)])
def test_public_multi_call_required_clock_and_refusal_cooldown_use_original_batch_start(monkeypatch, synthetic, start, blocked, end, triggered):
    batch = acting('batch-first')
    batch['choices'][0]['message']['tool_calls'] += acting('batch-second')['choices'][0]['message']['tool_calls']
    driver, state, body, posted = rig(monkeypatch, runtime(), synthetic=synthetic, replies=[batch])
    state.action_seq, state.blocked_fired_seq = start, blocked
    body['messages'] += refused_history()
    log = _Rlog()
    out = driver.drive(body, SESSION, None, log)
    assert len(posted) == 1 and len(out['choices'][0]['message']['tool_calls']) == 2
    assert state.action_seq == end and state.blocked_fired_seq == triggered
    assert state.redirect_due and state.repeat_count == 3
    fired = [fields for event, fields in log.events if event == 'loop.refusals']
    assert len(fired) == 1 and fired[0]['count'] == 3
    assert state.recent_writes == state.recent_write_ids == []


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_fact_clock_uses_immutable_call_count_before_selected_callbacks(monkeypatch, synthetic):
    retained, snapshots = [], []
    def observe(source, view, *, enabled=True):
        facts = source.measure()
        snapshots.append(facts)
        result = sw.observe(replace(source, measure=lambda: facts), view, enabled=enabled)
        retained[0]['choices'][0]['message']['tool_calls'] += acting('callback-added')['choices'][0]['message']['tool_calls']
        view.action_seq = 999  # selected observation must not forge the authoritative fact
        return result
    driver, state, body, _ = rig(monkeypatch, runtime(replace(sw.DEFINITION, execute=observe)), synthetic=synthetic)
    method = '_drive_single_item' if synthetic else '_work'
    original = getattr(driver, method)
    def remember(*args, **kwargs):
        out = original(*args, **kwargs)
        retained.append(out)
        return out
    monkeypatch.setattr(driver, method, remember)
    out = driver.drive(body, SESSION, None, _Rlog())
    assert out is retained[0] and len(out['choices'][0]['message']['tool_calls']) == 2
    assert len(snapshots) == 1 and snapshots[0].sequence_start == 0
    assert len(snapshots[0].calls) == 1 and snapshots[0].calls[0].call_id == 'next'
    assert state.action_seq == 1 and state.recent_write_ids == ['next']


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_selected_callback_failure_does_not_commit_required_clock(monkeypatch, synthetic):
    class RejectedObservation(Exception):
        pass
    def observe(source, view, *, enabled=True):
        raise RejectedObservation('no retained public return')
    driver, state, body, posted = rig(monkeypatch, runtime(replace(sw.DEFINITION, execute=observe)), synthetic=synthetic)
    with pytest.raises(RejectedObservation, match='no retained public return'):
        driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1 and state.action_seq == 0


@pytest.mark.parametrize('level', range(6))
def test_canonical_registration_and_exact_immutable_l5_projection(level):
    root = assistruntime.AssistRuntime.select(level=level)
    assert sum(d is sw.DEFINITION for d in assistruntime.DEFINITIONS) == 1
    assert root.stalled_work is (sw.DEFINITION if level == 5 else None)
    with pytest.raises(AttributeError):
        root.stalled_work = None
    assert sw.DEFINITION.policy.family_id == 'F44' and sw.DEFINITION.policy.migrated is False


@pytest.mark.parametrize('hook', ['execute', 'admit', 'settle_stage', 'progress_stage', 'acknowledge', 'reset_step'])
def test_malformed_selected_lifecycle_hook_is_rejected_before_execution(hook):
    with pytest.raises((TypeError, ValueError)):
        runtime(replace(sw.DEFINITION, **{hook: None}))


@pytest.mark.parametrize('actions', [None, object(), replace(ga.DEFINITION, author=None), replace(ga.DEFINITION, vet=None)])
def test_malformed_nested_authority_is_not_a_canonical_fallback(actions):
    with pytest.raises((TypeError, ValueError)):
        runtime(replace(sw.DEFINITION, actions=actions))


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('late', ['retained', 'equal-copy', 'replacement', 'none', 'exception', 'owner-replacement'])
def test_actual_retained_public_reply_alone_acknowledges_its_exact_pending_steer(monkeypatch, synthetic, late):
    views, steers, acknowledgements = [], [], []
    def admit(source, view, *, enabled=True):
        views.append(view)
        result = sw.DEFINITION.admit(source, view, enabled=enabled)
        if result.steer is not None:
            steers.append(result.steer)
        return result
    def acknowledge(view, steer, *, enabled=True):
        acknowledgements.append((view, steer))
        return sw.DEFINITION.acknowledge(view, steer, enabled=enabled)
    chosen = replace(sw.DEFINITION, admit=admit, acknowledge=acknowledge)
    driver, state, body, posted = rig(monkeypatch, runtime(chosen), synthetic=synthetic)
    state.redirect_due, state.repeat_count, state.repeat_action = True, 3, 'refused action'
    method = '_drive_single_item' if synthetic else '_work'
    original = getattr(driver, method)
    candidates = []
    class Interrupted(Exception):
        pass
    def return_late(*args, **kwargs):
        candidate = original(*args, **kwargs)
        candidates.append(candidate)
        assert steers and not acknowledgements, 'acknowledged before the actual public return'
        if late == 'equal-copy':
            return deepcopy(candidate)
        if late == 'replacement':
            return acting('replacement')
        if late == 'none':
            return None
        if late == 'exception':
            raise Interrupted('discarded coder reply')
        if late == 'owner-replacement':
            driver._store.drop(SESSION)
            driver._store.put(SESSION, loop.PlanSession(plan=loop.Plan(id='other', task='Other task',
                created='now', items=[loop.PlanItem('Other task')]), synthetic=synthetic, plan_off=synthetic))
        return candidate
    monkeypatch.setattr(driver, method, return_late)
    if late == 'exception':
        with pytest.raises(Interrupted, match='discarded coder reply'):
            driver.drive(body, SESSION, None, _Rlog())
    else:
        out = driver.drive(body, SESSION, None, _Rlog())
        if late == 'retained':
            assert out is candidates[0]
    assert len(posted) == 1 and len(steers) == 1
    steer = steers[0]
    assert steer.text in json.dumps(posted[0], ensure_ascii=False)
    assert views[0].recent_writes is state.recent_writes
    if late == 'retained':
        assert len(acknowledgements) == 1 and acknowledgements[0][1] is steer
        assert views[0].pending_steer is None and views[0].last_delivered is steer
        assert state.action_seq == 1
    else:
        assert acknowledgements == [] and views[0].pending_steer is steer
        assert views[0].last_delivered is None and state.action_seq == 0


@pytest.mark.parametrize('synthetic', [False, True])
def test_retained_reply_without_the_selected_steer_in_its_actual_body_earns_no_ack(monkeypatch, synthetic):
    views, steers, acknowledgements = [], [], []
    def admit(source, view, *, enabled=True):
        views.append(view)
        result = sw.DEFINITION.admit(source, view, enabled=enabled)
        if result.steer is not None:
            steers.append(result.steer)
        return result
    def acknowledge(view, steer, *, enabled=True):
        acknowledgements.append(steer)
        return sw.DEFINITION.acknowledge(view, steer, enabled=enabled)
    driver, state, body, posted = rig(monkeypatch,
        runtime(replace(sw.DEFINITION, admit=admit, acknowledge=acknowledge)), synthetic=synthetic)
    state.redirect_due, state.repeat_count, state.repeat_action = True, 3, 'refused action'
    prepare = driver._prepare_coder_context
    def overwrite(*args, **kwargs):
        framed, reoriented = prepare(*args, **kwargs)
        assert steers
        marker = steers[0].text
        framed = {**framed, 'messages': [dict(m, content='OTHER_POLICY_NOTE')
                  if marker in str(m.get('content', '')) else m for m in framed['messages']]}
        return framed, reoriented
    monkeypatch.setattr(driver, '_prepare_coder_context', overwrite)
    driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1 and 'OTHER_POLICY_NOTE' in json.dumps(posted[0])
    assert steers[0].text not in json.dumps(posted[0], ensure_ascii=False)
    assert acknowledgements == [] and views[0].pending_steer is steers[0]


@pytest.mark.parametrize('synthetic', [False, True])
def test_discarded_steer_survives_continuation_then_is_delivered_once(monkeypatch, synthetic):
    views, steers, acknowledgements = [], [], []
    def admit(source, view, *, enabled=True):
        views.append(view)
        result = sw.DEFINITION.admit(source, view, enabled=enabled)
        if result.steer is not None:
            steers.append(result.steer)
        return result
    def acknowledge(view, steer, *, enabled=True):
        acknowledgements.append(steer)
        return sw.DEFINITION.acknowledge(view, steer, enabled=enabled)
    driver, state, body, posted = rig(monkeypatch,
        runtime(replace(sw.DEFINITION, admit=admit, acknowledge=acknowledge)), synthetic=synthetic,
        replies=[acting('discarded'), acting('retained')])
    state.redirect_due, state.repeat_count, state.repeat_action = True, 3, 'refused action'
    method = '_drive_single_item' if synthetic else '_work'
    original = getattr(driver, method)
    def replace_return(*args, **kwargs):
        original(*args, **kwargs)
        return acting('other')
    monkeypatch.setattr(driver, method, replace_return)
    driver.drive(body, SESSION, None, _Rlog())
    assert steers and acknowledgements == []
    pending = steers[0]
    assert views[0].pending_steer is pending
    monkeypatch.setattr(driver, method, original)
    out = driver.drive(body, SESSION, None, _Rlog())
    assert out['choices'][0]['message']['tool_calls'][0]['id'] == 'retained'
    assert len(posted) == 2 and all(pending.text in json.dumps(p, ensure_ascii=False) for p in posted)
    assert acknowledgements == [pending] and views[0].last_delivered is pending
    assert views[0].pending_steer is None


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_view_assignments_alias_owner_and_durable_restore_resets_transients(monkeypatch, synthetic):
    views = []
    def observe(source, view, *, enabled=True):
        views.append(view)
        return sw.DEFINITION.execute(source, view, enabled=enabled)
    driver, state, body, posted = rig(monkeypatch, runtime(replace(sw.DEFINITION, execute=observe)), synthetic=synthetic,
                                    replies=[acting('first'), acting('restored')])
    driver.drive(body, SESSION, None, _Rlog())
    assert len(views) == 1
    view = views[0]
    writes, ids = ['real.py'], ['real-write']
    view.recent_writes, view.recent_write_ids = writes, ids
    view.action_seq, view.spin_due = 17, True
    view.steered_checks_text, view.same_checks_relooked = 'exact current checks', True
    assert state.recent_writes is writes and state.recent_write_ids is ids
    assert state.action_seq == 17 and state.spin_probe_due
    assert state.steered_checks_text == 'exact current checks' and state.same_checks_relooked
    restored = loop._session_from_dict(json.loads(json.dumps(loop._session_to_dict(state))))
    assert restored is not None and restored is not state
    driver._store.drop(SESSION)
    driver._store.put(SESSION, restored)
    driver.drive(body, SESSION, None, _Rlog())
    assert len(views) == 2 and len(posted) == 2
    fresh = views[-1]
    assert fresh.pending_probe is fresh.pending_steer is fresh.last_delivered is None
    assert fresh.action_seq == 1 and not fresh.spin_due
    assert fresh.recent_writes == [None] and fresh.recent_write_ids == ['restored']
    assert fresh.steered_checks_text == '' and not fresh.same_checks_relooked
    assert state.recent_writes is writes and state.action_seq == 17


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_distinct_sessions_do_not_share_windows_or_pending_identity(monkeypatch, synthetic):
    views = []
    def observe(source, view, *, enabled=True):
        views.append(view)
        return sw.DEFINITION.execute(source, view, enabled=enabled)
    driver, first, body, _ = rig(monkeypatch, runtime(replace(sw.DEFINITION, execute=observe)), synthetic=synthetic,
                                replies=[acting('one'), acting('two')])
    second = loop.PlanSession(plan=loop.Plan(id='second', task=first.plan.task, created='now',
        items=[loop.PlanItem(first.plan.task)]), synthetic=synthetic, plan_off=synthetic)
    driver._store.put('independent', second)
    driver.drive(body, SESSION, None, _Rlog())
    driver.drive(body, 'independent', None, _Rlog())
    assert len(views) == 2 and views[0].action_seq == views[1].action_seq == 1
    assert views[0].recent_writes is first.recent_writes and views[1].recent_writes is second.recent_writes
    assert views[0].recent_writes is not views[1].recent_writes
    views[0].repeat_count = 9
    assert first.repeat_count == 9 and second.repeat_count == 0
    assert views[1].pending_probe is views[1].pending_steer is views[1].last_delivered is None


@pytest.mark.parametrize('accepted', [False, True])
def test_public_periodic_progress_calls_same_selected_nested_author_and_vet(monkeypatch, accepted):
    seen = []
    def vet(owner, source):
        seen.append(('vet', source))
        return ga.CandidateResult(source.directive if accepted else None, '' if accepted else 'selected refusal')
    def author(owner, source, *, definition=None):
        seen.append(('author', source, definition))
        assert definition is actions
        result = definition.vet(owner, ga.CandidateInput('Inspect exact.py', 'exact checker bytes', source.log))
        return result.directive
    actions = replace(ga.DEFINITION, author=author, vet=vet)
    def progress(source, view, *, enabled=True, actions=None):
        seen.append(('progress', source, view, actions))
        return sw.progress(source, view, enabled=enabled, actions=actions)
    chosen = replace(sw.DEFINITION, actions=actions, progress_stage=progress)
    root = runtime(chosen)
    def resumed(source, state, *services):
        state.periodic_probe = state.awaiting_probe = False
        return repositorychecks.Result(repositorychecks.Status.OBSERVED, text='exact checker bytes',
                                       outcome=probegate.GateOutcome(ran=True))
    repo = replace(repositorychecks.DEFINITION, resume=resumed)
    root = replace(root, ordered_stages=tuple(repo if d.policy.id == repo.policy.id else d for d in root.ordered_stages))
    driver, state, body, posted = rig(monkeypatch, root)
    state.periodic_probe, state.gate_stall, state.last_gate_flag = True, 2, 'exact checker bytes'
    driver._ctx.reasoner_role = config.Role(name='reasoner', backend='local')
    driver._ctx.reasoner_chat = lambda *a, **k: (_ for _ in ()).throw(AssertionError('selected nested policy leaked inference'))
    driver.drive(body, SESSION, None, _Rlog())
    assert [entry[0] for entry in seen] == ['progress', 'author', 'vet']
    assert seen[0][3] is actions and seen[1][2] is actions
    assert seen[1][1].facts.original_task == state.plan.task
    assert seen[1][1].truth_text == 'exact checker bytes'
    assert len(posted) == 1
    text = 'Inspect exact.py' if accepted else 'exact checker bytes'
    assert text in json.dumps(posted[0], ensure_ascii=False)
    assert state.plan.status == 'in_progress' and not state.plan.items[0].done


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('returned', ['unknown', 'quiet', 'unrelated', 'mutated-launch'])
def test_public_returned_probe_requires_exact_ticket_and_matching_tool_result(monkeypatch, synthetic, returned):
    tickets, views, settled, acknowledgements = [], [], [], []
    probe = {'id': 'f44-owned', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"path":"checks.txt"}'}}
    def admit(source, view, *, enabled=True):
        views.append(view)
        if view.pending_steer is not None:
            return sw.Result(sw.Status.PENDING, steer=view.pending_steer)
        if view.pending_probe is None:
            view.pending_probe = sw.PendingProbe(sw.Trigger.WHEEL_SPIN, probe)
            tickets.append(view.pending_probe)
        return sw.Result(sw.Status.PENDING, sw.Trigger.WHEEL_SPIN, probe=view.pending_probe)
    def settle(source, view, *, enabled=True, actions=None):
        settled.append((source, view, actions))
        assert source.ticket is tickets[0]
        return sw.settle(source, view, enabled=enabled, actions=actions)
    def acknowledge(view, steer, *, enabled=True):
        acknowledgements.append(steer)
        return sw.acknowledge(view, steer, enabled=enabled)
    chosen = replace(sw.DEFINITION, admit=admit, settle_stage=settle, acknowledge=acknowledge)
    driver, state, body, posted = rig(monkeypatch, runtime(chosen), synthetic=synthetic)
    state.last_gate_ran = state.last_gate_red = True
    state.last_gate_flag, state.gate_stall = 'prior exact failure', 2
    if returned == 'mutated-launch':
        state.gate_plan = probegate.GatePlan(workspace='', candidates=[])
        method = '_drive_single_item' if synthetic else '_work'
        original = getattr(driver, method)
        def change_returned_id(*args, **kwargs):
            result = original(*args, **kwargs)
            calls = result['choices'][0]['message'].get('tool_calls') or []
            if calls and calls[0]['id'] == 'f44-owned':
                calls[0]['id'] = 'late-changed-launch'
            return result
        monkeypatch.setattr(driver, method, change_returned_id)
    out = driver.drive(body, SESSION, None, _Rlog())
    assert out['choices'][0]['message']['tool_calls'] == [probe] and posted == []
    assert len(tickets) == 1 and views[0].pending_probe is tickets[0]
    if returned == 'mutated-launch':
        assert state.probe_call_id == 'f44-owned' and tickets[0].call['id'] == 'late-changed-launch'
    body['messages'] += [out['choices'][0]['message'], {'role': 'tool',
        'tool_call_id': ('late-changed-launch' if returned == 'mutated-launch' else
                         'unrelated' if returned == 'unrelated' else 'f44-owned'),
        'content': ('___CRIA_GATE_probe-0___\nEXIT:1' if returned == 'mutated-launch' else
                    '' if returned == 'quiet' else 'unrecognized check output')}]
    driver.drive(body, SESSION, None, _Rlog())
    if returned in ('unrelated', 'mutated-launch'):
        assert settled == [] and acknowledgements == [] and views[0].pending_probe is tickets[0]
        # Required generic transport may record a neutral UNKNOWN independently;
        # F44 must not consume this unrelated result or erase the prior red facts.
        assert state.last_gate_red and state.gate_stall == 2
        if returned == 'mutated-launch':
            assert state.last_gate_ran and state.last_gate_flag == 'prior exact failure'
    else:
        assert len(settled) == 1 and settled[0][2] is chosen.actions
        assert views[0].pending_probe is None and len(acknowledgements) == 1
        assert not acknowledgements[0].grounded and not acknowledgements[0].authored
        assert state.last_gate_ran is False and state.last_gate_red
        assert state.gate_stall == 2 and state.last_gate_flag == 'prior exact failure'
        assert len(posted) == 1 and state.plan.status == 'in_progress'
        assert not state.plan.items[0].done


@pytest.mark.parametrize('synthetic', [False, True])
def test_pending_steer_does_not_suspend_required_forwarded_write_facts(monkeypatch, synthetic):
    views = []
    def admit(source, view, *, enabled=True):
        views.append(view)
        return sw.DEFINITION.admit(source, view, enabled=enabled)
    driver, state, body, _ = rig(monkeypatch, runtime(replace(sw.DEFINITION, admit=admit)), synthetic=synthetic,
        replies=[acting('new-write', 'write_file', {'path': 'a.py', 'content': 'new source\n'})])
    state.redirect_due, state.repeat_count, state.repeat_action = True, 3, 'refused action'
    state.write_call_ids = ['landed', 'failed']
    body['messages'] += [acting('landed', 'write_file', {'path': 'a.py', 'content': 'old\n'})['choices'][0]['message'],
        {'role': 'tool', 'tool_call_id': 'landed', 'content': 'Wrote a.py'},
        acting('failed', 'write_file', {'path': 'a.py', 'content': 'rejected\n'})['choices'][0]['message'],
        {'role': 'tool', 'tool_call_id': 'failed', 'content': '⟦ctx:denied⟧ not written'}]
    method = '_drive_single_item' if synthetic else '_work'
    original = getattr(driver, method)
    def discarded(*args, **kwargs):
        original(*args, **kwargs)
        return acting('different')
    monkeypatch.setattr(driver, method, discarded)
    driver.drive(body, SESSION, None, _Rlog())
    assert state.write_tracking and state.write_call_ids == ['landed', 'failed', 'new-write']
    assert state.write_result_ids == {'landed', 'failed'} and 'failed' in state.refused_write_ids
    assert views[0].pending_steer is not None and views[0].last_delivered is None
    assert views[0].recent_writes == [] and views[0].recent_write_ids == []


def test_actual_step_advance_calls_selected_reset_without_erasing_other_authority(monkeypatch):
    seen = []
    def reset(view, *, enabled=True):
        seen.append(view)
        return sw.DEFINITION.reset_step(view, enabled=enabled)
    driver, state, body, _ = rig(monkeypatch, runtime(replace(sw.DEFINITION, reset_step=reset)), synthetic=False)
    state.plan.items.append(loop.PlanItem('next requested step'))
    state.plan_off = False  # real STEP dispatch; missing reasoner keeps living-plan inference unavailable
    state.recent_writes, state.recent_write_ids = ['a.py'], ['write']
    state.spin_path, state.spin_probe_due, state.redirect_due = 'a.py', True, True
    state.steered_checks_text, state.same_checks_relooked = 'exact red findings', True
    state.last_gate_red, state.last_gate_flag = True, 'exact red findings'
    state.repeat_count, state.blocked_fired_seq = 4, 10
    monkeypatch.setattr(driver, '_persist_plan', lambda *a: None)
    work = driver._work
    advanced = []
    def verified_advance(*args, **kwargs):
        if not advanced:
            advanced.append(True)
            return driver._advance(state, SESSION, body, 1, 2, _Rlog())
        return work(*args, **kwargs)
    monkeypatch.setattr(driver, '_work', verified_advance)
    out = driver.drive(body, SESSION, None, _Rlog())
    assert advanced == [True] and out['choices'][0]['message']['tool_calls'][0]['id'] == 'next'
    assert len(seen) == 1
    view = seen[0]
    assert view.recent_writes == [None] and view.recent_write_ids == ['next']
    assert not view.spin_path and not view.spin_due and not view.redirect_due
    assert view.steered_checks_text == 'exact red findings' and view.same_checks_relooked
    assert view.repeat_count == 4 and view.blocked_fired_seq == 10
    assert state.last_gate_red and state.last_gate_flag == 'exact red findings'
    assert state.plan.items[0].done and not state.plan.items[1].done


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('latest_only', [False, True])
def test_public_partial_probe_transport_keeps_exact_ticket_until_complete_reading(monkeypatch, synthetic, latest_only):
    # Existing pure envelope fixtures only; no harness process or probe executes.
    from test_gate_outlives_the_harness_yield import _running_envelope, _page
    plan = probegate.GatePlan(workspace='', transport_required=True)
    probe = {'id': 'f44-transport', 'type': 'function', 'function': {'name': 'exec_command',
             'arguments': '{"cmd":"synthetic check, never executed"}'}}
    views, tickets, settlements, acknowledgements = [], [], [], []
    def admit(source, view, *, enabled=True):
        views.append(view)
        if view.pending_steer is not None:
            return sw.Result(sw.Status.PENDING, steer=view.pending_steer)
        if view.pending_probe is None:
            view.pending_probe = sw.PendingProbe(sw.Trigger.WHEEL_SPIN, probe)
            tickets.append(view.pending_probe)
        return sw.Result(sw.Status.PENDING, sw.Trigger.WHEEL_SPIN, probe=view.pending_probe)
    def settle(source, view, *, enabled=True, actions=None):
        settlements.append(source.ticket)
        assert plan.transport_complete and not plan.transport_error
        return sw.settle(source, view, enabled=enabled, actions=actions)
    def acknowledge(view, steer, *, enabled=True):
        acknowledgements.append(steer)
        return sw.acknowledge(view, steer, enabled=enabled)
    chosen = replace(sw.DEFINITION, admit=admit, settle_stage=settle, acknowledge=acknowledge)
    driver, state, body, posted = rig(monkeypatch, runtime(chosen), synthetic=synthetic)
    state.gate_plan = plan
    body['tools'].append({'type': 'function', 'function': {'name': 'exec_command', 'parameters': {
        'type': 'object', 'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}})
    launched = driver.drive(body, SESSION, None, _Rlog())
    assert launched['choices'][0]['message']['tool_calls'] == [probe]
    body['messages'] += [launched['choices'][0]['message'], {'role': 'tool',
        'tool_call_id': probe['id'], 'content': _running_envelope(plan)}]
    polling = driver.drive(body, SESSION, None, _Rlog())
    assert settlements == acknowledgements == posted == []
    assert views[0].pending_probe is tickets[0] and not plan.transport_complete
    poll = polling['choices'][0]['message']['tool_calls'][0]
    assert poll['id'] != probe['id']
    if latest_only:
        assert state.probe_call_id == poll['id']
        body['messages'] = [body['messages'][0]]
    body['messages'] += [polling['choices'][0]['message'], {'role': 'tool',
        'tool_call_id': poll['id'], 'content': _page(plan, '')}]
    driver.drive(body, SESSION, None, _Rlog())
    assert settlements == [tickets[0]] and settlements[0] is tickets[0]
    assert len(acknowledgements) == len(posted) == 1
    assert plan.transport_complete and not plan.transport_error
    assert views[0].pending_probe is None and views[0].last_delivered is acknowledgements[0]
    assert not state.last_gate_ran and not state.last_gate_red and not state.plan.items[0].done


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('settlement', ['noop', 'canonical'])
def test_public_matched_reading_is_required_before_selected_settlement_and_author_snapshot(monkeypatch, synthetic, settlement):
    from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
    candidate = ProbeCandidate(kind=ProbeKind.Lint, command=['pyflakes', 'x.py'], working_dir='',
        confidence=90, expected_value=80, cost=ProbeCost.Cheap, mutates_code=False,
        may_hang=False, may_need_services=False, reason='scripted returned check, never executed')
    plan = probegate.GatePlan(workspace='', surveyed_before=True, candidates=[candidate])
    probe = {'id': 'required-reading', 'type': 'function', 'function': {
        'name': 'read_file', 'arguments': '{"path":"checks.txt"}'}}
    views, tickets, before_stage = [], [], []
    def admit(source, view, *, enabled=True):
        views.append(view)
        if view.pending_steer is not None:
            return sw.Result(sw.Status.PENDING, steer=view.pending_steer)
        if view.pending_probe is None:
            view.pending_probe = sw.PendingProbe(sw.Trigger.WHEEL_SPIN, probe)
            tickets.append(view.pending_probe)
        return sw.Result(sw.Status.PENDING, sw.Trigger.WHEEL_SPIN, probe=view.pending_probe)
    def settle(source, view, *, enabled=True, actions=None):
        assert source.ticket is tickets[0] and source.author is not None
        before_stage.append((state.last_gate_ran, state.last_gate_red, state.gate_stall,
                             state.last_gate_flag, source.author.seat.facts.last_gate_flag,
                             source.author.seat.facts.gate_stall))
        if settlement == 'noop':
            return sw.Result(sw.Status.NO_OP)
        return sw.settle(source, view, enabled=enabled, actions=actions)
    chosen = replace(sw.DEFINITION, admit=admit, settle_stage=settle)
    driver, state, body, _ = rig(monkeypatch, runtime(chosen), synthetic=synthetic)
    state.gate_plan = plan
    driver._ctx.reasoner_role = config.Role(name='reasoner', backend='local')
    driver._ctx.reasoner_chat = lambda *a: json.dumps({'choices': [{'finish_reason': 'stop',
        'message': {'role': 'assistant', 'content': 'ON_TRACK'}}]}).encode()
    launch = driver.drive(body, SESSION, None, _Rlog())
    assert launch['choices'][0]['message']['tool_calls'] == [probe]
    body['messages'] += [launch['choices'][0]['message'], {'role': 'tool',
        'tool_call_id': probe['id'], 'content': '___CRIA_GATE_probe-0___\nx.py:1:1: undefined name \'missing\'\nEXIT:1'}]
    driver.drive(body, SESSION, None, _Rlog())
    assert len(before_stage) == 1
    ran, red, stall, findings, author_findings, author_stall = before_stage[0]
    assert ran is True and red is True and stall == 1
    assert "undefined name 'missing'" in findings and author_findings == findings and author_stall == 1
    assert state.last_gate_ran and state.last_gate_red and state.gate_stall == 1
    if settlement == 'noop':
        assert views[0].pending_probe is tickets[0]
    else:
        assert views[0].pending_probe is None


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('semantic', [False, True])
@pytest.mark.parametrize('failure', ['raise', 'malformed'])
def test_observation_failure_after_offered_steer_does_not_publish_delivery_or_lose_retry(monkeypatch, synthetic, semantic, failure):
    from cria import semanticquery
    views, steers, acknowledgements, observations, semantic_deliveries = [], [], [], [], []
    class RejectedObservation(Exception):
        pass
    def admit(source, view, *, enabled=True):
        views.append(view)
        result = sw.admit(source, view, enabled=enabled)
        if result.steer is not None:
            steers.append(result.steer)
        return result
    def acknowledge(view, steer, *, enabled=True):
        acknowledgements.append(steer)
        return sw.acknowledge(view, steer, enabled=enabled)
    def observe(source, view, *, enabled=True):
        observations.append((source, view))
        if len(observations) == 1:
            if failure == 'malformed':
                return {'status': 'not-a-typed-result'}
            raise RejectedObservation('failed observation after real coder reply')
        return sw.observe(source, view, enabled=enabled)
    chosen = replace(sw.DEFINITION, admit=admit, acknowledge=acknowledge, execute=observe)
    root = runtime(chosen)
    name, args = ('web_search', {'query': 'requested API documentation'}) if semantic else ('read_file', {'path': 'next.txt'})
    if semantic:
        def rehunt(source, state, *, enabled=True):
            return semanticquery.RehuntResult('requested API documentation', 'previous API documentation',
                                              True, True)
        def publish(result, coder, session, log):
            semantic_deliveries.append(coder)
            return semanticquery.REHUNT.settle(result, coder, session, log)
        rehunt_definition = replace(semanticquery.REHUNT, execute=rehunt, settle=publish)
        root = replace(root, ordered_stages=tuple(rehunt_definition if d.policy.id == rehunt_definition.policy.id else d
            for d in root.ordered_stages))
    driver, state, body, posted = rig(monkeypatch, root, synthetic=synthetic,
        replies=[acting('failed-return', name, args), acting('retry-compliance', name, args)])
    if semantic:
        body['tools'].append({'type': 'function', 'function': {'name': 'web_search', 'parameters': {
            'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}})
        driver._ctx.reasoner_role = config.Role(name='reasoner', backend='local')
        driver._ctx.reasoner_chat = lambda *a: (_ for _ in ()).throw(AssertionError('selected rehunt leaked inference'))
    state.redirect_due, state.repeat_count, state.repeat_action = True, 3, 'refused action'
    error, message = ((RejectedObservation, 'failed observation after real coder reply') if failure == 'raise'
                      else (TypeError, 'Stalled work replacement must return Result'))
    with pytest.raises(error, match=message):
        driver.drive(body, SESSION, None, _Rlog())
    assert len(observations) == len(posted) == 1 and steers[0].text in json.dumps(posted[0], ensure_ascii=False)
    if semantic:
        assert semantic_deliveries == [], 'semantic credit published before F44 observation validated'
    assert acknowledgements == [] and views[0].pending_steer is steers[0]
    assert views[0].last_delivered is None and state.action_seq == 0
    out = driver.drive(body, SESSION, None, _Rlog())
    assert out['choices'][0]['message']['tool_calls'][0]['id'] == 'retry-compliance'
    assert len(observations) == len(posted) == 2
    assert steers[-1] is steers[0] and all(steers[0].text in json.dumps(frame, ensure_ascii=False) for frame in posted)
    assert acknowledgements == [steers[0]] and views[0].last_delivered is steers[0]
    assert views[0].pending_steer is None and state.action_seq == 1
    assert views[0].recent_writes == [None] and views[0].recent_write_ids == ['retry-compliance']
    assert len(semantic_deliveries) == (1 if semantic else 0)


def test_public_canonical_progress_uses_real_author_vet_and_required_checker_facts(monkeypatch):
    def resumed(source, state, *services):
        state.periodic_probe = state.awaiting_probe = False
        return repositorychecks.Result(repositorychecks.Status.OBSERVED, text='compiler: exact failure',
                                       outcome=probegate.GateOutcome(ran=True))
    root = runtime()
    repo = replace(repositorychecks.DEFINITION, resume=resumed)
    root = replace(root, ordered_stages=tuple(repo if d.policy.id == repo.policy.id else d for d in root.ordered_stages))
    driver, state, body, posted = rig(monkeypatch, root)
    state.periodic_probe, state.gate_stall, state.last_gate_flag = True, 2, 'compiler: exact failure'
    questions = []
    replies = iter(['Inspect exact.py', 'SUPPORTED'])
    def reasoner(frame, log):
        questions.append((deepcopy(frame), log.phase))
        return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {
            'role': 'assistant', 'content': next(replies)}}]}).encode()
    driver._ctx.reasoner_chat = reasoner
    driver._ctx.reasoner_role = config.Role(name='reasoner', backend='local')
    driver.drive(body, SESSION, None, _Rlog())
    assert len(questions) == 2 and [phase for _, phase in questions] == ['reasoner', 'steer-code']
    assert state.plan.task in json.dumps(questions[0][0], ensure_ascii=False)
    assert 'compiler: exact failure' in json.dumps(questions[0][0], ensure_ascii=False)
    assert 'compiler: exact failure' in json.dumps(questions[1][0], ensure_ascii=False)
    assert questions[1][0]['temperature'] == 0.0
    assert len(posted) == 1 and 'Inspect exact.py' in json.dumps(posted[0], ensure_ascii=False)
    assert not state.plan.items[0].done and state.last_gate_flag == 'compiler: exact failure'


@pytest.mark.parametrize('synthetic', [False, True])
def test_actual_provider_interruption_does_not_ack_pending_steer(monkeypatch, synthetic):
    views, steers, acknowledgements = [], [], []
    class InterruptedProvider(Exception):
        pass
    def admit(source, view, *, enabled=True):
        views.append(view)
        result = sw.DEFINITION.admit(source, view, enabled=enabled)
        if result.steer is not None:
            steers.append(result.steer)
        return result
    def acknowledge(view, steer, *, enabled=True):
        acknowledgements.append(steer)
        return sw.acknowledge(view, steer, enabled=enabled)
    driver, state, body, posted = rig(monkeypatch,
        runtime(replace(sw.DEFINITION, admit=admit, acknowledge=acknowledge)), synthetic=synthetic,
        replies=[InterruptedProvider('no coder reply')])
    state.redirect_due, state.repeat_count, state.repeat_action = True, 3, 'refused action'
    with pytest.raises(InterruptedProvider, match='no coder reply'):
        driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == len(steers) == 1 and acknowledgements == []
    assert views[0].pending_steer is steers[0] and views[0].last_delivered is None
