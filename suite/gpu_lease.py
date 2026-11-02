"""Exclusive atomic publication of an owner-bound GPU lease (see docs/temporary-fleet-gpu.md)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def publish_lease(path: Path, lease: dict) -> None:
    # Exclusive atomic publication: readers can never see a partially written active lease.
    pending = path.with_name('gpu-lease.' + lease['operation'] + '.pending')
    try:
        with pending.open('x') as stream:
            os.chmod(pending, 0o600); json.dump(lease, stream); stream.flush(); os.fsync(stream.fileno())
        os.link(pending, path)
    finally:
        if pending.exists():
            pending.unlink()
