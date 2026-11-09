"""First-turn inventory traverses the real harness round trip before the coder."""
import json
import subprocess

from cria.classify import Classification
from cria.config import Role
from cria import initial_inventory, loop
from cria.plan import Plan, PlanItem
from loop_main_helpers import Chat, Rlog, acting, body, completion, loop_main_local_view, plan_off_loop  # noqa: F401


def drive_until_coder(driver, coder, request, root, followup=None):
    history = list(request['messages'])
    classification = Classification('task', 'coding', 'fixture')
    for _ in range(100):
        result = driver.drive({**request, 'messages': history}, 'sid:inventory', classification, Rlog())
        if coder.bodies:
            return coder.bodies[0]
        msg = result['choices'][0]['message']
        call = msg['tool_calls'][0]
        command = json.loads(call['function']['arguments'])['command']
        raw = subprocess.run(command if isinstance(command, list) else ['sh', '-c', command],
                             cwd=root, capture_output=True, text=True, check=True).stdout
        history.extend([msg, {'role': 'tool', 'tool_call_id': call['id'], 'content': raw}])
        if followup is not None:
            history.append({'role': 'user', 'content': followup})
            followup = None
    raise AssertionError('coder was not reached')


def test_unsafe_scratch_fails_open_to_coder_without_workspace_writes(tmp_path, monkeypatch):
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True)
    framed = drive_until_coder(driver, coder, body('Implement the feature'), tmp_path)
    assert 'Implement the feature' in json.dumps(framed['messages'])
    assert not list(tmp_path.iterdir())


def test_first_coder_turn_receives_harness_inventory(tmp_path):
    (tmp_path / 'seed.py').write_text('def ready():\n    pass\n')
    (tmp_path / 'seed.go').write_text('package seed\nfunc ReadyGo() {}\n')
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True)
    request = body('Implement the feature')
    framed = drive_until_coder(driver, coder, request, tmp_path)
    texts = [str(message.get('content') or '') for message in framed['messages']]
    assert 'Implement the feature' in texts
    assert any('seed.py' in text and 'seed.go' in text for text in texts)
    if not any('Symbol indexer unavailable' in text for text in texts):
        assert any('ready' in text and 'ReadyGo' in text for text in texts)


def test_large_first_inventory_asks_configured_reasoner_without_workspace_artifact(tmp_path):
    for i in range(350):
        (tmp_path / f'file-{i:04}.py').write_text(f'def item_{i}():\n    pass\n')
    def reply(decision):
        result = completion(None, ('verdict', {'decision': decision}))
        result['choices'][0]['finish_reason'] = 'tool_calls'
        return result
    reasoner = Chat(reply('RELEVANT'), *[reply('UNRELATED') for _ in range(349)])
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True, reasoner=reasoner,
                           reasoner_role=Role(name='reasoner', backend='local'))
    framed = drive_until_coder(driver, coder, body('Implement item zero'), tmp_path, followup='Additional instruction')
    listing = next(str(m.get('content')) for m in framed['messages'] if 'Initial harness workspace inventory' in str(m.get('content')))
    assert len(reasoner.bodies) == 350
    first = reasoner.bodies[0]
    assert first['messages'] == [{'role': 'user', 'content': (
        'Classify whether the candidate existing file is relevant to performing the coding task. Consider only the task and the candidate information provided. RELEVANT means it is useful for implementing or verifying the requested work; UNRELATED means it is not.\n\n'
        'task: Implement item zero\ncandidate: file-0000.py | ' +
        ('symbols available | item_0' if 'item_0' in first['messages'][0]['content'] else 'symbols unavailable') +
        '\n\nRecord your judgment with the verdict tool.')}]
    assert first['tool_choice'] == 'required' and first['stream'] is False
    assert first['tools'] == [{'type': 'function', 'function': {'name': 'verdict', 'description': 'Record the candidate file relevance decision.', 'parameters': {'type': 'object', 'properties': {'decision': {'type': 'string', 'enum': ['RELEVANT', 'UNRELATED']}}, 'required': ['decision'], 'additionalProperties': False}}}]
    assert 'selected by the configured reasoner' in listing and 'file-0000.py' in listing
    assert 'file-0349.py' not in listing
    assert 'current inventory' in listing and 'snapshot is not retained' in listing
    assert not (tmp_path / 'tmp').exists()
    command = listing[listing.index('python3 -I -c '):].strip()
    result = subprocess.run(['sh', '-c', command + ' 0'], cwd=tmp_path,
                            capture_output=True, text=True, check=True)
    assert result.stdout.startswith('current-inventory 0 ') and len(result.stdout) < 2048


