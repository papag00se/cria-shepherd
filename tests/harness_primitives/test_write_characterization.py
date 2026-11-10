"""Characterisation of write_file / edit_file: what the model reads and what lands on disk, case by case, against the capture of the
route that shipped before Phase 5 (tests/fixtures/write_characterization.json: one Python program per call, run by the harness).
`CRIA_CHARACTERIZE=<path>` writes a capture of the route under test instead.

The model-visible texts are the same byte for byte except where listed in INTENDED, with the reason; one thing is normalised everywhere:
the old route's results came through a pty and carried a CR before every line feed and a trailing newline, which the text cria composes
now does not have."""
import json
import os
import pathlib
import re
import shutil

import pytest

import char_rig
from ops_rig import isolated_home  # noqa: F401

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'write_characterization.json'


def norm(text):
    """The checker's own words, without what depends on which Node answered: its version and the frames of its own internals (the fixture was recorded with
    v20.19.5; the checker is looked up in the safe path, so on another machine it is another Node)."""
    text = re.sub(r'\r+\n', '\n', text)             # a pty doubles the carriage returns of what a checker printed
    text = re.sub(r'\n    at [^\n]*\(node:internal[^\n]*\)', '', text)
    return re.sub(r'Node\.js v[\d.]+', 'Node.js v<version>', text.rstrip('\n'))


def refused(*fragments):
    def check(got):
        assert len(got['results']) == 1 and got['results'][0].startswith('⟦ctx:denied⟧'), got['results']
        assert all(f in got['results'][0] for f in fragments), got['results'][0]
    return check


def landed_big(got):
    assert got['results'] == ['Wrote big.txt']
    on_disk = got['disk']['big.txt']
    assert on_disk['size'] >= 100_000 and 'text' in on_disk or on_disk['size'] > 60_000


def staged_in_reference(name):
    """What the old route wrote, plus the empty folders the staged payload passed through (./tmp/reference, where it is staged: never beside the file)."""
    def check(got):
        want = json.loads(FIXTURE.read_text())[name]
        assert [norm(t) for t in got['results']] == [norm(t) for t in want['results']]
        disk = {k: v for k, v in got['disk'].items() if k not in ('tmp/', 'tmp/reference/')}
        assert disk == want['disk'] and set(got['disk']) - set(disk) == {'tmp/', 'tmp/reference/'} and got['outside'] == want['outside']
    return check


# name -> (what changed, what the model reads / what is on disk now)
INTENDED = {
    'e_large_replacement': ('a replacement past one command is staged in ./tmp/reference (two empty folders remain there), no longer beside the file',
                            staged_in_reference('e_large_replacement')),
    'e_missing_file': ('a traceback became an answer in cria\'s words', refused('`nope.py` is not there — nothing was changed')),
    'e_dir_target': ('a traceback became an answer in cria\'s words', refused('`d` is a DIRECTORY, not a file — nothing was changed')),
    'w_symlink_outside': ('a link to a file outside the workspace is refused, not written through', refused('outside the project directory')),
    'e_symlink_outside': ('a link to a file outside the workspace is refused, not edited through', refused('outside the project directory')),
    'e_unsafe_cleanup': ('an edit whose complete candidate is proven unsafe is withheld on the bytes cria holds (the old route could only '
                         'judge it when the workspace view happened to hold the file)', refused('withheld for revision')),
    'w_100k': ('a write past the kernel\'s argument limit lands (it failed with E2BIG)', landed_big),
    'w_400k': ('a write past the kernel\'s argument limit lands (it failed with E2BIG)', landed_big),
}


TOOLS = {'rb': 'ruby', 'go': 'gofmt', 'js': 'node', 'mjs': 'node', 'php': 'php'}      # the harness's own checkers: a case needs the tool its language is checked with


@pytest.mark.parametrize('name', sorted(char_rig.CASES))
def test_case(tmp_path, name):
    tool = TOOLS.get(name.rsplit('_', 1)[-1])
    if tool and not shutil.which(tool):
        pytest.skip(f'no {tool}: the harness cannot check this language here (UNKNOWN never refuses)')
    got = char_rig.run_case(name, tmp_path)
    target = os.environ.get('CRIA_CHARACTERIZE')
    if target:
        path = pathlib.Path(target)
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = got
        path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False))
        return
    want = json.loads(FIXTURE.read_text())[name]
    if name in INTENDED:
        INTENDED[name][1](got)
        if name.endswith('_outside'):
            assert got['outside'] == json.loads(FIXTURE.read_text())['e_exact']['outside'] or all(
                v['text'] in ('OUTSIDE ORIGINAL\n', 'x = 1\n') for k, v in got['outside'].items() if 'text' in v)
        return
    assert [norm(t) for t in got['results']] == [norm(t) for t in want['results']]
    if name == 'w_mode_kept':          # a whole write keeps the file's mode and owner (the old route reset it to 0666 & ~umask)
        assert got['disk']['run.sh']['mode'] == '0o755' and got['disk']['run.sh']['text'] == want['disk']['run.sh']['text']
        return
    assert got['disk'] == want['disk'] and got['outside'] == want['outside']
