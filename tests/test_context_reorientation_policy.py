from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cria import reorientation as policy

# Frozen public/request bytes, not output from a retiring Loop adapter.
FALLBACK = ('context notice: the harness just compacted this conversation — earlier turns were replaced '
            'by a summary, so history above is lossy. Work it describes may be YOUR OWN from earlier in '
            "THIS session, not another agent's. Before creating any file or redoing a step, INSPECT the "
            'workspace first (list the directory, read the files that should already exist) and continue '
            'from what is actually there — do NOT recreate files or restart work that is already done.')
AUTHOR_SYSTEM = ("The coder's working history was just COMPACTED into the summary you are given — it no longer sees "
    'its own prior turns, only that summary, and a weak model in this state tends to DISOWN its earlier work '
    'and re-create files that already exist. From the summary, briefly orient the coder: state what has '
    'already been built (so it does not redo or duplicate it) and what still remains to finish the task, '
    'and tell it to INSPECT the existing files on disk before creating anything, then continue.\n\n'
    'The separately labelled original task governs requirements: requirements are not evidence of completed work. '
    'Do not relax, replace or drop them because the historical continuation describes a difficulty or a different approach. '
    'If the original task is unavailable, do not infer its requirements from that continuation. '
    'The coder retains any original task supplied separately; this directive does not replace it.\n\n'
    'For claims about work already done or its present state, say ONLY what the summary and the file listing beneath it state. If neither says what was built, '
    'or neither says what remains, say plainly that it does not and tell the coder to read the files on '
    'disk to find out. Never fill either gap with a guess: a list of remaining work that turns out to be '
    'already done sends the coder back into finished code to break it.\n\n'
    'Point only at what already exists. Never name a project, crate, file, module or command that neither '
    'the summary nor the file listing already names, and never tell the coder to start over, re-create, '
    'or begin a new project — whatever is on disk is the work, and a re-orientation that renames it destroys it.\n\n'
    'Output ONLY that directive to the coder — no preamble, no meta-commentary.')


AUTHOR_CONTEXT = ('ORIGINAL TASK — governing requirements, not evidence of completed work:\n'
    'ORIGINAL TASK\n\n'
    'HISTORICAL CONTINUATION — an account of earlier work, not permission to change requirements:\n'
    '⟦ctx:continuation⟧ summary\n\n'
    'WORKSPACE INVENTORY — use its stated coverage, filtering and freshness limits:\n'
    'current inventory')


class Log:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


def source(text='Inspect the existing files before creating anything.', **changes):
    log = Log()
    values = dict(rewritten=True,
                  facts=lambda: policy.ReorientationFacts(('ORIGINAL TASK', '⟦ctx:continuation⟧ summary'), True, 'ORIGINAL TASK'),
                  inventory=Mock(return_value='current inventory'), author=Mock(return_value=text),
                  consume_rewrite=Mock(), log=log)
    return policy.ReorientationInput(**(values | changes))


@pytest.mark.parametrize('answer,reason,directive,events', [
    ('Inspect the existing files.', 'authored', 'Inspect the existing files.', []),
    ('', 'empty', FALLBACK, []),
    ('```bash\ncat made-up\n```', 'script', FALLBACK,
     [('loop.reanchor_refused', {'level': 'warn', 'lines': 2, 'head': '```bash\ncat made-up\n```'})]),
    ('Inspect phantom.py', 'ungrounded', FALLBACK,
     [('loop.reanchor_ungrounded', {'level': 'warn', 'names': 'phantom.py', 'head': 'Inspect phantom.py'})])])
def test_reasoned_source_parity(answer, reason, directive, events):
    """A script or invented name never becomes the coder's continuation directive."""
    item = source(answer)
    result = policy.reorient(item)
    assert result.message == {'role': 'user', 'content': '⟦ctx:steer⟧ ' + directive}
    assert result.reason == reason
    assert result.consumed is True
    assert item.log.events == events
    item.author.assert_called_once_with(policy.AuthorRequest(
        AUTHOR_SYSTEM, AUTHOR_CONTEXT, 'reasoner'))
    item.inventory.assert_called_once_with()
    item.consume_rewrite.assert_called_once_with()


@pytest.mark.parametrize('available,summary', [
    (False, policy.CONTINUATION_MARKER + ' summary'),
    (True, 'only original task'),
    (True, policy.CONTINUATION_MARKER + ' ' + policy.DROPPED_PROSE_LEAD)])
def test_existing_alternative_without_extra_questions(available, summary):
    item = source(facts=lambda: policy.ReorientationFacts((summary,), available))
    result = policy.reorient(item)
    assert result.message['content'] == '⟦ctx:steer⟧ ' + FALLBACK
    item.author.assert_not_called()
    item.inventory.assert_not_called()
    item.consume_rewrite.assert_called_once_with()


