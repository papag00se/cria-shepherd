"""The deployable wheel must contain the runtime and its real prompt resources, not suite data."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_built_wheel_installs_runtime_and_loads_prompt_resources(tmp_path):
    if importlib.util.find_spec('setuptools') is None or importlib.util.find_spec('wheel') is None:
        pytest.skip('distribution build tools are not installed')
    wheels = tmp_path / 'wheels'
    wheels.mkdir()
    metadata = tmp_path / 'metadata'
    metadata.mkdir()
    settings = {'--global-option': ['egg_info', '--egg-base', str(metadata),
                                   'build', '--build-base', str(tmp_path / 'build')]}
    built = subprocess.run(
        [sys.executable, '-c', 'import setuptools.build_meta as b; b.build_wheel('
         + repr(str(wheels)) + ', config_settings=' + repr(settings) + ')'],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    wheel, = wheels.glob('*.whl')
    installed = tmp_path / 'installed'
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert not any(name.startswith(('suite/', 'tests/', 'runs/', 'walkdata/')) for name in names)
        expected_prompts = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'cria/prompts').glob('*.txt')}
        assert expected_prompts <= names
        assert {'cria/__main__.py', 'cria/system1.py', 'cria/system1wiring.py'} <= names
        archive.extractall(installed)
    # This is an installed distribution, not a source checkout; its prompt loader must work there.
    check = subprocess.run(
        [sys.executable, '-c',
         "from cria import prompts; from cria.config import Config; "
         "assert prompts.load('compaction_validate_retrospective'); "
         "assert prompts.load('offline_onejev_dictation'); "
         "assert not Config().system1.enabled; "
         "import sys; assert 'onnxruntime' not in sys.modules and 'tokenizers' not in sys.modules"],
        cwd=installed, env={**os.environ, 'PYTHONPATH': str(installed)}, capture_output=True, text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr
