"""Phase 2a of the harness-program migration (docs/harness-programs.md F1): Python that cria starts in the
harness must not import code from the repository, whichever process starts it."""
import ast
import os
import pathlib
import re
import stat
import subprocess
import sys

import pytest

from cria import probegate
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'write_edit'))
from write_edit_helpers import do, harness_env, operations_engine, write_edit_workspace_view  # noqa: F401,E402

CRIA = pathlib.Path(probegate.__file__).parent
POISON = "open('POISONED', 'a').write('executed\\n')\n"
SHADOWS = ('hashlib', 'base64', 'json', 'os', 'subprocess', 'shutil', 'sitecustomize', 'usercustomize')


def _hostile_workspace(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    for name in SHADOWS:
        (workspace / (name + '.py')).write_text(POISON)
    (workspace / 'ok.py').write_text('x = 1\n')
    (workspace / 'bin').mkdir()
    return workspace


def _environment(tmp_path, workspace):
    scratch = tmp_path / 'scratch'
    scratch.mkdir(exist_ok=True)
    return {**os.environ, 'TMPDIR': str(scratch), 'PYTHONPATH': str(workspace), 'PYTHONUSERBASE': str(workspace)}


def test_the_gate_runs_no_workspace_code_in_crias_own_plumbing_and_uses_no_planted_python3_or_env(tmp_path):
    """The gate is the `run` stub (a fixed text under `env -i PATH=<system dirs> python3 -I -S`) and the project's own checks as a shell text: in a
    workspace that shadows the standard library, with PYTHONPATH and the user base pointing at it and a planted `python3` and `env` first on PATH,
    cria's plumbing runs none of it. (A project's own check runs project code by design; this one is `true`.)"""
    from survey_fixtures import gate_of_disk
    from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
    workspace = _hostile_workspace(tmp_path)
    for tool, real in (('python3', os.path.realpath(sys.executable)), ('env', '/usr/bin/env')):
        planted = workspace / 'bin' / tool
        planted.write_text("#!/bin/sh\necho planted-%s >> POISONED\nexec %s \"$@\"\n" % (tool, real))
        planted.chmod(planted.stat().st_mode | stat.S_IXUSR)
    shim = pathlib.Path(harness_env(workspace)['PATH'].split(':')[0])
    hostile = {'PYTHONPATH': str(workspace), 'PYTHONUSERBASE': str(workspace), 'PATH': f'{workspace / "bin"}:{shim}:/usr/bin:/bin'}
    check = ProbeCandidate(ProbeKind.BuildCheck, ['true'], str(workspace), 100, 100, ProbeCost.Cheap, False, False, False, 'fixture')
    result = gate_of_disk(workspace, [check], env=hostile)
    assert result.complete and result.sections['probe-0'] == ('', 0) and result.failed == []          # the control: the legitimate gate ran to completion
    assert not (workspace / 'POISONED').exists()


def test_a_write_and_an_edit_run_no_workspace_code_and_use_no_planted_python3_or_env(tmp_path):
    """The write route (R1/R2/R7 of docs/harness-programs.md) is the fixed stubs: in a workspace that shadows the standard library
    (`hashlib`, `json`, `os`, `sitecustomize`, ...), with PYTHONPATH and the user base pointing at it and a planted `python3` and `env`
    first on PATH, a whole write, an edit and a refused candidate land and answer exactly as they do anywhere, and nothing planted runs."""
    workspace = _hostile_workspace(tmp_path)
    for tool, real in (('python3', os.path.realpath(sys.executable)), ('env', '/usr/bin/env')):
        planted = workspace / 'bin' / tool
        planted.write_text("#!/bin/sh\necho planted-%s >> POISONED\nexec %s \"$@\"\n" % (tool, real))
        planted.chmod(planted.stat().st_mode | stat.S_IXUSR)
    shim = pathlib.Path(harness_env(workspace)['PATH'].split(':')[0])
    hostile = {'PYTHONPATH': str(workspace), 'PYTHONUSERBASE': str(workspace), 'PATH': f'{workspace / "bin"}:{shim}:/usr/bin:/bin'}
    (workspace / 'a.py').write_text('x = 1\n')
    _, _, wrote = do('write_file', {'path': 'new.txt', 'content': 'written\n'}, workspace, env=hostile)
    _, _, edited = do('edit_file', {'path': 'a.py', 'old_string': 'x = 1', 'new_string': 'x = 2'}, workspace, cid='e', env=hostile)
    _, _, refused = do('edit_file', {'path': 'a.py', 'old_string': 'x = 2', 'new_string': 'x = (2'}, workspace, cid='r', env=hostile)
    assert not (workspace / 'POISONED').exists()
    assert (workspace / 'new.txt').read_text() == 'written\n' and (workspace / 'a.py').read_text() == 'x = 2\n'
    assert wrote[1]['content'] == 'Wrote new.txt' and edited[1]['content'] == 'Wrote a.py' and 'would break' in refused[1]['content']


def _python_invocations_without_isolation():
    """Every Python launch cria composes in source: a ``python3 ...`` shell word in a string constant, or an
    argv list starting with ``python``/``python3``/``sys.executable``. Prose (docstrings, bare string statements)
    is not a launch. The project's own test runner (a tuple in probediscovery's convention table) is project
    code by design: the gate runs the project's checks, and their isolation is the sandbox's."""
    found = []
    for path in sorted(CRIA.glob('*.py')):
        source = path.read_text()
        tree = ast.parse(source)
        prose = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose:
                for line in node.value.splitlines():
                    if re.search(r'(?:^|[\s;|&{(`\'"])python3\s+(?:-|<<)', line) and not re.search(r'python3 -I\b', line):
                        found.append(f'{path.name}:{node.lineno}: {line.strip()[:80]}')
            if isinstance(node, ast.List) and len(node.elts) > 1 and isinstance(node.elts[0], ast.Constant) \
                    and node.elts[0].value in ('python', 'python3') \
                    and not (isinstance(node.elts[1], ast.Constant) and node.elts[1].value == '-I'):
                found.append(f'{path.name}:{node.lineno}: {ast.unparse(node)[:80]}')
        for match in re.finditer(r'sys\.executable\s*,\s*([^,\]]*)', source):
            if match.group(1).strip().strip('\'"') != '-I':
                found.append(f'{path.name}: sys.executable launched without -I')
    return found


def test_every_python_cria_launches_is_isolated():
    assert _python_invocations_without_isolation() == []
