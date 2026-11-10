"""The survey's one harness-side text (cria/surveyops.py `probe_script`) is straight-line shell: one question per line, no loop and no branch, nothing decided in
it, and nothing it prints can teach cria anything it did not ask. The answers themselves are characterised against the old route in
test_survey_probe_characterization.py."""
import re
import shutil
import subprocess

import pytest
from survey_fixtures import survey_of_disk

from cria import surveyops
from ops_rig import isolated_home  # noqa: F401

CONTROL_FLOW = re.compile(r'(^|[;&|{(]\s*)(for|while|until|if|case|function)\b|;\s*(do|then|done|fi|esac)\b|\bwhile\b|\bexec\b|\beval\b|`|\$\(')


def run_text(text, env, cwd, shell='bash'):
    done = subprocess.run([shell], input=text, cwd=cwd, env=env, capture_output=True, text=True, timeout=30)
    return done.stdout + done.stderr, done.returncode


def test_the_text_is_straight_line_shell_and_small(tmp_path):
    text = surveyops.probe_script(['tool', 'zruby', 'a-b.c+d_e'], ['/a b', '~', '~/x y', '/var/lib/x'])
    assert not CONTROL_FLOW.search(text), text
    assert max(len(line) for line in text.split('\n')) < 200
    assert len(text) < 120 + 150 * 7
    # a name that is not a program name is not sent to the shell at all (it would be data in a command)
    unsafe = surveyops.probe_script(['weird name', 'a;b', '$(x)', '`x`', "it's", '', 'a/b'], [])
    assert unsafe == surveyops.probe_script([], [])


def test_a_path_with_shell_syntax_is_data_and_runs_nothing(tmp_path):
    marker = tmp_path / 'ran'
    paths = [f'$(touch {marker})', f'`touch {marker}`', f"x'; touch {marker}; '", f'/a\ntouch {marker}\n', f'~/$(touch {marker})']
    text = surveyops.probe_script([], paths)
    out, code = run_text(text, {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path)}, tmp_path)
    assert code == 0 and not marker.exists() and out.count('O\t') == len(paths), out


def test_what_a_file_name_prints_teaches_nothing(tmp_path):
    """Files on PATH named like headers, like another program or like an answer: only the exact name (or the name and a version) is taken."""
    bin_ = tmp_path / 'bin'
    bin_.mkdir()
    for name in ('tool', 'tool\nP\t1', 'P\t1\nzruby9', 'zruby3.2\nzruby3.1', 'O\t0\td', 'B\t1', 'zruby3.7', 'zrubyx'):
        f = bin_ / name
        f.write_text('#!/bin/sh\n')
        f.chmod(0o755)
    asked = ['tool', 'zruby', 'P', 'O', 'B', 'absent']
    out, code = run_text(surveyops.probe_script(asked, ['/']), {'PATH': f'{bin_}:/usr/bin:/bin', 'HOME': str(tmp_path)}, tmp_path)
    assert code == 0
    assert surveyops._resolved(out, asked) == {'tool': 'tool', 'zruby': 'zruby3.7', 'P': '', 'O': '', 'B': '', 'absent': ''}, out
    found = survey_of_disk(tmp_path, progs=asked, outside=['/'], env={'PATH': f'{bin_}:/usr/bin:/bin', 'HOME': str(tmp_path)})
    assert found.progs == {'tool': 'tool', 'zruby': 'zruby3.7', 'P': '', 'O': '', 'B': '', 'absent': ''} and found.outside == {'/': 'd'}


def test_a_program_named_like_a_marker_is_found_when_it_is_there(tmp_path):
    bin_ = tmp_path / 'bin'
    bin_.mkdir()
    for name in ('P', 'O', 'B'):
        (bin_ / name).write_text('#!/bin/sh\n')
        (bin_ / name).chmod(0o755)
    found = survey_of_disk(tmp_path, progs=['P', 'O', 'B'], env={'PATH': f'{bin_}:/usr/bin:/bin', 'HOME': str(tmp_path)})
    assert found.progs == {'P': 'P', 'O': 'O', 'B': 'B'}


def test_a_shell_without_the_features_answers_no_program_and_never_absent(tmp_path):
    if not shutil.which('dash'):
        pytest.skip('no dash here')
    text = surveyops.probe_script(['tool', 'sh'], ['/', '/nonexistent'])
    out, _ = run_text(text, {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path)}, tmp_path, shell='dash')
    assert surveyops._resolved(out, ['tool', 'sh']) == {}          # nothing is claimed absent: the shell could not answer
    assert 'O\t0\td' in out and 'O\t1\t-' in out                  # the plain tests still work


def test_the_wire_answer_is_read_by_name_only_for_the_names_asked():
    assert surveyops._resolved("B\t1\nP\t0\ntool\nP\t9\nzruby\n", ['tool']) == {'tool': 'tool'}
    assert surveyops._resolved('P\t0\ntool\n', ['tool']) == {}
    assert surveyops._resolved("B\t1\nP\t0\ntool2\ntool10.2.x\ntool10.2\ntool3\n", ['tool']) == {'tool': 'tool10.2'}
