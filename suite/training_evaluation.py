"""Prospective evaluation's deterministic intake screen, NOT a freshness/gold oracle.

No models, semantic similarity heuristics, training or live capture hooks. Humans or
isolated reviewers judge scenario ancestry. This module verifies their exact frozen
reservation and source receipts. Passing never admits a label or permits inference.
"""
from __future__ import annotations

from suite.training_admit import model_text
from suite.training_prepare import extract, sha, source_value
from suite.training_seed import canonical_input


_CASE_FIELDS = frozenset({
    'id', 'family', 'task', 'group_id', 'all_sessions', 'all_run_ids', 'ancestor_tasks',
    'ancestry_complete', 'source_kind', 'complete_input', 'input_sha256', 'candidate_sha256',
    'source', 'task_source', 'capture_event_source', 'coder_model', 'harness',
    'human_languages', 'programming_languages',
})
_SOURCE_FIELDS = frozenset({'request', 'request_sha256', 'pointer'})


def exclusion_index(real, synthetic, *, task_texts=()):
    """Known identities, INCLUDING holds, plus explicitly supplied whole task roots.

    Exact task text is checked independently of its assigned task/group name.
    Root coverage is explicit; this cannot invent missing ancestry or source roots.
    """
    nodes = {key: set() for key in ('task', 'group', 'session', 'run', 'raw', 'input', 'task_text')}
    nodes['task_text'].update(sha(text.encode('utf-8')) for text in task_texts)
    for row in real:
        nodes['task'].add(row['task'])
        nodes['group'].add(row['group_id'])
        nodes['session'].update(row['all_sessions'])
        nodes['run'].update(row['all_run_ids'])
        nodes['raw'].add(sha(model_text(row).encode('utf-8')))
        nodes['input'].add(sha(canonical_input(row['complete_input'])))
    for row in synthetic:
        nodes['group'].add(row['group_id'])
        nodes['input'].add(sha(canonical_input(row['complete_input'])))
        if row['family'] in ('retrospective', 'dictation'):
            nodes['raw'].add(sha(model_text(row).encode('utf-8')))
    return {key: sorted(values) for key, values in nodes.items()}


def screen(case, reservation, contract, exclusions, cutoff_ns):
    """Return explicit holds; malformed/changed source custody raises instead.

    Source event time must be an actual hash-bound integer-nanosecond JSON value,
    not a filename, copied mtime, intake time or an unverified case field. Sources
    with different timestamp formats require an explicitly reviewed adapter.
    """
    if set(case) - _CASE_FIELDS:
        raise ValueError('prospective intake must be blinded: unexpected case fields')
    for field in ('source', 'task_source', 'capture_event_source'):
        allowed = _SOURCE_FIELDS | ({'decoded_character_span', 'utf8_byte_span'} if field == 'source' else set())
        if set(case[field]) != allowed:
            raise ValueError('prospective intake must be blinded: unexpected source fields')
    for field in ('id', 'task', 'group_id'):
        if not isinstance(case[field], str) or not case[field].strip():
            raise ValueError('invalid lineage identity')
    for field in ('all_sessions', 'all_run_ids', 'ancestor_tasks'):
        if (not isinstance(case[field], list)
                or any(not isinstance(v, str) or not v.strip() for v in case[field])):
            raise ValueError('invalid lineage identifiers')
    text = model_text(case)
    if (case['input_sha256'] != sha(canonical_input(case['complete_input']))
            or case['candidate_sha256'] != sha(text.encode('utf-8'))):
        raise ValueError('complete input hash mismatch')
    source = {**case['source'], 'candidate_sha256': case['candidate_sha256']}
    if source_value(source, cutoff_ns) != text:
        raise ValueError('prospective intake requires a whole native candidate slot, not selected bounds')
    if extract(source, cutoff_ns) != text:
        raise ValueError('complete input differs from actual source slot')
    task = source_value(case['task_source'], cutoff_ns)
    event_ns = source_value(case['capture_event_source'], cutoff_ns)
    if not isinstance(task, str) or not task or type(event_ns) is not int:
        raise ValueError('task/time source has no supported complete value')
    if (contract['reservations'].get(case['task']) != sha(canonical_input(reservation))
            or reservation['exclusions_sha256'] != sha(canonical_input(exclusions))
            or contract['exclusions_sha256'] != reservation['exclusions_sha256']
            or reservation['task_sha256'] != sha(task.encode('utf-8'))
            or reservation['task'] != case['task']
            or reservation['group_id'] != case['group_id']
            or reservation['partition'] != 'EVAL_PROSPECTIVE_SEALED'):
        raise ValueError('frozen reservation/source binding differs')
    holds = []
    if case['source_kind'] != 'real_public_candidate':
        holds.append('NOT_REAL_PUBLIC_TRAFFIC')
    if case['ancestry_complete'] is not True:
        holds.append('UNRESOLVED_ANCESTRY')
    if not case['all_sessions'] or not case['all_run_ids']:
        holds.append('MISSING_SOURCE_LINEAGE')
    start, reserved = contract['collection_start_ns'], reservation['reserved_at_ns']
    if (type(start) is not int or type(reserved) is not int
            or not start <= reserved < event_ns <= cutoff_ns):
        holds.append('NOT_PROSPECTIVE_AFTER_RESERVATION')
    reviews = reservation['novelty_reviews']
    if (len(reviews) != 2 or len({r['reviewer'] for r in reviews}) != 2
            or any(not r['reviewer'].strip() or r['decision'] != 'INDEPENDENT_SCENARIO'
                   or not r['reason'].strip() for r in reviews)):
        holds.append('NOVELTY_NOT_INDEPENDENTLY_REVIEWED')
    nodes = {'task': [case['task'], *case['ancestor_tasks']], 'group': [case['group_id']],
             'session': case['all_sessions'], 'run': case['all_run_ids'],
             'raw': [case['candidate_sha256']], 'input': [case['input_sha256']],
             'task_text': [sha(task.encode('utf-8'))]}
    if any(set(values) & set(exclusions[kind]) for kind, values in nodes.items()):
        holds.append('KNOWN_ANCESTRY_OR_EXACT_INPUT')
    return holds
