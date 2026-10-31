"""The assist runtime refuses every malformed binding at construction (a stage definition replaced by something that cannot do its job, a duplicate
or unregistered id, a profile whose bindings disagree with its selection) instead of failing on the first request; the typed pilot stages
(arguments, periodic judgment, whole-task review) honour what was selected; focus settlement bindings are immutable and cannot change mid-obligation."""
import dataclasses
import types

import pytest

from cria import assistruntime as ar, bodykeys, focustrim
from cria.argumentconversion import ArgumentInput
from cria.assistcontract import Policy
from cria.completionreview import ReviewInput, ReviewResult, ReviewStatus, ReviewTrigger
from cria.modulestate import Judgment, ModuleResult


def stages():
    return list(ar.AssistRuntime().ordered_stages)


def stage(assist_id):
    return next(d for d in stages() if d.policy.id == assist_id)


def with_replaced(assist_id, **changes):
    return tuple(dataclasses.replace(d, **changes) if d.policy.id == assist_id else d for d in stages())


# (assist id, a callable field of its definition, the refusal when that field is not callable). Nothing is computed from the code under test.
BROKEN_FIELDS = [
    ("exact-file-form-approval", "measure", "Invalid completion approval binding"),
    ("negative-completion-diagnosis", "arm", "Invalid completion diagnosis binding"),
    ("negative-completion-diagnosis", "follow_up", "Invalid completion diagnosis binding"),
    ("repository-check-lifecycle", "resume", "Invalid repository check binding"),
    ("repository-check-lifecycle", "completion", "Invalid repository check binding"),
    ("evidence-summary", "settle", "Invalid evidence summary binding"),
    ("overlapping-search-new-direction", "settle", "Invalid semantic query binding"),
    ("grounded-stalled-work", "admit", "Invalid stalled work binding"),
    ("grounded-stalled-work", "progress_stage", "Invalid stalled work binding"),
    ("pasted-file-recovery", "redrive", "Invalid pasted file binding"),
    ("pasted-file-recovery", "settle", "Invalid pasted file binding"),
    ("learned-capacity-refit", "density", "Invalid capacity binding"),
    ("automatic-protocol-discovery", "execute_async", "Invalid protocol_discovery binding"),
    ("automatic-protocol-discovery", "observe", "Invalid protocol_discovery binding"),
    ("research-spill-admission", "settle", "Invalid externalization binding"),
    ("research-spill-admission", "reset", "Invalid externalization binding"),
    ("harness-memory-handoff", "frame", "Harness memory replacement must preserve its typed lifecycle"),
    ("text-call-recovery", "execute", "Incomplete or unsupported executable assist definition"),
]


@pytest.mark.parametrize("assist_id,field,message", BROKEN_FIELDS, ids=[f"{a}.{f}" for a, f, _ in BROKEN_FIELDS])
def test_a_stage_definition_whose_required_callable_is_missing_is_refused_at_construction(assist_id, field, message):
    with pytest.raises(ValueError, match=message):
        ar.AssistRuntime(ordered_stages=with_replaced(assist_id, **{field: None}))


def test_the_default_runtime_binds_every_typed_stage_it_registers_and_a_replaced_policy_contract_is_refused():
    runtime = ar.AssistRuntime()
    for attribute in ("completion_diagnosis", "completion_confirmation", "runner_contract", "repository_checks", "evidence_summary", "stalled_work",
                      "pasted_file", "capacity", "transient_recovery", "protocol_discovery", "document_guidance", "externalization", "completion_act_first"):
        assert getattr(runtime, attribute) is not None, attribute
    assert runtime.rehunt is not None and runtime.harness_memory_handoff is not None and runtime.pre_release and runtime.wire_folds
    other = Policy("evidence-summary", "returned", 0, family_id="x")
    with pytest.raises(ValueError, match="Replacement must preserve its registered policy contract"):
        ar.AssistRuntime(ordered_stages=with_replaced("evidence-summary", policy=other))


def test_construction_refuses_duplicates_unregistered_ids_untyped_collections_and_a_non_boolean_planning_consent():
    first = stages()
    with pytest.raises(ValueError, match="Duplicate atomic assist ID"):
        ar.AssistRuntime(ordered_stages=tuple(first + [first[0]]))
    stranger = dataclasses.replace(first[0], policy=dataclasses.replace(first[0].policy, id="never-registered"))
    with pytest.raises(ValueError, match="Unregistered executable assist: never-registered"):
        ar.AssistRuntime(ordered_stages=tuple(first[1:] + [stranger]))
    with pytest.raises(ValueError, match="immutable tuples"):
        ar.AssistRuntime(ordered_stages=first)
    with pytest.raises(ValueError, match="explicitly boolean"):
        ar.AssistRuntime(experimental_planning=1)
    with pytest.raises(ValueError, match="explicitly boolean"):
        ar.AssistRuntime.select(experimental_planning="yes")


