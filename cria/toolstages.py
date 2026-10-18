"""Typed stage bindings for output and returned tools.

The request/task owner binds this immutable value alongside AssistRuntime. No
configuration, discovery, evidence, or mutable session state lives here.
Unbound library calls use source defaults; requests must bind their authoritative
selection explicitly, including an empty selection.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import cache
from typing import Iterable, Literal

# Compatibility surface: the canonical records live below execution/default assembly.
from .toolcontracts import (EventLog, _PolicyLog, policy_log, CompletionTransform, CompletionRepair,
    CompletionDefinition, ShrinkFinding, ShrinkCheck, EditSequence, LoweringRequest,
    OutboundCall, RewrittenCall, ShellCommand, OutboundEffect, OutboundDefinition,
    MutationDefinition, ReturnedResult, ReturnedDefinition, ReturnedHistory,
    HistoryDefinition, RejectedDraft, DraftDefinition, ToolDefinition, ShrinkServices)


@dataclass(frozen=True)
class ToolStages:
    recovery: tuple[CompletionDefinition, ...]
    repair: tuple[CompletionDefinition, ...]
    text_answer: tuple[CompletionDefinition, ...]
    outbound: tuple[OutboundDefinition, ...]
    returned: tuple[ReturnedDefinition, ...]
    history: tuple[HistoryDefinition, ...]
    rejected_draft: DraftDefinition | None
    mutations: tuple[MutationDefinition, ...]

    def __post_init__(self):
        groups = ((self.recovery, 'output-recovery'), (self.repair, 'output-repair'),
                  (self.text_answer, 'text-answer'), (self.outbound, 'outbound-call'),
                  (self.returned, 'returned-result'), (self.history, 'returned-history'),
                  (((self.rejected_draft,) if self.rejected_draft else ()), 'rejected-draft'),
                  (self.mutations, 'mutation-command'))
        seen = set()
        for definitions, stage in groups:
            for definition in definitions:
                p = definition.policy
                if p.id in seen or p.stage != stage or not callable(definition.execute):
                    raise ValueError('Invalid tool stage binding: ' + p.id)
                seen.add(p.id)

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (self.recovery + self.repair + self.text_answer + self.outbound + self.mutations
                + self.returned + self.history + ((self.rejected_draft,) if self.rejected_draft else ()))

    @classmethod
    def from_definitions(cls, definitions: Iterable[object]) -> ToolStages:
        """Project already-validated authoritative bindings, including replacements.

        No defaults participate: an empty authoritative selection yields empty
        stages. Unrelated runtime definitions remain their owning stages' concern.
        Keep the input's order; registry validation owns dependencies and scope.
        """
        definitions = tuple(definitions)
        def stage(name, kind):
            return tuple(d for d in definitions if isinstance(d, kind) and d.policy.stage == name)
        drafts = stage('rejected-draft', DraftDefinition)
        if len(drafts) > 1:
            raise ValueError('Only one rejected-draft lifecycle can be bound')
        return cls(stage('output-recovery', CompletionDefinition),
                   stage('output-repair', CompletionDefinition),
                   stage('text-answer', CompletionDefinition),
                   stage('outbound-call', OutboundDefinition),
                   stage('returned-result', ReturnedDefinition),
                   stage('returned-history', HistoryDefinition),
                   drafts[0] if drafts else None,
                   stage('mutation-command', MutationDefinition))

    def completions(self, stage: Literal['recovery', 'repair', 'text_answer'], completion: dict,
                    tools=None, log: EventLog | None = None) -> dict:
        for definition in getattr(self, stage):
            tagged = policy_log(log, definition.policy)
            completion = (definition.execute(completion, tools, tagged) if definition.needs_menu
                          else definition.execute(completion, tagged))
        return completion

    def stream_start(self, content: str, log=None) -> int:
        for definition in self.recovery:
            if definition.stream_start is not None:
                position = definition.stream_start(content)
                if position >= 0:
                    tagged = policy_log(log, definition.policy)
                    if tagged is not None:
                        tagged.emit('massage.stream_leak_detected')
                    return position
        return -1

    def outbound_call(self, source: OutboundCall) -> tuple[dict, dict, ShellCommand | None]:
        from .toolargs import parse_args
        for definition in self.outbound:
            result = definition.execute(replace(source, log=policy_log(source.log, definition.policy)))
            if isinstance(result, ShellCommand):
                return source.call, source.arguments, result
            if isinstance(result, RewrittenCall):
                arguments = (result.arguments if result.arguments is not None else
                             parse_args((result.call.get('function') or {}).get('arguments')))
                source = OutboundCall(result.call, arguments, source.request, source.sequence, source.log)
        # Transport adaptation only, at the original last-admission position.
        # Research owns selection, detection, state and the refusal text.
        effect = None
        if source.name == 'web_search':
            from . import researchpolicies, webfetch
            from .toolwire import _refusal_command
            # Explicit request/tool bindings must not summon namespace defaults.
            # A canonical research binding always wins, including an empty one.
            if researchpolicies.is_bound() or not is_bound():
                refusal = webfetch.gate_search(source.request.session, str(source.arguments.get('query') or ''))
                if refusal is not None:
                    effect = ShellCommand(_refusal_command(refusal))
        return source.call, source.arguments, effect

    def mutation_command(self, source: OutboundCall, command: str) -> str:
        for definition in self.mutations:
            command = definition.execute(replace(source, log=policy_log(source.log, definition.policy)), command)
        return command

    def returned_result(self, source: ReturnedResult) -> dict | None:
        for definition in self.returned:
            result = definition.execute(replace(source, log=policy_log(source.log, definition.policy)))
            if result is not None:
                return result
        return None

    def returned_history(self, source: ReturnedHistory) -> None:
        for definition in self.history:
            definition.execute(replace(source, log=policy_log(source.log, definition.policy)))

    def preserve_draft(self, call: dict, path: str, log=None) -> RejectedDraft:
        definition = self.rejected_draft
        if definition is None:
            return RejectedDraft(call, '')
        return definition.execute(call, path, policy_log(log, definition.policy))


_CURRENT: ContextVar[ToolStages | None] = ContextVar('tool_stage_bindings', default=None)


@cache
def defaults() -> ToolStages:
    from . import outputpolicies, outboundpolicies, returnedpolicies
    return ToolStages(outputpolicies.RECOVERY, outputpolicies.REPAIR, outputpolicies.TEXT_ANSWER,
                      outboundpolicies.DEFINITIONS, returnedpolicies.RESULTS,
                      returnedpolicies.HISTORY, returnedpolicies.REJECTED_DRAFT, outboundpolicies.MUTATIONS)


def is_bound() -> bool:
    return _CURRENT.get() is not None


def current() -> ToolStages:
    selected = _CURRENT.get()
    return defaults() if selected is None else selected


@contextmanager
def bound(stages: ToolStages):
    token = _CURRENT.set(stages)
    try:
        yield stages
    finally:
        _CURRENT.reset(token)
