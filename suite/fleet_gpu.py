"""Explicit, owner-bound temporary GPU leases; canonical fleet profiles never change.

Installed byte-identically beside fleet_cli.py for the service-side launch and PID guard.
A stale/malformed lease refuses launch, never silently selects another GPU.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

PROFILE_GPU = 'GPU-393d4998-707c-0ef0-a514-761015477256'
LEASE_PATH = Path('/run/user') / str(os.getuid()) / 'cria-fleet/gpu-lease.json'
_KEYS = {'schema', 'authorized', 'model', 'gpu', 'profile_gpu', 'owner_pid', 'owner_start_ticks', 'operation'}


def process_start_ticks(pid: int) -> int:
    return int((Path('/proc') / str(pid) / 'stat').read_text().rpartition(') ')[2].split()[19])


def read_lease(path: Path | None = None) -> dict | None:
    path = path if path is not None else LEASE_PATH
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd) as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('GPU lease must be an operator-owned regular file with mode 0600')
        lease = json.load(handle)
    if not isinstance(lease, dict) or set(lease) != _KEYS:
        raise ValueError('invalid GPU lease fields')
    if (type(lease['schema']) is not int or lease['schema'] != 1 or lease['authorized'] is not True
            or lease['profile_gpu'] != PROFILE_GPU
            or not isinstance(lease['gpu'], str) or not re.fullmatch(r'GPU-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', lease['gpu'])
            or lease['gpu'] == PROFILE_GPU
            or not isinstance(lease['model'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', lease['model'])
            or not isinstance(lease['operation'], str) or not re.fullmatch(r'[0-9a-f]{32}', lease['operation'])
            or type(lease['owner_pid']) is not int or lease['owner_pid'] <= 0
            or type(lease['owner_start_ticks']) is not int or lease['owner_start_ticks'] <= 0):
        raise ValueError('invalid authorized GPU lease')
    try:
        current = process_start_ticks(lease['owner_pid'])
    except (OSError, ValueError, IndexError) as exc:
        raise ValueError('GPU lease owner is not alive; explicit cleanup required') from exc
    if current != lease['owner_start_ticks']:
        raise ValueError('GPU lease owner PID was reused; explicit cleanup required')
    return lease


def execution_gpu(model: str, *, path: Path | None = None) -> str:
    lease = read_lease(path)
    if lease is None:
        return PROFILE_GPU
    if lease['model'] != model:
        raise ValueError('temporary GPU lease exclusively reserves a different model')
    return lease['gpu']