@pytest.mark.parametrize("policy_change,message", [
    (dict(id=""), "Incomplete or unsupported"), (dict(stage=""), "Incomplete or unsupported"), (dict(scope="planner-only"), "Incomplete or unsupported"),
    (dict(migrated="yes"), "Invalid executable hook/regression references"), (dict(hooks=[1]), "Invalid executable hook/regression references"),
    (dict(hooks=(ar.Reference("/abs/path.py", "x"),)), "Invalid executable hook/regression references"),
    (dict(regressions=(ar.Reference("a/../b.py", "x"),)), "Invalid executable hook/regression references"),
    (dict(migrated=True, hooks=(), regressions=()), "Claimed migrated policy requires hooks and regressions"),
    (dict(default_level=6), "Invalid assist engagement level"), (dict(default_level=True), "Invalid assist engagement level"),
    (dict(triggers=(("a", 3), ("a", 4))), "Invalid assist caller triggers"), (dict(default_level=2, triggers=(("a", 1),)), "Invalid assist caller triggers"),
    (dict(triggers=(("", 3),)), "Invalid assist caller triggers"), (dict(triggers=(("a", 6),)), "Invalid assist caller triggers"),
    (dict(dependencies=("evidence-summary", "evidence-summary")), "Duplicate assist dependency"),
    (dict(dependencies=("no-such-assist",)), "Unresolved assist dependency"),
])
def test_a_registered_policy_with_inconsistent_metadata_is_refused_by_name(policy_change, message):
    victim = stage("evidence-summary")
    broken = dataclasses.replace(victim, policy=dataclasses.replace(victim.policy, **policy_change))
    with pytest.raises(ValueError, match=message):
        ar.validate(tuple(d for d in stages() if d is not victim) + (broken,))


def test_a_dependency_must_be_registered_before_the_assist_that_needs_it():
    victim = stage("evidence-summary")
    later = [d for d in stages() if d is not victim][-1]
    needy = dataclasses.replace(victim, policy=dataclasses.replace(victim.policy, dependencies=(later.policy.id,)))
    rest = tuple(d for d in stages() if d is not victim)
    ar.validate(rest + (needy,))                                                                          # after its dependency: fine
    with pytest.raises(ValueError, match="Invalid assist dependency order: evidence-summary"):
        ar.validate((needy,) + rest)


def test_pilot_selection_is_by_level_with_dependencies_and_named_exclusions_and_refuses_nonsense():
    regs = ar.DEFINITIONS
    assert ar.select_definitions(regs, level=0) == tuple(d for d in regs if d.policy.default_level == 0)
    for level in (-1, 6, True, "3", None):
        with pytest.raises(ValueError, match="integer 0..5"):
            ar.select_definitions(regs, level=level)
    with pytest.raises(ValueError, match="immutable tuple"):
        ar.select_definitions(list(regs))
    with pytest.raises(ValueError, match="Unknown or duplicate pilot assist selection"):
        ar.select_definitions(regs, disabled=("evidence-summary", "evidence-summary"))
    with pytest.raises(ValueError, match="Unknown or duplicate"):
        ar.validate_selection_ids(("nope",))
    needed = next(d for d in regs if any(d.policy.id in o.policy.dependencies for o in regs))
    with pytest.raises(ValueError, match="Disabled dependency for assist"):
        ar.select_definitions(regs, disabled=(needed.policy.id,))


