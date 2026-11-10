"""Rig for the primitive-operation tests: a real CriaServer over a scripted model, and a harness that runs cria's calls as the
pinned Codex does (`bash -lc` on a pty, LF to CRLF, the 10,000-byte cut, its envelope) in a real workspace."""
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'read_multipart'))
from read_multipart_helpers import Wire as _Wire, codex_result, chatty_pty  # noqa: E402,F401
import urllib.error  # noqa: E402

from cria import privatepaths  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """The key, the ledger and every other private artefact live under CRIA_HOME: each test gets its own."""
    (tmp_path / 'home').mkdir()
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(privatepaths, 'CRIA_HOME', tmp_path / 'home' / '.cria')


class Wire(_Wire):
    """The read tests' rig, with a server error shown as what it said; ``level`` is [safety] external_dir_permission."""
    def __init__(self, *args, level=None, **kw):
        super().__init__(*args, **kw)
        if level:
            import dataclasses
            from cria.config import SafetyConfig
            self.srv.cfg = dataclasses.replace(self.srv.cfg, safety=SafetyConfig(level))

    def post(self):
        try:
            return super().post()
        except urllib.error.HTTPError as exc:
            raise AssertionError(f'cria answered {exc.code}: {exc.read().decode()[:2000]}') from None


def command_of(call):
    return json.loads(call['function']['arguments'])['cmd']


class Harness:
    """Runs a call's command in `cwd` the way the pinned Codex does (a real `bash -lc` on a real pty, CRLF, a private HOME and
    TMPDIR beside the workspace, never inside it); returns the text the harness would hand back."""
    def __init__(self, cwd, env=None, **noise):
        self.cwd, self.noise, self.env, self.ran = str(cwd), noise, env or {}, []
        self.home = self.cwd + '.home'

    def __call__(self, call):
        self.ran.append(call)
        os.makedirs(self.home, exist_ok=True)
        env = {'TMPDIR': self.cwd + '.scratch', **self.env}
        os.makedirs(env['TMPDIR'], exist_ok=True)
        raw, code = chatty_pty(command_of(call), self.cwd, env=env, home=self.home, **self.noise)
        return codex_result(raw, code)


def start_in(wire, workspace):
    """Point a started Wire's conversation at `workspace` (the harness's announced cwd), not at the directory its logs live in."""
    wire.messages[0]['content'] = f'<environment_context><cwd>{workspace}</cwd></environment_context> list'
    return wire


class ListBackend:
    """Scripted model: turn 1 calls `list_dir` for each path; every later turn answers 'seen'. Records request bodies."""
    def __init__(self, *paths, name='list_dir'):
        self.paths, self.name, self.bodies = paths, name, []

    def loaded_model(self, rlog=None):
        return 'test-model'

    def chat(self, body, rlog=None):
        self.bodies.append(body)
        calls = [{'id': 'model_call_%d' % i, 'type': 'function', 'function': {'name': self.name, 'arguments': json.dumps({'path': str(p)})}}
                 for i, p in enumerate(self.paths)] if len(self.bodies) == 1 else None
        msg = {'role': 'assistant', 'content': None, 'tool_calls': calls} if calls else {'role': 'assistant', 'content': 'seen'}
        return json.dumps({'id': 'f', 'object': 'chat.completion', 'created': 1, 'model': 'test-model',
                           'choices': [{'index': 0, 'message': msg, 'finish_reason': 'tool_calls' if calls else 'stop'}]})

    def tool_results(self):
        return [m for m in self.bodies[-1]['messages'] if m.get('role') == 'tool']


class TurnBackend:
    """Scripted model: turn N issues the calls ``turns[N-1]`` (a list of ``(tool, arguments)``), then answers 'seen'."""
    def __init__(self, *turns):
        self.turns, self.bodies = turns, []

    def loaded_model(self, rlog=None):
        return 'test-model'

    def chat(self, body, rlog=None):
        self.bodies.append(body)
        n = len(self.bodies) - 1
        calls = [{'id': f'model_call_{n}_{i}', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}
                 for i, (name, args) in enumerate(self.turns[n])] if n < len(self.turns) else None
        msg = {'role': 'assistant', 'content': None, 'tool_calls': calls} if calls else {'role': 'assistant', 'content': 'seen'}
        return json.dumps({'id': 'f', 'object': 'chat.completion', 'created': 1, 'model': 'test-model',
                           'choices': [{'index': 0, 'message': msg, 'finish_reason': 'tool_calls' if calls else 'stop'}]})
