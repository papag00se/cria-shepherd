"""Production selection is authoritative across library, request and task contexts."""
from contextvars import copy_context
import subprocess
import sys
from unittest.mock import Mock

import pytest

from cria import (assistruntime, completionapproval, completiondiagnosis, completionconfirmation, runnercontract, repositorychecks, evidencesummary, memoryhandoff, semanticquery, stalledwork, planner, pastedfile, livingplan, stepreview, completedwork, contextrestoration, focustrim, ledgercopies, massage,
                  modelview, outputpolicies, preamblepolicy, reorientation, selfcompact,
                  steppreparation, toolstages, capacitypolicy, transientpolicy, discoverypolicy,
                  documentguidance, externalization, completionredrive)
from cria.config import AssistConfig, Config, LoggingConfig, RoutingConfig
from cria.server import CriaServer, ThreadingHTTPServer
from test_output_selection_boundary import LEAK, MENU


def completion():
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': LEAK}}]}


def recovered():
    return massage.apply(completion(), MENU)['choices'][0]['message'].get('tool_calls')


def test_default_registry_and_constructor_include_the_actual_source_bindings():
    source = toolstages.defaults().definitions
    assert assistruntime.TOOL_DEFINITIONS == source
    context = ((selfcompact.DEFINITION,) + focustrim.FOCUS_STAGE + modelview.WIRE_FOLD_STAGE
               + (contextrestoration.DEFINITION, ledgercopies.DEFINITION,
                  reorientation.DEFINITION, preamblepolicy.DEFINITION)
               + steppreparation.DEFINITIONS)
    assert assistruntime.CONTEXT_DEFINITIONS == context
    assert all(actual is expected for actual, expected in
               zip(assistruntime.CONTEXT_DEFINITIONS, context, strict=True))
    assert assistruntime.DEFINITIONS == (assistruntime.ARGUMENTS, assistruntime.MODULE,
                                        assistruntime.TASK_REVIEW) + source + assistruntime.RESEARCH_DEFINITIONS + assistruntime.HISTORY_DEFINITIONS + assistruntime.ADMISSION_DEFINITIONS + assistruntime.GENERATION_DEFINITIONS + context + completionapproval.PRE_RELEASE + completiondiagnosis.DEFINITIONS + completionconfirmation.DEFINITIONS + (runnercontract.DEFINITION,) + repositorychecks.DEFINITIONS + (evidencesummary.DEFINITION, memoryhandoff.DEFINITION) + semanticquery.DEFINITIONS + (stalledwork.DEFINITION,) + planner.DEFINITIONS + (pastedfile.DEFINITION,) + livingplan.DEFINITIONS + (stepreview.DEFINITION, completedwork.DEFINITION, capacitypolicy.DEFINITION, transientpolicy.TRANSIENT_RECOVERY, discoverypolicy.DEFINITION, documentguidance.DEFINITION, externalization.DEFINITION, completionredrive.DEFINITION)
    assert assistruntime.AssistRuntime().definitions == assistruntime.AssistRuntime.select().definitions
    assert assistruntime.DEFAULT.definitions == assistruntime.AssistRuntime.select().definitions
    assert toolstages.ToolStages.from_definitions(assistruntime.DEFAULT.definitions) == toolstages.defaults()
    l0 = tuple(d for d in source if d.policy.default_level == 0) + (preamblepolicy.DEFINITION, capacitypolicy.DEFINITION, transientpolicy.TRANSIENT_RECOVERY, discoverypolicy.DEFINITION, documentguidance.DEFINITION, externalization.DEFINITION)
    assert assistruntime.AssistRuntime.select(level=0).definitions == l0
    assert assistruntime.AssistRuntime.select(level=0,
        disabled=tuple(d.policy.id for d in l0)).definitions == ()


@pytest.mark.parametrize('first', ['cria.assistruntime', 'cria.outputpolicies', 'cria.massage', 'cria.writeproxy'])
def test_registry_import_is_independent_of_entry_module(first):
    # Fresh Python is necessary to detect partially initialized import cycles;
    # the child imports modules only, with no providers, sockets or commands.
    script = f'import {first}; from cria import assistruntime, toolstages; assert assistruntime.TOOL_DEFINITIONS == toolstages.defaults().definitions'
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_nested_task_bindings_restore_parent_and_library_selection_after_error():
    def run():
        massage.set_tool_call_fixes(True)
        high = assistruntime.AssistRuntime.select(level=5)
        low = assistruntime.AssistRuntime.select(level=0,
            disabled=tuple(d.policy.id for d in assistruntime.TOOL_DEFINITIONS if d.policy.default_level == 0))
        assert not toolstages.is_bound() and recovered()
        with assistruntime.bound(high):
            parent = toolstages.current()
            assert recovered() and parent.definitions == assistruntime.TOOL_DEFINITIONS
            with pytest.raises(RuntimeError):
                with assistruntime.bound(low):
                    assert toolstages.is_bound() and toolstages.current().definitions == ()
                    assert not recovered()
                    raise RuntimeError('task aborted')
            assert assistruntime.current() is high and toolstages.current() is parent and recovered()
        assert not toolstages.is_bound() and assistruntime.current() is assistruntime.DEFAULT
        assert recovered()
    copy_context().run(run)


def test_config_optout_selects_before_recovery_and_keeps_unrelated_bindings():
    identifier = outputpolicies.RECOVERY[0].policy.id
    cfg = Config(assists=AssistConfig(disabled=(identifier,)))
    selected = assistruntime.AssistRuntime.select(level=cfg.routing.engagement_level,
                                                 disabled=cfg.assists.disabled)
    assert identifier not in selected.selected
    assert selected.selected == tuple(d.policy.id for d in assistruntime.DEFAULT.definitions if d.policy.id != identifier)
    with assistruntime.bound(selected):
        assert massage.apply(completion(), MENU)['choices'][0]['message']['content'] == LEAK
    assert identifier in assistruntime.current().selected


def test_actual_server_construction_never_overrides_unbound_library_optout(tmp_path, monkeypatch):
    monkeypatch.setattr(ThreadingHTTPServer, '__init__', lambda *_a, **_k: None)
    monkeypatch.setattr(massage, 'set_tool_call_fixes', lambda *_: pytest.fail('server mutated library selection'))
    for level in (5, 0, 5):
        cfg = Config(routing=RoutingConfig(engagement_level=level),
                     logging=LoggingConfig(dir=str(tmp_path / str(level))))
        server = CriaServer(cfg, Mock(), Mock())
        assert server.pilot_runtime == assistruntime.AssistRuntime.select(level=level)
        assert not toolstages.is_bound()
