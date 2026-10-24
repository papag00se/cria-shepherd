"""Read-only structural validator for quarantined synthetic proposals, never a gold labeler.

Only complete_input may feed a future, separately authorized model serializer. This
utility does not tokenize, infer, train, normalize text, or certify semantic truth,
privacy, source independence, native fit, evaluation eligibility or training admission.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


LABELS = {
    'searchdirection': {'SAME_HUNT', 'NEW_DIRECTION', 'UNKNOWN'},
    'requiredoutput': {'REQUIRED_OUTPUT', 'NOT_REQUIRED_OUTPUT', 'UNKNOWN'},
    'exactform': {'EXACT_FILE_FORM', 'NO_EXACT_FILE_FORM', 'UNKNOWN'},
    'intake': {'QUESTION', 'SIMPLE', 'TASK', 'UNKNOWN'},
    'compactionrequest': {'YES', 'NO', 'UNKNOWN'},
    'retrospective': {'RETROSPECTIVE', 'PLAN', 'UNKNOWN'},
    'dictation': {'DICTATES', 'DESCRIBES', 'UNKNOWN'},
    'wholefile': {'WHOLE_FILE', 'OTHER', 'UNKNOWN'},
    'runtimee2e': {'E2E_REQUIRED', 'NOT_REQUIRED', 'UNKNOWN'},
}
# These are versioned data shapes, not lexical rules for making a semantic decision.
INPUTS = {
    'searchdirection': ({'previous_query', 'proposed_query', 'question_context', 'previous_results_available'}, set()),
    'requiredoutput': ({'original_task', 'subject'}, {'available_note'}),
    'exactform': ({'original_task', 'subject'}, {'prior_agreement'}),
    'intake': ({'latest_request', 'public_context'}, set()),
    'compactionrequest': ({'latest_turn', 'tools_offered'}, {'preceding_control_message'}),
    'retrospective': ({'candidate_briefing'}, {'referenced_note'}),
    'dictation': ({'public_directive'}, {'attached_patch'}),
    'wholefile': ({'target', 'presentation', 'candidate_payload', 'original_file_facts'}, set()),
    'runtimee2e': ({'original_task', 'requested_interface'}, {'linked_ticket'}),
}
CONSTANTS = {
    'schema_version': 'synthetic-decision-seed-v1', 'source_kind': 'synthetic',
    'label_status': 'proposed_independentreview_pending', 'partition': 'UNASSIGNED_QUARANTINE',
    'partition_constraint': 'TRAIN_ONLY_IF_REVIEWED_AND_ADMITTED', 'fit_status': 'NOT_MEASURED',
}
FIELDS = set(CONSTANTS) | {
    'id', 'family', 'policy_id', 'complete_input', 'label', 'support_spans', 'language',
    'task_domain', 'harness_style', 'group_id', 'variation_type', 'contrast', 'origin',
    'research_refs', 'annotation',
}


class SeedValidationError(ValueError):
    """The declared seed data contract is broken; no admission is implied by success."""


def require(condition, message):
    if not condition:
        raise SeedValidationError(message)


def nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def reject_constant(value):
    raise SeedValidationError(f'non-finite JSON value: {value}')


def canonical_input(value):
    """Lossless structured-value identity, NOT a tokenizer or approved training format."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def check_record(r):
    require(isinstance(r, dict) and set(r) == FIELDS, 'record fields differ from seed v1 schema')
    name = r['id']
    require(all(nonempty_string(r[k]) for k in ('id', 'family', 'policy_id', 'task_domain', 'harness_style', 'group_id', 'variation_type')), 'missing record metadata')
    family = r['family']
    require(family in LABELS, f'{name}: unsupported family')
    require(r['policy_id'] == f'{family}-research-v1', f'{name}: wrong policy_id')
    require(r['label'] in LABELS[family], f'{name}: unsupported label')
    for key, value in CONSTANTS.items():
        require(r[key] == value, f'{name}: {key} must remain {value}')
    evidence = r['complete_input']
    required, optional = INPUTS[family]
    require(isinstance(evidence, dict) and required <= set(evidence) <= required | optional, f'{name}: input keys differ from family contract')
    for key, value in evidence.items():
        if key == 'previous_results_available':
            require(value is None or isinstance(value, bool), f'{name}: invalid availability flag')
        elif key == 'tools_offered':
            require(value == [], f'{name}: seed v1 requires an empty tool menu')
        else:
            require(value is None or isinstance(value, str), f'{name}: evidence must be a full string or explicit null')
    require(not re.search(r'\bcria\b', canonical_input(evidence).decode('utf-8'), re.IGNORECASE), f'{name}: project marker in model evidence')
    spans = r['support_spans']
    require(isinstance(spans, list) and bool(spans), f'{name}: missing support spans')
    for span in spans:
        require(isinstance(span, dict) and set(span) == {'field', 'start', 'end', 'text', 'unit', 'bounds'}, f'{name}: invalid span shape')
        pointer = span['field']
        require(isinstance(pointer, str) and pointer.startswith('/') and pointer[1:] in evidence, f'{name}: invalid span pointer')
        text = evidence[pointer[1:]]
        start, end = span['start'], span['end']
        require(span['unit'] == 'unicode_codepoints' and span['bounds'] == 'zero_based_half_open', f'{name}: invalid span units')
        require(isinstance(text, str) and type(start) is int and type(end) is int and 0 <= start < end <= len(text), f'{name}: invalid span bounds')
        require(isinstance(span['text'], str) and text[start:end] == span['text'], f'{name}: span is not literal original evidence')
    if family == 'requiredoutput' and r['label'] == 'REQUIRED_OUTPUT':
        subject = evidence['subject']
        require(nonempty_string(subject) and any(s['field'] == '/original_task' and subject in s['text'] for s in spans), f'{name}: positive output subject lacks literal task support')
    language = r['language']
    require(isinstance(language, dict) and set(language) == {'programming', 'human'}, f'{name}: invalid language metadata')
    for value in [*language.values(), r['research_refs']]:
        require(isinstance(value, list) and bool(value) and all(nonempty_string(x) for x in value) and len(set(value)) == len(value), f'{name}: invalid slice/reference list')
    origin = r['origin']
    require(isinstance(origin, dict) and origin.get('method') == 'standalone_authored_for_review' and nonempty_string(origin.get('authoring_batch')), f'{name}: invalid origin')
    require(origin.get('archive_split_lineage', 'MISSING') is None and origin.get('archive_parent_ids') == [] and origin.get('evaluation_cases_used_as_generation_inputs') is False, f'{name}: origin must not claim archive ancestry or evaluation generation')
    require(origin.get('author_previously_exposed_to_research_evaluation') is True and origin.get('semantic_independence_from_prior_research_not_claimed') is True, f'{name}: origin exposure declarations missing')
    annotation = r['annotation']
    require(isinstance(annotation, dict) and {'review_rationale', 'target_fields', 'evidence_scope'} <= set(annotation) <= {'review_rationale', 'target_fields', 'evidence_scope', 'proposal_history', 'admission_blocker'}, f'{name}: invalid annotation fields')
    require(all(nonempty_string(annotation[k]) for k in ('review_rationale', 'evidence_scope')), f'{name}: incomplete external annotation')
    targets = annotation['target_fields']
    if family == 'exactform' and r['label'] == 'EXACT_FILE_FORM':
        require(isinstance(targets, dict) and set(targets) == {'bytes', 'ends_with_line_break'}, f'{name}: exact target fields missing')
        size, newline = targets['bytes'], targets['ends_with_line_break']
        require((size is None or (type(size) is int and size >= 0)) and (newline is None or isinstance(newline, bool)) and (size is not None or newline is not None), f'{name}: malformed exact target')
        require(any(s['field'] == '/original_task' for s in spans), f'{name}: exact target lacks original-task support')
    else:
        require(targets == {}, f'{name}: unexpected target fields')
    if 'admission_blocker' in annotation:
        require(nonempty_string(annotation['admission_blocker']), f'{name}: invalid admission blocker')
    if 'proposal_history' in annotation:
        require(isinstance(annotation['proposal_history'], list) and bool(annotation['proposal_history']) and all(isinstance(h, dict) for h in annotation['proposal_history']), f'{name}: invalid proposal history')
    contrast = r['contrast']
    require(isinstance(contrast, dict) and set(contrast) == {'parent_id', 'expected_relation'}, f'{name}: invalid contrast')
    relation = contrast['expected_relation']
    require(relation in {'base', 'label_invariant', 'label_changing', 'abstention'}, f'{name}: invalid relation')
    require((relation == 'base' and contrast['parent_id'] is None) or (relation != 'base' and nonempty_string(contrast['parent_id'])), f'{name}: invalid parent')


