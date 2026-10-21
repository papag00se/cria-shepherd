#!/usr/bin/env python3
"""Machine-local, finite three-loop Dory sweep on the temporarily borrowed RTX3090.

Never touches the RTX3080 fleet or cria. Stops and restores the exact existing
3090 Docker container; complete requests/replies go to ~/.cria/calls/.
"""
from __future__ import annotations

import argparse
import ast
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

FLEET = Path('/home/jesse/.local/share/cria/fleet')
GPU = 'GPU-907a7f7a-b541-8208-2bce-e1361e3110d6'
OTHER_GPU = 'GPU-393d4998-707c-0ef0-a514-761015477256'
CONTAINER = '37d22bcfd043cb7c9498e3dfe14b4e6ff66e07509d6e8375f1b031b1d9105b24'
PORT = 18486
BASE = f'http://127.0.0.1:{PORT}'
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cria import prompts  # noqa: E402


def command(*argv):
    return subprocess.run(argv, check=True, text=True, capture_output=True).stdout.strip()


class RateLimited(RuntimeError):
    """Abort a finite timing experiment rather than retry a quota-bound request."""


_BLOCKED_ORIGINS = {}


def quota_headers(headers):
    return {key.lower(): value for key, value in dict(headers or {}).items()
            if key.lower() == 'retry-after' or key.lower().startswith(('x-ratelimit-', 'ratelimit-'))}


def limit_announced(headers):
    return 'retry-after' in headers or any(headers.get(key) in ('0', '0.0')
        for key in ('x-ratelimit-remaining', 'ratelimit-remaining'))


def http_open(req, timeout):
    origin = urllib.parse.urlsplit(req if isinstance(req, str) else req.full_url).netloc
    if origin in _BLOCKED_ORIGINS:
        raise RateLimited(_BLOCKED_ORIGINS[origin])
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        headers = quota_headers(error.headers)
        if error.code == 429 or limit_announced(headers):
            # Keep server delays (including JSON retry_after / RetryInfo) verbatim;
            # no origin is retried by this process, including readiness polling.
            detail = error.read()
            error.close()
            note = f'rate limit at {origin}: HTTP {error.code}, {headers}, {detail!r}; experiment aborted without retry'
            _BLOCKED_ORIGINS[origin] = note
            raise RateLimited(note) from error
        raise
    headers = quota_headers(response.headers)
    if limit_announced(headers):
        response.close()
        note = f'rate limit at {origin}: {headers}; experiment aborted without another request'
        _BLOCKED_ORIGINS[origin] = note
        raise RateLimited(note)
    return response


def fetch(base, path, body=None, timeout=600, headers=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', **(headers or {})})
    with http_open(req, timeout=timeout) as response:
        return json.load(response)


def original_models():
    # Read the existing container's secret without logging its environment or request headers.
    env = json.loads(command('docker', 'inspect', '--format', '{{json .Config.Env}}', CONTAINER))
    key = next(value.split('=', 1)[1] for value in env if value.startswith('VLLM_API_KEY='))
    return fetch('http://127.0.0.1:18020', '/v1/models', headers={'Authorization': 'Bearer ' + key})


def wait_ready(base, proc=None, seconds=900):
    deadline = time.monotonic() + seconds
    while True:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f'server exited with {proc.returncode}')
        try:
            # vLLM returns an empty HTTP 200 body; llama.cpp returns JSON.
            with http_open(base + '/health', timeout=3) as response:
                if response.status != 200:
                    raise OSError(f'unhealthy HTTP status {response.status}')
            return
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise TimeoutError('server readiness')
            time.sleep(1)


def gpu_processes():
    result = command('nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_gpu_memory', '--format=csv,noheader,nounits')
    return [line.split(', ') for line in result.splitlines()]


