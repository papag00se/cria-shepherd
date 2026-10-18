"""Explicit source references are inert discovery, never execution proof."""
from dataclasses import dataclass, replace
from typing import Callable

import pytest

from cria.assistcontract import Policy
from cria.assistruntime import validate


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable


BASE = Definition(Policy("fixture", "fixture-stage", 1, family_id="fixture"), lambda *_: None)


@pytest.mark.parametrize("missing", ["hooks", "regressions"])
def test_claimed_migrated_definition_requires_both_hooks_and_regressions(missing):
    from cria.assistcontract import Reference
    fields = dict(migrated=True,
        hooks=(Reference("cria/loop.py", "Loop._review_task"),),
        regressions=(Reference("tests/test_whole_task_evaluation.py",
                              "test_selected_owner_composes_once_and_records_the_authoritative_transition"),))
    fields[missing] = ()
    with pytest.raises(ValueError, match="migrated.*hooks.*regressions"):
        validate((replace(BASE, policy=replace(BASE.policy, **fields)),))


def test_source_references_are_immutable_inert_and_accept_staged_defaults():
    from cria.assistcontract import Reference
    validate((BASE,))  # staged source units are not claimed fully migrated
    hooks = (Reference("cria/loop.py", "Loop._review_task"),)
    tests = (Reference("tests/test_whole_task_evaluation.py", "test_unknown_original_claim_records_negative_without_judging_or_gathering"),)
    migrated = replace(BASE, policy=replace(BASE.policy, migrated=True, hooks=hooks, regressions=tests))
    validate((migrated,))
    assert migrated.policy.hooks is hooks and migrated.policy.regressions is tests
    with pytest.raises(AttributeError):
        hooks[0].symbol = "changed"
    with pytest.raises(ValueError, match="references"):
        validate((replace(BASE, policy=replace(migrated.policy, hooks=list(hooks))),))


@pytest.mark.parametrize("path,symbol", [("/external.py", "hook"), ("../external.py", "hook"),
                                        ("cria/loop.py", ""), ("", "hook")])
def test_reference_shape_is_repository_relative_without_scanning_or_guessing(path, symbol):
    from cria.assistcontract import Reference
    bad = Reference(path, symbol)
    with pytest.raises(ValueError, match="references"):
        validate((replace(BASE, policy=replace(BASE.policy, hooks=(bad,))),))
