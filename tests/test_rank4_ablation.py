"""The pinned ablation is an exact opt-out, never a planning opt-in."""
import io
import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from cria import classify, loop, massage, server, upstream, webfetch
from cria.assistprofiles import RANK4_DISABLED, RANKING_REVISION
from cria.config import LoggingConfig
from test_upstream import _Rlog

import pytest

from cria import assistruntime
from cria.config import AssistConfig, Config


def ranked_ids(rank):
    text = Path('docs/audits/assist-principles-ranking.md').read_text()
    section = text.split(f'## Rank {rank} —', 1)[1].split('\n## ', 1)[0]
    return tuple(re.findall(r'^\| \d+ \| `([^`]+)`', section, re.M))


@pytest.mark.parametrize('level', range(6))
def test_profile_disables_exact_pinned_48_and_preserves_other_capabilities(level):
    cfg = Config(assists=AssistConfig(profile='rank4-ablation'))
    selected = assistruntime.AssistRuntime.select(profile=cfg.assists.profile, level=level)
    ordinary = assistruntime.AssistRuntime.select(level=level)
    excluded = ranked_ids(4)
    assert RANKING_REVISION == '079116e4c99635722a0f3327246fd9e359586eb5'
    assert excluded == RANK4_DISABLED
    assert len(excluded) == len(set(excluded)) == 48
    assert set(selected.selected) == set(ordinary.selected) - set(excluded)
    assert set(selected.selected) <= set(ranked_ids(1) + ranked_ids(2) + ranked_ids(3))
    assert not cfg.planner.enabled and not selected.experimental_planning
    # Capability selection with explicit experimental consent is also exact;
    # selecting this profile alone must never supply that consent.
    enabled = assistruntime.AssistRuntime.select(experimental_planning=True, level=level)
    ablated = assistruntime.AssistRuntime.select(profile=cfg.assists.profile, level=level,
                                               experimental_planning=True)
    assert set(ablated.selected) == set(enabled.selected) - set(excluded)


@pytest.mark.parametrize('profile', ['rank4', '', None, False, ['rank4-ablation']])
def test_unknown_or_malformed_profile_is_rejected(profile):
    with pytest.raises(ValueError):
        AssistConfig(profile=profile)


def test_exact_profile_rejects_additional_optouts():
    with pytest.raises(ValueError):
        AssistConfig(profile='rank4-ablation', disabled=('schema-argument-conversion',))


def test_profile_cannot_be_relabelled_or_silently_redistribute_bindings():
    ordinary = assistruntime.AssistRuntime.select()
    with pytest.raises(ValueError, match='exact selected profile'):
        replace(ordinary, profile='rank4-ablation')
    selected = assistruntime.AssistRuntime.select(profile='rank4-ablation')
    with pytest.raises(ValueError, match='exact selected profile'):
        replace(selected, argument_conversion=None)
    runaway = next(d for d in ordinary.ordered_stages if d.policy.id == 'generation-runaway-guard')
    with pytest.raises(ValueError, match='exact selected profile'):
        replace(selected, ordered_stages=selected.ordered_stages + (runaway,))


def test_toml_profile_reaches_real_server_without_enabling_planning(tmp_path, monkeypatch):
    path = tmp_path / 'profile.toml'
    path.write_text('[assists]\nprofile = "rank4-ablation"\n[engagement]\nlevel = 5\n'
                    '[backends.local]\nbase_url = "http://offline.invalid"\n'
                    '[roles.coder]\nbackend = "local"\n')
    cfg = Config.load(path)
    monkeypatch.setattr(server.ThreadingHTTPServer, '__init__', lambda *_a, **_k: None)
    cfg = replace(cfg, logging=LoggingConfig(dir=str(tmp_path / 'logs')))
    instance = server.CriaServer(cfg, Mock(), Mock())
    expected = assistruntime.AssistRuntime.select(profile='rank4-ablation')
    assert instance.pilot_runtime == expected
    assert instance.loop is not None and not instance.loop._ctx.planner_enabled
    with assistruntime.bound(instance.pilot_runtime):
        service = classify.Classifier(Mock())
        handler = server.CriaHandler.__new__(server.CriaHandler)
        handler.server = SimpleNamespace(classifier=service)
        assert handler._classify({'messages': [{'role': 'user', 'content': 'Change a file'}]}, Mock()) is None
        service._provider.chat.assert_not_called()