def make_arms():
    arms = []
    for name, k, v, fa, batch, ubatch, mode, spec, extra, env in [
        ('f16-fa-off', 'f16', 'f16', 'off', 512, 512, 'per_loop', 'none', [], {}),
        ('f16-fa-on', 'f16', 'f16', 'on', 512, 512, 'per_loop', 'none', [], {}),
        ('q8-fa-on', 'q8_0', 'q8_0', 'on', 512, 512, 'per_loop', 'none', [], {}),
        ('q8k-q4v', 'q8_0', 'q4_0', 'on', 512, 512, 'per_loop', 'none', [], {}),
        ('q4-kv', 'q4_0', 'q4_0', 'on', 512, 512, 'per_loop', 'none', [], {}),
        ('f16-b1024', 'f16', 'f16', 'on', 1024, 1024, 'per_loop', 'none', [], {}),
        ('f16-b2048-u1024', 'f16', 'f16', 'on', 2048, 1024, 'per_loop', 'none', [], {}),
        ('q8-b1024', 'q8_0', 'q8_0', 'on', 1024, 1024, 'per_loop', 'none', [], {}),
        ('q8-b2048-u1024', 'q8_0', 'q8_0', 'on', 2048, 1024, 'per_loop', 'none', [], {}),
        ('q8-last-loop', 'q8_0', 'q8_0', 'on', 512, 512, 'last_loop', 'none', [], {}),
        ('q8-ngram-mod', 'q8_0', 'q8_0', 'on', 512, 512, 'per_loop', 'ngram-mod',
         ['--spec-ngram-mod-n-min', '16', '--spec-ngram-mod-n-max', '32', '--spec-ngram-mod-n-match', '12'], {}),
        ('q8-ngram-simple', 'q8_0', 'q8_0', 'on', 512, 512, 'per_loop', 'ngram-simple',
         ['--spec-ngram-simple-size-n', '12', '--spec-ngram-simple-size-m', '32'], {}),
        ('q8-graph-opt', 'q8_0', 'q8_0', 'on', 512, 512, 'per_loop', 'none', [], {'GGML_CUDA_GRAPH_OPT': '1'}),
        ('q8-b2048-u1024-ngram-simple', 'q8_0', 'q8_0', 'on', 2048, 1024, 'per_loop', 'ngram-simple',
         ['--spec-ngram-simple-size-n', '12', '--spec-ngram-simple-size-m', '32'], {}),
    ]:
        arms.append(dict(name=name, k=k, v=v, fa=fa, batch=batch, ubatch=ubatch, mode=mode, spec=spec, extra=extra, env=env))
    return arms


def fleet_plan():
    # The operational fleet is a machine-local launch dependency, not a test dependency.
    sys.path.insert(0, str(FLEET / 'tools'))
    from fleet_cli import make_plan, records
    return make_plan(records()['dory1.0_4b'])


def launch_argv(arm):
    plan = fleet_plan()
    argv = plan['argv'][:]
    for flag, value in {
        '--port': PORT, '--cache-type-k': arm['k'], '--cache-type-v': arm['v'],
        '--flash-attn': arm['fa'], '--batch-size': arm['batch'], '--ubatch-size': arm['ubatch'],
        '--override-kv': f"dory.num_loops=int:3,dory.recurrent_kv_cache_mode=str:{arm['mode']}",
        '--spec-type': arm['spec'],
    }.items():
        argv[argv.index(flag) + 1] = str(value)
    if '--cache-ram' in argv:
        argv[argv.index('--cache-ram') + 1] = '0'
    else:
        argv += ['--cache-ram', '0']
    argv += arm['extra']
    env = {**os.environ, **plan['env'], 'CUDA_VISIBLE_DEVICES': GPU}
    env.pop('LD_PRELOAD', None)
    env.pop('GGML_CUDA_GRAPH_OPT', None)
    env.update(arm['env'])
    return argv, env


