"""Assist selection: a runtime holds exactly the assists its level/profile declares (planning stays OFF), and that selection decides at the wire."""
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Callable

import pytest

from cria import assistbinding, assistprofiles, assistruntime as ar, denial, loop, toolstages, wsview
from cria.assistcontract import Policy, Reference
from write_edit_helpers import do, surveyed_view, write_edit_workspace_view  # noqa: F401

# Capabilities of the experimental planner: ON only by explicit opt-in. Commit 4a089fe7 re-enabled planning at L5 by accident.
PLANNING = {"experimental-plan-gather", "experimental-plan-coverage", "experimental-plan-readiness", "experimental-plan-revision",
            "experimental-living-plan", "experimental-step-review", "experimental-completed-work-briefing"}
LEVEL = {d.policy.id: d.policy.default_level for d in ar.DEFINITIONS}


@pytest.mark.parametrize("level", range(6))
def test_a_level_selects_every_assist_declared_at_or_below_it_in_registration_order_and_never_the_planner(level):
    """Selection = default_level <= level, order kept; planning capabilities are absent at EVERY level unless explicitly consented."""
    chosen = ar.AssistRuntime.select(level=level).selected
    assert chosen == tuple(i for i, rung in LEVEL.items() if rung <= level and i not in PLANNING)
    assert not PLANNING & set(chosen)
    assert PLANNING <= set(ar.AssistRuntime.select(level=5, experimental_planning=True).selected)
    assert not PLANNING & set(ar.AssistRuntime.select(level=0, experimental_planning=True).selected)
    for anchor, rung in (("shrinking-file-protection", 5), ("unread-file-protection", 5), ("edit-failure-recovery", 2),
                         ("workspace-boundary", 2), ("tool-free-text-recovery", 0)):
        assert (anchor in chosen) == (level >= rung)


def test_profiles_and_opt_outs_remove_exactly_what_they_name_and_never_below_level_five():
    """rank4-ablation drops exactly two assists at L5 and nothing at L0-4 (assists are L5-only; the ablation once disabled 39 wire fixes
    at lower levels); it takes no extra opt-outs; an unknown profile, unknown/duplicate id, or a disabled dependency is an error."""
    full = ar.AssistRuntime.select(level=5)
    ablated = ar.AssistRuntime.select(level=5, profile=assistprofiles.RANK4_ABLATION)
    assert set(full.selected) - set(ablated.selected) == {"experimental-step-preparation", "search-spill-read-judgment"}
    assert ablated.selected == tuple(i for i in full.selected if i not in assistprofiles.RANK4_ABLATION_DISABLED)
    for level in range(5):
        assert ar.AssistRuntime.select(level=level, profile=assistprofiles.RANK4_ABLATION).selected == ar.AssistRuntime.select(level=level).selected
    assert ar.AssistRuntime.select(level=5, disabled=("edit-failure-recovery",)).selected == tuple(
        i for i in full.selected if i != "edit-failure-recovery")
    for bad in (dict(profile="nonsense"), dict(profile=None), dict(profile=assistprofiles.RANK4_ABLATION, disabled=("edit-failure-recovery",)),
                dict(disabled=("no-such-assist",)), dict(disabled=("edit-failure-recovery",) * 2),
                dict(disabled=("unread-file-protection",), experimental_planning=1)):
        with pytest.raises(ValueError):
            ar.AssistRuntime.select(**bad)


POM = "".join(f"<l{i}/>\n" for i in range(29))


@pytest.mark.parametrize("kwargs,unread_held,steered", [
    (dict(level=5), True, True), (dict(level=4), False, True), (dict(level=1), False, False),
    (dict(level=5, disabled=("unread-file-protection",)), False, True), (dict(level=5, profile="rank4-ablation"), True, True),
    (dict(level=5, disabled=("edit-failure-recovery",)), True, False),
])
def test_the_bound_selection_decides_which_write_and_edit_assists_act(tmp_path, kwargs, unread_held, steered):
    """The same lowered calls behave per the BOUND selection: unread-file protection (L5) answers a write over an unread file with the
    file; edit-failure recovery (L2) turns a typed miss into a directive — below its rung the coder sees no cria directive."""
    (tmp_path / "pom.xml").write_text(POM)
    sess = SimpleNamespace(read_files={}, written_files={})
    view = surveyed_view(tmp_path, ("pom.xml", len(POM)))
    token = wsview.bind(view)
    try:
        with ar.bound(ar.AssistRuntime.select(**kwargs)):
            check = lambda path: loop.unread_target_fact(sess, wsview.current(str(tmp_path)), path, [])
            _, _, w = do("write_file", {"path": "pom.xml", "content": "<p/>\n"}, tmp_path, unread_target=check)
            assert denial.refused(w[1]) is unread_held and (tmp_path / "pom.xml").read_text() == (POM if unread_held else "<p/>\n")
            (tmp_path / "pom.xml").write_text(POM)
            _, _, e = do("edit_file", {"path": "pom.xml", "old_string": "zzz", "new_string": "y"}, tmp_path, cid="e")
            assert ("you cannot pin its exact current text" in e[1]["content"]) is steered
    finally:
        wsview.unbind(token)


