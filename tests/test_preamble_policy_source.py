"""Virtual-only provenance fixtures; never create instruction files on disk."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cria import assistruntime, loop, preamblepolicy as policy

OWN = '# House rules\r\n\r\nRun the local unit tests before reporting success.\r\n'
FOREIGN = 'An unrelated workspace rule.'
TASK = 'Implement the requested function. Preserve every existing public entry point.'
ROOT = '/virtual/workspace'
VERIFIED_BODY = ('Project instructions (from the repo — follow these):\n'
                 '# House rules\n\nRun the local unit tests before reporting success.\n\n'
                 'Working environment — cwd: /virtual/workspace, shell: bash, date: 2026-10-15, timezone: UTC.')
ENV_BODY = 'Working environment — cwd: /virtual/workspace, shell: bash, date: 2026-10-15, timezone: UTC.'
FIRST_READS = ['AGENTS.md', 'AGENT.md', 'CLAUDE.md', 'GEMINI.md', 'CONVENTIONS.md']
ALL_READS = FIRST_READS + ['.cursorrules', '.windsurfrules', '.github/copilot-instructions.md']


def preamble(instructions=OWN, root=ROOT, tag='INSTRUCTIONS'):
    # Literal observed harness prefix, entirely virtual. The filename is data,
    # not a test fixture created on disk or an instruction to this test runner.
    return (f'# AGENTS.md instructions for {root}\n<{tag}>{instructions}</{tag}>\n'
        f'<environment_context>\n<cwd>{root}</cwd>\n<shell>bash</shell>\n'
        '<current_date>2026-10-15</current_date>\n<timezone>UTC</timezone>\n'
        '<sandbox_mode>workspace-write</sandbox_mode>\n</environment_context>')


def message(text, role='user', **extra):
    return {'role': role, 'content': text, **extra}


class View:
    def __init__(self, bodies=None, surveyed=True):
        self.surveyed = surveyed
        self.bodies = bodies or {}
        self.reads = []

    def read(self, path):
        self.reads.append(path)
        return self.bodies.get(Path(path).relative_to(ROOT).as_posix())


@pytest.mark.parametrize('text,bodies,surveyed,body,provenance,reads', [
    (preamble(), {'CONVENTIONS.md': OWN}, True, VERIFIED_BODY, 'VERIFIED', FIRST_READS),
    (preamble(FOREIGN + '\n\n' + OWN), {'CONVENTIONS.md': OWN}, True, VERIFIED_BODY, 'VERIFIED', FIRST_READS),
    (preamble(FOREIGN), {'CONVENTIONS.md': OWN}, True, ENV_BODY, 'UNVERIFIED', ALL_READS),
    (preamble(), {}, True, ENV_BODY, 'UNVERIFIED', ALL_READS),
    (preamble(), {'CONVENTIONS.md': None}, True, ENV_BODY, 'UNVERIFIED', ALL_READS),
    (preamble(), {'CONVENTIONS.md': OWN}, False, ENV_BODY, 'UNSURVEYED', []),
    (preamble(tag='user_instructions'), {'CONVENTIONS.md': OWN}, True, VERIFIED_BODY, 'VERIFIED', FIRST_READS),
    ('<INSTRUCTIONS>' + OWN + '</INSTRUCTIONS>', {'CONVENTIONS.md': OWN}, True, None, 'NO_WORKSPACE', []),
    ('<environment_details>native shell metadata</environment_details>', {}, True, None, 'NOT_REQUESTED', []),
    ('<Environment_Context><cwd>/virtual/workspace</cwd></Environment_Context>', {}, True, None, 'NOT_REQUESTED', []),
    ('<environment_context><cwd>/virtual/workspace</cwd>', {}, True, None, 'NOT_REQUESTED', []),
    ('<environment_context><sandbox_mode>restricted</sandbox_mode></environment_context>', {}, True, None, 'NOT_REQUESTED', []),
    (TASK, {}, True, None, 'NOT_REQUESTED', []),
])
def test_source_parity(text, bodies, surveyed, body, provenance, reads):
    """Frozen provenance/body oracles survive retirement of the legacy Loop policy."""
    view = View(bodies, surveyed)
    original = message(text, provenance='harness', sequence=7)
    workspace = Mock(return_value=view)
    result = policy.reframe(policy.PreambleInput(original, workspace))
    if provenance in ('VERIFIED', 'UNVERIFIED', 'UNSURVEYED'):
        workspace.assert_called_once_with(ROOT)
    else:
        workspace.assert_not_called()
    assert result.message == {'role': 'user', 'content': text if body is None else body,
                              'provenance': 'harness', 'sequence': 7}
    assert result.instructions.provenance.name == provenance
    assert view.reads == [Path(ROOT) / name for name in reads]
    assert result.effect is (policy.Effect.UNCHANGED if body is None else policy.Effect.REFRAMED)
    if body is None:
        assert result.message is original
    assert original['content'] == text


def test_verified_part_keeps_literal_file_text_and_excludes_unverified_authority():
    view = View({'CONVENTIONS.md': OWN})
    result = policy.reframe(policy.PreambleInput(message(preamble(FOREIGN + '\n' + OWN)), lambda root: view))
    assert result.instructions.provenance is policy.Provenance.VERIFIED
    assert result.instructions.filename == 'CONVENTIONS.md'
    assert OWN.replace('\r', '').strip() in result.message['content']
    assert FOREIGN not in result.message['content']
    assert 'cwd: /virtual/workspace' in result.message['content']
    assert 'shell: bash' in result.message['content']
    assert 'date: 2026-10-15' in result.message['content']
    assert 'timezone: UTC' in result.message['content']
    assert 'sandbox_mode' not in result.message['content']
    assert view.bodies['CONVENTIONS.md'] == OWN


@pytest.mark.parametrize('bodies,surveyed,expected', [
    ({}, True, policy.Provenance.UNVERIFIED),
    ({'CONVENTIONS.md': None}, True, policy.Provenance.UNVERIFIED),
    ({'CONVENTIONS.md': FOREIGN}, True, policy.Provenance.UNVERIFIED),
    ({'CONVENTIONS.md': OWN}, False, policy.Provenance.UNSURVEYED),
])
def test_unknown_unreadable_and_unverified_do_not_assert_absence(bodies, surveyed, expected):
    view = View(bodies, surveyed)
    result = policy.reframe(policy.PreambleInput(message(preamble()), lambda root: view))
    assert result.instructions.provenance is expected
    assert result.instructions.text is None
    assert 'Project instructions' not in result.message['content']
    assert 'bash' in result.message['content']
    assert 'does not exist' not in result.message['content']
    if not surveyed:
        assert view.reads == []


def test_no_cwd_or_extractable_fields_keeps_raw_instead_of_destroying_user_directives():
    raw = message('<INSTRUCTIONS>Keep this legitimate user directive.</INSTRUCTIONS>')
    workspace = Mock(side_effect=AssertionError)
    result = policy.reframe(policy.PreambleInput(raw, workspace))
    assert result.message is raw
    assert result.instructions.provenance is policy.Provenance.NO_WORKSPACE
    workspace.assert_not_called()
    ordinary = message('Keep this legitimate user directive. <Context> is a component name.')
    assert policy.reframe(policy.PreambleInput(ordinary, workspace)).message is ordinary


@pytest.mark.parametrize('role', ['system', 'developer', 'assistant', 'tool'])
def test_nonuser_environment_and_tool_bytes_are_never_policy_input(role):
    raw = message(preamble(), role=role, tool_call_id='result-id', name='native-tool')
    workspace = Mock(side_effect=AssertionError)
    with patch.object(policy.selfcompact, 'is_env_context', side_effect=AssertionError):
        assert policy.reframe(policy.PreambleInput(raw, workspace)).message is raw
    workspace.assert_not_called()


def test_structured_text_part_body_matches_original_without_changing_other_metadata():
    raw = message([{'type': 'text', 'text': preamble()}, {'type': 'text', 'text': ''}], trace='same')
    view = View({'CONVENTIONS.md': OWN})
    result = policy.reframe(policy.PreambleInput(raw, lambda root: view))
    assert result.message == {'role': 'user', 'content': VERIFIED_BODY, 'trace': 'same'}
    assert result.message['trace'] == 'same'
    assert isinstance(raw['content'], list)


@pytest.mark.parametrize('synthetic', [False, True])
def test_real_coder_and_reasoner_body_parity(synthetic):
    view = View({'CONVENTIONS.md': OWN})
    messages = [message('Harness agent frame', role='system'),
                message('Harness configured constraint', role='developer'),
                message(preamble(FOREIGN + '\n' + OWN)), message(TASK),
                message('literal tool bytes\n<environment_context>tool data</environment_context>\n',
                        role='tool', tool_call_id='unmodified')]
    before = deepcopy(messages)
    def coder():
        return loop._frame_for_item(messages, 'Implement function', '', 1, 1, synthetic=synthetic)
    # Exercise the real consumers once. Comparing an adapter to a patched call
    # into its new owner would prove nothing about the delivered preamble.
    with patch.object(loop.wsview, 'current', return_value=view):
        actual_coder = coder()
        actual_reasoner = loop._drop_harness_frame(messages)
    assert actual_reasoner == [message(VERIFIED_BODY), messages[3], messages[4]]
    assert view.reads == [Path(ROOT) / name for name in FIRST_READS] * 2
    assert sum(m.get('content') == VERIFIED_BODY for m in actual_coder) == 1
    assert actual_coder[0]['role'] == 'system'
    assert not any(m.get('role') == 'developer' for m in actual_coder)
    assert not any(m.get('content') in ('Harness agent frame', 'Harness configured constraint')
                   for m in actual_coder)
    assert messages == before
    assert any(m['content'] == TASK for m in actual_coder)
    assert any(m['content'] == TASK for m in actual_reasoner)
    assert any(m is messages[-1] for m in actual_coder)
    assert actual_reasoner[-1] is messages[-1]


def test_disabled_stage_skips_recognition_reads_and_frame_mutation():
    raw = message(preamble())
    workspace = Mock(side_effect=AssertionError)
    with patch.object(policy.selfcompact, 'is_env_context', side_effect=AssertionError):
        result = policy.reframe(policy.PreambleInput(raw, workspace), enabled=False)
        assert result.message is raw
        assert result.effect is policy.Effect.NOT_SELECTED
        messages = [raw]
        assert policy.reframe_messages(policy.BatchInput(messages, workspace), None) is messages
        assert policy.reframe_messages(policy.BatchInput(messages, workspace), policy.DEFINITION,
                                       enabled=False) is messages
    workspace.assert_not_called()


def test_selected_replacement_is_the_only_batch_implementation():
    workspace = Mock(side_effect=AssertionError)
    raw = message(preamble())
    replacement_message = message('replacement')
    replacement = Mock(return_value=policy.PreambleResult(replacement_message, policy.Effect.REFRAMED))
    definition = replace(policy.DEFINITION, execute=replacement)
    selected = assistruntime.select_definitions((definition,), level=3)
    with patch.object(policy.selfcompact, 'is_env_context', side_effect=AssertionError):
        assert policy.reframe_messages(policy.BatchInput([raw], workspace), selected[0]) == [replacement_message]
    replacement.assert_called_once()
    workspace.assert_not_called()
    # Metadata preserves the earliest legacy handoff-evidence invocation, not
    # permission to start a coder/compactor on a lower engagement rung.
    assert assistruntime.select_definitions((definition,), level=0) == (definition,)
    assert dict(definition.policy.triggers) == {
        'harness-handoff-evidence': 0, 'compaction-context': 3, 'coder-frame': 4}
    assert assistruntime.select_definitions((definition,), level=5,
                                            disabled=(definition.policy.id,)) == ()
    assert not policy.DEFINITION.policy.migrated


def test_no_cached_provenance_across_mutation_task_reset_or_session():
    raw = message(preamble())
    first = View({'CONVENTIONS.md': OWN})
    other = View({'CONVENTIONS.md': FOREIGN})
    assert policy.reframe(policy.PreambleInput(raw, lambda root: first)).instructions.provenance is policy.Provenance.VERIFIED
    assert policy.reframe(policy.PreambleInput(raw, lambda root: other)).instructions.provenance is policy.Provenance.UNVERIFIED
    # A new task/current view needs no private reset: provenance is re-read, not
    # inherited from a previous successful lookup at the very same path.
    first.bodies['CONVENTIONS.md'] = 'Updated project rules'
    result = policy.reframe(policy.PreambleInput(raw, lambda root: first))
    assert result.instructions.provenance is policy.Provenance.UNVERIFIED
    updated = message(preamble('Updated project rules'))
    assert policy.reframe(policy.PreambleInput(updated, lambda root: first)).instructions.provenance is policy.Provenance.VERIFIED
    first.surveyed = False
    assert policy.reframe(policy.PreambleInput(updated, lambda root: first)).instructions.provenance is policy.Provenance.UNSURVEYED


def test_first_matching_file_precedence_and_whitespace_normalization_are_unchanged():
    view = View({'AGENT.md': 'alpha\n beta', 'CONVENTIONS.md': 'gamma'})
    result = policy.reframe(policy.PreambleInput(message(preamble('prefix alpha   beta gamma')), lambda root: view))
    assert result.instructions.filename == 'AGENT.md'
    assert result.instructions.text == 'alpha\n beta'
    assert view.reads == [Path(ROOT) / 'AGENTS.md', Path(ROOT) / 'AGENT.md']


def test_harness_handoff_evidence_uses_same_policy_without_owning_compaction_scope():
    from cria import server
    view = View({'CONVENTIONS.md': OWN})
    history = [message(preamble()), message(TASK),
               message('native result bytes\r\n', role='tool', tool_call_id='r'),
               message('Summarize the prior work.')]
    with patch.object(loop.wsview, 'current', return_value=view):
        actual = server._compaction_messages(history)
    assert actual == [message(VERIFIED_BODY), history[1], history[2]]
    assert view.reads == [Path(ROOT) / name for name in FIRST_READS]
    assert actual[-1] is history[-2]
    assert any(m is history[1] for m in actual)
    assert all(m is not history[-1] for m in actual)
