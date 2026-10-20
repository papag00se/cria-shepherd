"""Successful repository checks retain evidence, not an authored success verdict."""
import json

import pytest

from cria import assistruntime, bodykeys, probediscovery, probegate, upstream
from cria.assistprofiles import RANK4_ABLATION_DISABLED
from test_gate_outlives_the_harness_yield import _page
from test_upstream import _Rlog


def test_clean_checks_keep_exact_output_and_command_scope():
    output = ('[INFO] --- compiler:testCompile (default-testCompile) @ project ---\n'
              '[INFO] No sources to compile\n'
              '[INFO] No tests to run.\n'
              '[INFO] BUILD SUCCESS\n'
              '  checker-specific detail  \n')
    candidate = probediscovery.ProbeCandidate(
        command=['mvn', 'test'], kind=probediscovery.ProbeKind.Test,
        working_dir='/remote/project', confidence=90, expected_value=80,
        cost=probediscovery.ProbeCost.Cheap, mutates_code=False,
        may_hang=False, may_need_services=False, reason='declared build')
    plan = probegate.GatePlan(workspace='/remote/project', candidates=[candidate])
    raw = probegate._marker('probe-0') + '\n' + output + '\nEXIT:0\n'
    with assistruntime.bound(assistruntime.AssistRuntime.select(profile='rank4-ablation')):
        shown = probegate.clean_gate_output(raw, plan)
    assert output in shown
    assert 'mvn test' in shown
    assert 'exit 0' in shown
    assert "repo's own checks that ran reported no error-class problems" not in shown


def test_silent_clean_check_reports_exit_without_inventing_tool_words():
    raw = probegate._marker('probe-0') + '\n\nEXIT:0\n'
    shown = probegate.clean_gate_output(raw)
    assert 'exit 0' in shown
    assert 'no output' in shown
    assert 'no error-class problems' not in shown


def test_clean_output_is_not_capped_outside_wire_floor():
    output = ''.join(f'  record {i}: evidence  \n' for i in range(4000))
    raw = probegate._marker('probe-0') + '\n' + output + '\nEXIT:0\n'
    assert output in probegate.clean_gate_output(raw)


@pytest.mark.parametrize('original_command_known', [True, False])
def test_no_tests_output_survives_new_plan_and_final_wire(original_command_known):
    # Baseline 1792305296: 0016 had the no-tests qualifier, 0031 replaced it
    # after scratch/CsvTest.java appeared. The original checker's own scope must
    # not depend on mutable discovery metadata from a different gate.
    output = ('[INFO] No sources to compile\n[INFO] No tests to run.\n'
              '[INFO] BUILD SUCCESS\nchecker quoted: no usable result\n')
    raw = probegate._marker('probe-0') + '\n' + output + '\nEXIT:0\n'
    original = probediscovery.cand(probediscovery.ProbeKind.Test, ['mvn', 'test'],
        '/remote/project', 90, 80, probediscovery.ProbeCost.Cheap, 'project tests')
    other = probediscovery.cand(probediscovery.ProbeKind.BuildCheck, ['javac', 'scratch/Probe.java'],
        '/other/project', 90, 80, probediscovery.ProbeCost.Cheap, 'scratch compilation')
    old = probegate.GatePlan(workspace='/remote/project', transport_required=True,
                            candidates=[original] if original_command_known else [],
                            untested=['No matching project tests were found.'])
    page = _page(old, raw)
    assert probegate.ingest_transport(old, page) == 'complete'
    messages = [
        {'role': 'user', 'content': 'Improve this project'},
        {'role': 'assistant', 'tool_calls': [{'id': 'check', 'type': 'function',
            'function': {'name': 'exec_command', 'arguments': '{"cmd":"mvn test"}'}}]},
        {'role': 'tool', 'tool_call_id': 'check', 'content': page},
        {'role': 'user', 'content': 'Continue'},
    ]
    selected = assistruntime.AssistRuntime.select(profile='rank4-ablation')
    with assistruntime.bound(selected):
        newest = probegate.clean_gate_results(messages, old)
        historical = probegate.clean_gate_results(messages,
            probegate.GatePlan(workspace='/other/project', candidates=[other]))
        up = upstream.Upstream('http://offline.invalid', engagement_level=5, context_window=32768)
        wire, _estimate, _error = up._prep({'messages': historical}, False, _Rlog())
        sent = json.loads(wire)
    assert output in newest[2]['content']
    assert output in historical[2]['content']
    assert 'javac' not in historical[2]['content']
    assert ('mvn test — exit 0' if original_command_known else 'probe-0 — exit 0') in historical[2]['content']
    assert '[INFO] No tests to run.' in json.dumps(sent)
    assert "repo's own checks that ran reported no error-class problems" not in json.dumps(sent)
    assert sent['messages'][2]['tool_call_id'] == sent['messages'][1]['tool_calls'][0]['id']
    assert not set(bodykeys.ALL) & sent.keys()
    assert all(not set(bodykeys.ALL) & m.keys() for m in sent['messages'])
    assert json.loads(sent['messages'][1]['tool_calls'][0]['function']['arguments']) == {'cmd': 'mvn test'}