@dataclass(frozen=True)
class Def:
    policy: Policy
    execute: Callable


def forbidden(*_a, **_k):
    raise AssertionError("selection executed a policy")


FIRST = Def(Policy("fx-first", "fx-stage", 1, family_id="F03", services=("s",)), forbidden)
SECOND = Def(Policy("fx-second", "fx-stage", 3, family_id="F03", services=("s",), dependencies=("fx-first",)), forbidden)
HOOK = (Reference("cria/loop.py", "Loop.x"),)


def bad(**changes):
    return (replace(FIRST, policy=replace(FIRST.policy, **changes)),)


@pytest.mark.parametrize("registrations", [
    bad(default_level=True), bad(default_level=1.5), bad(default_level=6), bad(triggers=(("t", True),)),
    bad(triggers=(("t", 0),)), (FIRST, replace(SECOND, policy=replace(SECOND.policy, dependencies=("fx-first", "fx-first"))),),
    (SECOND,), (SECOND, FIRST), (FIRST, FIRST), bad(scope="experimental_planning"), bad(migrated=True, hooks=HOOK),
    bad(hooks=(Reference("../up.py", "x"),)),
], ids=["level-bool", "level-float", "level-6", "trigger-bool", "trigger-below-default", "dup-dependency", "missing-dependency",
        "forward-dependency", "dup-id", "planning-scope", "migrated-without-regressions", "reference-escapes-repo"])
def test_a_malformed_registration_is_an_error_before_any_policy_executes(registrations):
    """Structural errors fail closed at validation; nothing is executed, reordered or silently collapsed."""
    with pytest.raises(ValueError):
        ar.select_definitions(registrations)


def test_selection_order_dependencies_and_ids_are_exact_without_executing_anything():
    """Registration order is kept; a disabled dependency, unknown or duplicate id is an error rather than a silent drop."""
    assert ar.select_definitions((FIRST, SECOND), level=3) == (FIRST, SECOND)
    assert ar.select_definitions((FIRST, SECOND), level=2) == (FIRST,) and ar.select_definitions((FIRST, SECOND), level=0) == ()
    assert ar.select_definitions((FIRST, SECOND), disabled=("fx-second",)) == (FIRST,)
    for disabled in (("fx-first",), ("missing",), ("fx-first", "fx-first")):
        with pytest.raises(ValueError):
            ar.select_definitions((FIRST, SECOND), disabled=disabled)
    ar.validate()                                              # the shipped registry itself is well-formed


def test_a_binding_is_scoped_distinguishes_unbound_from_empty_and_restores_after_an_error():
    """UNBOUND is absence, never a default selection; an explicit EMPTY selection runs nothing; leaving a scope (even by error) restores the outer one."""
    high = ar.AssistRuntime.select()
    empty = ar.AssistRuntime.select(level=0, disabled=tuple(i for i, rung in LEVEL.items() if rung == 0))
    assert assistbinding.current() is assistbinding.UNBOUND and ar.current() is ar.DEFAULT
    with ar.bound(high):
        with pytest.raises(RuntimeError):
            with ar.bound(empty):
                assert assistbinding.is_bound() and ar.current().definitions == () and toolstages.current().definitions == ()
                raise RuntimeError("leave")
        assert assistbinding.current() is high
    assert assistbinding.current() is assistbinding.UNBOUND and toolstages.current() is toolstages.defaults()
    with pytest.raises(ValueError):
        with assistbinding.bound(assistbinding.UNBOUND):
            pass
