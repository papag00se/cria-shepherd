"""Public completed-work delivery: memory follows release, never authorizes it."""
import copy
import json
from dataclasses import replace

import pytest

from cria import assistruntime, completedwork as cw, loop, planner, probegate, probediscovery, livingplan, stepreview
from cria.config import Role
from cria.plan import Plan, PlanItem
from test_completed_work_briefing import Log, completion


def finished_driver(runtime):
    calls = []
    def summary(body, log):
        calls.append(copy.deepcopy(body))
        return json.dumps(completion('Built cli.py; the recorded checker passed.')).encode()
    def coder(body, log):
        raise AssertionError('An already settled completed plan must not redrive the coder')
    context = loop.LoopContext(planner=None, planner_enabled=True, pilot_runtime=runtime,
        coder_chat=coder, reasoner_chat=summary, reasoner_role=None,
        compactor_role=Role(name='compactor', backend='local', reasoning='off'),
        runs_dir='', self_compact=False, focus_trim=False, assists=False)
    plan = Plan(id='finished-public', task='Build the CLI.', created='now',
        items=[PlanItem('Build CLI', True)], status='in_progress')
    session = loop.PlanSession(plan=plan, gate_fresh=True, last_gate_ran=True)
    store = loop.LoopStore()
    store.put('sid:completed-public', session)
    body = {'messages': [{'role': 'user', 'content': plan.task}], 'tools': [
        {'type': 'function', 'function': {'name': 'write_file', 'parameters': {
            'type': 'object', 'properties': {'path': {'type': 'string'},
                'content': {'type': 'string'}}, 'required': ['path', 'content']}}},
        {'type': 'function', 'function': {'name': 'exec_command', 'parameters': {
            'type': 'object', 'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}}]}
    return loop.Loop(context, store), session, body, calls


@pytest.mark.parametrize('consent', [False, True], ids=['consent-off', 'id-absent'])
def test_public_completion_without_selected_briefing_does_not_generate_or_embed(consent):
    # Explicit initial-planning consent is not consent to a missing briefing ID.
    registrations = tuple(d for d in assistruntime.DEFINITIONS
                          if d.policy.id != cw.DEFINITION.policy.id)
    runtime = assistruntime.AssistRuntime.select(
        registrations=registrations, experimental_planning=consent)
    driver, session, body, calls = finished_driver(runtime)
    result = driver.drive(body, 'sid:completed-public', None, Log())
    text = result['choices'][0]['message']['content']
    assert calls == []
    assert cw.BRIEFING_OPEN not in text and cw.BRIEFING_CLOSE not in text
    assert 'plan complete' in text
    assert session.phase is loop.Phase.DONE and session.plan.status == 'done'
    assert driver._store.get('sid:completed-public') is None


def selected_runtime(definition=cw.DEFINITION, *, disabled=(), consent=True):
    registrations = tuple(definition if d.policy.id == definition.policy.id else d
                          for d in assistruntime.DEFINITIONS)
    return assistruntime.AssistRuntime.select(registrations=registrations,
        disabled=disabled, experimental_planning=consent)


def test_public_completion_executes_and_embeds_the_exact_selected_lifecycle():
    seen, generated = [], []
    def generate(source):
        seen.append(('generate', source))
        assert source.release_authorized is True and source.planner_enabled is True
        assert not source.synthetic
        result = cw.generate(source)
        generated.append(result)
        return result
    def embed(base, source, result):
        seen.append(('embed', source))
        assert result is generated[0]
        return cw.embed(base, source, result)
    definition = replace(cw.DEFINITION, execute=generate, embed=embed)
    runtime = selected_runtime(definition)
    driver, session, body, calls = finished_driver(runtime)
    result = driver.drive(body, 'sid:completed-public', None, Log())
    assert [kind for kind, source in seen] == ['generate', 'embed']
    assert seen[0][1].messages == body['messages']
    assert len(calls) == 1 and calls[0]['messages'][0]['content'].startswith(
        'You are writing a handoff summary, not doing the work.')
    assert result['choices'][0]['message']['content'] == (
        '⟦cria⟧ plan complete — all 1 steps verified.\n\n⟦ctx:briefing⟧\n'
        'Built cli.py; the recorded checker passed.\n⟦/ctx:briefing⟧')
    assert session.phase is loop.Phase.DONE and session.plan.status == 'done'
    assert driver._store.get('sid:completed-public') is None


@pytest.mark.parametrize('exit', ['scheduled-no-shell', 'held-probe'])
def test_public_alternate_release_runs_selected_generation_and_embedding(exit):
    from test_executable_assist_pilots import _candidate
    seen, generated = [], []
    def generate(source):
        seen.append(('generate', source))
        assert source.release_authorized is True and source.planner_enabled is True
        result = cw.generate(source)
        generated.append(result)
        return result
    def embed(base, source, result):
        seen.append(('embed', source))
        assert result is generated[0]
        return cw.embed(base, source, result)
    definition = replace(cw.DEFINITION, execute=generate, embed=embed)
    # A live planned task does not need another initial plan. This also lets the
    # scheduled no-shell release reach its real native-write-only driver route.
    runtime = selected_runtime(definition, disabled=tuple(d.policy.id for d in planner.DEFINITIONS)
        + (livingplan.DEFINITION.policy.id, stepreview.DEFINITION.policy.id))
    runtime = replace(runtime, task_review=replace(runtime.task_review,
        execute=lambda source, state: loop.ReviewResult(loop.ReviewStatus.APPROVED, 'Requested work is complete.')))
    driver, session, body, calls = finished_driver(runtime)
    session.plan.items[0].done = False
    if exit == 'scheduled-no-shell':
        body['tools'] = [body['tools'][0]]
        driver._ctx.assists = True
        driver._ctx.satisfaction_check_start = 1
        driver._ctx.satisfaction_check_every = 1
    else:
        session.done_probe = True
        session.pending_done_parts = ('Requested work is complete.',)
        session.probe_call_id = 'release-check'
        candidate = _candidate(probediscovery.ProbeKind.Test, ['pytest', '-q'])
        session.gate_plan = probegate.GatePlan(workspace='/offline', candidates=[candidate])
        body['messages'] += [
            {'role': 'assistant', 'tool_calls': [{'id': 'release-check', 'type': 'function',
                'function': {'name': 'exec_command', 'arguments': '{"cmd":"pytest -q"}'}}]},
            {'role': 'tool', 'tool_call_id': 'release-check', 'content':
                f'{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n2 passed\nEXIT:0\n'}]
    result = driver.drive(body, 'sid:completed-public', None, Log())
    assert [kind for kind, source in seen] == ['generate', 'embed']
    assert len(calls) == 1
    text = result['choices'][0]['message']['content']
    assert cw.read_history([{'role': 'assistant', 'content': text}]).text == (
        'Built cli.py; the recorded checker passed.')
    if exit == 'held-probe':
        assert session.last_gate_ran and not session.last_gate_red
    assert not result['choices'][0]['message'].get('tool_calls')


@pytest.mark.parametrize('blocker', ['task-rejected', 'checker-red'])
def test_public_nonrelease_never_asks_a_briefing_to_authorize_completion(blocker):
    from test_executable_assist_pilots import _candidate
    def poison(*args):
        raise AssertionError('Briefing ran before actual task release')
    runtime = selected_runtime(replace(cw.DEFINITION, execute=poison, embed=poison),
        disabled=tuple(d.policy.id for d in planner.DEFINITIONS)
        + (livingplan.DEFINITION.policy.id, stepreview.DEFINITION.policy.id))
    runtime = replace(runtime, task_review=replace(runtime.task_review,
        execute=lambda source, state: loop.ReviewResult(loop.ReviewStatus.REJECTED)))
    driver, session, body, calls = finished_driver(runtime)
    session.plan.items[0].done = False
    driver._ctx.coder_chat = lambda body, log: json.dumps({'choices': [{'message': {
        'role': 'assistant', 'tool_calls': [{'id': 'keep-working', 'type': 'function',
            'function': {'name': 'exec_command', 'arguments': '{"cmd":"pwd"}'}}]},
        'finish_reason': 'tool_calls'}]}).encode()
    if blocker == 'task-rejected':
        driver._ctx.assists = True
        driver._ctx.satisfaction_check_start = 1
        driver._ctx.satisfaction_check_every = 1
    else:
        session.done_probe = True
        session.pending_done_parts = ('Claimed complete.',)
        session.probe_call_id = 'release-check'
        session.gate_plan = probegate.GatePlan(workspace='/offline', candidates=[
            _candidate(probediscovery.ProbeKind.Test, ['pytest', '-q'])])
        body['messages'] += [
            {'role': 'assistant', 'tool_calls': [{'id': 'release-check', 'type': 'function',
                'function': {'name': 'exec_command', 'arguments': '{"cmd":"pytest -q"}'}}]},
            {'role': 'tool', 'tool_call_id': 'release-check', 'content':
                f'{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\ncli.py:4: AssertionError\nEXIT:1\n'}]
    result = driver.drive(body, 'sid:completed-public', None, Log())
    assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'keep-working'
    assert not calls and cw.BRIEFING_OPEN not in json.dumps(result, ensure_ascii=False)
    assert driver._store.get('sid:completed-public') is session
    assert session.phase is not loop.Phase.DONE and not session.plan.items[0].done
    if blocker == 'checker-red':
        assert session.last_gate_red and not session.gate_fresh


def test_selected_projection_is_lazy_and_never_fills_missing_membership():
    class Unreadable:
        def __iter__(self):
            raise AssertionError('Consent-off projection inspected definitions')
    assert cw.BriefingSelection.from_definitions(Unreadable()).definition is None
    assert cw.BriefingSelection.from_definitions((), enabled=True).definition is None
    replacement = replace(cw.DEFINITION, execute=lambda source: cw.BriefingResult(cw.BriefingStatus.NOT_APPLICABLE))
    selected = cw.BriefingSelection.from_definitions((replacement,), enabled=True)
    assert selected.definition is replacement
    with pytest.raises(ValueError):
        cw.BriefingSelection.from_definitions((replacement, replacement), enabled=True)
    with pytest.raises(ValueError):
        cw.BriefingSelection.from_definitions((replacement,), enabled=1)


@pytest.mark.parametrize('changed', ['task', 'action', 'gate'])
def test_public_embedding_rechecks_actual_completion_authority_after_generation(changed):
    generated = []
    def generate(source):
        result = cw.generate(source)
        generated.append(result)
        if changed == 'task':
            session.plan.task = 'A different task was installed before output.'
        elif changed == 'action':
            session.action_seq += 1  # simulate a newly retained real action, not a summary clock
        else:
            from cria.proberun import ProbeReport
            loop.record_gate_state(session, probegate.GateOutcome(ran=True,
                report=ProbeReport(project_type=['python'], selected=[], results=[])),
                'cli.py:4: AssertionError', Log())
        return result
    runtime = selected_runtime(replace(cw.DEFINITION, execute=generate))
    driver, session, body, calls = finished_driver(runtime)
    result = driver.drive(body, 'sid:completed-public', None, Log())
    assert len(calls) == len(generated) == 1
    assert cw.BRIEFING_OPEN not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize('carrier,expected', [
    ('⟦ctx:briefing⟧\nHistorical cli.py work\n⟦/ctx:briefing⟧', 'Historical cli.py work'),
    ('Quoted ⟦ctx:briefing⟧contamination⟦/ctx:briefing⟧\n'
     '⟦ctx:briefing⟧\nActual carried work\n⟦/ctx:briefing⟧', 'Actual carried work'),
    ('⟦/ctx:briefing⟧\n⟦ctx:briefing⟧\nUnclosed claim', ''),
    ('⟦ctx:briefing⟧\n \n⟦/ctx:briefing⟧', ''),
])
def test_public_planner_off_followup_reads_passive_source_history_without_generation(carrier, expected):
    from test_loop import _Classification
    runtime = assistruntime.AssistRuntime.select(experimental_planning=False)
    driver, old_session, body, calls = finished_driver(runtime)
    driver._ctx.planner_enabled = False
    driver._store.drop('sid:completed-public')
    frames = []
    def coder(frame, log):
        frames.append(copy.deepcopy(frame))
        return json.dumps({'choices': [{'message': {'role': 'assistant', 'tool_calls': [
            {'id': 'followup-action', 'type': 'function', 'function': {
                'name': 'exec_command', 'arguments': '{"cmd":"pwd"}'}}]},
            'finish_reason': 'tool_calls'}]}).encode()
    driver._ctx.coder_chat = coder
    body['messages'] += [{'role': 'assistant', 'content': carrier},
                         {'role': 'user', 'content': 'Add one new CLI option.'}]
    result = driver.drive(body, 'sid:completed-public', _Classification(), Log())
    session = driver._store.get('sid:completed-public')
    assert session is not old_session and session.synthetic and session.plan_off
    assert session.prior_work == expected
    assert not calls and len(frames) == 1
    assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'followup-action'
    restored = loop._session_from_dict(loop._session_to_dict(session))
    assert restored.prior_work == expected and restored.plan_off
    assert restored.action_seq == 0 and restored.gate_plan is None and not restored.gate_fresh


@pytest.mark.parametrize('resume', ['same-owner', 'restart', 'fork'])
def test_public_interrupted_generation_keeps_owner_and_does_not_reuse_abandoned_text(tmp_path, resume):
    from test_gate_outlives_the_harness_yield import _page
    from wsfixture import survey
    generated, embedded = [], []
    def generate(source):
        result = cw.generate(source)
        generated.append(result)
        if len(generated) == 1:
            raise RuntimeError('Interrupted before selected output could be embedded')
        return result
    def embed(base, source, result):
        embedded.append(result)
        assert result is generated[-1] and result is not generated[0]
        return cw.embed(base, source, result)
    runtime = selected_runtime(replace(cw.DEFINITION, execute=generate, embed=embed))
    driver, session, body, calls = finished_driver(runtime)
    state_path = tmp_path / 'completed-work-state.json'
    driver._store._state_path = state_path
    driver._store.persist('sid:completed-public')
    with pytest.raises(RuntimeError, match='Interrupted before selected output'):
        driver.drive(body, 'sid:completed-public', None, Log())
    assert driver._store.get('sid:completed-public') is session and not embedded
    restored = loop._session_from_dict(loop._session_to_dict(session))
    assert restored is not session and restored.action_seq == 0 and restored.gate_plan is None
    key = 'sid:completed-public'
    if resume == 'restart':
        driver = loop.Loop(driver._ctx, loop.LoopStore(str(state_path)))
        assert driver._store.get(key) is not session
    elif resume == 'fork':
        key = 'sid:completed-fork'
        fork_store = loop.LoopStore()
        fork_store.put(key, restored)
        driver = loop.Loop(driver._ctx, fork_store)
    result = driver.drive(body, key, None, Log())
    if resume != 'same-owner':
        # Reconstructed owners lost their transient gate authority. Answer the
        # actual required probe, never restore freshness or invent a passed test.
        owner = driver._store.get(key)
        assert owner is not session and not owner.gate_fresh
        answered = set()
        while result['choices'][0]['message'].get('tool_calls'):
            assert len(calls) == len(generated) == 1 and not embedded
            message = result['choices'][0]['message']
            assert len(message['tool_calls']) == 1
            issued = message['tool_calls'][0]
            assert issued['id'] == owner.completion_probe_id == owner.probe_call_id
            assert issued['id'] not in answered
            answered.add(issued['id'])
            plan = owner.gate_plan
            assert plan.transport_required and not plan.candidates
            assert plan.transport_id in issued['function']['arguments']
            # This fixture has no known workspace/check command: the real plan
            # is git-only. Its checked response is an attempted, zero-check gate.
            raw = f'{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}\n'
            if not plan.surveyed_before:
                raw += survey()
            body['messages'] += [message, {'role': 'tool', 'tool_call_id': issued['id'],
                                          'content': _page(plan, raw)}]
            result = driver.drive(body, key, None, Log())
            assert plan.transport_complete and not plan.transport_error
        assert answered and not owner.last_gate_ran and not owner.gate_plan.candidates
    assert len(calls) == len(generated) == 2 and embedded == [generated[1]]
    assert cw.read_history([result['choices'][0]['message']]).text == 'Built cli.py; the recorded checker passed.'
    assert driver._store.get(key) is None


def test_public_embedding_interruption_keeps_finishing_owner_and_retry_generates_new_memory():
    generated, embedded = [], []
    def generate(source):
        result = cw.generate(source)
        generated.append(result)
        return result
    def embed(base, source, result):
        embedded.append(result)
        assert result is generated[-1]
        if len(embedded) == 1:
            raise RuntimeError('Selected embedding interrupted before final output')
        assert result is not generated[0]
        return cw.embed(base, source, result)
    runtime = selected_runtime(replace(cw.DEFINITION, execute=generate, embed=embed))
    driver, session, body, calls = finished_driver(runtime)
    def summary(request, log):
        calls.append(copy.deepcopy(request))
        text = 'Abandoned first memory.' if len(calls) == 1 else 'New retry memory.'
        return json.dumps(completion(text)).encode()
    driver._ctx.reasoner_chat = summary
    with pytest.raises(RuntimeError, match='Selected embedding interrupted'):
        driver.drive(body, 'sid:completed-public', None, Log())
    assert driver._store.get('sid:completed-public') is session
    assert len(calls) == len(generated) == len(embedded) == 1
    result = driver.drive(body, 'sid:completed-public', None, Log())
    assert len(calls) == len(generated) == len(embedded) == 2
    assert embedded[1] is generated[1] and generated[1] is not generated[0]
    text = result['choices'][0]['message']['content']
    assert cw.read_history([{'role': 'assistant', 'content': text}]).text == 'New retry memory.'
    assert 'Abandoned first memory.' not in text
    assert driver._store.get('sid:completed-public') is None


def test_public_held_embedding_interruption_preserves_original_claim_for_checked_replay():
    from test_executable_assist_pilots import _candidate
    from test_gate_outlives_the_harness_yield import _page
    generated, embedded = [], []
    def generate(source):
        result = cw.generate(source)
        generated.append(result)
        return result
    def embed(base, source, result):
        embedded.append(result)
        assert result is generated[-1]
        if len(embedded) == 1:
            raise RuntimeError('Held task embedding interrupted before final output')
        assert result is not generated[0]
        return cw.embed(base, source, result)
    runtime = selected_runtime(replace(cw.DEFINITION, execute=generate, embed=embed))
    driver, session, body, calls = finished_driver(runtime)
    session.plan.items[0].done = False  # whole-task release is not step approval
    session.done_probe = True
    original_parts = ('The requested CLI work is complete.',)
    original_held = 'The original held task claim.'
    session.pending_done_parts, session.pending_done = original_parts, original_held
    session.probe_call_id = 'held-release-check'
    candidate = _candidate(probediscovery.ProbeKind.Test, ['pytest', '-q'])
    plan = session.gate_plan = probegate.GatePlan(workspace='/offline', candidates=[candidate],
        transport_required=True, script=probegate._gate_sentinel(['pytest -q']))
    body['messages'] += [
        {'role': 'assistant', 'tool_calls': [{'id': 'held-release-check', 'type': 'function',
            'function': {'name': 'exec_command', 'arguments': json.dumps({'cmd': plan.script})}}]},
        {'role': 'tool', 'tool_call_id': 'held-release-check', 'content': _page(plan,
            f'{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n2 passed\nEXIT:0\n')}]
    def summary(request, log):
        calls.append(copy.deepcopy(request))
        return json.dumps(completion('Abandoned held memory.' if len(calls) == 1 else 'Fresh held replay memory.')).encode()
    driver._ctx.reasoner_chat = summary
    with pytest.raises(RuntimeError, match='Held task embedding interrupted'):
        driver.drive(body, 'sid:completed-public', None, Log())
    assert driver._store.get('sid:completed-public') is session
    assert session.done_probe and session.pending_done_parts is original_parts
    assert session.pending_done == original_held
    assert session.probe_call_id == 'held-release-check' and session.gate_plan is plan
    assert plan.transport_complete and not plan.transport_error
    assert session.last_gate_ran and not session.last_gate_red
    assert len(calls) == len(generated) == len(embedded) == 1
    # Replay the same genuine checked result through the actual held-claim path;
    # no new approval, raw freshness flag, task claim or briefing token is seeded.
    result = driver.drive(body, 'sid:completed-public', None, Log())
    assert len(calls) == len(generated) == len(embedded) == 2
    assert embedded[1] is generated[1] and generated[1] is not generated[0]
    text = result['choices'][0]['message']['content']
    assert cw.read_history([{'role': 'assistant', 'content': text}]).text == 'Fresh held replay memory.'
    assert 'Abandoned held memory.' not in text
    assert not session.plan.items[0].done
    assert driver._store.get('sid:completed-public') is None
