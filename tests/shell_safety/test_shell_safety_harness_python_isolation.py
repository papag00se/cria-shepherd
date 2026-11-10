"""Phase 2a of the harness-program migration (docs/harness-programs.md F1): Python that cria starts in the
harness must not import code from the repository, whichever process starts it."""
import ast
import os
import pathlib
import re
import stat
import subprocess
import sys
import time

import pytest

from cria import probegate
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'write_edit'))
from write_edit_helpers import call, command_of, harness_env, lower, run, write_edit_workspace_view  # noqa: F401,E402

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


def test_gate_and_its_detached_worker_do_not_import_workspace_modules(tmp_path):
    workspace = _hostile_workspace(tmp_path)
    environment = _environment(tmp_path, workspace)
    plan = probegate.plan_gate(str(workspace))
    result = subprocess.run(['bash', '-c', plan.script], cwd=workspace, env=environment,
                            capture_output=True, timeout=120)
    # the worker is detached: wait for it to finish its work (the spool's .done marker) before judging
    deadline = time.monotonic() + 60
    done = []
    while time.monotonic() < deadline and not done:
        done = list(pathlib.Path(environment['TMPDIR']).glob('.ctx-private-*/*.done'))
        time.sleep(.2)
    assert not (workspace / 'POISONED').exists(), result.stderr.decode(errors='replace')
    # control: the legitimate worker ran to completion and the gate returned its output
    assert done, result.stdout.decode(errors='replace')[-2000:]
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert result.stdout.startswith(b'___CTX_GATE_TRANSPORT_') and b'___CTX_GATE_TRANSPORT_END_' in result.stdout


UNSAFE_EDIT = {'old_string': 'os.close(fd)', 'new_string': 'shutil.rmtree(os.path.dirname(path), ignore_errors=True)'}
SAFE_SOURCE = ("import os, shutil, tempfile\n\n\ndef test_it():\n    fd, path = tempfile.mkstemp()\n    os.close(fd)\n")


def _unsafe_edit_command(workspace):
    """The real lowering of an edit whose candidate is proven unsafe: the refuse-if-unchanged wrapper that runs python3 in the harness."""
    target = workspace / 'test_http.py'
    target.write_text(SAFE_SOURCE)
    tc = lower([call('edit_file', {'path': str(target), **UNSAFE_EDIT})], root=str(workspace))[0]
    assert 'python3' in command_of(tc)
    return tc, target


def test_candidate_safety_stale_check_does_not_import_workspace_modules(tmp_path):
    workspace = _hostile_workspace(tmp_path)
    environment = {'PYTHONPATH': str(workspace), 'PYTHONUSERBASE': str(workspace)}
    tc, target = _unsafe_edit_command(workspace)
    done = run(tc, workspace, env=environment)
    assert not (workspace / 'POISONED').exists()
    assert 'withheld' in done.stdout and target.read_text() == SAFE_SOURCE        # control: unchanged file, the refusal still lands
    tc, target = _unsafe_edit_command(workspace)
    target.write_text(SAFE_SOURCE + '# changed after review\n')
    done = run(tc, workspace, env=environment)
    assert not (workspace / 'POISONED').exists()
    assert 'changed or could not be read after this edit was reviewed' in done.stdout                  # control: the stale branch still compares real bytes


def test_candidate_safety_check_does_not_resolve_python3_through_a_planted_path_entry(tmp_path):
    workspace = _hostile_workspace(tmp_path)
    planted = workspace / 'bin' / 'python3'
    planted.write_text("#!/bin/sh\necho planted >> POISONED\nexec %s \"$@\"\n" % os.path.realpath(sys.executable))
    planted.chmod(planted.stat().st_mode | stat.S_IXUSR)
    tc, _ = _unsafe_edit_command(workspace)
    shim = pathlib.Path(harness_env(workspace)['PATH'].split(':')[0])
    run(tc, workspace, env={'PATH': f'{workspace / "bin"}:{shim}:/usr/bin:/bin'})
    assert not (workspace / 'POISONED').exists()


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
