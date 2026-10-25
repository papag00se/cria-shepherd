"""Bounded offline OneJev GGUF replay. No production imports or deployment.

The official qev engine owns option-slot probabilities. No generated answer text
is used as a classifier and no private reasoning is requested or scored.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import socket
import subprocess
import threading

from cria import prompts
from suite.training_admit import LABEL_ORDER
from suite.training_prepare import sha


def checked_probabilities(answer, family):
    probabilities = answer['probabilities']
    if set(probabilities) != set(LABEL_ORDER[family]):
        raise ValueError('native decision interface returned unexpected classes')
    values = [probabilities[label] for label in LABEL_ORDER[family]]
    if any(type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1 for p in values):
        raise ValueError('invalid native decision probabilities')
    if not math.isclose(sum(values), 1, abs_tol=1e-6):
        raise ValueError('native decision probabilities do not sum to one')
    return dict(zip(LABEL_ORDER[family], values))


def checked_decision(answer, family):
    probabilities = checked_probabilities(answer, family)
    prediction = answer['choice']
    if prediction not in probabilities or probabilities[prediction] < max(probabilities.values()):
        raise ValueError('native choice conflicts with its declared probabilities')
    return prediction, probabilities


def frozen_policy(family, expected_hash):
    # Preserve the already frozen transport bytes, including its terminal newline.
    text = prompts.load('offline_onejev_' + family) + '\n'
    if sha(text.encode()) != expected_hash:
        raise ValueError('canonical question transport differs from the frozen policy')
    return text


def native_server_ready(line, port):
    return f'listening on http://127.0.0.1:{port}' in line


def append(path, value):
    with path.open('a') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b''):
            digest.update(chunk)
    return digest.hexdigest()


def native_request(case, policy_hashes):
    from qev.schema import SystemOneRequest
    labels = LABEL_ORDER[case['family']]
    return SystemOneRequest.model_validate({'state': case['complete_input'], 'questions': {'decision': {
        'type': 'choice', 'instructions': frozen_policy(case['family'], policy_hashes[case['family']]),
        'criteria': {label: label for label in labels}}}})


def run(root, binary, *, expected_count=24):
    contract = json.loads((root / 'contract.json').read_bytes())
    cases = json.loads((root / 'cases.json').read_bytes())
    artifact = json.loads((root / 'artifacts.json').read_bytes())
    if len(cases) != expected_count or sha((root / 'cases.json').read_bytes()) != contract['cases_sha256']:
        raise ValueError('frozen bounded cohort changed')
    for family, filename in contract['policy_files'].items():
        if sha(Path(filename).read_bytes()) != contract['policy_sha256'][family]:
            raise ValueError('frozen question transport changed')
    model_path = Path(artifact['path'])
    if file_sha(model_path) != artifact['sha256'] or model_path.stat().st_size != artifact['bytes']:
        raise ValueError('Q4 artifact changed')
    if (root / 'results.jsonl').exists():
        raise ValueError('existing run; do not duplicate inference')
    from qev.llamacpp import LlamaCppEngine
    from qev.prompt import render_question

    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    argv = [str(binary), '-m', str(model_path), '--host', '127.0.0.1', '--port', str(port),
            '-c', '8192', '-np', '1', '-ngl', '0', '-t', '6', '-tb', '6', '--no-context-shift']
    (root / 'execution.json').write_text(json.dumps({'argv': argv, 'binary_sha256': file_sha(binary),
        'driver_sha256': sha(Path(__file__).read_bytes()), 'device': 'CPU_ONLY_NO_GPU_CHANGE'}, indent=2) + '\n')
    proc = subprocess.Popen(argv, stdout=(root / 'server.stdout.log').open('w'),
                            stderr=subprocess.PIPE, text=True)
    ready = threading.Event()
    listening = []

    def drain():
        with (root / 'server.stderr.log').open('w') as stream:
            for line in proc.stderr:
                stream.write(line)
                stream.flush()
                if native_server_ready(line, port):
                    listening.append(True)
                    ready.set()
            ready.set()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        if not ready.wait(120) or not listening or proc.poll() is not None:
            raise RuntimeError('native server did not start; inspect complete stderr log')
        engine = LlamaCppEngine(f'http://127.0.0.1:{port}', artifact['tokenizer_path'],
                               name=artifact['repo'] + ':' + artifact['file'],
                               max_branch_tokens=8192, max_request_tokens=8192)
        (root / 'engine.json').write_text(json.dumps(asdict(engine.info), indent=2) + '\n')
        current = {'id': None}
        original_post = engine._post

        def observed_post(path, body):
            result = original_post(path, body)
            append(root / 'wire.jsonl', {'id': current['id'], 'path': path, 'request': body, 'response': result})
            return result

        engine._post = observed_post
        matrices = {f: [[0, 0], [0, 0]] for f in LABEL_ORDER}
        for case in cases:
            family = case['family']
            labels = LABEL_ORDER[family]
            if case['label_id'] != labels.index(case['label']):
                raise ValueError('frozen label ID differs from source class order')
            current['id'] = case['id']
            request = native_request(case, contract['policy_sha256'])
            rendered = render_question('decision', request.questions['decision'], style=engine.style)
            prompt = engine._render_prompt(request.state, rendered.suffix)
            tokens = engine._encode(prompt)
            if len(tokens) > 8192:
                raise ValueError('NO_FIT; do not shorten or split the input')
            append(root / 'calls.jsonl', {'id': case['id'], 'request': request.model_dump(),
                'rendered_prompt': prompt, 'native_tokens': tokens, 'reasoning': None})
            response, meta = engine.decide(request, debias=1, debug=True)
            response = response.model_dump()
            predicted, probabilities = checked_decision(response['answers']['decision'], family)
            matrices[family][case['label_id']][labels.index(predicted)] += 1
            result = {'id': case['id'], 'task': case['task'], 'family': family,
                'reviewed_target': case['label'], 'prediction': predicted,
                'probabilities': probabilities, 'native_response': response, 'native_metadata': meta}
            append(root / 'results.jsonl', result)
            print(json.dumps({'id': case['id'], 'target': case['label'], 'prediction': predicted,
                              'probabilities': probabilities}), flush=True)
        (root / 'completed.json').write_text(json.dumps({'count': len(cases),
            'reviewed_target_by_prediction': matrices, 'class_order': LABEL_ORDER,
            'not_fresh_evaluation_or_human_gold': True, 'quarantines_unchanged': True,
            'inference_only': True, 'deployed': False}, indent=2) + '\n')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        reader.join(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--count', type=int, default=24, help='exact frozen cohort size, never a row limit')
    args = parser.parse_args()
    run(args.root, args.binary, expected_count=args.count)


if __name__ == '__main__':
    main()
