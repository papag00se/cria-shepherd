"""Source projection uses only authoritative lower storage, never Root methods/defaults."""
from dataclasses import dataclass, replace
import subprocess
import sys

import pytest

from cria import argumentconversion as source, assistbinding
from cria.assistcontract import Policy
from cria.toolcontracts import CompletionDefinition


@dataclass(frozen=True)
class Selection:
    definitions: tuple = ()
    engagement_level: int = 0


def test_only_unbound_uses_canonical_standalone_definition():
    assert assistbinding.current() is assistbinding.UNBOUND
    assert source.selected_definition() is source.DEFINITION
    with assistbinding.bound(Selection()):
        assert source.selected_definition() is None
    assert source.selected_definition() is source.DEFINITION


@pytest.mark.parametrize('level', [0, 1, 5])
def test_exact_selected_replacement_is_projected_without_root_methods_or_level_reselection(level):
    calls = []
    def replacement(name, args, schemas):
        calls.append((name, args, schemas))
        return {'replacement': name}
    selected = replace(source.DEFINITION, execute=replacement)
    with assistbinding.bound(Selection((selected,), level)):
        assert source.selected_definition() is selected
        assert calls == []  # Projection does not execute conversion or authorize transport recovery.
        assert source.selected_definition().execute('chosen', {}, {}) == {'replacement': 'chosen'}
        assert calls == [('chosen', {}, {})]


def test_absent_source_in_nonempty_selection_does_not_summon_default():
    unrelated = CompletionDefinition(Policy('other', 'output-repair', 1, family_id='F99'), lambda value: value)
    with assistbinding.bound(Selection((unrelated,), 5)):
        assert source.selected_definition() is None


def test_nested_empty_exception_scope_restores_exact_outer_replacement():
    selected = replace(source.DEFINITION, execute=lambda *args: {})
    with assistbinding.bound(Selection((selected,), 5)):
        with pytest.raises(RuntimeError):
            with assistbinding.bound(Selection()):
                assert source.selected_definition() is None
                raise RuntimeError('leave child')
        assert source.selected_definition() is selected
    assert source.selected_definition() is source.DEFINITION


@pytest.mark.parametrize('definitions', [
    (source.DEFINITION, source.DEFINITION),
    (CompletionDefinition(source.DEFINITION.policy, lambda value: value),),
    (replace(source.DEFINITION, execute=None),),
    (replace(source.DEFINITION, policy=replace(source.DEFINITION.policy, default_level=0)),),
    (replace(source.DEFINITION, policy=replace(source.DEFINITION.policy, stage='other')),),
])
def test_invalid_or_duplicate_matching_contract_is_rejected_not_defaulted(definitions):
    with assistbinding.bound(Selection(definitions, 5)):
        with pytest.raises(ValueError):
            source.selected_definition()


def test_projection_cold_import_and_execution_need_no_catalog_or_dispatcher():
    script = '''import sys
from types import SimpleNamespace
from cria import argumentconversion as source, assistbinding
assert source.selected_definition() is source.DEFINITION
with assistbinding.bound(SimpleNamespace(definitions=(), engagement_level=5)):
    assert source.selected_definition() is None
with assistbinding.bound(SimpleNamespace(definitions=(source.DEFINITION,), engagement_level=1)):
    selected = source.selected_definition()
    assert selected is source.DEFINITION
    assert selected.execute('tool', {'n': '7'}, {'tool': {'properties': {'n': {'type': 'integer'}}}}) == {'n': 7}
for name in ('assistruntime', 'toolstages', 'massage', 'writeproxy', 'outputpolicies'):
    assert 'cria.' + name not in sys.modules, name
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
