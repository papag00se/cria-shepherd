"""Characterisation of grep / glob / web_fetch / web_search: what the model reads and what is on disk, case by case, against the capture of the route that
shipped before Phase 6b (tests/fixtures/search_characterization.json). `CRIA_CHARACTERIZE=<path>` writes a capture of the route under test instead."""
import hashlib
import json
import os
import pathlib

import pytest

import search_rig
from ops_rig import isolated_home  # noqa: F401

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'search_characterization.json'


def slim(disk):
    """The disk of a case with every long file reduced to its size, hash and ends (the fixture stays small; a difference anywhere still shows)."""
    out = {}
    for rel, entry in disk.items():
        text = entry.get('text')
        if text is not None and len(text) > 3000:
            entry = {**{k: v for k, v in entry.items() if k != 'text'}, 'sha': hashlib.sha256(text.encode()).hexdigest(), 'head': text[:200], 'tail': text[-200:]}
        out[rel] = entry
    return out


def norm(text):
    return text.replace('\r\n', '\n').rstrip('\n')


@pytest.mark.parametrize('name', sorted(search_rig.CASES))
def test_case(tmp_path, monkeypatch, name):
    got = search_rig.run_case(name, tmp_path, monkeypatch)
    target = os.environ.get('CRIA_CHARACTERIZE')
    if target:
        path = pathlib.Path(target)
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = {**got, 'disk': slim(got['disk'])}
        path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False))
        return
    want = json.loads(FIXTURE.read_text())[name]
    assert [norm(t) for t in got['results']] == [norm(t) for t in want['results']]
    assert slim(got['disk']) == want['disk']
