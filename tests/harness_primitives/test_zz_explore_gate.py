import json, sys, os
import pytest
import gate_char_rig as rig
from ops_rig import isolated_home  # noqa

CASES = {
 'pass': dict(files={'app.py': 'x = 1\n', 'test_app.py': 'def test_a():\n    assert 1\n'}, script=[('text', 'Done.')]),
 'fail': dict(files={'app.py': 'x = 1\n', 'test_app.py': 'def test_a():\n    assert 1 == 2\n'}, script=[('text', 'Done.')]),
}
@pytest.mark.parametrize('name', sorted(CASES))
def test_explore(tmp_path, monkeypatch, name):
    got = rig.run_case(CASES[name], tmp_path, monkeypatch)
    print(json.dumps(got, indent=1))