def test_disabled_and_no_rewrite_have_no_owned_effects():
    bomb = Mock(side_effect=AssertionError)
    item = source(facts=bomb, inventory=bomb, author=bomb, consume_rewrite=bomb)
    assert policy.DEFINITION.execute(item, enabled=False).message is None
    assert policy.reorient(replace(item, rewritten=False)).message is None
    bomb.assert_not_called()


def test_explicit_none_defers_acknowledgement_without_changing_prepared_directive():
    item = source('Inspect the existing files.', consume_rewrite=None)
    result = policy.reorient(item)
    assert result == policy.ReorientationResult(
        {'role': 'user', 'content': '⟦ctx:steer⟧ Inspect the existing files.'}, 'authored', False)
    item.author.assert_called_once_with(policy.AuthorRequest(
        AUTHOR_SYSTEM, AUTHOR_CONTEXT, 'reasoner'))
    item.inventory.assert_called_once_with()
    assert item.log.events == []


def test_deferred_acknowledgement_keeps_disabled_and_no_rewrite_lazy():
    bomb = Mock(side_effect=AssertionError)
    item = source(facts=bomb, inventory=bomb, author=bomb, consume_rewrite=None)
    assert policy.reorient(item, enabled=False) == policy.ReorientationResult(None, 'not-selected', False)
    assert policy.reorient(replace(item, rewritten=False)) == policy.ReorientationResult(None, 'no-rewrite', False)
    bomb.assert_not_called()


def test_consumption_mode_must_be_supplied_explicitly():
    item = source()
    with pytest.raises(TypeError, match='consume_rewrite'):
        policy.ReorientationInput(rewritten=item.rewritten, facts=item.facts,
            inventory=item.inventory, author=item.author, log=item.log)
    item.author.assert_not_called()
    item.consume_rewrite.assert_not_called()


def test_retry_consumption_and_session_isolation():
    pending = {'first': True, 'other': True}
    item = source(consume_rewrite=lambda: pending.__setitem__('first', False))
    assert policy.reorient(item).consumed
    assert not policy.reorient(replace(item, rewritten=pending['first'])).consumed
    assert pending['other']
    item.author.assert_called_once()
    replacement = lambda source: policy.ReorientationResult(None, 'replacement', False)
    assert replace(policy.DEFINITION, execute=replacement).execute(item).reason == 'replacement'
    item.author.assert_called_once()


def test_failed_author_does_not_consume_rewrite():
    item = source(author=Mock(side_effect=RuntimeError('provider unavailable')))
    with pytest.raises(RuntimeError):
        policy.reorient(item)
    item.consume_rewrite.assert_not_called()


@pytest.mark.parametrize('text,evidence,expected', [
    ('Inspect lib/shipping/rates.rb.', 'lib/shipping/rates.rb', []),
    ('Inspect rates.rb', 'lib/shipping/rates.rb', []),
    ('Inspect lib/shipping.rb', 'lib/shipping/rates.rb', ['lib/shipping.rb']),
    ('Check I/O and problems/risks in target/.', 'target/.', []),
    ('Use v1.5.0 then v1.5.0', 'v1.4.0', ['v1.5.0']),
    ('Inspect README.md', 'readme.md', [])])
def test_owned_name_check_matches_original_without_legacy_service(text, evidence, expected):
    """Pin false-path/version refusals and the punctuation/prose false-positive repairs."""
    assert policy.invented_names(text, evidence) == expected


def test_shared_provider_adapter_preserves_exact_author_call_and_count():
    from cria import groundedaction
    provider = Mock(return_value='Inspect the existing files.')
    providers = groundedaction.ProviderServices(provider, Mock(side_effect=AssertionError))
    chat, role, log = Mock(), object(), Log()
    author = policy.SummaryAuthor(providers.summarize, chat, role, log)
    item = source(author=author, log=log)
    result = policy.reorient(item)
    assert result.reason == 'authored'
    provider.assert_called_once_with(chat, role, AUTHOR_SYSTEM,
        AUTHOR_CONTEXT, log, phase='reasoner')
    providers.judge_completion.assert_not_called()


def test_general_candidate_vet_does_not_replace_reorientation_name_authority():
    from cria import groundedaction
    # Exercise the real shared vet with narrow deterministic evidence services;
    # no provider call, workspace read, or legacy policy callback is available.
    facts = SimpleNamespace(merge_fetches=lambda a, b: {}, extract_fetches=lambda m: {},
                            ledger_field_names=lambda ledger: set(), touched_paths=lambda messages: [])
    providers = Mock(side_effect=AssertionError)
    actions = groundedaction.GroundedActions(facts, providers)
    candidate = groundedaction.CandidateInput('Inspect phantom.py', 'existing.py', Log())
    general = actions.vet(candidate)
    assert general.directive == candidate.directive
    assert policy.invented_names(candidate.directive, candidate.evidence) == ['phantom.py']
    item = source(candidate.directive)
    result = policy.reorient(item)
    assert result.reason == 'ungrounded'
    assert result.message['content'] == '⟦ctx:steer⟧ ' + FALLBACK
    providers.assert_not_called()
