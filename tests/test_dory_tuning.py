"""The optional workstation probe must restore the borrowed service on failures."""
import importlib.util
import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cria import prompts

SPEC = importlib.util.spec_from_file_location('tune_dory', Path(__file__).resolve().parents[1] / 'scripts/vram-probes/tune_dory.py')
tune = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tune)


def test_launch_changes_only_experiment_gpu_and_preserves_three_loops():
    original = ['server', '--port', '18084', '--cache-type-k', 'f16', '--cache-type-v', 'f16',
                '--flash-attn', 'on', '--batch-size', '512', '--ubatch-size', '512',
                '--override-kv', 'original', '--spec-type', 'none']
    plan = {'argv': original, 'env': {'CUDA_VISIBLE_DEVICES': tune.OTHER_GPU}}
    with patch.object(tune, 'fleet_plan', return_value=plan):
        for arm in tune.make_arms():
            argv, env = tune.launch_argv(arm)
            assert env['CUDA_VISIBLE_DEVICES'] == tune.GPU
            assert argv[argv.index('--port') + 1] == str(tune.PORT)
            assert argv[argv.index('--override-kv') + 1] == f"dory.num_loops=int:3,dory.recurrent_kv_cache_mode=str:{arm['mode']}"
    assert plan['env']['CUDA_VISIBLE_DEVICES'] == tune.OTHER_GPU
    assert original[original.index('--port') + 1] == '18084'
    assert original[original.index('--override-kv') + 1] == 'original'


@pytest.mark.parametrize('failure', ['stop', 'arm'])
def test_restores_original_container_even_if_stop_or_sweep_raises(tmp_path, failure):
    (tmp_path / 'locks').mkdir()
    calls = []
    def command(*args):
        calls.append(args)
        if args[1] == 'inspect':
            return 'true'
        if args[1] == 'stop' and failure == 'stop':
            raise RuntimeError('control connection lost after stop')
        return tune.CONTAINER
    metrics = MagicMock()
    metrics.__enter__.return_value = metrics
    metrics.read.return_value = b'vllm:num_requests_running{engine="0"} 0\nvllm:num_requests_waiting{engine="0"} 0\n'
    output = tmp_path / 'run'
    with patch.object(tune, 'FLEET', tmp_path), patch.object(tune, 'command', side_effect=command), \
         patch.object(tune, 'gpu_processes', return_value=[]), patch.object(tune.urllib.request, 'urlopen', return_value=metrics), \
         patch.object(tune, 'wait_ready'), patch.object(tune, 'original_models', return_value={'data': []}), \
         patch.object(tune, 'run_arm', side_effect=RuntimeError('injected sweep failure')), \
         patch.object(tune.signal, 'signal'), patch.object(tune.socket, 'socket'), \
         patch.object(tune.sys, 'argv', ['probe', '--output', str(output)]):
        with pytest.raises(RuntimeError):
            tune.main()
    assert ('docker', 'start', tune.CONTAINER) in calls
    assert json.loads((output / 'state.json').read_text())['restored'] is True


def test_restored_identity_uses_existing_container_auth_without_persisting_secret():
    with patch.object(tune, 'command', return_value='["VLLM_API_KEY=fixture-secret"]'), \
         patch.object(tune, 'fetch', return_value={'data': [{'id': 'original'}]}) as fetch:
        assert tune.original_models() == {'data': [{'id': 'original'}]}
    fetch.assert_called_once_with('http://127.0.0.1:18020', '/v1/models', headers={'Authorization': 'Bearer fixture-secret'})


def test_readiness_accepts_vllm_empty_http_200_health_body():
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = b''
    with patch.object(tune.urllib.request, 'urlopen', return_value=response):
        tune.wait_ready('http://localhost:18020', seconds=0)


@pytest.mark.parametrize('status,headers,body', [
    (429, {'Retry-After': '120'}, b'{"error":"limited"}'),
    (429, {}, b'{"retry_after":120}'),
    (503, {'Retry-After': '120'}, b'{"error":"limited"}'),
    (200, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '9999999999'}, b''),
])
def test_rate_signals_abort_without_readiness_polling_or_another_origin_request(status, headers, body):
    base = f'http://localhost:{19000 + status + bool(headers)}'
    url = base + '/health'
    response = MagicMock(headers=headers, status=status)
    response.__enter__.return_value = response
    error = urllib.error.HTTPError(url, status, 'limited', headers, io.BytesIO(body))
    # A distinct origin keeps tests independent; a second path must still be blocked.
    with patch.object(tune.urllib.request, 'urlopen', side_effect=error if status != 200 else None,
                      return_value=response) as opener, patch.object(tune.time, 'sleep') as sleep:
        with pytest.raises(RuntimeError, match='limit') as caught:
            tune.wait_ready(base, seconds=0)
        assert ('120' if status != 200 else '9999999999') in str(caught.value)
        with pytest.raises(RuntimeError, match='limit'):
            tune.fetch(base, '/other')
    assert opener.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize('names', [[], ['unknown-arm']])
def test_bad_arm_selection_is_rejected_before_any_resource_or_output_mutation(tmp_path, names):
    output = tmp_path / 'run'
    with patch.object(tune, 'FLEET', tmp_path / 'must-not-open'), \
         patch.object(tune, 'command') as control, \
         patch.object(tune.sys, 'argv', ['probe', '--output', str(output), '--arms', *names]):
        with pytest.raises(SystemExit) as caught:
            tune.main()
    assert caught.value.code == 2
    control.assert_not_called()
    assert not output.exists()


def test_case_generation_fills_template_without_interpreting_json_braces():
    cases = prompts.load_map('dory_tune_cases')
    row = prompts.fill(cases['row'], index='012', retries=5)
    text = prompts.fill(cases['retrieval'], block=row)
    assert 'item_012 = {"enabled": True, "retries": 5, "label": "worker_012"}' in text
    assert '{{' not in text