def test_unknown_transport_stays_unknown_at_final_wire():
    plan = probegate.GatePlan(workspace='/remote/project', transport_required=True)
    page = _page(plan, probegate._marker('probe-0') + '\nEXIT:0\n')
    assert probegate.ingest_transport(plan, page) == 'complete'
    probegate.fail_transport(plan, 'incomplete evidence')
    messages = [
        {'role': 'user', 'content': 'Improve this project'},
        {'role': 'assistant', 'tool_calls': [{'id': 'unknown', 'type': 'function',
            'function': {'name': 'exec_command', 'arguments': '{"cmd":"project-check"}'}}]},
        {'role': 'tool', 'tool_call_id': 'unknown', 'content': page},
        {'role': 'user', 'content': 'Continue'},
    ]
    with assistruntime.bound(assistruntime.AssistRuntime.select(profile='rank4-ablation')):
        cleaned = probegate.clean_gate_results(messages, plan)
        up = upstream.Upstream('http://offline.invalid', engagement_level=5, context_window=32768)
        wire, _estimate, _error = up._prep({'messages': cleaned}, False, _Rlog())
    sent = json.loads(wire)
    assert sent['messages'][2]['content'] == probegate.prompts.load('probe_transport_unknown')
    assert 'Recorded checker results' not in wire.decode()
    assert sent['messages'][2]['tool_call_id'] == sent['messages'][1]['tool_calls'][0]['id']


def test_large_clean_output_uses_existing_labelled_final_wire_floor():
    output = ''.join(f'record {i}: distinct checker detail {i * 17}\n' for i in range(4000))
    raw = probegate._marker('probe-0') + '\n' + output + '\nEXIT:0\n'
    shown = probegate.clean_gate_output(raw)
    messages = [
        {'role': 'user', 'content': 'Improve this project'},
        {'role': 'assistant', 'tool_calls': [{'id': 'check', 'type': 'function',
            'function': {'name': 'exec_command', 'arguments': '{"cmd":"project-check"}'}}]},
        {'role': 'tool', 'tool_call_id': 'check', 'content': shown},
        {'role': 'user', 'content': 'Continue'},
    ]
    selected = assistruntime.AssistRuntime.select(profile='rank4-ablation')
    with assistruntime.bound(selected):
        up = upstream.Upstream('http://offline.invalid', engagement_level=5, context_window=4096)
        wire, _estimate, _error = up._prep(
            {'messages': messages, bodykeys.PINNED_TASK: 'Improve this project'}, False, _Rlog())
    sent = json.loads(wire)
    visible = json.dumps(sent, ensure_ascii=False)
    assert len(visible) < len(shown)
    assert '⟦ctx:reduced⟧' in visible or '⟦ctx:compacted⟧' in visible
    assert 'no error-class problems' not in visible
    assert not set(bodykeys.ALL) & sent.keys()
    assert all(not set(bodykeys.ALL) & m.keys() for m in sent['messages'])
    calls = {tc['id'] for m in sent['messages'] for tc in m.get('tool_calls', [])}
    assert all(m['tool_call_id'] in calls for m in sent['messages'] if m['role'] == 'tool')
    assert not set(selected.selected) & set(RANK4_ABLATION_DISABLED)
