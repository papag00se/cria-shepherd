"""Assist selection by level/profile/opt-outs through the real AssistRuntime: what each rung selects (independently derived from the registry's declared
levels), the refusals (bad level, unknown/duplicate/ill-typed opt-outs, unknown profile, non-boolean planning consent) and the unselected-arm behaviours."""
import copy

import pytest

from cria import assistprofiles, assistruntime as A, completionreview as CR, focustrim
from cria.argumentconversion import ArgumentInput
from cria.assistruntime import AssistRuntime, DEFINITIONS


PLANNING = {"experimental-plan-gather", "experimental-plan-coverage", "experimental-plan-readiness", "experimental-plan-revision",
            "experimental-living-plan", "experimental-step-review", "experimental-completed-work-briefing"}   # the seven that need [planner].enabled consent


def expected(level, planning=False):
    return {d.policy.id for d in DEFINITIONS if d.policy.default_level <= level and (planning or d.policy.id not in PLANNING)}


def test_each_rung_selects_exactly_the_assists_declared_for_it_and_never_loses_one_going_up():
    """Selection is the registry's own contract: id's default_level <= rung, planner-family ids only with explicit consent, and rungs nest."""
    previous = set()
    for level in range(6):
        chosen = set(AssistRuntime.select(level=level).selected)
        assert chosen == expected(level) and previous <= chosen
        previous = chosen
    assert set(AssistRuntime.select(level=5, experimental_planning=True).selected) == expected(5, True) > expected(5)


def test_opt_outs_and_profiles_remove_exactly_what_they_name():
    """One disabled id leaves every other selected id in place; the rank-4 profile drops its recorded set; a profile refuses extra opt-outs."""
    full = AssistRuntime.select(level=5)
    victim = "pasted-file-recovery"
    assert set(AssistRuntime.select(level=5, disabled=(victim,)).selected) == set(full.selected) - {victim}
    profiled = set(AssistRuntime.select(level=5, profile=assistprofiles.RANK4_ABLATION).selected)
    assert profiled == set(full.selected) - set(assistprofiles.RANK4_ABLATION_DISABLED) and profiled < set(full.selected)
    with pytest.raises(ValueError, match="rank4-ablation is exact"):
        AssistRuntime.select(level=5, profile=assistprofiles.RANK4_ABLATION, disabled=(victim,))


@pytest.mark.parametrize("kwargs, message", [
    ({"level": 6}, "level must be an integer 0..5"), ({"level": -1}, "level must be an integer 0..5"), ({"level": "5"}, "level must be an integer 0..5"),
    ({"level": True}, "level must be an integer 0..5"),
    ({"disabled": ("no-such-id",)}, "Unknown or duplicate"), ({"disabled": ("pasted-file-recovery",) * 2}, "Unknown or duplicate"),
    ({"profile": "no-such-profile"}, "Unknown assist profile"), ({"experimental_planning": "yes"}, "explicitly boolean"), ({"experimental_planning": 1}, "explicitly boolean"),
])
def test_invalid_selections_are_refused_with_their_reason(kwargs, message):
    """Nothing is clamped or coerced: a malformed selection raises before any runtime exists."""
    with pytest.raises(ValueError, match=message):
        AssistRuntime.select(**{"level": 5, **kwargs})


def test_unselected_arms_answer_as_absent_and_selected_ones_expose_their_stage():
    """At level 0 argument conversion/task review/module judgment are not selected: they pass inputs through; bindings(stage) is the registry order for that stage; review gates on its trigger level."""
    low, high = AssistRuntime.select(level=0), AssistRuntime.select(level=5)
    source = ArgumentInput("t", {"n": "1"}, {"t": {"properties": {"n": {"type": "integer"}}}})
    result = low.arguments(source)
    assert result.arguments == {"n": "1"} and result.changed is False
    assert high.arguments(source).arguments == {"n": 1}
    assert not low.review_applies(CR.ReviewTrigger.CLAIM) and high.review_applies(CR.ReviewTrigger.SCHEDULED)
    stages = {d.policy.stage for d in high.definitions}
    assert all(d.policy.stage == s for s in stages for d in high.bindings(s)) and sum(len(high.bindings(s)) for s in stages) == len(high.definitions)
    assert high.bindings("no-such-stage") == () and AssistRuntime.select(level=3).review_applies(CR.ReviewTrigger.CLAIM) is False
    assert AssistRuntime.select(level=4).review_applies(CR.ReviewTrigger.CLAIM) and not AssistRuntime.select(level=4).review_applies(CR.ReviewTrigger.SCHEDULED)


def test_the_runtime_binding_is_scoped_and_focus_wire_bindings_are_immutable_private_packets():
    """bound() makes the runtime current only inside its block; a focus binding packet keeps its executors through copies but cannot be edited, and empty/untyped definitions are refused."""
    runtime = AssistRuntime.select(level=2)
    assert not A.is_bound()
    with A.bound(runtime):
        assert A.is_bound() and A.current() is runtime
    assert not A.is_bound()
    producers = tuple(d for d in AssistRuntime.select(level=5).definitions if isinstance(d, focustrim.FocusDefinition) and d.settle is not None)
    packet = A.FocusWireBindings(producers)
    assert copy.copy(packet) is packet and copy.deepcopy(packet) is packet and list(packet) == [d.policy.id for d in producers]
    with pytest.raises(AttributeError):
        packet.definitions = ()
    for bad in ((), ("x",), [producers[0]]):
        with pytest.raises(ValueError):
            A.FocusWireBindings(bad)
