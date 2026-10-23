"""Explicit executable pilot registrations; not an all-policy switchboard.

Each stage has its own types and ordered bindings. The context-local binding is
immutable selection, not mutable evidence/state. It covers nested recovery and
retry paths without process-global policy settings or model-visible hints.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field, fields

from .assistcontract import ExecutableDefinition, Reference
from . import assistprofiles
from . import assistbinding, completionapproval, completiondiagnosis, completionconfirmation, runnercontract, repositorychecks, evidencesummary, memoryhandoff, semanticquery, stalledwork, groundedaction, planner, pastedfile, livingplan, stepreview, completedwork, capacitypolicy, transientpolicy, discoverypolicy, documentguidance, externalization, completionredrive

from .argumentconversion import ArgumentDefinition, ArgumentInput, ArgumentResult, DEFINITION as ARGUMENTS
from .modulestate import ModuleDefinition, ModuleInput, ModuleResult, ModuleState, Judgment, DEFINITION as MODULE
from .completionreview import (ReviewDefinition, ReviewInput, ReviewResult, ReviewStatus,
                               ReviewTrigger, SatisfactionState, DEFINITION as TASK_REVIEW)

from . import toolstages, researchpolicies, historyarguments, classify, toolmenu, generationguards
from . import bodykeys, selfcompact, focustrim, modelview, contextrestoration, ledgercopies, reorientation, preamblepolicy, steppreparation

TOOL_DEFINITIONS = toolstages.defaults().definitions
RESEARCH_DEFINITIONS = researchpolicies.DEFINITIONS
HISTORY_DEFINITIONS = (historyarguments.DEFINITION,)
ADMISSION_DEFINITIONS = (classify.DEFINITION,) + toolmenu.DEFINITIONS
GENERATION_DEFINITIONS = generationguards.DEFINITIONS
CONTEXT_DEFINITIONS = ((selfcompact.DEFINITION,) + focustrim.FOCUS_STAGE + modelview.WIRE_FOLD_STAGE
                       + (contextrestoration.DEFINITION, ledgercopies.DEFINITION,
                          reorientation.DEFINITION, preamblepolicy.DEFINITION)
                       + steppreparation.DEFINITIONS)
DEFINITIONS = (ARGUMENTS, MODULE, TASK_REVIEW) + TOOL_DEFINITIONS + RESEARCH_DEFINITIONS + HISTORY_DEFINITIONS + ADMISSION_DEFINITIONS + GENERATION_DEFINITIONS + CONTEXT_DEFINITIONS + completionapproval.PRE_RELEASE + completiondiagnosis.DEFINITIONS + completionconfirmation.DEFINITIONS + (runnercontract.DEFINITION,) + repositorychecks.DEFINITIONS + (evidencesummary.DEFINITION, memoryhandoff.DEFINITION) + semanticquery.DEFINITIONS + (stalledwork.DEFINITION,) + planner.DEFINITIONS + (pastedfile.DEFINITION,) + livingplan.DEFINITIONS + (stepreview.DEFINITION, completedwork.DEFINITION, capacitypolicy.DEFINITION, transientpolicy.TRANSIENT_RECOVERY, discoverypolicy.DEFINITION, documentguidance.DEFINITION, externalization.DEFINITION, completionredrive.DEFINITION)


class FocusWireBindings(tuple):
    """JSON-safe private packet retaining exact immutable producer executors.

    The tuple surface contains IDs for diagnostics only. Executors are strong
    in-process references, survive lossless copies, and never reach serialization.
    This carries existing obligations, not permission to produce new history.
    """
    def __new__(cls, definitions):
        if not isinstance(definitions, tuple) or not definitions or any(
                not isinstance(d, focustrim.FocusDefinition) or d.settle is None for d in definitions):
            raise ValueError("Focus wire bindings require immutable settlement definitions")
        result = super().__new__(cls, (d.policy.id for d in definitions))
        object.__setattr__(result, "definitions", definitions)
        return result

    def __setattr__(self, name, value):
        raise AttributeError("Focus wire bindings are immutable")

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


def retain_focus_bindings(body: dict, result: focustrim.FocusResult, definitions: tuple) -> dict:
    """Publish wire-private provenance only when a selected source holds promises."""
    if not result.pending_settlement:
        return body
    producers = tuple(d for d in definitions if d.settle is not None)
    prior = body.get(bodykeys.FOCUS_PRODUCERS)
    if isinstance(prior, FocusWireBindings) and prior.definitions != producers:
        raise ValueError("Focus producer bindings cannot change while obligations are pending")
    return {**body, bodykeys.FOCUS_PRODUCERS: FocusWireBindings(producers)}


def _valid_rung(value) -> bool:
    return type(value) is int and 0 <= value <= 5


def validate(definitions=DEFINITIONS) -> None:
    ids = [item.policy.id for item in definitions]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate atomic assist ID")
    for item in definitions:
        p = item.policy
        if (not p.id or not p.family_id or not p.stage or not p.state
                or not callable(item.execute)
                or not (p.scope == "runtime" or p == steppreparation.DEFINITION.policy
                        or any(p == d.policy for d in planner.DEFINITIONS + livingplan.DEFINITIONS
                               + (stepreview.DEFINITION, completedwork.DEFINITION)))):
            raise ValueError("Incomplete or unsupported executable assist definition")
        if (type(p.migrated) is not bool or not isinstance(p.hooks, tuple)
                or not isinstance(p.regressions, tuple)
                or any(not isinstance(ref, Reference) or not isinstance(ref.path, str)
                       or not isinstance(ref.symbol, str) or not ref.path or not ref.symbol
                       or ref.path.startswith("/") or ".." in ref.path.split("/")
                       for ref in p.hooks + p.regressions)):
            raise ValueError("Invalid executable hook/regression references: " + p.id)
        if p.migrated and (not p.hooks or not p.regressions):
            raise ValueError("Claimed migrated policy requires hooks and regressions: " + p.id)
        if not _valid_rung(p.default_level):
            raise ValueError("Invalid assist engagement level (must be integer 0..5): " + p.id)
        if (len({name for name, _level in p.triggers}) != len(p.triggers)
                or any(not name or not _valid_rung(level) or level < p.default_level
                       for name, level in p.triggers)):
            raise ValueError("Invalid assist caller triggers (rungs must be integer 0..5): " + p.id)
        if len(set(p.dependencies)) != len(p.dependencies):
            raise ValueError("Duplicate assist dependency: " + p.id)
        if any(dep not in ids or dep == p.id for dep in p.dependencies):
            raise ValueError("Unresolved assist dependency: " + p.id)
    # Registration order is explicit; a dependency must have appeared earlier.
    seen = set()
    for item in definitions:
        if not set(item.policy.dependencies) <= seen:
            raise ValueError("Invalid assist dependency order: " + item.policy.id)
        seen.add(item.policy.id)


@dataclass(frozen=True)
class AssistRuntime:
    argument_conversion: ArgumentDefinition | None = ARGUMENTS
    periodic_judgments: tuple[ModuleDefinition, ...] = (MODULE,)
    task_review: ReviewDefinition | None = TASK_REVIEW
    engagement_level: int = 5
    ordered_stages: tuple[ExecutableDefinition, ...] = TOOL_DEFINITIONS + RESEARCH_DEFINITIONS + HISTORY_DEFINITIONS + ADMISSION_DEFINITIONS + GENERATION_DEFINITIONS + CONTEXT_DEFINITIONS + completionapproval.PRE_RELEASE + completiondiagnosis.DEFINITIONS + completionconfirmation.DEFINITIONS + (runnercontract.DEFINITION,) + repositorychecks.DEFINITIONS + (evidencesummary.DEFINITION, memoryhandoff.DEFINITION) + semanticquery.DEFINITIONS + (stalledwork.DEFINITION, pastedfile.DEFINITION, capacitypolicy.DEFINITION, transientpolicy.TRANSIENT_RECOVERY, discoverypolicy.DEFINITION, documentguidance.DEFINITION, externalization.DEFINITION, completionredrive.DEFINITION)
    registrations: tuple[ExecutableDefinition, ...] = DEFINITIONS
    experimental_planning: bool = False
    profile: str = "default"
    initial_planning: planner.PlanningSelection = field(init=False, repr=False)
    living_plan: livingplan.LivingSelection = field(init=False, repr=False)
    step_review: stepreview.StepSelection = field(init=False, repr=False)
    completed_work: completedwork.BriefingSelection = field(init=False, repr=False)
    pasted_file: pastedfile.Definition | None = field(init=False, repr=False)
    capacity: capacitypolicy.Definition | None = field(init=False, repr=False)
    transient_recovery: transientpolicy.Definition | None = field(init=False, repr=False)
    protocol_discovery: discoverypolicy.DiscoveryDefinition | None = field(init=False, repr=False)
    document_guidance: documentguidance.GuidanceDefinition | None = field(init=False, repr=False)
    externalization: externalization.Definition | None = field(init=False, repr=False)
    completion_act_first: completionredrive.Definition | None = field(init=False, repr=False)
    wire_folds: tuple[modelview.WireDefinition, ...] = field(init=False, repr=False)
    pre_release: tuple[completionapproval.ParticipationDefinition | completionapproval.ExactFormDefinition, ...] = field(init=False)

    completion_diagnosis: completiondiagnosis.DiagnosisDefinition | None = field(init=False)
    completion_confirmation: completionconfirmation.Definition | None = field(init=False)
    runner_contract: runnercontract.RunnerDefinition | None = field(init=False)
    repository_checks: repositorychecks.Definition | None = field(init=False)
    evidence_summary: evidencesummary.Definition | None = field(init=False)
    harness_memory_handoff: memoryhandoff.HandoffDefinition | None = field(init=False)
    rehunt: semanticquery.RehuntDefinition | None = field(init=False)
    stalled_work: stalledwork.Definition | None = field(init=False)

    def __post_init__(self):
        if (not isinstance(self.registrations, tuple) or not isinstance(self.ordered_stages, tuple)
                or not isinstance(self.periodic_judgments, tuple)):
            raise ValueError("Executable registrations and bindings must be immutable tuples")
        if type(self.experimental_planning) is not bool:
            raise ValueError('Experimental planning consent must be explicitly boolean')
        validate(self.registrations)
        definitions = (((self.argument_conversion,) if self.argument_conversion else ())
                       + self.periodic_judgments + ((self.task_review,) if self.task_review else ())
                       + self.ordered_stages)
        ids = [d.policy.id for d in definitions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate atomic assist ID")
        canonical = {d.policy.id: d.policy for d in self.registrations}
        for definition in definitions:
            if definition.policy.id not in canonical:
                raise ValueError("Unregistered executable assist: " + definition.policy.id)
            if definition.policy != canonical[definition.policy.id]:
                if definition is self.argument_conversion and definition.policy.stage != ARGUMENTS.policy.stage:
                    raise ValueError("Argument policy registered at the wrong stage")
                raise ValueError("Replacement must preserve its registered policy contract")
        validate(self.definitions)
        excluded = assistprofiles.resolve(self.profile, ())
        if self.profile != "default":
            expected = configured_definitions(self.registrations, level=self.engagement_level,
                                              disabled=excluded,
                                              experimental_planning=self.experimental_planning)
            if ids != [d.policy.id for d in expected]:
                raise ValueError("Assist bindings do not match the exact selected profile")
        object.__setattr__(self, "wire_folds", self.bindings("wire-evidence-fold"))
        approvals = {}
        for definition in self.definitions:
            canonical = next((d for d in completionapproval.PRE_RELEASE
                              if d.policy.id == definition.policy.id), None)
            if canonical is None and definition.policy.stage != completionapproval.PARTICIPATION.policy.stage:
                continue
            if (canonical is None or not isinstance(definition, type(canonical))
                    or definition.policy != canonical.policy
                    or isinstance(definition, completionapproval.ExactFormDefinition)
                    and not callable(definition.measure)):
                raise ValueError("Invalid completion approval binding")
            approvals[definition.policy.id] = definition
        object.__setattr__(self, "pre_release", tuple(approvals[d.policy.id]
                           for d in completionapproval.PRE_RELEASE if d.policy.id in approvals))
        diagnosis = None
        canonical = completiondiagnosis.DEFINITION
        for definition in self.definitions:
            if definition.policy.id != canonical.policy.id and definition.policy.stage != canonical.policy.stage:
                continue
            if (not isinstance(definition, completiondiagnosis.DiagnosisDefinition)
                    or definition.policy != canonical.policy
                    or any(not callable(getattr(definition, f.name))
                           for f in fields(completiondiagnosis.DiagnosisDefinition) if f.name != "policy")):
                raise ValueError("Invalid completion diagnosis binding")
            diagnosis = definition
        object.__setattr__(self, "completion_diagnosis", diagnosis)
        confirmation = None
        canonical = completionconfirmation.DEFINITION
        for definition in self.definitions:
            if definition.policy.id != canonical.policy.id and definition.policy.stage != canonical.policy.stage:
                continue
            if (not isinstance(definition, completionconfirmation.Definition)
                    or definition.policy != canonical.policy or not callable(definition.execute)):
                raise ValueError("Invalid completion confirmation binding")
            confirmation = definition
        object.__setattr__(self, "completion_confirmation", confirmation)
        runner = None
        canonical = runnercontract.DEFINITION
        for definition in self.definitions:
            if (not isinstance(definition, runnercontract.RunnerDefinition)
                    and definition.policy.id != canonical.policy.id
                    and definition.policy.stage != canonical.policy.stage):
                continue
            if (not isinstance(definition, runnercontract.RunnerDefinition)
                    or definition.policy != canonical.policy or not callable(definition.execute)):
                raise ValueError("Invalid runner contract binding")
            runner = definition
        object.__setattr__(self, "runner_contract", runner)
        checks = None
        canonical = repositorychecks.DEFINITION
        for definition in self.definitions:
            if (not isinstance(definition, repositorychecks.Definition)
                    and definition.policy.id != canonical.policy.id
                    and definition.policy.stage != canonical.policy.stage):
                continue
            if (not isinstance(definition, repositorychecks.Definition)
                    or definition.policy != canonical.policy
                    or any(not callable(getattr(definition, f.name))
                           for f in fields(repositorychecks.Definition) if f.name != "policy")):
                raise ValueError("Invalid repository check binding")
            checks = definition
        object.__setattr__(self, "repository_checks", checks)
        evidence = None
        canonical = evidencesummary.DEFINITION
        for definition in self.definitions:
            if (not isinstance(definition, evidencesummary.Definition)
                    and definition.policy.id != canonical.policy.id
                    and definition.policy.stage != canonical.policy.stage):
                continue
            if (not isinstance(definition, evidencesummary.Definition)
                    or definition.policy != canonical.policy
                    or not callable(definition.execute) or not callable(definition.settle)):
                raise ValueError("Invalid evidence summary binding")
            evidence = definition
        object.__setattr__(self, "evidence_summary", evidence)
        object.__setattr__(self, "harness_memory_handoff",
                           memoryhandoff.selected_definition(self.definitions))
        for name, canonical in (("rehunt", semanticquery.REHUNT),):
            selected = None
            for definition in self.definitions:
                if (not isinstance(definition, type(canonical))
                        and definition.policy.id != canonical.policy.id
                        and definition.policy.stage != canonical.policy.stage):
                    continue
                if (not isinstance(definition, type(canonical)) or definition.policy != canonical.policy
                        or any(not callable(getattr(definition, f.name))
                               for f in fields(type(canonical)) if f.name != "policy")):
                    raise ValueError("Invalid semantic query binding")
                selected = definition
            object.__setattr__(self, name, selected)
        stalled = None
        canonical = stalledwork.DEFINITION
        for definition in self.definitions:
            if (not isinstance(definition, stalledwork.Definition)
                    and definition.policy.id != canonical.policy.id
                    and definition.policy.stage != canonical.policy.stage):
                continue
            if (not isinstance(definition, stalledwork.Definition)
                    or definition.policy != canonical.policy
                    or any(not callable(getattr(definition, name)) for name in
                           ('execute', 'admit', 'settle_stage', 'progress_stage', 'settle', 'progress',
                            'acknowledge', 'reset_step'))
                    or not isinstance(definition.actions, groundedaction.Definition)
                    or not callable(definition.actions.author) or not callable(definition.actions.vet)):
                raise ValueError('Invalid stalled work binding')
            stalled = definition
        object.__setattr__(self, 'stalled_work', stalled)
        object.__setattr__(self, 'initial_planning', planner.PlanningSelection.from_definitions(
            self.definitions if self.experimental_planning else (), enabled=self.experimental_planning))
        object.__setattr__(self, 'living_plan', livingplan.LivingSelection.from_definitions(
            self.definitions, enabled=self.experimental_planning))
        object.__setattr__(self, 'step_review', stepreview.StepSelection.from_definitions(
            self.definitions, enabled=self.experimental_planning))
        object.__setattr__(self, 'completed_work', completedwork.BriefingSelection.from_definitions(
            self.definitions, enabled=self.experimental_planning))
        pasted = None
        canonical = pastedfile.DEFINITION
        for definition in self.definitions:
            if (not isinstance(definition, pastedfile.Definition)
                    and definition.policy.id != canonical.policy.id
                    and definition.policy.stage != canonical.policy.stage):
                continue
            if (not isinstance(definition, pastedfile.Definition)
                    or definition.policy != canonical.policy
                    or any(not callable(getattr(definition, f.name))
                           for f in fields(pastedfile.Definition) if f.name != 'policy')):
                raise ValueError('Invalid pasted file binding')
            pasted = definition
        object.__setattr__(self, 'pasted_file', pasted)
        capacity = None
        canonical = capacitypolicy.DEFINITION
        for definition in self.definitions:
            if (not isinstance(definition, capacitypolicy.Definition)
                    and definition.policy.id != canonical.policy.id
                    and definition.policy.stage != canonical.policy.stage):
                continue
            if (not isinstance(definition, capacitypolicy.Definition)
                    or definition.policy != canonical.policy
                    or not callable(definition.execute) or not callable(definition.density)):
                raise ValueError('Invalid capacity binding')
            capacity = definition
        object.__setattr__(self, 'capacity', capacity)
        transient = None
        canonical = transientpolicy.TRANSIENT_RECOVERY
        for definition in self.definitions:
            if (not isinstance(definition, transientpolicy.Definition)
                    and definition.policy.id != canonical.policy.id
                    and definition.policy.stage != canonical.policy.stage):
                continue
            if (not isinstance(definition, transientpolicy.Definition)
                    or definition.policy != canonical.policy or not callable(definition.execute)):
                raise ValueError('Invalid transient recovery binding')
            transient = definition
        object.__setattr__(self, 'transient_recovery', transient)
        for name, kind, canonical, callbacks in (
                ('protocol_discovery', discoverypolicy.DiscoveryDefinition, discoverypolicy.DEFINITION,
                 ('execute', 'execute_async', 'observe')),
                ('document_guidance', documentguidance.GuidanceDefinition, documentguidance.DEFINITION,
                 ('execute',)),
                ('externalization', externalization.Definition, externalization.DEFINITION,
                 ('execute', 'settle', 'cancel', 'reset', 'search_program')),
                ('completion_act_first', completionredrive.Definition, completionredrive.DEFINITION,
                 ('execute',))):
            selected = None
            for definition in self.definitions:
                if (not isinstance(definition, kind)
                        and definition.policy.id != canonical.policy.id
                        and definition.policy.stage != canonical.policy.stage):
                    continue
                if (not isinstance(definition, kind) or definition.policy != canonical.policy
                        or any(not callable(getattr(definition, callback)) for callback in callbacks)):
                    raise ValueError('Invalid ' + name + ' binding')
                selected = definition
            object.__setattr__(self, name, selected)
        if not _valid_rung(self.engagement_level):
            raise ValueError("Pilot assist level must be an integer 0..5")
        if self.argument_conversion:
            if self.argument_conversion.policy.stage != ARGUMENTS.policy.stage:
                raise ValueError("Argument policy registered at the wrong stage")

        if any(d.policy.stage != MODULE.policy.stage for d in self.periodic_judgments):
            raise ValueError("Judgment policy registered at the wrong stage")

        if self.engagement_level >= TASK_REVIEW.policy.default_level and self.task_review is None:
            raise ValueError("whole-task-review is required for reactive completion at L4/L5")

    @property
    def definitions(self) -> tuple[ExecutableDefinition, ...]:
        bound = (((self.argument_conversion,) if self.argument_conversion else ())
                 + self.periodic_judgments + ((self.task_review,) if self.task_review else ())
                 + self.ordered_stages)
        chosen = {d.policy.id: d for d in bound}
        return tuple(chosen[d.policy.id] for d in self.registrations if d.policy.id in chosen)

    @property
    def selected(self) -> tuple[str, ...]:
        return tuple(d.policy.id for d in self.definitions)

    def bindings(self, stage: str) -> tuple[ExecutableDefinition, ...]:
        """Immutable registration order; consumers retain source-owned typed calls.

        This is selection, not scheduling. New stages execute only when explicitly
        integrated at their existing caller boundary; no generic context/dispatcher.
        """
        return tuple(d for d in self.definitions if d.policy.stage == stage)

    @classmethod
    def select(cls, *, level=5, disabled=(), registrations=None, experimental_planning=False,
               profile="default"):
        if type(experimental_planning) is not bool:
            raise ValueError('Experimental planning consent must be explicitly boolean')
        registry = DEFINITIONS if registrations is None else registrations
        validate(registry)
        disabled = assistprofiles.resolve(profile, disabled)
        validate_selection_ids(disabled, registry)
        chosen = configured_definitions(registry, level=level, disabled=disabled,
                                        experimental_planning=experimental_planning)
        by_id = {d.policy.id: d for d in chosen}
        typed_ids = {ARGUMENTS.policy.id, MODULE.policy.id, TASK_REVIEW.policy.id}
        return cls(by_id.get(ARGUMENTS.policy.id),
                   (by_id[MODULE.policy.id],) if MODULE.policy.id in by_id else (),
                   by_id.get(TASK_REVIEW.policy.id), level,
                   tuple(d for d in chosen if d.policy.id not in typed_ids), registry,
                   experimental_planning=experimental_planning, profile=profile)

    def arguments(self, source: ArgumentInput, log=None) -> ArgumentResult:
        if self.argument_conversion is None:
            return ArgumentResult(source.arguments, False)
        result = self.argument_conversion.execute(source.name, source.arguments, source.schemas)
        changed = result != source.arguments
        if changed and log is not None:
            log.emit("massage.arguments_converted", assist_id=self.argument_conversion.policy.id,
                     family_id=self.argument_conversion.policy.family_id, tool=source.name)
        return ArgumentResult(result, changed)

    def module_judgment(self, source: ModuleInput, state: ModuleState) -> ModuleResult:
        for definition in self.periodic_judgments:
            result = definition.execute(source, state)
            if result.judgment is not Judgment.NOT_APPLICABLE:
                return result
        return ModuleResult(Judgment.NOT_APPLICABLE)

    def review_applies(self, trigger: ReviewTrigger) -> bool:
        return self.task_review is not None and self.engagement_level >= trigger.level

    def review(self, source: ReviewInput, state: SatisfactionState) -> ReviewResult:
        if not self.review_applies(source.trigger):
            return ReviewResult(ReviewStatus.NOT_SELECTED)
        result = self.task_review.execute(source, state)
        if not isinstance(result, ReviewResult):
            raise ValueError("Task review replacement must return ReviewResult")
        return result


def validate_selection_ids(disabled, registrations=None) -> None:
    known = {d.policy.id for d in (DEFINITIONS if registrations is None else registrations)}
    if len(set(disabled)) != len(disabled) or set(disabled) - known:
        raise ValueError("Unknown or duplicate pilot assist selection: " + repr(disabled))


def select_definitions(registrations: tuple[ExecutableDefinition, ...], *, level=5, disabled=()) -> tuple[ExecutableDefinition, ...]:
    """One metadata selection algorithm for source-owned, differently typed stages."""
    if not _valid_rung(level):
        raise ValueError("Pilot assist level must be an integer 0..5")
    if not isinstance(registrations, tuple):
        raise ValueError("Executable registrations must be an immutable tuple")
    validate(registrations)
    validate_selection_ids(disabled, registrations)
    selected = {d.policy.id for d in registrations if d.policy.default_level <= level} - set(disabled)
    for definition in registrations:
        if definition.policy.id in selected and not set(definition.policy.dependencies) <= selected:
            raise ValueError("Disabled dependency for assist: " + definition.policy.id)
    return tuple(d for d in registrations if d.policy.id in selected)


def configured_definitions(registry, *, level, disabled, experimental_planning):
    """Select capabilities without granting experimental planning consent."""
    initial_ids = {d.policy.id for d in planner.DEFINITIONS + livingplan.DEFINITIONS
                   + (stepreview.DEFINITION, completedwork.DEFINITION)}
    eligible = (registry if experimental_planning else
                tuple(d for d in registry if d.policy.id not in initial_ids))
    eligible_disabled = tuple(name for name in disabled
                              if experimental_planning or name not in initial_ids)
    return select_definitions(eligible, level=level, disabled=eligible_disabled)


DEFAULT = AssistRuntime()


def current() -> AssistRuntime:
    selected = assistbinding.current()
    return DEFAULT if selected is assistbinding.UNBOUND else selected


def is_bound() -> bool:
    """Factual request/task binding, including an explicitly empty selection."""
    return assistbinding.is_bound()


@contextmanager
def bound(runtime: AssistRuntime):
    from .toolstages import ToolStages, bound as bind_tools
    stages = ToolStages.from_definitions(runtime.definitions)
    research = researchpolicies.ResearchSelection.from_definitions(runtime.definitions)
    with assistbinding.bound(runtime), bind_tools(stages), researchpolicies.bound(research):
        yield runtime
