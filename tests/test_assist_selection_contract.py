"""Structural selection errors must fail before any policy executes.

Synthetic registrations exercise the registry contract, not model behavior.
"""
from dataclasses import dataclass, replace
from typing import Callable

import pytest

from cria.assistcontract import Policy
from cria.assistruntime import select_definitions, validate


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable


def forbidden(*_args, **_kwargs):
    raise AssertionError("selection executed a policy")


FIRST = Definition(Policy("fixture-first", "fixture-stage", 1, family_id="F03",
                          services=("synthetic-input",)), forbidden)
SECOND = Definition(Policy("fixture-second", "fixture-stage", 3, family_id="F03",
                           services=("synthetic-input",), dependencies=("fixture-first",)), forbidden)


@pytest.mark.parametrize("level", [True, False, 1.5, "1", None])
def test_registered_default_level_is_an_exact_integer(level):
    invalid = replace(FIRST, policy=replace(FIRST.policy, default_level=level))
    with pytest.raises(ValueError):
        validate((invalid,))


@pytest.mark.parametrize("level", [True, 1.5, "5", None])
def test_registered_trigger_level_is_an_exact_integer(level):
    invalid = replace(FIRST, policy=replace(FIRST.policy, triggers=(("fixture-trigger", level),)))
    with pytest.raises(ValueError):
        validate((invalid,))


def test_duplicate_dependency_is_not_silently_collapsed_to_a_set():
    invalid = replace(SECOND, policy=replace(SECOND.policy,
                      dependencies=(FIRST.policy.id, FIRST.policy.id)))
    with pytest.raises(ValueError):
        validate((FIRST, invalid))


def test_selection_preserves_registration_order_without_executing():
    assert select_definitions((FIRST, SECOND), level=3) == (FIRST, SECOND)
    assert select_definitions((FIRST, SECOND), level=2) == (FIRST,)
    assert select_definitions((FIRST, SECOND), level=0) == ()
    assert select_definitions((FIRST, SECOND), disabled=(SECOND.policy.id,)) == (FIRST,)


def test_missing_and_forward_dependencies_are_errors_not_reordered_or_ignored():
    for registrations in ((SECOND,), (SECOND, FIRST)):
        with pytest.raises(ValueError):
            select_definitions(registrations)
    with pytest.raises(ValueError):
        select_definitions((FIRST, SECOND), disabled=(FIRST.policy.id,))


def test_unknown_and_duplicate_selection_ids_are_errors():
    for disabled in (("missing",), (FIRST.policy.id, FIRST.policy.id)):
        with pytest.raises(ValueError):
            select_definitions((FIRST, SECOND), disabled=disabled)


def test_unqualified_external_and_experimental_definitions_do_not_activate():
    for scope in ("native_artifacts", "configured_cli_provider", "experimental_planning"):
        unsupported = replace(FIRST, policy=replace(FIRST.policy, scope=scope))
        with pytest.raises(ValueError):
            select_definitions((unsupported,))
