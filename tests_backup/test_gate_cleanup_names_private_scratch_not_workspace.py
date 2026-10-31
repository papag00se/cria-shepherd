"""The gate's cleanup note must not read as a statement about the coder's own files.

Incident, run 20261027T035849 (ornith1.5_9b / Java, until75-6f279c1b): the coder kept its own
scratch in a workspace ``aux/`` (``aux/TestBigDecimal.java``, ``aux/baseline.txt``). Every gate
result then carried ``⟦ctx:checks-cleanup⟧ The harness reclaimed these exclusively owned private
temporary check resources ...:`` followed by the bare line ``"aux/"`` — the harness's PRIVATE
auxiliary directory, named relative to its private scratch directory, with nothing saying so.
The coder reasoned "the checker just reclaimed aux/ ... So aux/ might be GONE now!" (0064) and
"The diagnostic is a scratch file in aux/ which the harness reclaims" (0097); briefing 0067 wrote
"The `aux/` directory was reclaimed by the harness after the checker ran, so the test harness is no
longer on disk", was judged FAITHFUL and delivered, and refold 0084 carried it on — while the same
evidence showed ``aux/TestBigDecimal.java`` being read back and listed by the workspace survey.
Across captured coder prompts the note rendered 3,728 times, every time as exactly that one line.

The cleanup facts stay (a real removal is still reported, failures still are); what changes is
that every path says what it is relative to."""
import json
import os
import re

from cria import probegate, prompts
from test_gate_cleanup_finishes_before_coder_resumes import auxiliary, exact_profile, run_gate  # noqa: F401
from test_historical_gate_scope_remains_bound import history


def _render(plan, raw, extra=()):
    messages = history(plan, raw) + list(extra)
    return probegate.clean_gate_results(messages)


def _cleanup_block(text):
    start = text.index('⟦ctx:checks-cleanup⟧ The harness reclaimed')
    return text[start:]


def test_a_reclaimed_private_path_is_never_rendered_as_a_bare_workspace_looking_path(tmp_path, monkeypatch):
    # The coder's OWN aux/ directory, holding its own files, exists before the gate runs.
    (tmp_path / 'aux').mkdir()
    (tmp_path / 'aux' / 'baseline.txt').write_text('SKU-00000: 4326.28\n')
    plan, raw = run_gate(tmp_path, monkeypatch)
    rendered = _render(plan, raw)
    block = _cleanup_block('\n'.join(m.get('content') or '' for m in rendered))
    path_lines = [line for line in block.splitlines()[1:] if '"aux' in line]
    assert path_lines, block
    # Before the fix the note's lines were exactly `"aux/compiled"` and `"aux/"`: a JSON string
    # alone on its line, indistinguishable from a workspace-relative path.
    for line in path_lines:
        assert not re.fullmatch(r'\s*"[^"]*"\s*', line), block
        assert 'private check scratch directory' in line, block
    assert 'not to the workspace' in block, block


def test_the_real_cleanup_is_still_reported_and_the_coder_files_are_untouched(tmp_path, monkeypatch):
    (tmp_path / 'aux').mkdir()
    (tmp_path / 'aux' / 'baseline.txt').write_text('SKU-00000: 4326.28\n')
    plan, raw = run_gate(tmp_path, monkeypatch)
    rendered = _render(plan, raw)
    text = '\n'.join(m.get('content') or '' for m in rendered)
    block = _cleanup_block(text)
    # Control 1: the harness's real removals are still named, with their exact path text.
    assert json.dumps('aux/compiled') in block and json.dumps('aux/') in block
    assert not auxiliary(plan).exists()
    # The world agrees with the note: the coder's same-named directory and file survive.
    assert (tmp_path / 'aux' / 'baseline.txt').read_text() == 'SKU-00000: 4326.28\n'
    # The checker's own voice is untouched.
    assert 'native build output for output/compiled' in text


def test_a_coder_result_naming_its_own_aux_path_passes_through_as_the_coders(tmp_path, monkeypatch):
    (tmp_path / 'aux').mkdir()
    (tmp_path / 'aux' / 'baseline.txt').write_text('x\n')
    plan, raw = run_gate(tmp_path, monkeypatch)
    listing = 'total 4\n-rw------- 1 u u 2 Oct 27 04:07 baseline.txt\n'
    coder = [{'role': 'assistant', 'tool_calls': [{'id': 'ls', 'type': 'function', 'function': {
                 'name': 'exec_command', 'arguments': json.dumps({'cmd': 'ls -la aux/'})}}]},
             {'role': 'tool', 'tool_call_id': 'ls', 'content': listing}]
    rendered = _render(plan, raw, coder)
    assert rendered[-1] == coder[-1]            # byte-identical: the coder's result stays the coder's
    assert rendered[-2] == coder[-2]


def test_no_internal_name_reaches_the_model(tmp_path, monkeypatch):
    plan, raw = run_gate(tmp_path, monkeypatch)
    gate_text = '\n'.join(m.get('content') or '' for m in _render(plan, raw) if m.get('role') == 'tool')
    assert 'cria' not in _cleanup_block(gate_text).lower()
    for name in ('checks_artifacts_removed', 'checks_cleanup_failed'):
        assert 'cria' not in prompts.load(name).lower()


def test_failures_qualify_private_paths_and_keep_absolute_ones_as_stated(tmp_path):
    workspace = str(tmp_path)
    record = dict(removed=[], failed=[dict(path='aux', error='directory_identity_changed'),
                                      dict(path=workspace, error='workspace_identity_changed')],
                  requested_workspace=workspace)
    note = probegate.cleanup_fact({probegate.LITTER_REMOVED_SECTION: json.dumps(record)})
    lines = note.splitlines()
    private = [line for line in lines if json.dumps('aux') in line]
    absolute = [line for line in lines if json.dumps(workspace) in line]
    assert private and all('private check scratch directory' in line for line in private), note
    assert 'directory_identity_changed' in note and 'workspace_identity_changed' in note
    # An absolute path is already unambiguous: it is stated as it is, never relabelled as private.
    assert absolute and not any('private check scratch directory' in line for line in absolute), note
    assert os.path.isabs(workspace)
