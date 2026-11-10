"""Characterisation of the config parse floor: what the model reads of the gate when a TOML, JSON or XML file of the project does not parse (and when it does).

`tests/fixtures/config_floor_characterization.json` is the capture of the route that shipped before Phase 9b: three Python one-liners (`tomllib`, `json`,
`xml.etree`) run by the harness as checks of the gate. `CRIA_CHARACTERIZE=<path>` writes a capture of the route under test instead. Each case is driven
through a real CriaServer at L5 over a scripted upstream and a harness that runs cria's calls with real bash on a real pty in a real workspace (the rig of the
gate's characterisation); what the MODEL READS of the gate is compared, byte for byte, except where `INTENDED` says otherwise, with the reason."""
import json
import os
import pathlib

import pytest

import gate_char_rig as rig
from ops_rig import isolated_home  # noqa: F401

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'config_floor_characterization.json'
PASS_TEST = rig.PASS_TEST
BIG_TOML = ''.join(f'[table{i}]\nkey = "value {i}"\nnumbers = [1, 2, 3]\n\n' for i in range(9000))      # ~300 KB: paged
BIG_JSON = '{"items": [' + ','.join('{"a": %d, "b": "x"}' % i for i in range(20000)) + ']}'


NAMES = []


def floor(name, files, expect, **extra):
    NAMES.append(name)
    rig.case(name, files, expect=expect, **extra)


# toml
floor('toml_bad', {'pyproject.toml': '[project\nname = "x"\n'}, 'pyproject.toml')
floor('toml_good', {'pyproject.toml': '[project]\nname = "x"\n', 'app.py': 'x = 1\n', 'test_app.py': PASS_TEST}, 'pytest -q — exit 0')
floor('toml_two_files', {'pyproject.toml': '[project]\nname = "x"\nname = "y"\n', 'sub/tool.toml': '[package\n', 'ok.toml': 'a = 1\n'}, 'tool.toml')
floor('toml_not_utf8', {'pyproject.toml': b'[project]\nname = "x\xff"\n'}, 'pyproject.toml')
floor('toml_crlf', {'pyproject.toml': '[project]\r\nname = "x"\r\n[oops\r\n'}, 'pyproject.toml')
floor('toml_empty', {'pyproject.toml': '', 'app.py': 'x = 1\n', 'test_app.py': PASS_TEST}, 'pytest -q — exit 0')
floor('toml_big_good', {'pyproject.toml': BIG_TOML, 'app.py': 'x = 1\n', 'test_app.py': PASS_TEST}, 'pytest -q — exit 0')
floor('toml_big_bad', {'pyproject.toml': BIG_TOML + '[broken\n'}, 'pyproject.toml')
floor('toml_in_skipped_dir', {'node_modules/x/pyproject.toml': '[bad\n', 'app.py': 'x = 1\n', 'test_app.py': PASS_TEST}, 'pytest -q — exit 0')
# json
floor('json_bad', {'package.json': '{"name": "x",}\n'}, 'package.json')
floor('json_good', {'package.json': '{"name": "x", "version": "1.0.0"}\n', 'app.py': 'x = 1\n', 'test_app.py': PASS_TEST}, 'pytest -q — exit 0')
floor('json_empty', {'package.json': ''}, 'package.json')
floor('json_bom', {'composer.json': '\ufeff{"name": "a/b"}\n'}, 'composer.json')
floor('json_not_utf8', {'package.json': b'{"name": "\xff"}\n'}, 'package.json')
floor('json_crlf', {'package.json': '{\r\n  "name": "x",\r\n  "v": oops\r\n}\r\n'}, 'package.json')
floor('json_two_files', {'package.json': '{"a": }', 'sub/composer.json': '[1, 2'}, 'composer.json')
floor('json_big_bad', {'package.json': BIG_JSON[:-3] + ',,]}'}, 'package.json')
# xml (the floor reads a build XML file only in a project directory, and only the names the project inventory knows: pom.xml and phpunit.xml[.dist])
PROJ = {'composer.json': '{"name": "a/b"}\n'}
floor('xml_bad', {**PROJ, 'phpunit.xml': '<project>\n  <a></b>\n</project>\n'}, 'phpunit.xml')
floor('xml_good', {**PROJ, 'phpunit.xml': '<?xml version="1.0"?>\n<!DOCTYPE project>\n<project><a>1</a></project>\n', 'app.py': 'x = 1\n', 'test_app.py': PASS_TEST}, 'pytest -q — exit 0')
floor('xml_empty', {**PROJ, 'phpunit.xml': ''}, 'phpunit.xml')
floor('xml_latin1', {**PROJ, 'phpunit.xml': b'<?xml version="1.0" encoding="iso-8859-1"?>\n<project><a>\xe9</a></project>\n', 'app.py': 'x = 1\n', 'test_app.py': PASS_TEST}, 'pytest -q — exit 0')
floor('xml_not_utf8', {**PROJ, 'phpunit.xml': b'<?xml version="1.0"?>\n<project><a>\xff</a></project>\n'}, 'phpunit.xml')
floor('xml_bom', {**PROJ, 'phpunit.xml.dist': b'\xef\xbb\xbf<web-app></web-app>\n', 'app.py': 'x = 1\n', 'test_app.py': PASS_TEST}, 'pytest -q — exit 0')
floor('xml_unclosed', {**PROJ, 'sub/composer.json': '{"name": "c/d"}\n', 'sub/phpunit.xml.dist': '<web-app>\n<a>\n'}, 'phpunit.xml.dist')
floor('xml_not_a_build_file', {**PROJ, 'data.xml': '<a>', 'app.py': 'x = 1\n', 'test_app.py': PASS_TEST}, 'pytest -q — exit 0')
# all three, with a python file that is broken too
floor('all_three_bad', {'pyproject.toml': '[x\n', 'package.json': '{', 'composer.json': '{"a": 1}', 'phpunit.xml': '<a>', 'app.py': 'def f(:\n    pass\n'}, 'phpunit.xml')
# the link and the directory
floor('toml_symlink', {'real/conf.toml': '[package\n'}, 'conf.toml', setup=lambda ws: (ws / 'pyproject.toml').symlink_to('real/conf.toml'))
floor('toml_dir_named_like_a_file', {'a.py': 'x = 1\n', 'test_app.py': PASS_TEST}, 'pytest -q — exit 0', setup=lambda ws: (ws / 'package.json').mkdir())

# name -> (what changed on purpose, whether the new text is the intended one)
INTENDED = {}


def text_of(block):
    return block.get('text') or block['head'] + block['tail']


@pytest.mark.parametrize('name', sorted(NAMES))
def test_case(tmp_path, monkeypatch, name):
    got = rig.run_case(rig.CASES[name], tmp_path, monkeypatch)
    target = os.environ.get('CRIA_CHARACTERIZE')
    if target:
        path = pathlib.Path(target)
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = got
        path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False))
        return
    old = json.loads(FIXTURE.read_text())[name]
    assert got['litter'] == []
    new_texts, old_texts = [e for e in got['evidence']], [e for e in old['evidence']]
    if name in INTENDED:
        assert INTENDED[name][1](got, old), [text_of(e)[:400] for e in new_texts]
    else:
        assert new_texts == old_texts, ([text_of(e)[:600] for e in new_texts], [text_of(e)[:600] for e in old_texts])