def test_inventory_abstains_when_coder_has_no_room(tmp_path, monkeypatch):
    for i in range(60):
        (tmp_path / f'file-{i:04}.py').write_text('def example(): pass\n')
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True)
    monkeypatch.setattr(driver, '_coder_sizing', lambda *args: (2000, 100, 1.0))
    framed = drive_until_coder(driver, coder, body('Implement the feature'), tmp_path)
    text = json.dumps(framed['messages'])
    assert 'Implement the feature' in text
    assert 'omitted to fit' in text
    assert 'Initial harness workspace inventory' not in text


def test_user_followup_after_survey_remains_after_the_inventory(tmp_path):
    (tmp_path / 'seed.py').write_text('def seeded(): pass\n')
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True)
    request = body('Original task')
    classification = Classification('task', 'coding', 'fixture')
    first = driver.drive(request, 'sid:inventory', classification, Rlog())
    message = first['choices'][0]['message']
    call = message['tool_calls'][0]
    command = json.loads(call['function']['arguments'])['command']
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=True)
    history = request['messages'] + [message,
        {'role': 'tool', 'tool_call_id': call['id'], 'content': result.stdout},
        {'role': 'user', 'content': 'The later instruction.'}]
    driver.drive({**request, 'messages': history}, 'sid:inventory', classification, Rlog())
    framed = coder.bodies[0]['messages']
    listing = next(i for i, m in enumerate(framed) if 'Initial harness workspace inventory' in str(m.get('content')))
    later = next(i for i, m in enumerate(framed) if m.get('content') == 'The later instruction.')
    assert listing < later
    assert any(m.get('content') == 'Original task' for m in framed)


def test_unavailable_survey_construction_continues_to_coder(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('unavailable')
    monkeypatch.setattr(initial_inventory, 'plan', unavailable)
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True)
    driver.drive(body('Implement the task'), 'sid:inventory', Classification('task', 'coding', 'fixture'), Rlog())
    assert coder.bodies and 'Implement the task' in json.dumps(coder.bodies[0]['messages'])


def test_refused_survey_keeps_user_messages_and_does_not_claim_checks_ran(tmp_path):
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True)
    request = body('Implement the original task')
    classification = Classification('task', 'coding', 'fixture')
    first = driver.drive(request, 'sid:inventory', classification, Rlog())
    call_message = first['choices'][0]['message']
    call_id = call_message['tool_calls'][0]['id']
    messages = request['messages'] + [call_message,
        {'role': 'tool', 'tool_call_id': call_id, 'content': 'Permission denied'},
        {'role': 'user', 'content': 'Also preserve this instruction.'}]
    driver.drive({**request, 'messages': messages}, 'sid:inventory', classification, Rlog())
    text = json.dumps(coder.bodies[0]['messages'])
    assert 'Implement the original task' in text and 'Also preserve this instruction.' in text
    assert 'Permission denied' not in text and '___CTX_GATE_' not in text
    assert '⟦ctx:checks⟧' not in text


def test_inventory_provenance_is_scoped_to_its_session():
    store = loop.LoopStore()
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'call_owned'}]}]
    store.remember_initial_calls('sid:first', {'call_owned': 'identity'})
    assert store.initial_calls_in('sid:first', messages) == {'call_owned': 'identity'}
    assert store.initial_calls_in('sid:other', messages) == {}


def test_pending_inventory_and_owned_ids_survive_session_reconstruction():
    session = loop.PlanSession(plan=Plan(id='p', task='task', created='now', items=[PlanItem('task')]),
                               initial_listing='survey evidence', initial_private_ids=('call_1',),
                               initial_private_calls={'call_1': 'identity'})
    restored = loop._session_from_dict(loop._session_to_dict(session))
    assert restored.initial_listing == 'survey evidence'
    assert restored.initial_private_ids == ('call_1',)
    assert restored.initial_private_calls == {'call_1': 'identity'}


def test_unstable_session_does_not_represent_refused_private_survey_as_a_coder_tool(tmp_path):
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True)
    request = body('Implement the original task')
    classification = Classification('task', 'coding', 'fixture')
    first = driver.drive(request, 'task:inventory', classification, Rlog())
    private = first['choices'][0]['message']
    history = request['messages'] + [private,
        {'role': 'tool', 'tool_call_id': private['tool_calls'][0]['id'], 'content': 'Permission denied'}]
    second = driver.drive({**request, 'messages': history}, 'task:inventory', classification, Rlog())
    action = second['choices'][0]['message']
    history += [action, {'role': 'tool', 'tool_call_id': action['tool_calls'][0]['id'], 'content': 'real result'}]
    driver.drive({**request, 'messages': history}, 'task:inventory', classification, Rlog())
    assert len(coder.bodies) == 2
    assert 'Permission denied' not in json.dumps(coder.bodies[1]['messages'])
    assert 'real result' in json.dumps(coder.bodies[1]['messages'])
