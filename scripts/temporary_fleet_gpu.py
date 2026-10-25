#!/usr/bin/env python3
"""Run one command with an explicit GPU lease; use systemd ExecStopPost for crash cleanup."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from suite import fleet_gpu
from suite.restored_roles import render


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)


def publish_lease(path, lease):
    # Exclusive atomic publication: readers can never see a partially written active lease.
    pending = path.with_name('gpu-lease.' + lease['operation'] + '.pending')
    try:
        with pending.open('x') as stream:
            os.chmod(pending, 0o600); json.dump(lease, stream); stream.flush(); os.fsync(stream.fileno())
        os.link(pending, path)
    finally:
        if pending.exists():
            pending.unlink()


def cleanup(args, *, run=subprocess.run, lease_path=None, config_path=None, roles_path=None):
    lease_path = lease_path or fleet_gpu.LEASE_PATH
    config_path = config_path or Path.home() / '.cria/cria.toml'
    roles_path = roles_path or Path.home() / '.config/llama-fleet/roles.json'
    receipt = Path(args.receipt_dir)
    if not lease_path.exists():
        return
    lease = json.loads(lease_path.read_text())  # owner may have died: cleanup must not require liveness
    if (lease.get('operation') != args.operation or lease.get('model') != args.model
            or lease.get('gpu') != args.gpu or lease.get('profile_gpu') != fleet_gpu.PROFILE_GPU):
        raise ValueError('refusing to clean another GPU lease')
    # The model is managed by a separate system service, not the wrapper's process group.
    run(['sudo', '-n', 'systemctl', 'stop', args.unit], check=True, timeout=90)
    result = {'operation': args.operation, 'model_stopped': args.unit,
              'lease_removed': True, 'default_gpu': fleet_gpu.PROFILE_GPU}
    original = (receipt / 'config-before.toml').read_bytes()
    current = config_path.read_bytes()
    reload_needed = current == original
    roles = json.loads(roles_path.read_text())[args.model]
    if current == original:
        result['config'] = 'already original'
    elif current == render(original.decode(), roles).encode():
        config_path.write_bytes(original)
        reload_needed = True
        result['config'] = 'restored exact original after interrupted scoped sampling'
    else:
        result['config'] = 'newer operator edits preserved; not overwritten'
    # Matching bytes alone do not prove the daemon reloaded them: a previous attempt may have
    # written the original and then failed its restart. Retain ownership until that reload succeeds.
    if reload_needed:
        run(['sudo', '-n', 'systemctl', 'restart', 'cria.service'], check=True, timeout=60)
    save(receipt / 'restored.json', result)
    lease_path.unlink()
    if fleet_gpu.execution_gpu(args.model, path=lease_path) != fleet_gpu.PROFILE_GPU:
        raise ValueError('GPU restoration did not resolve to the canonical device')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', required=True)
    p.add_argument('--unit', required=True)
    p.add_argument('--gpu', required=True)
    p.add_argument('--operation', required=True)
    p.add_argument('--receipt-dir', required=True)
    p.add_argument('--cleanup', action='store_true')
    p.add_argument('command', nargs=argparse.REMAINDER)
    args = p.parse_args()
    if args.cleanup:
        cleanup(args)
        return 0
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        p.error('one command is required')
    receipt = Path(args.receipt_dir); receipt.mkdir(parents=True, exist_ok=True)
    recipes = json.loads((Path.home() / '.local/share/cria/fleet/profiles/model-recipes.json').read_text())
    if args.model not in recipes or recipes[args.model]['unit'] != args.unit:
        raise ValueError('temporary unit must be the registered model service')
    # Refuse to borrow an already running model or GPU. Never stop someone else's workload.
    managed = sorted({record['unit'] for record in recipes.values()})
    pids = subprocess.check_output(['systemctl', 'show', *managed, '-p', 'MainPID', '--value'], text=True)
    if any(value.strip() != '0' for value in pids.splitlines() if value.strip()):
        raise ValueError('a managed model is already running; will not interrupt it')
    devices = subprocess.check_output(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid', '--format=csv,noheader'], text=True)
    if any(line.split(',')[0].strip() == args.gpu for line in devices.splitlines()):
        raise ValueError('temporary GPU already has a compute workload')
    config = Path.home() / '.cria/cria.toml'
    original = config.read_bytes()
    before = receipt / 'config-before.toml'
    if before.exists() and before.read_bytes() != original:
        raise ValueError('existing recovery configuration differs')
    before.write_bytes(original); before.chmod(0o600)
    lease = dict(schema=1, authorized=True, model=args.model, gpu=args.gpu,
                 profile_gpu=fleet_gpu.PROFILE_GPU, owner_pid=os.getpid(),
                 owner_start_ticks=fleet_gpu.process_start_ticks(os.getpid()), operation=args.operation)
    path = fleet_gpu.LEASE_PATH; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    publish_lease(path, lease)
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if fleet_gpu.execution_gpu(args.model) != args.gpu:
            raise ValueError('lease did not select the requested device')
        save(receipt / 'lease.json', lease)
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL)
        save(receipt / 'command.json', {'argv': command, 'pid': child.pid})
        return child.wait()
    finally:
        cleanup(args)


if __name__ == '__main__':
    raise SystemExit(main())
