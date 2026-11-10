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


def text_of(block):
    return block.get('text') or block['head'] + block['tail']


# name -> (what changed on purpose, what the new text must be)
INTENDED = {
    'no_tests': ('the old gate was planned before the survey and ran the parse floor with a program that is not installed; the first gate now knows the project',
                 lambda block, old: 'cover syntax only' in text_of(block) and 'No pytest tests were found by default' in text_of(block)),
    'big_output': ('a check that prints 6,000 lines was lost whole by the old route ("no usable result"); it is paged complete now and the model reads the checker\'s own words',
                   lambda block, old: block.get('n', 0) > 300_000 and 'FAILED test_app.py::test_a - AssertionError: the last word' in block['tail']),
    'forged_frames': ('the old route removed every line that began with `EXIT:` from what a check printed (its own sentinel was text); a line a check printed is shown as printed',
                      lambda block, old: any(block.get('text', '').replace('\nEXIT:0\n', '\n', 1) == o.get('text') for o in old)),
}


@pytest.mark.parametrize('continuation', [False, True], ids=['detached', 'foreground'])
@pytest.mark.parametrize('name', sorted(rig.CASES))
def test_case(tmp_path, monkeypatch, name, continuation):
    """``foreground``: the harness offers a tool to continue a yielded call (Codex's `write_stdin`), so the gate runs in the foreground of its call
    (Phase 9a); what the model reads of a check that ends in one call is the same either way."""
    import shutil
    if TOOLS.get(name) and not shutil.which(TOOLS[name]):
        pytest.skip(f'no {TOOLS[name]} here')
    got = rig.run_case(rig.CASES[name], tmp_path, monkeypatch, continuation=continuation)
    target = os.environ.get('CRIA_CHARACTERIZE')
    if target and continuation:
        return
    if target:
        path = pathlib.Path(target)
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = got
        path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False))
        return
    from cria import privatepaths
    modes = {r['args'].get('mode') for f in (privatepaths.CRIA_HOME / 'ops').iterdir() for r in map(json.loads, f.read_text().splitlines()) if r['t'] == 'step' and r['what'] == 'grun'}
    assert modes and modes <= ({'fg', 'wait'} if continuation else {'start', 'wait'}), modes                  # the gate ran the way the harness's tools say it can
    fixture = json.loads(FIXTURE.read_text())
    ws = tmp_path / 'ws'
    assert not [p for p in os.listdir(ws) if p.startswith('MARK-')], "cria's own plumbing ran project code"
    if name == 'hostile':               # the old route ran the planted interpreter in its own plumbing and read nothing (UNKNOWN)
        ran = (ws / 'RAN').read_text().splitlines() if (ws / 'RAN').exists() else []
        assert not [line for line in ran if line.startswith('env -i') or ' -S ' in line or ' -c ' in line], ran      # only the checks' own `env PYTHONPYCACHEPREFIX=... python3 -I -m compileall`
        assert any('go test' in text_of(e) for e in got['evidence']) and not any('UNKNOWN' in text_of(e) for e in got['evidence'])
        return
    assert got['litter'] == []          # intended: the old route left its helper and a private directory in the harness's temp directory
    # Every text the model read of the checks is one the old route showed, byte for byte, or an intended difference. The new route may show FEWER of
    # them: the old gate was planned before the workspace was surveyed (it ran the parse floor, then the checks the survey delivered); the survey is
    # now an operation of its own that has answered by the time the gate is planned, so the first gate already runs the project's own checks.
    old = [sorted_removed(e) for e in fixture[name]['evidence']]
    new = [sorted_removed(e) for e in got['evidence']]
    extra = [e for e in new if e not in old]
    assert new and all(INTENDED[name][1](e, old) for e in extra) if extra else bool(new), [text_of(e)[:300] for e in extra]
    decisive = rig.CASES[name].get('expect', 'pytest -q')
    assert any(decisive in text_of(e) for e in new), 'the checks the case is about never reached the model'
