"""Parallel battery lanes: one model per card, many slots of that one model, one cell per slot.

3090 lane: 4 slots at 49,152 tokens each. 3080 lane: 2 slots at the largest per-slot window that fits with
margin (LANE_WINDOWS; 49,152 -> 45,056 -> 40,960 -> 36,864). `--ctx-size` handed to llama.cpp is the TOTAL
(slots x per-slot); the window cria and Codex are told is always the PER-SLOT one. The canonical single-slot
RTX3080 profiles and `llama-fleet switch` are untouched: a lane plan is the profile's own plan with only
`--parallel`, `--ctx-size`, port and device overridden. The RTX3090 is taken through the owner-bound lease
(suite/fleet_gpu.py); the HyperQwen container and its idle-check timer are stopped and restored around the run.

One cria instance serves each ACTIVE ROW (lane x model x level): every concurrent cell of a row shares it,
relying on cria's session-scoped state. A row's config is a copy of ~/.cria/cria.toml with that row's role
sampling applied (the same before/active receipts as the serial path) plus transport-only edits.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import tomllib
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

try:
    from . import fleet_gpu
    from .gpu_lease import publish_lease
    from .restored_roles import receipt as role_receipt
except ImportError:
    import fleet_gpu
    from gpu_lease import publish_lease
    from restored_roles import receipt as role_receipt

FLEET = Path.home() / '.local/share/cria/fleet'
ROOT = Path.home() / '.cria/suite/_lanes'
LIVE_CONFIG = Path.home() / '.cria/cria.toml'
CRIA_SERVICE = 'cria.service'
HYPERQWEN = 'qwen38-27b-rtx3090-single-1'
IDLE_TIMER = 'gpu3090-idle-check.timer'
GPU_3090 = 'GPU-907a7f7a-b541-8208-2bce-e1361e3110d6'
GPU_3080 = fleet_gpu.PROFILE_GPU
ROW_PORT_BASE = 18400
MARGIN_MIB = 768            # free VRAM that must remain after a loaded lane server has served its load


@dataclass(frozen=True)
class Lane:
    name: str
    card: str               # '3090' | '3080'
    gpu: str
    slots: int
    port: int
    windows: tuple          # candidate per-slot windows, preferred first


LANES = {
    '3090x4': Lane('3090x4', '3090', GPU_3090, 4, 18194, (49152,)),
    '3080x2': Lane('3080x2', '3080', GPU_3080, 2, 18294, (49152, 45056, 40960, 36864)),
}

# 3080 lane per-slot window, MEASURED by `python suite/lane_measure.py` (largest candidate that loads with
# MARGIN_MIB to spare). None = the weights do not fit two slots on the 3080 even at 36,864: 3090 lane only.
LANE_WINDOWS = {
    'gemma4_12b': 49152, 'ornith1.5_9b': 45056, 'nemotron-elastic': 49152, 'ling3.0_tiny': 49152,
    'qwen3.8_9b_distill': 40960, 'bonsai2': None, 'phi4': None, 'k2_horizon_7b': None,
}

# Reported wall minutes = measured wall minutes x factor[model][lane], factor = per-stream tok/s at the lane's
# slot count / solo tok/s on the same card (fixed 600-token outputs over a ~6K-token code prompt).
# A model not yet measured uses the ornith1.5_9b factor of its lane.
REFERENCE_MODEL = 'ornith1.5_9b'
LANE_FACTORS = {   # measured 2026-11-02 with suite/lane_measure.py (llama.cpp current8345/Bonsai/K2 builds, q-KV per profile)
    'gemma4_12b': {'3090x4': 0.589, '3080x2': 0.557},
    'ornith1.5_9b': {'3090x4': 0.545, '3080x2': 0.668},
    'bonsai2': {'3090x4': 0.439},
    'nemotron-elastic': {'3090x4': 0.359, '3080x2': 0.581},
    'ling3.0_tiny': {'3090x4': 0.486, '3080x2': 0.75},
    'phi4': {'3090x4': 0.368},
    'k2_horizon_7b': {'3090x4': 0.494},
    'qwen3.8_9b_distill': {'3090x4': 0.548, '3080x2': 0.724},
}


def wall_factor(model, lane):
    return (LANE_FACTORS.get(model, {}).get(lane) or LANE_FACTORS[REFERENCE_MODEL][lane])


def wall_minutes(row):
    """Solo-equivalent rough wall minutes of a result row: measured minutes x its lane factor."""
    minutes = row['wall_seconds'] / 60
    lane = (row.get('lane') or {}).get('name')
    return minutes * wall_factor(row['model'], lane) if lane else minutes


def fleet_cli():
    tools = str(FLEET / 'tools')
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import fleet_cli as module
    return module


def profile_context(model):
    return fleet_cli().records()[model]['config']['ctx']


def lane_window(model, lane_name, window=None):
    """Per-slot window for `model` on `lane_name`, or None when the model does not run there."""
    lane = LANES[lane_name]
    if window is None:
        window = lane.windows[0] if lane.card == '3090' else LANE_WINDOWS.get(model)
        if window is None:
            return None
    if window not in lane.windows:
        raise ValueError(f'{window} is not a declared {lane_name} window')
    return min(window, profile_context(model))


def unit_server_options(unit):
    """Operator-declared `LLAMA_ARG_*` options of the model's effective unit (drop-ins), which a lane honors."""
    out = subprocess.run(['systemctl', 'show', unit, '-p', 'Environment', '--value'], capture_output=True,
                         text=True, check=True).stdout
    return dict(t.split('=', 1) for t in out.split() if t.startswith('LLAMA_ARG_') and t != 'LLAMA_ARG_OFFLINE=1')


