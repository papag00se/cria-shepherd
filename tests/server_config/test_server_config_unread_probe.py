"""The unread-write rule asks the file when nothing known settles it (cria/probeops.py), through a real server: the inventory reads no file, the coder's first write
over an unread seed is answered with the seed after one probe the model never sees, and a seed it has been shown is never asked again."""
import json
import subprocess

import pytest

from cria import system1wiring
from cria.config import Backend, Role, RoutingConfig
from test_server_config_http import Wire

PRIVATE = ('CTX1', 'ctx_', 'python3', '-I -S', 'harness-call', 'CTX_EOF', 'env -i', 'unread-write check')


def run_session(tmp_path, monkeypatch, files, *, task='Implement the feature __TOOL__', stop=lambda root: False, limit=40):
    """Drive the real server over the fake upstream (whose coder answers every turn with `write_file hello.txt`), running every call it hands the harness in the
    workspace, until ``stop(root)`` or ``limit`` requests. Returns ``(the harness's commands, the coder's request bodies, the workspace)``."""
    monkeypatch.setattr(system1wiring, 'build', lambda *args, **kwargs: None)
    root = tmp_path / 'workspace'
    root.mkdir()
    for rel, text in files.items():
        (root / rel).write_text(text)
    shell = {'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}
    env = f'<environment_context><cwd>{root}</cwd></environment_context>'
    request = {'model': 'm', 'tools': [{'type': 'function', 'function': shell}], 'messages': [{'role': 'user', 'content': t} for t in (env, task)]}
    wire = Wire(tmp_path, routing=lambda url: RoutingConfig(
        backends={'local': Backend('local')},
        roles={'classifier': Role('classifier', 'local'), 'coder': Role('coder', 'local'), 'compactor': Role('compactor', 'local'), 'reasoner': Role('reasoner', 'local')},
        failover={'coding': ('coder',)}, engagement_bias='task', engagement_level=5))
    commands = []
    try:
        for _ in range(limit):
            _, raw = wire.post('/v1/chat/completions', request, sid='probe')
            message = json.loads(raw)['choices'][0]['message']
            calls = message.get('tool_calls') or []
            if not calls:
                break
            request['messages'].append(message)
            for call in calls:
                command = json.loads(call['function']['arguments'])['cmd']
                commands.append(command)
                run = subprocess.run(['bash', '-c', command], cwd=root, capture_output=True, text=True)
                request['messages'].append({'role': 'tool', 'tool_call_id': call['id'], 'content': run.stdout})
            if stop(root):
                break
        coder = [body for _, body in wire.fake.chats if body.get('tools') and any('__TOOL__' in json.dumps(m) for m in body.get('messages', []))]
        return commands, coder, root
    finally:
        wire.close()


def comments(commands):
    return [c.split('\n', 1)[0] for c in commands]


def test_an_unread_seed_is_held_after_one_lazy_read_the_model_never_sees(tmp_path, monkeypatch):
    commands, coder, root = run_session(tmp_path, monkeypatch, {'hello.txt': 'seed text\n', 'other.py': 'x = 1\n'},
                                        stop=lambda root: (root / 'hello.txt').read_text() == 'hi there\n')
    assert comments(commands) == ['# workspace inventory .', '# workspace inventory (symbols)',
                                  '# unread-write check hello.txt',                    # the one question, asked when the write names the file
                                  '# write_file hello.txt',                            # the held write answered with the file (the read it stands for)
                                  '# write_file hello.txt']                            # the model's second write: credit, one call
    assert (root / 'hello.txt').read_text() == 'hi there\n'
    assert len(coder) == 2                                                          # the model was asked for the write and for the retry: the probe is no model turn
    held = coder[1]['messages']
    shown = {m['tool_call_id']: m['content'] for m in held if m.get('role') == 'tool'}
    assert shown['call_1'].startswith('⟦ctx:denied⟧') and 'seed text\n' in shown['call_1'] and 'This write_file call was not run' in shown['call_1']
    assert [(c['id'], c['function']['name']) for m in held if m.get('tool_calls') for c in m['tool_calls']] == [('call_1', 'write_file')]
    assert not [p for p in PRIVATE if p in json.dumps(coder)]                       # no probe, no primitive in any body the model received


def test_a_seed_the_coder_has_been_shown_is_not_asked_again_and_a_new_file_is_never_asked(tmp_path, monkeypatch):
    commands, coder, root = run_session(tmp_path, monkeypatch, {'hello.txt': 'seed text\n'}, limit=12)
    assert comments(commands).count('# unread-write check hello.txt') == 1          # asked once, whatever the coder does after the hold lifted it
    commands, _, root = run_session(tmp_path / 'again', monkeypatch, {'other.py': 'x = 1\n'}, stop=lambda root: (root / 'hello.txt').exists()) if (tmp_path / 'again').mkdir() is None else None
    assert not [c for c in comments(commands) if 'unread-write check' in c] and (root / 'hello.txt').read_text() == 'hi there\n'      # a path the inventory does not list is not there to ask
