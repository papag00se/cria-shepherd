"""The config-file syntax floor is cria's own (cria/configfloor.py, cria/floorops.py): the harness is asked for the bytes of each file with `read` and runs no
program for it. Real stubs, real bash, real directories. What the model reads of the gate, case by case against the old route (three Python one-liners run
in the harness), is test_config_floor_characterization.py."""
import os
import pathlib
import random
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ops_rig import isolated_home  # noqa: F401,E402
from survey_fixtures import gate_of_disk  # noqa: E402

from cria import configfloor, gatescript, probegate, proberun  # noqa: E402
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind, cand  # noqa: E402

# The three programs the harness used to run (kept here as the oracle: the messages cria prints must be the ones these printed).
OLD_TOML = ("import sys\ntry:\n    import tomllib\nexcept ModuleNotFoundError:\n    sys.exit(0)\nbad = 0\nfor f in sys.argv[1:]:\n    try:\n"
            "        with open(f, 'rb') as fh:\n            tomllib.load(fh)\n    except Exception as e:\n        print('%s: %s' % (f, e))\n        bad = 1\nsys.exit(bad)\n")
OLD_JSON = ("import sys, json\nbad = 0\nfor f in sys.argv[1:]:\n    try:\n        with open(f) as fh:\n            json.load(fh)\n    except Exception as e:\n"
            "        print('%s: %s' % (f, e))\n        bad = 1\nsys.exit(bad)\n")
OLD_XML = ("import sys\nfrom xml.etree import ElementTree as ET\nbad = 0\nfor f in sys.argv[1:]:\n    try:\n        ET.parse(f)\n    except Exception as e:\n"
           "        print('%s: %s' % (f, e))\n        bad = 1\nsys.exit(bad)\n")
OLD = {'toml': OLD_TOML, 'json': OLD_JSON, 'xml': OLD_XML}
GOOD = {'toml': b'[a]\nb = 1\n', 'json': b'{"a": [1, 2, {"b": null}]}', 'xml': b'<a><b x="1">t</b></a>'}


def old_says(fmt, path):
    done = subprocess.run([sys.executable, '-I', '-c', OLD[fmt], str(path)], capture_output=True, text=True, env={'LC_ALL': 'C.UTF-8', 'PATH': '/usr/bin:/bin'})
    return done.stdout.rstrip('\n'), done.returncode


def new_says(fmt, path, raw=None):
    line = configfloor.error(fmt, pathlib.Path(path).read_bytes() if raw is None else raw, str(path))
    return line, 1 if line else 0


