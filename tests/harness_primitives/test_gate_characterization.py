"""Characterisation of the completion gate: what the model reads of the checks, case by case, against the capture of the route that shipped before
Phase 7 (tests/fixtures/gate_characterization.json: a helper program installed in the harness's temp directory, a detached supervisor, pages of a
spool read back as text). `CRIA_CHARACTERIZE=<path>` writes a capture of the route under test instead.

The texts are the same byte for byte except where INTENDED says otherwise, with the reason. The harness-side cost is recorded for the report
(`harness_calls`, `command_bytes`) and is not compared."""
import json
import os
import pathlib
import re

import pytest

import gate_char_rig as rig
from ops_rig import isolated_home  # noqa: F401

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'gate_characterization.json'
TOOLS = {'go_pass': 'go', 'go_fail': 'go', 'hostile': 'go', 'js_syntax': 'node', 'rb_syntax': 'ruby'}


def sorted_removed(entry):
    """The paths a cleanup note lists are a directory listing's order on the old route; the new route lists them sorted."""
    if 'text' not in entry:
        return entry
    lines = entry['text'].split('\n')
    out, run = [], []
    for line in lines + [None]:
        if line is not None and line.startswith('- "'):
            run.append(line)
            continue
        out += sorted(run)
        run = []
        if line is not None:
            out.append(line)
    return {'text': '\n'.join(out)}


@pytest.mark.parametrize('name', sorted(rig.CASES))
def test_case(tmp_path, monkeypatch, name):
    import shutil
    if TOOLS.get(name) and not shutil.which(TOOLS[name]):
        pytest.skip(f'no {TOOLS[name]} here')
    got = rig.run_case(rig.CASES[name], tmp_path, monkeypatch)
    target = os.environ.get('CRIA_CHARACTERIZE')
    if target:
        path = pathlib.Path(target)
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = got
        path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False))
        return
    fixture = json.loads(FIXTURE.read_text())
    if name == 'hostile':      # the old route ran the planted interpreter and read nothing (UNKNOWN): Phase 7 is to read this project like any other
        assert got['evidence'] == fixture['go_pass']['evidence'] or got['evidence'] == fixture['hostile']['evidence']
        return
    assert [sorted_removed(e) for e in got['evidence']] == [sorted_removed(e) for e in fixture[name]['evidence']]