def stop_server(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run_arm(arm, folder, repeats, long_check=False, novel_check=False, benchmark_temp=0.0):
    folder.mkdir()
    result = {'settings': arm, 'benchmark_temperature': benchmark_temp, 'measurements': [], 'quality': {}}
    argv, env = launch_argv(arm)
    result['argv'] = argv
    result['environment_overrides'] = {**arm['env'], 'CUDA_VISIBLE_DEVICES': GPU}
    cases = prompts.load_map('dory_tune_cases')
    log = (folder / 'server.log').open('w')
    proc = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
    sequence = 0

    def request(path, body=None, label='call', stream=False):
        nonlocal sequence
        sequence += 1
        started = time.monotonic()
        first = None
        req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        with http_open(req, timeout=600) as response:
            if stream:
                lines, chunks = [], []
                for line in response:
                    line = line.decode()
                    lines.append(line)
                    if line.startswith('data: ') and line.strip() != 'data: [DONE]':
                        chunk = json.loads(line[6:])
                        chunks.append(chunk)
                        if first is None and chunk.get('content'):
                            first = time.monotonic() - started
                raw = ''.join(lines)
                value = next(c for c in reversed(chunks) if c.get('stop'))
                value = {**value, 'complete_content': ''.join(c.get('content', '') for c in chunks)}
            else:
                raw = response.read().decode()
                value = json.loads(raw)
        capture = {'path': path, 'request': body, 'response': value, 'raw_response': raw,
                   'elapsed_s': time.monotonic() - started, 'first_content_s': first}
        (folder / f'{sequence:03d}-{label}.json').write_text(json.dumps(capture, indent=2) + '\n')
        return capture

    try:
        wait_ready(BASE, proc)
        result['gpu_processes'] = gpu_processes()
        own = [r for r in result['gpu_processes'] if r[1] == str(proc.pid)]
        if len(own) != 1 or own[0][0] != GPU:
            raise RuntimeError('Dory not exclusively on requested RTX3090')
        request('/props', label='props')
        request('/v1/models', label='identity')
        block = '\n'.join(prompts.fill(cases['row'], index=f'{i:03d}', retries=i % 7) for i in range(160))
        user_cases = {name: prompts.fill(cases[name.replace('-', '_')], block=block) for name in ('new-code', 'copy-code')}
        rendered_prompts = {}
        for name, text in user_cases.items():
            template = request('/apply-template', {'messages': [{'role': 'user', 'content': text}],
                               'chat_template_kwargs': {'enable_thinking': False}}, label=name + '-template')
            rendered_prompts[name] = template['response']['prompt']
        for name, prompt in rendered_prompts.items():
            for rep in range(-1, repeats):
                for reuse in (False, True):
                    capture = request('/completion', {'prompt': prompt, 'n_predict': 192,
                        'temperature': benchmark_temp, 'seed': 42, 'ignore_eos': True, 'cache_prompt': reuse,
                        'stream': True}, label=f'{name}-{rep}-reuse-{reuse}', stream=True)
                    final = capture['response']
                    result['measurements'].append({'case': name, 'repeat': rep, 'warmup': rep == -1,
                        'reuse': reuse, 'timings': final.get('timings'), 'elapsed_s': capture['elapsed_s'],
                        'first_content_s': capture['first_content_s'],
                        'tokens_cached': final.get('tokens_cached'),
                        'tokens_predicted': final.get('tokens_predicted'),
                        'tokens_evaluated': final.get('tokens_evaluated')})
        if novel_check:
            result['novel_measurements'] = []
            for name in ('novel_lru', 'novel_toposort', 'novel_interval'):
                rendered = request('/apply-template', {'messages': [{'role': 'user', 'content': cases[name]}],
                    'chat_template_kwargs': {'enable_thinking': False}}, label=name + '-template')
                capture = request('/completion', {'prompt': rendered['response']['prompt'], 'n_predict': 384,
                    'temperature': benchmark_temp, 'seed': 42, 'ignore_eos': True, 'cache_prompt': False, 'stream': True}, label=name, stream=True)
                result['novel_measurements'].append({'case': name, 'timings': capture['response']['timings'],
                    'elapsed_s': capture['elapsed_s'], 'first_content_s': capture['first_content_s']})
        common = {'model': 'dory1.0_4b', 'temperature': 0, 'max_tokens': 1024,
                  'chat_template_kwargs': {'enable_thinking': False}}
        def chat(messages, label, **extra):
            return request('/v1/chat/completions', {**common, 'messages': messages, **extra}, label=label)['response']['choices'][0]
        arithmetic = chat([{'role': 'user', 'content': cases['arithmetic']}], 'arithmetic')
        result['quality']['arithmetic'] = arithmetic['message']['content'].strip() == '723'
        tool = {'type': 'function', 'function': {'name': 'get_weather', 'description': cases['tool_description'],
                'parameters': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']}}}
        messages = [{'role': 'user', 'content': cases['tool_request']}]
        response = chat(messages, 'tool', tools=[tool], tool_choice='auto')
        assistant = response['message']
        calls = assistant.get('tool_calls', [])
        tool_ok = len(calls) == 1 and calls[0]['function']['name'] == 'get_weather' and json.loads(calls[0]['function']['arguments']) == {'city': 'Santa Clara'}
        result['quality']['tool_arguments'] = tool_ok
        if tool_ok:
            reply = chat(messages + [assistant, {'role': 'tool', 'tool_call_id': calls[0]['id'],
                'content': cases['tool_result']},
                {'role': 'user', 'content': cases['tool_followup']}], 'tool-result', tools=[tool])
            result['quality']['tool_result'] = '22' in reply['message']['content'] and not reply['message'].get('tool_calls')
        retrieval = chat([{'role': 'user', 'content': prompts.fill(cases['retrieval'], block=block)}], 'retrieval')
        result['quality']['retrieval_beyond_swa'] = retrieval['message']['content'].strip() == 'amber-7319'
        code = chat([{'role': 'user', 'content': cases['python']}], 'python')
        try:
            tree = ast.parse(code['message']['content'])
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'add')
            result['quality']['python_structure'] = any(isinstance(n, ast.Return) and isinstance(n.value, ast.BinOp) and isinstance(n.value.op, ast.Add) for n in ast.walk(function))
        except (SyntaxError, StopIteration):
            result['quality']['python_structure'] = False
        if long_check:
            long_block = '\n'.join(prompts.fill(cases['row'], index=f'{i:03d}', retries=i % 7) for i in range(1600))
            long_reply = chat([{'role': 'user', 'content': prompts.fill(cases['retrieval'], block=long_block)}], 'long-retrieval')
            result['quality']['long_retrieval'] = long_reply['message']['content'].strip() == 'amber-7319'
        result['gpu_processes_after'] = gpu_processes()
        result['status'] = 'completed'
    except Exception as exc:
        result['status'] = 'error'
        result['error'] = repr(exc)
        if isinstance(exc, RateLimited):
            raise
    finally:
        stop_server(proc)
        log.close()
        (folder / 'arm.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--bench-temp', type=float, choices=(0.0, 1.0), default=0.0,
                        help='benchmark at greedy zero or publisher-recommended temperature one')
    parser.add_argument('--arms', nargs='*')
    parser.add_argument('--long-check', action='store_true', help='also retrieve a fact across a roughly 45K-token prompt')
    parser.add_argument('--novel-check', action='store_true', help='also measure three distinct, never-repeated coding prompts')
    opts = parser.parse_args()
    if opts.repeats < 1:
        parser.error('positive repeats required')
    arms = make_arms()
    if opts.arms is not None:
        unknown = set(opts.arms) - {arm['name'] for arm in arms}
        if not opts.arms or unknown:
            parser.error('select at least one known arm; unknown: ' + ', '.join(sorted(unknown)))
    opts.output.mkdir(parents=True, exist_ok=False)
    state = {'gpu': GPU, 'loops': 3, 'benchmark_temperature': opts.bench_temp, 'container': CONTAINER, 'arms': []}
    def save():
        (opts.output / 'state.json').write_text(json.dumps(state, indent=2) + '\n')
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    lock = (FLEET / 'locks/dory-3090.lock').open('a+b')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', PORT))
    if command('docker', 'inspect', '--format', '{{.State.Running}}', CONTAINER) != 'true':
        raise RuntimeError('expected original container running')
    with http_open('http://127.0.0.1:18020/metrics', timeout=10) as response:
        metrics = response.read().decode()
    active = [line for line in metrics.splitlines() if line.startswith(('vllm:num_requests_running{', 'vllm:num_requests_waiting{'))]
    if not active or any(float(line.split()[-1]) != 0 for line in active):
        raise RuntimeError('3090 server busy; no interruption performed')
    state['original_models'] = original_models()
    state['original_gpu_processes'] = gpu_processes()
    state['original_other_gpu_pids'] = [r[1] for r in state['original_gpu_processes'] if r[0] == OTHER_GPU]
    save()
    stopped = False
    try:
        # A failed control connection can still have stopped the container.
        stopped = True
        command('docker', 'stop', '--time', '120', CONTAINER)
        state['borrowed'] = True
        save()
        if any(r[0] == GPU for r in gpu_processes()):
            raise RuntimeError('unexpected remaining process on RTX3090')
        for arm in arms:
            if opts.arms and arm['name'] not in opts.arms:
                continue
            print('START', arm['name'], flush=True)
            state['current_arm'] = arm['name']
            save()
            result = run_arm(arm, opts.output / arm['name'], opts.repeats,
                             long_check=opts.long_check, novel_check=opts.novel_check,
                             benchmark_temp=opts.bench_temp)
            state['arms'].append(result)
            save()
            print('END', arm['name'], result['status'], result.get('error', ''), flush=True)
            if [r[1] for r in gpu_processes() if r[0] == OTHER_GPU] != state['original_other_gpu_pids']:
                raise RuntimeError('RTX3080 process changed externally; sweep stopped')
    finally:
        if stopped:
            state['restore_start'] = command('docker', 'start', CONTAINER)
            save()
            wait_ready('http://127.0.0.1:18020')
            state['restored_models'] = original_models()
            if sorted(m['id'] for m in state['restored_models']['data']) != sorted(m['id'] for m in state['original_models']['data']):
                raise RuntimeError('restored model identity differs from original')
            state['restored_gpu_processes'] = gpu_processes()
            state['restored'] = True
            save()
        lock.close()
    print('RESTORED', flush=True)


if __name__ == '__main__':
    main()