def mutants(fmt, seed):
    """Hand-picked broken inputs and random damage to good ones: what a coder's edit does to a config file."""
    rng = random.Random(seed)
    base = GOOD[fmt]
    out = [b'', b'\n', b' ', b'\xef\xbb\xbf' + base, b'\xff' + base, base + b'\x00', base.replace(b'\n', b'\r\n'), base.replace(b'\n', b'\r'), base[:-1], base[:len(base) // 2],
           base + base, b'\x80', 'é'.encode('latin-1') + base, b'[' * 2000, b'{' * 2000 if fmt == 'json' else b'<a>' * 2000]
    for _ in range(40):
        raw = bytearray(base)
        for _ in range(rng.randint(1, 3)):
            kind, at = rng.randint(0, 2), rng.randrange(len(raw) + 1)
            if kind == 0 and raw:
                del raw[min(at, len(raw) - 1)]
            elif kind == 1:
                raw.insert(at, rng.choice(b'[]{}<>"\'=,:\n\r\x00\xff'))
            elif raw:
                raw[min(at, len(raw) - 1)] = rng.choice(b'[]{}<>"\'=,:\n\r\x00\xff')
        out.append(bytes(raw))
    return out


@pytest.mark.parametrize('fmt', ['toml', 'json', 'xml'])
def test_what_cria_says_of_a_file_is_what_the_python_programs_said(tmp_path, fmt):
    for i, raw in enumerate([GOOD[fmt], *mutants(fmt, fmt)]):
        f = tmp_path / f'f{i}.cfg'
        f.write_bytes(raw)
        old, new = old_says(fmt, f), new_says(fmt, f)
        assert new == old, (fmt, raw[:80], old, new)


def test_an_unreadable_file_is_the_one_liners_oserror_text(tmp_path):
    for fmt in ('toml', 'json', 'xml'):
        missing, directory = tmp_path / f'missing.{fmt}', tmp_path / f'dir.{fmt}'
        directory.mkdir()
        assert configfloor.unreadable(str(missing), 2) == old_says(fmt, missing)[0]
        assert configfloor.unreadable(str(directory), 21) == old_says(fmt, directory)[0]


# ---------------------------------------------------------------- through the gate

def floor(fmt, root, *names):
    return cand(ProbeKind.SyntaxCheck, [configfloor.HEADS[fmt], *(str(root / n) for n in names)], root, 95, 95, ProbeCost.Cheap, 't', composed_by_cria=True, parsed_by_cria=fmt)


def real(root, program, kind=ProbeKind.BuildCheck):
    return ProbeCandidate(kind=kind, command=['sh', '-c', program], working_dir=str(root), confidence=90, expected_value=80, cost=ProbeCost.Cheap,
                          mutates_code=False, may_hang=False, may_need_services=False, reason='t')


def gate(root, candidates, **kw):
    """The gate as the loop issues it: the harness script holds the project's own checks only, the gate's facts hold every check of the plan."""
    script, sections = gatescript.compose([c for c in candidates if not c.parsed_by_cria], str(root), 240.0, (str(root),))
    return gate_of_disk(root, candidates, script=script, sections=sections, **kw)


def test_floor_sections_are_numbered_by_the_plan_and_carry_the_one_liners_text_and_status(tmp_path):
    (tmp_path / 'a.toml').write_text('[a]\nb = 1\n')
    (tmp_path / 'bad.toml').write_text('[a\n')
    (tmp_path / 'package.json').write_text('{"a": 1,}')
    (tmp_path / 'pom.xml').write_text('<a><b></a>')
    ran, rounds = [], []
    plan = [real(tmp_path, 'echo first; exit 2'), floor('toml', tmp_path, 'a.toml', 'bad.toml'), floor('json', tmp_path, 'package.json'), real(tmp_path, 'echo last', ProbeKind.Test),
            floor('xml', tmp_path, 'pom.xml')]
    r = gate(tmp_path, plan, ran=ran, rounds=rounds)
    assert r.complete
    assert list(r.sections) == ['probe-0', 'probe-1', 'probe-2', 'probe-3', 'probe-4', 'offline']
    assert r.sections['probe-0'] == ('first\n', 2) and r.sections['probe-3'] == ('last\n', 0)
    assert r.sections['probe-1'] == (f"{tmp_path}/bad.toml: Expected ']' at the end of a table declaration (at line 1, column 3)\n", 1)
    assert r.sections['probe-2'] == (f'{tmp_path}/package.json: Illegal trailing comma before end of object: line 1 column 8 (char 7)\n', 1)
    assert r.sections['probe-4'] == (f'{tmp_path}/pom.xml: mismatched tag: line 1, column 8\n', 1)
    assert r.removed == ['aux/'] and r.failed == []
    # the harness was asked for no program of the floor: the files came through `read`, and the checks' script holds the project's own checks only
    assert not [c for c in ran if 'tomllib' in c or 'json.load(fh)' in c or 'ElementTree' in c or 'toml-syntax' in c or 'json-syntax' in c]
    assert sum('repository checks (config)' in c for c in ran) == 4
    start = next(c for c in ran if c.startswith('# repository checks') and 'run' in c and 'echo first' in c)
    assert 'toml' not in start.split("<<'CTX_EOF")[-1] and 'pom.xml' not in start


def test_a_clean_floor_is_exit_zero_and_empty_and_only_floor_checks_still_run_a_gate(tmp_path):
    (tmp_path / 'a.toml').write_text('x = 1\n')
    (tmp_path / 'package.json').write_text('{}')
    r = gate(tmp_path, [floor('toml', tmp_path, 'a.toml'), floor('json', tmp_path, 'package.json')])
    assert r.complete and r.sections == {'probe-0': ('', 0), 'probe-1': ('', 0)}
    assert os.listdir(str(tmp_path) + '.scratch') == ['bin']             # the run's directory is gone as for any gate


def test_a_file_the_harness_cannot_read_says_so_in_the_one_liners_words(tmp_path):
    (tmp_path / 'a.toml').write_text('x = 1\n')
    (tmp_path / 'dir.json').mkdir()
    r = gate(tmp_path, [floor('toml', tmp_path, 'a.toml', 'gone.toml'), floor('json', tmp_path, 'dir.json')])
    assert r.sections['probe-0'] == (f'{tmp_path}/gone.toml: [Errno 2] No such file or directory: {str(tmp_path / "gone.toml")!r}\n', 1)
    assert r.sections['probe-1'] == (f'{tmp_path}/dir.json: [Errno 21] Is a directory: {str(tmp_path / "dir.json")!r}\n', 1)


def test_a_check_that_cannot_be_evaluated_has_no_section_and_is_never_clean(tmp_path, monkeypatch):
    """Too large, reached through a link, changed under the read: the check did not run (the gate lists it as such), and the other checks are read."""
    (tmp_path / 'big.toml').write_text('# ' + 'x' * 5000 + '\nx = 1\n')
    (tmp_path / 'real.toml').write_text('x = 1\n')
    (tmp_path / 'link.toml').symlink_to('real.toml')
    (tmp_path / 'ok.json').write_text('{}')
    monkeypatch.setattr(configfloor, 'FILE_MAX', 4000)
    r = gate(tmp_path, [floor('toml', tmp_path, 'big.toml'), floor('toml', tmp_path, 'link.toml'), floor('json', tmp_path, 'ok.json'), real(tmp_path, 'echo hi')])
    assert r.complete and r.sections == {'probe-2': ('', 0), 'probe-3': ('hi\n', 0)}


def test_a_file_that_changes_while_it_is_read_is_not_judged(tmp_path):
    target = tmp_path / 'big.json'
    target.write_text('[' + ','.join(str(i) for i in range(30000)) + ']')
    seen = []

    def change(command, text):
        if 'repository checks (config)' in command:
            seen.append(1)
            if len(seen) == 2:
                target.write_text('[' + ','.join(str(i + 1) for i in range(30000)) + ']')        # the file moves under the second page
        return text
    r = gate(tmp_path, [floor('json', tmp_path, 'big.json')], alter=change)
    assert r.complete and 'probe-0' not in r.sections and len(seen) > 2


def test_a_big_file_is_paged_whole_and_checked_against_its_hash(tmp_path):
    target = tmp_path / 'big.toml'
    target.write_text(''.join(f'[t{i}]\nkey = "value {i}"\n\n' for i in range(9000)) + '[broken\n')
    ran = []
    r = gate(tmp_path, [floor('toml', tmp_path, 'big.toml')], ran=ran)
    assert r.sections['probe-0'] == (f"{target}: Expected ']' at the end of a table declaration (at line 27001, column 8)\n", 1)
    assert sum('repository checks (config)' in c for c in ran) > 4


def test_a_frame_the_harness_cut_is_asked_again_smaller(tmp_path):
    target = tmp_path / 'big.json'
    import hashlib
    target.write_text('{"k": [' + ','.join('"' + hashlib.sha256(str(i).encode()).hexdigest() + '"' for i in range(1000)) + ']')
    cuts = []

    def cut(command, text):
        if 'repository checks (config)' in command and len(text) > 5000:
            cuts.append(1)
            return text[:2000] + '\n… 77 chars truncated …\n' + text[-2000:]
        return text
    r = gate(tmp_path, [floor('json', tmp_path, 'big.json')], alter=cut)
    text, code = r.sections['probe-0']
    assert cuts and code == 1 and text == f"{target}: Expecting ',' delimiter: line 1 column {len(target.read_text()) + 1} (char {len(target.read_text())})\n"


def test_a_restarted_cria_reads_the_same_floor(tmp_path):
    (tmp_path / 'bad.toml').write_text('[a\n')
    (tmp_path / 'ok.json').write_text('{}')
    plan = [floor('toml', tmp_path, 'bad.toml'), real(tmp_path, 'echo hi'), floor('json', tmp_path, 'ok.json')]
    steady = gate(tmp_path, plan)
    again = gate(tmp_path, plan, restart=True)
    assert steady.sections == again.sections and steady.sections['probe-0'][1] == 1 and steady.sections['probe-2'] == ('', 0)


def test_a_workspace_that_shadows_the_interpreter_runs_nothing_while_the_floor_is_read(tmp_path):
    (tmp_path / 'bin').mkdir()
    marker = tmp_path / 'ran'
    for name in ('python3', 'env', 'bash', 'sh', 'base64', 'cat'):
        (tmp_path / 'bin' / name).write_text(f'#!/bin/sh\necho {name} >> {marker}\nexit 0\n')
        (tmp_path / 'bin' / name).chmod(0o755)
    for mod in ('hashlib', 'base64', 'json', 'os', 'sys', 'zlib', 'sitecustomize', 'tomllib', 'xml'):
        (tmp_path / f'{mod}.py').write_text(f'open({str(marker)!r}, "w").write("x")\n')
    (tmp_path / 'p.toml').write_text('[a\n')
    r = gate(tmp_path, [floor('toml', tmp_path, 'p.toml')], env={'PATH': f'{tmp_path / "bin"}:/usr/bin:/bin', 'PYTHONPATH': str(tmp_path)})
    assert not marker.exists() and r.sections['probe-0'][1] == 1


# ---------------------------------------------------------------- the plan

def test_the_plan_names_the_floor_and_the_script_does_not_run_it(tmp_path, monkeypatch):
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n')
    (tmp_path / 'package.json').write_text('{}')
    (tmp_path / 'app.py').write_text('x = 1\n')
    from cria import linterprobe, probediscovery, toolpath, wsview
    monkeypatch.setattr(linterprobe, 'collect_files', lambda root, exts: [str(tmp_path / 'pyproject.toml')] if exts == ['toml'] else [str(tmp_path / 'app.py')] if exts == ['py'] else [])
    monkeypatch.setattr(probediscovery, '_strict_json_files', lambda root: [str(tmp_path / 'package.json')])
    monkeypatch.setattr(probediscovery, '_strict_xml_files', lambda root: [])
    found = probediscovery.syntax_floor_candidates(tmp_path)
    parsed = [c for c in found if c.parsed_by_cria]
    assert [(c.parsed_by_cria, c.command) for c in parsed] == [('toml', ['toml-syntax', str(tmp_path / 'pyproject.toml')]), ('json', ['json-syntax', str(tmp_path / 'package.json')])]
    assert all(c.composed_by_cria and c.kind is ProbeKind.SyntaxCheck for c in parsed)
    # a program the coder's shell does not resolve drops a check; these checks run no program there
    monkeypatch.setattr(toolpath, 'resolved', lambda program: '')
    assert all(proberun.program_is_installed(c) for c in parsed) and not proberun.program_is_installed(found[0])
    plan = probegate.GatePlan(workspace=str(tmp_path), candidates=found)
    script, sections = gatescript.compose([c for c in plan.candidates if not c.parsed_by_cria], str(tmp_path), 240.0, ())
    assert 'toml' not in script and 'package.json' not in script and sections == ['probe-0']
    del wsview


def test_the_check_a_persisted_gate_keeps_is_recognised_by_what_it_is_not_by_its_words():
    assert configfloor.format_of('SyntaxCheck', True, ['toml-syntax', 'a.toml']) == 'toml'
    assert configfloor.format_of('SyntaxCheck', False, ['toml-syntax', 'a.toml']) == ''           # a project's own command of that name is a command
    assert configfloor.format_of('Test', True, ['toml-syntax', 'a.toml']) == ''
    assert configfloor.format_of('SyntaxCheck', True, ['node', '--check', 'a.js']) == ''
