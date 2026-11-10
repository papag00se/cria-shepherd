"""Characterisation of what the survey learns of the coder's shell: which programs it resolves and which paths outside the workspace exist.

`tests/fixtures/survey_probe_characterization.json` is the capture of the route that shipped before Phase 9b (a harness-side shell script with `for`
loops, `case` and `[ -f ] && [ -x ]` over `$PATH` and `[ -d ]`/`[ -f ]` over the asked paths). `CRIA_CHARACTERIZE=<path>` writes a capture of the route
under test instead. The answers are the same for every case except those named in `INTENDED`, with the reason."""
import json
import os
import pathlib

import pytest
from survey_fixtures import survey_of_disk

from ops_rig import isolated_home  # noqa: F401

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'survey_probe_characterization.json'


def _exe(path, text='#!/bin/sh\nexit 0\n'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def tree(tmp):
    """Three directories of programs the harness's PATH names, and what lies around them."""
    b1, b2, home, ws = tmp / 'b1', tmp / 'b2', tmp / 'home', tmp / 'ws'
    for d in (b1, b2, home, ws):
        d.mkdir(parents=True, exist_ok=True)
    for name in ('tool', 'zruby3.2', 'zruby3.10', 'only9', 'dup'):
        _exe(b1 / name)
    (b1 / 'notexec').write_text('x')
    (b1 / 'dirprog').mkdir()
    (b1 / 'brokenlink').symlink_to('missing')
    (b1 / 'linktool').symlink_to('tool')
    (b1 / 'linknotexec').symlink_to('notexec')
    (b1 / 'weird name').write_text('#!/bin/sh\n')
    (b1 / 'weird name').chmod(0o755)
    (b1 / "it's").write_text('#!/bin/sh\n')
    (b1 / "it's").chmod(0o755)
    for name in ('tool2', 'zruby3.5', 'dup', 'py3'):
        _exe(b2 / name)
    _exe(b2 / 'znode20.5.1')
    (b2 / 'zpython').write_text('#!/bin/sh\n')               # not executable
    (b2 / 'zpython3.12').write_text('#!/bin/sh\n')           # not executable
    _exe(ws / 'localtool')                                  # beside the work: an empty or relative PATH entry sees it
    (ws / 'rel').mkdir()
    _exe(ws / 'rel' / 'reltool')
    out = tmp / 'out'
    (out / 'dir').mkdir(parents=True)
    (out / 'file').write_text('x')
    (out / 'linkdir').symlink_to(out / 'dir')
    (out / 'linkfile').symlink_to(out / 'file')
    (out / 'broken').symlink_to(out / 'nowhere')
    (out / 'with space').mkdir()
    (out / "it's here").write_text('x')
    (home / 'sub').mkdir()
    (home / 'file').write_text('x')
    (home / 'with space').mkdir()
    (home / 'linkdir').symlink_to(home / 'sub')
    return b1, b2, home, ws, out


def path_of(*dirs):
    return ':'.join(str(d) for d in dirs) + ':/usr/bin:/bin'


# name -> (PATH as a function of the trees, programs asked, outside paths asked ({out} and {home} are filled in))
CASES = {
    'plain': (lambda b1, b2, ws: path_of(b1, b2), ['tool', 'tool2', 'nothing-here', 'sh', 'ls'], []),
    'not_a_program': (lambda b1, b2, ws: path_of(b1, b2), ['notexec', 'dirprog', 'brokenlink', 'linknotexec'], []),
    'symlink': (lambda b1, b2, ws: path_of(b1, b2), ['linktool'], []),
    'first_directory_wins': (lambda b1, b2, ws: path_of(b2, b1), ['dup', 'tool'], []),
    'versioned': (lambda b1, b2, ws: path_of(b1, b2), ['zruby', 'znode', 'zpython', 'zpython3', 'zruby3', 'zruby3.2', 'only', 'tool', 'py'], []),
    'versioned_in_two_directories': (lambda b1, b2, ws: path_of(b2, b1), ['zruby'], []),
    'quoted_names': (lambda b1, b2, ws: path_of(b1), ['weird name', "it's", 'a b', '"q"', '$x', '`x`', 'a;b', ''], []),
    'empty_and_relative_entries': (lambda b1, b2, ws: f'::rel:{b1}:/usr/bin:/bin', ['localtool', 'reltool', 'tool'], []),
    'outside': (lambda b1, b2, ws: path_of(b1), [], ['{out}/dir', '{out}/file', '{out}/linkdir', '{out}/linkfile', '{out}/broken', '{out}/missing',
                                                     '{out}/with space', "{out}/it's here", '/', '/nonexistent/x', '{out}/file/under']),
    'tilde': (lambda b1, b2, ws: path_of(b1), [], ['~', '~/sub', '~/file', '~/with space', '~/linkdir', '~/nothing', '~nobody/x', '~x']),
    'shell_builtins': (lambda b1, b2, ws: path_of(b1), ['cd', 'if', 'type', 'echo', 'tool'], []),
    'both': (lambda b1, b2, ws: path_of(b1, b2), ['tool', 'nothing-here'], ['{out}/dir', '~/sub', '{out}/missing']),
    'many': (lambda b1, b2, ws: path_of(b1, b2), [f'prog{i}' for i in range(20)] + ['tool', 'zruby'], [f'{{out}}/dir{i}' for i in range(20)] + ['{out}/dir']),
}

# name -> why the new route answers differently, and the check that the new answer is the intended one: (progs, outside) -> bool
INTENDED = {
    'shell_builtins': ('the shell resolves a builtin, a keyword or a function (`cd`, `if`, `type`) as it runs them; the old script looked for files on PATH only (the program names asked are tools, '
                       'so no question changes: `echo` and `tool` are files and are answered as before)',
                       lambda got, old: got['progs'] == {'cd': 'cd', 'if': 'if', 'type': 'type', 'echo': 'echo', 'tool': 'tool'} and old['progs'] == {'cd': '', 'if': '', 'type': '', 'echo': 'echo', 'tool': 'tool'}),
    'empty_and_relative_entries': ('an empty entry of PATH is the working directory and the coder\'s shell does resolve a program there; the old script skipped empty entries',
                                   lambda got, old: got['progs'] == {**old['progs'], 'localtool': 'localtool'} and got['outside'] == old['outside']),
    'quoted_names': ('a name with a space or a quote is not a name a shell finds by searching PATH: it is answered as absent without asking (the old script looked for a file of that name)',
                     lambda got, old: got['progs'] == {**old['progs'], 'weird name': '', "it's": ''} and got['outside'] == old['outside']),
    'versioned_in_two_directories': ('the versioned fallback takes the first of the versions found, in sorted order, across PATH; the old script took the first PATH directory that had any',
                                     lambda got, old: got == {'progs': {'zruby': 'zruby3.10'}, 'outside': {}}),
}


def answer(name, tmp, monkeypatch):
    b1, b2, home, ws, out = tree(tmp)
    make_path, progs, outside = CASES[name]
    outside = [p.format(out=out, home=home) for p in outside]
    env = {'PATH': make_path(b1, b2, ws), 'HOME': str(home), 'LC_ALL': 'C'}
    found = survey_of_disk(ws, progs=progs, outside=outside, env=env)
    clean = lambda d: {k.replace(str(tmp), '$T'): v for k, v in d.items()}      # noqa: E731
    return {'progs': clean(found.progs), 'outside': clean(found.outside)}


@pytest.mark.parametrize('name', sorted(CASES))
def test_the_survey_learns_what_the_coders_shell_resolves(tmp_path, monkeypatch, name):
    got = answer(name, tmp_path, monkeypatch)
    target = os.environ.get('CRIA_CHARACTERIZE')
    if target:
        path = pathlib.Path(target)
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = got
        path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False))
        return
    old = json.loads(FIXTURE.read_text())[name]
    if name in INTENDED:
        assert INTENDED[name][1](got, old), got
    else:
        assert got == old