def test_the_typed_pilot_stages_run_what_was_selected_and_a_missing_one_changes_nothing():
    """Arguments: converted (and logged once, with the assist and family ids) or untouched; periodic judgment: the first applicable result wins and
    none is NOT_APPLICABLE; whole-task review: not selected below the trigger's rung, and a replacement that answers with anything but a ReviewResult
    is refused."""
    events = []
    log = types.SimpleNamespace(emit=lambda kind, **kw: events.append((kind, kw)))
    runtime = ar.AssistRuntime()
    unchanged = runtime.arguments(ArgumentInput("exec_command", {"cmd": "ls"}, {"exec_command": {"properties": {"cmd": {"type": "string"}}}}), log)
    assert unchanged.arguments == {"cmd": "ls"} and unchanged.changed is False and events == []
    schemas = {"exec_command": {"properties": {"yield_time_ms": {"type": "integer"}}}}
    converted = runtime.arguments(ArgumentInput("exec_command", {"cmd": "ls", "yield_time_ms": "30000"}, schemas), log)
    assert converted.changed and converted.arguments["yield_time_ms"] == 30000
    assert [k for k, _ in events] == ["massage.arguments_converted"] and events[0][1]["tool"] == "exec_command"
    bare = dataclasses.replace(runtime, argument_conversion=None)
    assert bare.arguments(ArgumentInput("t", {"a": "1"}, {}), log).changed is False
    steer = ModuleResult(Judgment.REPEATED)
    skipping = dataclasses.replace(ar.MODULE, execute=lambda source, state: ModuleResult(Judgment.NOT_APPLICABLE))
    answering = dataclasses.replace(ar.MODULE, execute=lambda source, state: steer)
    in_order = types.SimpleNamespace(periodic_judgments=(skipping, answering, dataclasses.replace(answering, execute=lambda *a: pytest.fail("past the first answer"))))
    assert ar.AssistRuntime.module_judgment(in_order, None, None) is steer
    assert dataclasses.replace(runtime, periodic_judgments=(answering,)).module_judgment(None, None) is steer
    assert dataclasses.replace(runtime, periodic_judgments=(skipping,)).module_judgment(None, None).judgment is Judgment.NOT_APPLICABLE
    assert dataclasses.replace(runtime, periodic_judgments=()).module_judgment(None, None).judgment is Judgment.NOT_APPLICABLE
    task = lambda trigger: ReviewInput(trigger, "t", lambda: "", lambda: "", lambda *a: (True, "", ""), lambda: "", log)
    low = ar.AssistRuntime.select(level=3)
    assert low.review(task(ReviewTrigger.SCHEDULED), None).status is ReviewStatus.NOT_SELECTED and not low.review_applies(ReviewTrigger.SCHEDULED)
    assert low.review_applies(ReviewTrigger.CLAIM) is False and runtime.review_applies(ReviewTrigger.CLAIM)
    four = ar.AssistRuntime.select(level=4)                                                              # the reactive trigger's rung, not the scheduled one's
    assert four.review_applies(ReviewTrigger.CLAIM) and not four.review_applies(ReviewTrigger.SCHEDULED)
    assert four.review(task(ReviewTrigger.SCHEDULED), None).status is ReviewStatus.NOT_SELECTED
    with pytest.raises(ValueError, match="whole-task-review is required for reactive completion at L4/L5"):
        dataclasses.replace(runtime, task_review=None)
    assert ar.AssistRuntime.review_applies(types.SimpleNamespace(task_review=None, engagement_level=5), ReviewTrigger.CLAIM) is False   # nothing selected, however high the level
    wrong = dataclasses.replace(runtime, task_review=dataclasses.replace(ar.TASK_REVIEW, execute=lambda source, state: "approved"))
    with pytest.raises(ValueError, match="must return ReviewResult"):
        wrong.review(task(ReviewTrigger.CLAIM), None)
    right = dataclasses.replace(runtime, task_review=dataclasses.replace(ar.TASK_REVIEW, execute=lambda source, state: ReviewResult(ReviewStatus.REJECTED, "no")))
    assert right.review(task(ReviewTrigger.CLAIM), None).reason == "no"


def test_focus_settlement_bindings_are_immutable_and_cannot_change_while_obligations_are_pending():
    producer = next(d for d in focustrim.DEFINITIONS if d.settle is not None) if hasattr(focustrim, "DEFINITIONS") else None
    if producer is None:
        producer = focustrim.FocusDefinition(Policy("p1", "history", 1, family_id="f"), lambda m: (m, 0), settle=lambda m: m)
    other = focustrim.FocusDefinition(Policy("p2", "history", 1, family_id="f"), lambda m: (m, 0), settle=lambda m: m)
    bindings = ar.FocusWireBindings((producer,))
    assert tuple(bindings) == (producer.policy.id,) and bindings.definitions == (producer,) and bindings.__copy__() is bindings and bindings.__deepcopy__({}) is bindings
    with pytest.raises(AttributeError, match="immutable"):
        bindings.definitions = ()
    for bad in ((), [producer], (dataclasses.replace(producer, settle=None),), ("x",)):
        with pytest.raises(ValueError, match="immutable settlement definitions"):
            ar.FocusWireBindings(bad)
    pending = types.SimpleNamespace(pending_settlement=("notice",))
    quiet = types.SimpleNamespace(pending_settlement=())
    body = {"messages": []}
    assert ar.retain_focus_bindings(body, quiet, (producer,)) is body
    held = ar.retain_focus_bindings(body, pending, (producer, dataclasses.replace(other, settle=None)))
    assert held[bodykeys.FOCUS_PRODUCERS].definitions == (producer,) and bodykeys.FOCUS_PRODUCERS not in body
    assert ar.retain_focus_bindings(held, pending, (producer,)) [bodykeys.FOCUS_PRODUCERS].definitions == (producer,)
    with pytest.raises(ValueError, match="cannot change while obligations are pending"):
        ar.retain_focus_bindings(held, pending, (other,))