def validate_seed(path: Path):
    """Validate the whole seed without changing it; return metadata, never example text."""
    raw = Path(path).read_bytes()
    require(raw.endswith(b'\n'), 'seed must be LF-terminated, not a partial final record')
    try:
        text = raw.decode('utf-8')
        rows = []
        for number, line in enumerate(text[:-1].split('\n'), 1):
            require(bool(line.strip()), f'empty JSONL record at line {number}')
            try:
                row = json.loads(line, object_pairs_hook=unique_object, parse_constant=reject_constant)
                check_record(row)
            except (ValueError, TypeError, KeyError) as exc:
                raise SeedValidationError(f'line {number}: {exc}') from exc
            rows.append(row)
    except UnicodeError as exc:
        raise SeedValidationError('seed is not valid UTF-8') from exc
    require(bool(rows), 'empty seed')
    by_id, inputs = {}, set()
    for row in rows:
        name = row['id']
        require(name not in by_id, f'duplicate id: {name}')
        identity = row['family'], hashlib.sha256(canonical_input(row['complete_input'])).hexdigest()
        require(identity not in inputs, f'{name}: duplicate family input, not an independent example')
        by_id[name] = row
        inputs.add(identity)
    groups = Counter()
    for row in rows:
        contrast = row['contrast']
        relation, parent_id = contrast['expected_relation'], contrast['parent_id']
        if relation == 'base':
            groups[row['group_id']] += 1
            continue
        require(parent_id in by_id and parent_id != row['id'], f"{row['id']}: missing/self parent")
        parent = by_id[parent_id]
        require((parent['family'], parent['policy_id'], parent['group_id'], parent['origin']['authoring_batch']) == (row['family'], row['policy_id'], row['group_id'], row['origin']['authoring_batch']), f"{row['id']}: parent crosses a policy/group/batch")
        equal = parent['label'] == row['label']
        require((relation == 'label_invariant' and equal) or (relation == 'label_changing' and not equal and 'UNKNOWN' not in {parent['label'], row['label']}) or (relation == 'abstention' and row['label'] == 'UNKNOWN'), f"{row['id']}: declared label relation contradicted")
        visited = {row['id']}
        while parent_id is not None:
            require(parent_id in by_id and parent_id not in visited, f"{row['id']}: cyclic/missing parent")
            visited.add(parent_id)
            parent_id = by_id[parent_id]['contrast']['parent_id']
    require(set(groups) == {r['group_id'] for r in rows} and all(n == 1 for n in groups.values()), 'each group needs one base')
    return {
        'schema': 'synthetic-seed-structural-review-v1', 'source_sha256': hashlib.sha256(raw).hexdigest(),
        'source_bytes': len(raw), 'records': len(rows), 'groups': len(groups),
        'families': dict(sorted(Counter(r['family'] for r in rows).items())),
        'label_relations': dict(sorted(Counter(r['contrast']['expected_relation'] for r in rows).items())),
        'explicit_admission_blockers': {r['id']: r['annotation']['admission_blocker'] for r in rows if 'admission_blocker' in r['annotation']},
        'semantic_review': 'NOT_CERTIFIED', 'privacy_review': 'NOT_CERTIFIED',
        'provenance': 'DECLARATIONS_CHECKED_NOT_INDEPENDENTLY_VERIFIED',
        'native_fit': 'NOT_MEASURED', 'training_admission': 'NOT_GRANTED',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', type=Path, default=Path(__file__).parent / 'training_data/synthetic_seed.jsonl')
    args = parser.parse_args()
    try:
        result = validate_seed(args.path)
    except (OSError, SeedValidationError) as exc:
        parser.exit(1, f'Invalid synthetic proposal seed: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