def lane_plan(model, lane_name, window):
    """The model's own profile plan with only parallel/ctx/port/device overridden for the lane."""
    import copy
    lane = LANES[lane_name]
    cli = fleet_cli()
    record = copy.deepcopy(cli.records()[model])
    record['config']['parallel'] = lane.slots
    record['config']['ctx'] = lane.slots * window
    plan = cli.make_plan(record, port=lane.port)
    plan['env']['CUDA_VISIBLE_DEVICES'] = lane.gpu
    plan['env'].update(unit_server_options(record['unit']))
    plan['window'] = window
    return plan


# ----------------------------------------------------------------------------- process helpers

def start_ticks(pid):
    return fleet_gpu.process_start_ticks(pid)


def alive(pid, ticks):
    try:
        return start_ticks(pid) == ticks
    except (OSError, ValueError, IndexError):
        return False


def stop_pid(pid, ticks, *, grace=60):
    """Stop only a process we started, identified by pid AND start time."""
    for sig, wait in ((signal.SIGINT, grace), (signal.SIGTERM, 20), (signal.SIGKILL, 20)):
        if not alive(pid, ticks):
            return
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        end = time.monotonic() + wait
        while time.monotonic() < end and alive(pid, ticks):
            try:
                os.waitpid(pid, os.WNOHANG)    # reaps when we are the parent; ECHILD otherwise
            except ChildProcessError:
                pass
            time.sleep(0.5)
    if alive(pid, ticks):
        raise RuntimeError(f'process {pid} survived SIGKILL')


