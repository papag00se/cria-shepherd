"""Canonical private artifact root; independent of configuration and policy catalogs."""
import os
from pathlib import Path

# Config, credentials, logs and plan mirrors live outside the driven workspace.
CRIA_HOME = Path('~/.cria').expanduser()


def mkdir_private(path) -> Path:
    """Create ``path`` and every missing ancestor as owner-only (0700) directories. A capture/log tree holds
    whole conversations, tool output and file contents; the default umask left them world-readable."""
    path = Path(path).expanduser()
    for d in reversed([path, *path.parents]):
        if d.exists():
            continue
        try:
            os.mkdir(d, 0o700)
        except FileExistsError:
            pass
    return path


def write_private(path, data: bytes | str) -> None:
    """Write ``data`` to ``path`` as an owner-only (0600) file, tightening one that already exists."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as fh:
            fh.write(raw)
    finally:
        os.close(fd)
