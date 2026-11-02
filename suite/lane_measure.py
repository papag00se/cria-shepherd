#!/usr/bin/env python3
"""Measure each model's lane window (3080 fit) and wall-minute factor with a short fixed-output load.

For each model x lane it serves the lane (candidate per-slot windows, largest first), then sends a ~6K-token
code prompt with a fixed 600-token output: once alone (solo tok/s on that card), then from every slot at once
(per-stream tok/s). factor = per-stream / solo. A window FITS when, after that load, at least MARGIN_MIB of the
card remains free. Results print as JSON; copy them into LANE_WINDOWS / LANE_FACTORS in suite/lanes.py.

    python suite/lane_measure.py --models ornith1.5_9b,gemma4_12b --lanes 3090x4,3080x2
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
try:
    from . import l0_campaign, lanes
except ImportError:
    import l0_campaign
    import lanes

PROMPT_TOKENS = 6000
OUTPUT_TOKENS = 600
ROUNDS = 2                  # speculative decoding varies run to run; average solo and concurrent rounds


def post(port, path, body, timeout=1800):
    request = urllib.request.Request(f'http://127.0.0.1:{port}{path}', json.dumps(body).encode(),
                                     {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def code_prompt(port):
    text = ''.join(p.read_text(errors='replace') for p in sorted((REPO / 'cria').glob('*.py'))[:40])
    tokens = post(port, '/tokenize', {'content': text})['tokens']
    if len(tokens) < PROMPT_TOKENS:
        raise ValueError('not enough code to build the load prompt')
    return tokens[:PROMPT_TOKENS]


def stream(port, prompt, seed):
    result = post(port, '/completion', {'prompt': prompt, 'n_predict': OUTPUT_TOKENS, 'ignore_eos': True,
                                        'cache_prompt': False, 'seed': seed, 'temperature': 0.6})
    if result['timings']['predicted_n'] != OUTPUT_TOKENS:
        raise ValueError(f"expected {OUTPUT_TOKENS} output tokens, got {result['timings']['predicted_n']}")
    return result['timings']['predicted_per_second']


def measure(state, gpu):
    port, slots = state['port'], state['slots']
    prompt = code_prompt(port)
    peak, stop = [0], threading.Event()

    def sample():
        while not stop.is_set():
            peak[0] = max(peak[0], lanes.card_memory(gpu)[0])
            time.sleep(1)
    watcher = threading.Thread(target=sample, daemon=True)
    watcher.start()
    try:
        stream(port, prompt, 1)                           # warm-up, discarded
        solo = statistics.mean(stream(port, prompt, 2 + i) for i in range(ROUNDS))
        together = []
        with ThreadPoolExecutor(slots) as pool:
            for r in range(ROUNDS):
                together += list(pool.map(lambda i: stream(port, prompt, 10 + 10 * r + i), range(slots)))
    finally:
        stop.set()
        watcher.join()
    used, total = peak[0], lanes.card_memory(gpu)[1]
    return {'solo_tok_s': round(solo, 1), 'per_stream_tok_s': round(statistics.mean(together), 1),
            'total_tok_s': round(sum(together) / ROUNDS, 1), 'factor': round(statistics.mean(together) / solo, 3),
            'peak_used_mib': used, 'free_mib': total - used, 'fits': total - used >= lanes.MARGIN_MIB}


def run_lane(model, lane_name):
    lane = lanes.LANES[lane_name]
    tried = []
    for candidate in dict.fromkeys(lanes.lane_window(model, lane_name, w) for w in lane.windows):
        outcome = {'model': model, 'lane': lane_name, 'window': candidate}
        try:
            state = lanes.start_server(model, lane_name, candidate)
        except (RuntimeError, TimeoutError, ValueError, OSError) as exc:
            outcome['load_error'] = str(exc)
            tried.append(outcome)
            print(json.dumps(outcome), flush=True)
            continue
        try:
            outcome.update(measure(state, lane.gpu))
        finally:
            lanes.stop_server(lane_name)
        tried.append(outcome)
        print(json.dumps(outcome), flush=True)
        if outcome['fits']:
            return outcome
    return {'model': model, 'lane': lane_name, 'window': None, 'tried': tried}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--models', default=','.join(l0_campaign.MODELS))
    ap.add_argument('--lanes', default=','.join(lanes.LANES))
    args = ap.parse_args()
    lane_names = args.lanes.split(',')
    models = args.models.split(',')
    results = []
    lanes.take_hardware(lane_names)
    try:
        with lanes.FleetLocks(lane_names):
            for model in models:
                for lane_name in lane_names:
                    results.append(run_lane(model, lane_name))
    finally:
        for lane_name in lane_names:
            lanes.stop_server(lane_name)
        lanes.restore_hardware()
    print(json.dumps(results, indent=1))


if __name__ == '__main__':
    main()