def get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def wait_json(url, ok, *, seconds=600, alive_check=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = get_json(url)
            if ok(value):
                return value
        except (OSError, ValueError):
            pass
        if alive_check is not None and not alive_check():
            raise RuntimeError('process exited before becoming ready: ' + url)
        time.sleep(2)
    raise TimeoutError('not ready: ' + url)


def compute_apps():
    out = subprocess.run(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_memory', '--format=csv,noheader,nounits'],
                         capture_output=True, text=True, check=True).stdout
    return [tuple(part.strip() for part in line.split(',')) for line in out.splitlines() if line.strip()]


def card_memory(gpu):
    out = subprocess.run(['nvidia-smi', '--query-gpu=uuid,memory.used,memory.total', '--format=csv,noheader,nounits'],
                         capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        uuid_, used, total = (p.strip() for p in line.split(','))
        if uuid_ == gpu:
            return int(used), int(total)
    raise ValueError('unknown GPU ' + gpu)


# ----------------------------------------------------------------------------- hardware ownership

STATE = ROOT / 'hardware.json'


def _active(*cmd, user=False):
    return subprocess.run(['systemctl', *(['--user'] if user else []), 'is-active', '--quiet', *cmd]).returncode == 0


def take_hardware(lane_names):
    """Stop what occupies the lanes' cards and record exactly what to restore. Never signals anything else."""
    ROOT.mkdir(parents=True, exist_ok=True)
    if STATE.exists():
        raise ValueError(f'{STATE} exists: restore the previous lane run first (python suite/lanes.py restore)')
    recipes = json.loads((FLEET / 'profiles/model-recipes.json').read_text())
    cards = {LANES[n].card for n in lane_names}
    state = {'cards': sorted(cards), 'managed_units': [], 'timer': False, 'container': False}
    if '3080' in cards:
        state['managed_units'] = sorted({r['unit'] for r in recipes.values() if _active(r['unit'])})
    if '3090' in cards:
        state['timer'] = _active(IDLE_TIMER, user=True)
        state['container'] = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', HYPERQWEN],
                                            capture_output=True, text=True).stdout.strip() == 'true'
    STATE.write_text(json.dumps(state, indent=2) + '\n')
    try:
        if state['timer']:
            subprocess.run(['systemctl', '--user', 'stop', IDLE_TIMER], check=True)
        if state['container']:
            subprocess.run(['docker', 'stop', HYPERQWEN], check=True, capture_output=True)
        if state['managed_units']:
            subprocess.run(['sudo', '-n', 'systemctl', 'stop', *state['managed_units']], check=True)
        busy = [app for app in compute_apps() if app[0] in {LANES[n].gpu for n in lane_names}]
        if busy:
            raise ValueError(f'lane card still has compute workloads: {busy}')
    except BaseException:
        restore_hardware()
        raise
    return state


def restore_hardware():
    if not STATE.exists():
        return None
    state = json.loads(STATE.read_text())
    if state['container']:
        subprocess.run(['docker', 'start', HYPERQWEN], check=True, capture_output=True)
    if state['timer']:
        subprocess.run(['systemctl', '--user', 'start', IDLE_TIMER], check=True)
    recipes = json.loads((FLEET / 'profiles/model-recipes.json').read_text())
    for model, record in recipes.items():
        if record['unit'] in state['managed_units']:
            # The canonical managed switch also re-syncs the frontend when its cached model/context is stale.
            subprocess.run([str(Path.home() / '.local/bin/llama-fleet'), 'switch', model], check=True)
    STATE.unlink()
    return state


class FleetLocks:
    """Hold the fleet's GPU locks of the lanes' cards for the whole run, as `llama-fleet serve` does, so no other
    launcher overlaps: the three fleet locks guard the RTX3080, `dory-3090.lock` the RTX3090."""
    BY_CARD = {'3080': ('control-gpu.lock', 'reconciliation-gpu.lock', 'model-io.lock'), '3090': ('dory-3090.lock',)}

    def __init__(self, lane_names):
        self.names = [n for card in sorted({LANES[l].card for l in lane_names}) for n in self.BY_CARD[card]]

    def __enter__(self):
        self.files = []
        for name in self.names:
            stream = (FLEET / 'locks' / name).open('r+b')
            self.files.append(stream)
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return self

    def __exit__(self, *_):
        for stream in reversed(self.files):
            stream.close()


# ----------------------------------------------------------------------------- lane server

def lane_dir(lane_name):
    return ROOT / lane_name


def server_state(lane_name):
    path = lane_dir(lane_name) / 'server.json'
    return json.loads(path.read_text()) if path.exists() else None


def lease_for(model):
    """Publish the owner-bound RTX3090 lease for the model being served; replaces the previous model's."""
    path = fleet_gpu.LEASE_PATH
    if path.exists():
        release_lease()
    lease = dict(schema=1, authorized=True, model=model, gpu=GPU_3090, profile_gpu=GPU_3080,
                 owner_pid=os.getpid(), owner_start_ticks=start_ticks(os.getpid()), operation=uuid.uuid4().hex)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    publish_lease(path, lease)
    return lease


def release_lease():
    fleet_gpu.LEASE_PATH.unlink(missing_ok=True)


SERVERS = {}      # lane -> Popen of the server this process started


def check_server(lane_name):
    """Raise when a lane server this process started has exited, naming how (negative = killed by that signal)."""
    code = SERVERS[lane_name].poll()
    if code is not None:
        raise RuntimeError(f'{lane_name} server exited with status {code}')


def start_server(model, lane_name, window):
    """Launch the model on the lane's card with the lane's slots; wait until ready; return verified state."""
    lane = LANES[lane_name]
    if server_state(lane_name) is not None:
        raise ValueError(f'{lane_name} already has a recorded server')
    plan = lane_plan(model, lane_name, window)
    directory = lane_dir(lane_name)
    directory.mkdir(parents=True, exist_ok=True)
    if lane.card == '3090':
        lease_for(model)
    env = dict(os.environ)
    env.pop('LD_PRELOAD', None)
    env.update(plan['env'])
    log = directory / f'server-{model}-{int(time.time())}.log'
    with log.open('wb') as stream:
        proc = subprocess.Popen(plan['argv'], cwd=plan['cwd'], env=env, stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    SERVERS[lane_name] = proc
    state = dict(lane=lane_name, model=model, window=window, slots=lane.slots, port=lane.port, gpu=lane.gpu,
                 pid=proc.pid, start_ticks=start_ticks(proc.pid), argv=plan['argv'],
                 argv_sha256=hashlib.sha256(json.dumps(plan['argv']).encode()).hexdigest(), log=str(log),
                 started=time.time())
    (directory / 'server.json').write_text(json.dumps(state, indent=2) + '\n')
    try:
        wait_json(f'http://127.0.0.1:{lane.port}/health', lambda v: v.get('status') == 'ok',
                  alive_check=lambda: proc.poll() is None)
        state['served'] = verify_server(state)
    except BaseException:
        stop_server(lane_name)
        raise
    return state


def verify_server(state):
    """The lane's SERVED configuration must match its declared lane configuration; return the evidence."""
    base = f"http://127.0.0.1:{state['port']}"
    if not alive(state['pid'], state['start_ticks']):
        raise ValueError(f"{state['lane']} server process is not alive")
    if get_json(base + '/health').get('status') != 'ok':
        raise ValueError(f"{state['lane']} server is unhealthy")
    props = get_json(base + '/props')
    ids = [m.get('id') for m in get_json(base + '/v1/models').get('data', [])]
    served = {'model': state['model'], 'slots': props.get('total_slots'),
              'window': (props.get('default_generation_settings') or {}).get('n_ctx')}
    if (state['model'] not in ids or served['slots'] != state['slots'] or served['window'] != state['window']):
        raise ValueError(f"{state['lane']} served config {served} differs from declared "
                         f"{state['model']} x{state['slots']} @ {state['window']}")
    if not any(gpu == state['gpu'] and int(pid) == state['pid'] for gpu, pid, _ in compute_apps()):
        raise ValueError(f"{state['lane']} server is not a compute process on its declared card")
    return {**served, 'port': state['port'], 'gpu': state['gpu'], 'pid': state['pid'],
            'argv_sha256': state['argv_sha256'], 'used_mib': card_memory(state['gpu'])[0]}


def stop_server(lane_name):
    state = server_state(lane_name)
    if state is None:
        return
    stop_pid(state['pid'], state['start_ticks'])
    SERVERS.pop(lane_name, None)
    (lane_dir(lane_name) / 'server.json').unlink()
    if LANES[lane_name].card == '3090':
        release_lease()


# ----------------------------------------------------------------------------- row cria instances

def cria_service_launch():
    """The python, release directory and environment of the deployed cria.service: row instances run that code."""
    out = subprocess.run(['systemctl', 'show', CRIA_SERVICE, '-p', 'ExecStart', '-p', 'WorkingDirectory',
                          '-p', 'Environment'], capture_output=True, text=True, check=True).stdout
    values = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
    argv = re.search(r'argv\[\]=(.*?) ;', values['ExecStart']).group(1).split()
    python = argv[0]
    env = dict(item.split('=', 1) for item in values.get('Environment', '').split() if '=' in item)
    return python, values['WorkingDirectory'], env


def set_toml(text, section, key, literal):
    """Set `key = literal` inside `[section]` (created when absent), preserving trailing comments."""
    header = re.search(rf'(?m)^[ \t]*\[{re.escape(section)}\][ \t]*(?:#[^\n]*)?(?:\n|\Z)', text)
    if header is None:
        return text.rstrip('\n') + f'\n\n[{section}]\n{key} = {literal}\n'
    following = re.search(r'(?m)^[ \t]*\[', text[header.end():])
    end = header.end() + following.start() if following else len(text)
    body, changed = re.subn(rf'(?m)^([ \t]*{re.escape(key)}[ \t]*=[ \t]*)[^#\n]*?([ \t]*(?:#[^\n]*)?)$',
                            lambda m: m.group(1) + literal + m.group(2), text[header.end():end], count=1)
    if not changed:
        lead = '' if text[:header.end()].endswith('\n') else '\n'
        return text[:header.end()] + lead + f'{key} = {literal}\n' + text[header.end():]
    return text[:header.end()] + body + text[end:]


def transport(text, *, port, endpoint, logs, calls, level):
    """Transport-only edits: where this instance listens, what it fronts, where it writes, and the row's level."""
    for section, key, value in (('engagement', 'level', level), ('server', 'port', port), ('logging', 'dir', logs), ('logging', 'capture_dir', calls),
                                ('defaults', 'base_url', endpoint), ('backends.local', 'base_url', endpoint)):
        text = set_toml(text, section, key, json.dumps(value))
    parsed = tomllib.loads(text)
    if (parsed['engagement']['level'] != level or parsed['server']['port'] != port or parsed['logging']['dir'] != logs or parsed['logging']['capture_dir'] != calls
            or parsed['defaults']['base_url'] != endpoint or parsed['backends']['local']['base_url'] != endpoint
            or parsed['logging'].get('capture_calls') is not True):
        raise ValueError('row cria transport config did not round-trip')
    return text


def row_name(lane_name, model, level):
    return f'{model}-L{level}'


def start_row(lane_name, model, level, roles, window, *, port):
    """Start a cria instance for one row (lane x model x level) on its own port, config copy and capture/log dirs."""
    lane = LANES[lane_name]
    directory = lane_dir(lane_name) / 'rows' / f'{row_name(lane_name, model, level)}-{int(time.time())}'
    original = LIVE_CONFIG.read_bytes()
    logs, calls = directory / 'logs', directory / 'calls'
    logs.mkdir(parents=True), calls.mkdir(parents=True)
    if level == 5:
        active, receipt = role_receipt(original, roles, directory / 'roles')
    else:
        active, receipt = original, None
        (directory / 'config-before.toml').write_bytes(original)
    endpoint = f'http://127.0.0.1:{lane.port}'
    config = directory / 'cria.toml'
    config.write_text(transport(active.decode(), port=port, endpoint=endpoint, logs=str(logs), calls=str(calls),
                                level=level))
    python, workdir, extra_env = cria_service_launch()
    log = (directory / 'cria.out').open('wb')
    proc = subprocess.Popen([python, '-m', 'cria', '--config', str(config)], cwd=workdir, stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **extra_env},
                            start_new_session=True)
    row = dict(lane=lane_name, model=model, level=level, port=port, window=window, endpoint=endpoint,
               dir=str(directory), config=str(config), calls_dir=str(calls), logs_dir=str(logs),
               role_receipt=receipt, pid=proc.pid, start_ticks=start_ticks(proc.pid), release=workdir, python=python,
               config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
               live_sha256=hashlib.sha256(original).hexdigest())
    (directory / 'row.json').write_text(json.dumps(row, indent=2) + '\n')
    try:
        wait_json(f'http://127.0.0.1:{port}/health', lambda v: True, seconds=300, alive_check=lambda: proc.poll() is None)
        verify_row(row)
    except BaseException:
        stop_row(row)
        raise
    return row


def config_derived(row):
    """True when the row's cria config is exactly its source (live config, or the row-sampled active copy)
    with only the transport edits applied."""
    config = Path(row['config'])
    parsed = tomllib.loads(config.read_text())
    source = Path(row['role_receipt']['active']) if row['role_receipt'] else Path(row['dir']) / 'config-before.toml'
    expected = transport(source.read_text(), port=parsed['server']['port'], endpoint=row['endpoint'],
                         logs=parsed['logging']['dir'], calls=parsed['logging']['capture_dir'], level=row['level'])
    return (config.read_text() == expected and parsed['server']['port'] == row['port']
            and parsed['logging']['capture_dir'] == row['calls_dir'] and parsed['logging']['dir'] == row['logs_dir'])


def verify_row(row):
    """The row's cria is alive, fronts the lane at the per-slot window, and serves the row's model."""
    if not alive(row['pid'], row['start_ticks']):
        raise ValueError('row cria process is not alive')
    cards = get_json(f"http://127.0.0.1:{row['port']}/v1/models").get('data', [])
    if not any(c.get('id') == row['model'] and c.get('context_window') == row['window'] for c in cards):
        raise ValueError(f"row cria card {cards} is not {row['model']} at per-slot window {row['window']}")
    if hashlib.sha256(Path(row['config']).read_bytes()).hexdigest() != row['config_sha256']:
        raise ValueError('row cria config changed')
    return row


def stop_row(row):
    stop_pid(row['pid'], row['start_ticks'], grace=30)


def load_row(path):
    return json.loads(Path(path).read_text())


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='lane hardware recovery')
    ap.add_argument('action', choices=['restore'])
    ap.parse_args(argv)
    for lane_name in LANES:
        state = server_state(lane_name)
        if state is not None:
            stop_server(lane_name)
    print(json.dumps(restore_hardware()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
