"""Low contracts/storage cannot acquire defaults, policy catalogs or dispatchers."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from typing import get_type_hints

import pytest

from cria import assistbinding, assistruntime, config, planningcontracts, privatepaths, shrinkcontracts, toolcontracts, toolstages
from cria.assistcontract import Policy


@pytest.mark.parametrize('module', ['assistbinding', 'toolcontracts', 'shrinkcontracts', 'privatepaths', 'planningcontracts'])
def test_lower_modules_import_without_catalog_or_implementations(module):
    script = f'''import sys
import cria.{module}
for name in ('assistruntime', 'toolstages', 'outputpolicies', 'outboundpolicies', 'returnedpolicies',
             'shrinkprotection', 'planner', 'experimentalplanning', 'config', 'massage', 'writeproxy'):
    assert 'cria.' + name not in sys.modules, (name, sorted(sys.modules))
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('name', ['EventLog', '_PolicyLog', 'policy_log', 'CompletionTransform',
    'CompletionRepair', 'CompletionDefinition', 'ShrinkFinding', 'ShrinkCheck', 'EditSequence',
    'LoweringRequest', 'OutboundCall', 'RewrittenCall', 'ShellCommand', 'OutboundEffect',
    'OutboundDefinition', 'MutationDefinition', 'ReturnedResult', 'ReturnedDefinition',
    'ReturnedHistory', 'HistoryDefinition', 'RejectedDraft', 'DraftDefinition', 'ToolDefinition'])
def test_legacy_tool_exports_are_same_canonical_objects(name):
    assert getattr(toolstages, name) is getattr(toolcontracts, name)


def test_low_request_and_return_records_preserve_construction_and_type_identity():
    request = toolcontracts.LoweringRequest(frozenset({'write_file'}))
    assert request.shrink_services is None and request.external_dir_permission == 'write'
    assert request.declared_roots == () and request.pack is request.edit_echo is False
    source = toolcontracts.OutboundCall({'function': {'name': 'write_file'}}, {'path': 'one'}, request)
    assert source.function is source.call['function'] and source.name == 'write_file'
    assert isinstance(toolcontracts.ShellCommand('real command'), toolstages.ShellCommand)
    assert get_type_hints(toolcontracts.LoweringRequest)['shrink_services'] == shrinkcontracts.ShrinkServices | None
    with pytest.raises(FrozenInstanceError):
        request.pack = True


def test_event_attribution_retains_nested_source_identity_and_real_fields():
    events = []
    class Log:
        def emit(self, kind, **fields):
            events.append((kind, fields))
    policy = Policy(id='owned', stage='output-repair', default_level=1, family_id='F1')
    tagged = toolcontracts.policy_log(Log(), policy)
    tagged.emit('actual.event', count=7)
    tagged.emit('nested.event', assist_id='nested', family_id='F2', count=9)
    assert events == [('actual.event', {'count': 7, 'assist_id': 'owned', 'family_id': 'F1'}),
                      ('nested.event', {'assist_id': 'nested', 'family_id': 'F2', 'count': 9})]
    assert toolcontracts.policy_log(None, policy) is None


def empty_runtime():
    return assistruntime.AssistRuntime.select(level=0,
        disabled=tuple(d.policy.id for d in assistruntime.DEFINITIONS if d.policy.default_level == 0))


def test_storage_distinguishes_unbound_from_explicit_empty_and_restores_after_error():
    assert assistbinding.current() is assistbinding.UNBOUND
    assert not assistbinding.is_bound() and assistruntime.current() is assistruntime.DEFAULT
    high, empty = assistruntime.AssistRuntime.select(), empty_runtime()
    with assistruntime.bound(high):
        assert assistbinding.current() is high and assistruntime.current() is high
        with pytest.raises(RuntimeError):
            with assistruntime.bound(empty):
                assert assistbinding.current() is empty and assistbinding.is_bound()
                assert assistruntime.current().definitions == ()
                assert toolstages.current().definitions == ()
                raise RuntimeError('scope exited')
        assert assistbinding.current() is high
    assert assistbinding.current() is assistbinding.UNBOUND
    assert assistruntime.current() is assistruntime.DEFAULT
    assert toolstages.current() is toolstages.defaults()
    with pytest.raises(ValueError):
        with assistbinding.bound(assistbinding.UNBOUND):
            pytest.fail('absence cannot be an executable selection')


def test_storage_can_hold_structural_selection_without_owning_a_catalog():
    @dataclass(frozen=True)
    class Selection:
        definitions: tuple = ()
        engagement_level: int = 0
    selection = Selection()
    with assistbinding.bound(selection):
        assert assistbinding.current() is selection
        assert assistbinding.current().definitions == ()
    assert assistbinding.current() is assistbinding.UNBOUND


def test_replacement_identity_is_not_substituted_by_storage_or_tool_projection():
    original = assistruntime.TOOL_DEFINITIONS[0]
    replacement = replace(original, execute=lambda *args, **kwargs: {'exact': 'replacement'})
    base = assistruntime.AssistRuntime.select()
    selected = replace(base, ordered_stages=tuple(
        replacement if d.policy.id == replacement.policy.id else d for d in base.ordered_stages))
    with assistruntime.bound(selected):
        assert next(d for d in assistbinding.current().definitions if d.policy.id == original.policy.id) is replacement
        assert next(d for d in toolstages.current().definitions if d.policy.id == original.policy.id) is replacement
    assert assistbinding.current() is assistbinding.UNBOUND


def test_nested_concurrent_storage_scopes_do_not_share_bindings():
    barrier = Barrier(2)
    def worker(level):
        outer = assistruntime.AssistRuntime.select(level=level)
        with assistruntime.bound(outer):
            barrier.wait(timeout=5)
            assert assistbinding.current() is outer
            with assistruntime.bound(empty_runtime()):
                barrier.wait(timeout=5)
                assert assistbinding.current().definitions == ()
            assert assistbinding.current() is outer
        assert assistbinding.current() is assistbinding.UNBOUND
        return outer.engagement_level
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(worker, (1, 5))) == [1, 5]
    assert assistbinding.current() is assistbinding.UNBOUND


def test_private_path_is_one_canonical_object_not_configuration_owned():
    assert config.CRIA_HOME is privatepaths.CRIA_HOME
    assert privatepaths.CRIA_HOME == Path('~/.cria').expanduser()


def test_shared_planning_records_keep_mutability_positional_fields_and_pending_fact():
    outcome = planningcontracts.PlanOutcome()
    assert outcome.survey_pending is False
    outcome.survey_pending = True
    assert outcome.survey_pending is True
    assert planningcontracts.ToolResult('no answer', False) == planningcontracts.ToolResult('no answer', False, False)
    waiting = planningcontracts.ToolResult('awaiting bytes', False, True)
    assert waiting.pending is True and waiting.learned is False
    with pytest.raises(FrozenInstanceError):
        waiting.pending = False
    assert 'A refusal, an error' in planningcontracts.ToolResult.__doc__