def test_profile_controls_recovery_and_research_without_removing_quarantine(monkeypatch):
    from test_output_selection_boundary import LEAK, MENU
    selected = assistruntime.AssistRuntime.select(profile='rank4-ablation')
    webfetch.clear_cache()
    try:
        webfetch.set_visible('rank4', [], ['widget api docs'])
        with assistruntime.bound(assistruntime.AssistRuntime.select()):
            baseline = {'choices': [{'finish_reason': 'stop', 'message': {'content': LEAK}}]}
            assert massage.apply(baseline, MENU, tool_call_fixes=True)['choices'][0]['message']['tool_calls']
            assert webfetch.gate_search('rank4', 'widget api docs') is not None
        with assistruntime.bound(selected):
            completion = {'choices': [{'finish_reason': 'stop', 'message': {'content': LEAK}}]}
            assert massage.apply(completion, MENU, tool_call_fixes=True)['choices'][0]['message']['content'] == LEAK
            assert webfetch.gate_search('rank4', 'widget api docs') is None
            assert webfetch.gate_search('rank4', 'widget api docs') is None
            # The retained output-truncation lifecycle is not the disabled runaway
            # lifecycle. Malformed native calls must still be quarantined.
            partial = {'choices': [{'finish_reason': 'tool_calls', 'message': {
                'tool_calls': [{'id': 'partial', 'type': 'function', 'function': {
                    'name': 'native_write', 'arguments': '{"path":"x","content":"unfinished'}}]}}]}
            result = loop._generation_recovery(partial, {'messages': []}, Mock(), _Rlog())
            assert not result.completion['choices'][0]['message'].get('tool_calls')
    finally:
        webfetch.clear_cache()


def test_real_transient_retry_keeps_ablation_at_each_final_wire_boundary(monkeypatch):
    selected = assistruntime.AssistRuntime.select(profile='rank4-ablation')
    attempts = []
    waits = []
    monkeypatch.setattr(upstream.time, 'sleep', waits.append)
    repeated = 'Evidence line with a different seed: 123456789abcdef\n' * 30
    messages = [{'role': 'user', 'content': 'Keep all evidence'},
                {'role': 'assistant', 'content': repeated},
                {'role': 'user', 'content': repeated}]
    def open_request(request, **options):
        assert assistruntime.current() is selected
        sent = json.loads(request.data)
        assert sent['messages'] == messages  # no optional repeated-payload fold
        assert not any(key.startswith('_cria') for key in sent)
        attempts.append(sent)
        if len(attempts) == 1:
            raise OSError('timed out')
        return io.BytesIO(b'{"choices":[{"message":{"content":"unchanged"}}]}')
    up = upstream.Upstream('http://offline.invalid', engagement_level=5,
                           context_window=32768, open_request=open_request)
    with assistruntime.bound(selected):
        raw = up.chat({'messages': messages}, _Rlog())
        assert assistruntime.current() is selected
    assert json.loads(raw)['choices'][0]['message']['content'] == 'unchanged'
    assert len(attempts) == 2 and waits == [.5]


def test_real_driver_protocol_redrive_preserves_profile_and_required_recovery(monkeypatch):
    from test_generation_driver_policy import setup_driver, reject, generation_transport, completion
    from test_loop import _Rlog as DriverLog
    driver, session, body = setup_driver()
    selected = assistruntime.AssistRuntime.select(profile='rank4-ablation')
    driver._ctx.pilot_runtime = selected
    driver._ctx.focus_trim = driver._ctx.self_compact = True
    good = completion('tool_calls', evidence=False)
    good['choices'][0]['message']['tool_calls'][0]['function'] = {
        'name': 'read_file', 'arguments': '{"path":"notes.txt"}'}
    transport = generation_transport([reject(), io.BytesIO(json.dumps(good).encode())])
    attempts = []
    def send(request, **kwargs):
        assert assistruntime.current() is selected
        if request.full_url.endswith('/v1/chat/completions'):
            attempts.append(json.loads(request.data))
        return transport(request, **kwargs)
    monkeypatch.setattr(upstream.urllib.request, 'urlopen', send)
    gate = Mock(side_effect=AssertionError('acting reply must not release completion'))
    monkeypatch.setattr(driver, '_verify', gate)
    out = driver.drive(body, 'driver-fixture', None, DriverLog())
    assert len(attempts) == 2 and attempts[0] != attempts[1]
    assert '⟦ctx:generation⟧' in json.dumps(attempts[1], ensure_ascii=False)
    assert out['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'read_file'
    assert session.unexecuted_nudges == 1
    gate.assert_not_called()
