"""First-turn inventory traverses the real harness round trip before the coder."""
import json
import os

from cria.classify import Classification
from cria.config import Role
from cria import loop
from cria.plan import Plan, PlanItem
from loop_main_helpers import (Chat, Rlog, acting, body, completion, drive_with_ops, run_call, loop_main_local_view, loop_main_private_home,  # noqa: F401
                               plan_off_loop)


def drive_until_coder(driver, coder, request, root, followup=None):
    """The server's part: cria's inventory operation is answered by the engine through the harness until the loop reaches the coder."""
    classification = Classification('task', 'coding', 'fixture')
    history = list(request['messages'])
    if followup:      # the user types again while cria's inventory is in flight: the task the judgments are asked about is the one it began with
        first = driver.drive(request, 'sid:inventory', classification, Rlog())['choices'][0]['message']
        history += [first] + [{'role': 'tool', 'tool_call_id': c['id'], 'content': run_call(c, root)} for c in first['tool_calls']]
        history.append({'role': 'user', 'content': followup})
    drive_with_ops(driver, request, history, 'sid:inventory', classification, Rlog(), cwd=root)
    assert coder.bodies, 'coder was not reached'
    return coder.bodies[0]


def test_the_inventory_writes_nothing_in_the_workspace_even_when_the_harness_scratch_is_inside_it(tmp_path, monkeypatch):
    (tmp_path / 'seed.py').write_text('def ready():\n    pass\n')
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    before = sorted(os.listdir(tmp_path))
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True)
    framed = drive_until_coder(driver, coder, body('Implement the feature'), tmp_path)
    assert 'Implement the feature' in json.dumps(framed['messages']) and 'seed.py' in json.dumps(framed['messages'])
    assert sorted(os.listdir(tmp_path)) == before


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
    assert 'snapshot is not retained' in listing and 'listing and search tools' in listing and 'python3' not in listing
    assert not (tmp_path / 'tmp').exists()


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
    drive_with_ops(driver, request, request['messages'] + [{'role': 'user', 'content': 'The later instruction.'}], 'sid:inventory',
                   classification, Rlog())
    framed = coder.bodies[0]['messages']
    listing = next(i for i, m in enumerate(framed) if 'Initial harness workspace inventory' in str(m.get('content')))
    later = next(i for i, m in enumerate(framed) if m.get('content') == 'The later instruction.')
    assert listing < later
    assert any(m.get('content') == 'Original task' for m in framed)


def test_unavailable_inventory_construction_continues_to_coder(tmp_path):
    from cria.opspath import OpsUnavailable

    def unavailable(*args, **kwargs):
        raise OpsUnavailable('unavailable')
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True, issue_inventory=unavailable)
    driver.drive(body('Implement the task'), 'sid:inventory', Classification('task', 'coding', 'fixture'), Rlog())
    assert coder.bodies and 'Implement the task' in json.dumps(coder.bodies[0]['messages'])


def test_a_refused_inventory_keeps_user_messages_and_the_model_never_sees_cria_s_calls(tmp_path):
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True)
    request = body('Implement the original task')
    drive_with_ops(driver, request, request['messages'] + [{'role': 'user', 'content': 'Also preserve this instruction.'}], 'sid:inventory',
                   Classification('task', 'coding', 'fixture'), Rlog(), harness=lambda call: 'Permission denied')
    text = json.dumps(coder.bodies[0]['messages'])
    assert 'Implement the original task' in text and 'Also preserve this instruction.' in text
    assert 'Permission denied' not in text and 'ctx_' not in text and 'CTX1' not in text
    assert 'Initial harness workspace inventory' not in text or '"files":[]' in text


def test_the_inventory_operation_is_scoped_to_its_session_and_survives_session_reconstruction(tmp_path):
    session = loop.PlanSession(plan=Plan(id='p', task='task', created='now', items=[PlanItem('task')]), initial_listing='survey evidence')
    assert loop._session_from_dict(loop._session_to_dict(session)).initial_listing == 'survey evidence'
    (tmp_path / 'seed.py').write_text('x = 1\n')
    coder = Chat(acting())
    driver = plan_off_loop(coder, workspace_root=str(tmp_path), assists=True)
    request = body('Task')
    drive_with_ops(driver, request, request['messages'], 'sid:one', Classification('task', 'coding', 'fixture'), Rlog())
    assert driver._store.get_bootstrap('sid:two') is None and 'seed.py' in json.dumps(coder.bodies[0]['messages'])
