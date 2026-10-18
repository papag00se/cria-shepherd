"""Historical literal recovery with unconditional lossless wire enveloping.

Only malformed *string* arguments enter optional recovery. Valid JSON, including
scalars/null/empty objects, stays byte-for-byte; non-string/unknown historical
shapes stay unchanged. No current schema, tool-name mapping, role/correlation
inference, execution, or model call belongs here. The final Upstream._prep owner
must invoke this after downstream appends and retain its other wire-integrity
foundations independently of this optional definition.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable, Iterable, Protocol

from . import jsontext
from .assistcontract import ExecutableDefinition, Policy, Reference


class EventLog(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


@dataclass(frozen=True)
class HistoricalArguments:
    values: tuple[str, ...]


@dataclass(frozen=True)
class RecoveredArguments:
    values: tuple[dict | None, ...]

    def __post_init__(self):
        if not isinstance(self.values, tuple) or any(value is not None and not isinstance(value, dict)
                                                    for value in self.values):
            raise ValueError('Historical recovery requires a tuple of literal objects or unknowns')


def recover_arguments(source: HistoricalArguments) -> RecoveredArguments:
    """The real historical reconstruction, using the same literal readers as fresh repair.

    The complete-write reader remains in its existing foundation location until
    its owner relocates it. This imports only that reader, never the old history
    policy or the fresh response callback (which also handles fused actions).
    """
    from .callliterals import _recover_write_args
    recovered = []
    for raw in source.values:
        obj = jsontext.extract_json_object(raw) or _recover_write_args(raw)
        # A recovered empty object conveys none of the original malformed call.
        recovered.append(None if obj == {} else obj)
    return RecoveredArguments(tuple(recovered))


@dataclass(frozen=True)
class HistoricalDefinition:
    policy: Policy
    execute: Callable[[HistoricalArguments], RecoveredArguments]


DEFINITION = HistoricalDefinition(
    Policy('historical-argument-recovery', 'historical-arguments', 1, family_id='F06',
           scope='runtime', state='none', prompts=(),
           services=('common-json-literal-reader', 'complete-write-literal-reader'),
           hooks=(Reference('cria/upstream.py', 'Upstream._prep'),
                  Reference('cria/massage.py', 'repair_history_tool_args')),
           regressions=(Reference('tests/test_history_argument_policy.py',
                                  'test_full_history_keeps_names_ids_roles_outputs_and_literal_values'),
                        Reference('tests/test_history_argument_policy.py',
                                  'test_final_prep_repairs_a_downstream_append_with_optional_recovery_disabled'),
                        Reference('tests/test_history_argument_policy.py',
                                  'test_public_compat_and_final_prep_use_the_same_replacement_raw_bytes_and_logs')),
           migrated=False), recover_arguments)


def selected_definition(definitions: Iterable[ExecutableDefinition]) -> HistoricalDefinition | None:
    """Project the canonical selected source/replacement; absence stays absent."""
    selected = None
    for definition in definitions:
        if definition.policy.id != DEFINITION.policy.id:
            continue
        if selected is not None:
            raise ValueError('Duplicate historical argument recovery selection')
        if (not isinstance(definition, HistoricalDefinition) or definition.policy != DEFINITION.policy
                or not callable(definition.execute)):
            raise ValueError('Historical replacement must preserve its typed policy contract')
        selected = definition
    return selected


def prepare_history(messages: list, rlog: EventLog | None = None, *,
                    definition: HistoricalDefinition | None, recover: bool = True) -> list:
    """Final-wire hook: optional reconstruction cannot bypass required enveloping.

    The caller supplies the authoritative selected definition/replacement or None;
    no independent selection or default fallback exists. ``recover=False`` retains
    the configured/direct-library opt-out. Recovery requires both applicability
    and an explicitly selected definition; applicability alone selects nothing.

    JSON validity and candidate positions are gathered once as required transport
    facts. Optional readers never see valid arguments, identities, schemas or tool
    output. Replacement outputs must align exactly; no guessed correlation.
    """
    positions, values = [], []
    for mi, message in enumerate(messages):
        calls = message.get('tool_calls') if isinstance(message, dict) else None
        if not isinstance(calls, list):
            continue
        for ci, call in enumerate(calls):
            function = call.get('function') if isinstance(call, dict) else None
            raw = function.get('arguments') if isinstance(function, dict) else None
            if isinstance(raw, str):
                try:
                    json.loads(raw)
                except json.JSONDecodeError:
                    positions.append((mi, ci))
                    values.append(raw)
    active = definition is not None and recover
    objects = (None,) * len(values)
    if values and active:
        result = definition.execute(HistoricalArguments(tuple(values)))
        if not isinstance(result, RecoveredArguments) or len(result.values) != len(values):
            raise ValueError('Historical recovery must preserve candidate count and order')
        objects = result.values
    # Required wire foundation: unknown, refused and disabled recoveries all carry
    # the exact original malformed text. Neither the role nor the call is invented.
    fixed = {(mi, ci): json.dumps(obj if obj is not None and obj != {} else {'_unparsed': raw},
                                  ensure_ascii=False)
             for (mi, ci), raw, obj in zip(positions, values, objects)}
    out = []
    for mi, message in enumerate(messages):
        calls = message.get('tool_calls') if isinstance(message, dict) else None
        if not isinstance(calls, list) or not calls:
            out.append(message)
            continue
        replaced = []
        for ci, call in enumerate(calls):
            if (mi, ci) in fixed:
                call = {**call, 'function': {**call['function'], 'arguments': fixed[mi, ci]}}
            replaced.append(call)
        out.append({**message, 'tool_calls': replaced})
    if values and rlog is not None:
        event = 'massage.history_args_repaired' if active else 'upstream.history_args_enveloped'
        fields = {'count': len(values)}
        if active:
            fields.update(assist_id=definition.policy.id, family_id=definition.policy.family_id)
        rlog.emit(event, **fields)
    return out
