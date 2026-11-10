"""Characterisation of write_file / create_file / edit_file / str_replace: what the model reads and what lands on disk, case by case, against the
capture of the route that shipped before Phase 5 (tests/fixtures/write_characterization.json). `CRIA_CHARACTERIZE=<path>` writes the capture instead."""
import json
import os
import pathlib

import pytest

import char_rig
from ops_rig import isolated_home  # noqa: F401

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'write_characterization.json'


@pytest.mark.parametrize('name', sorted(char_rig.CASES))
def test_case(tmp_path, name):
    got = char_rig.run_case(name, tmp_path)
    target = os.environ.get('CRIA_CHARACTERIZE')
    if target:
        path = pathlib.Path(target)
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = got
        path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False))
        return
    want = json.loads(FIXTURE.read_text())[name]
    assert got['results'] == want['results']
    assert got['disk'] == want['disk'] and got['outside'] == want['outside']
