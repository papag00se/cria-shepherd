"""Env-file loading + one normalized secret accessor.

cria reads secrets (the Brave search key, cloud provider keys) from ``os.environ`` — but a
systemd service does NOT source a shell `.env`, so the daemon started with those variables
ABSENT and every key read silently returned "". This makes cria self-sufficient: it loads a
configured env file at startup (stdlib, no python-dotenv), NORMALIZING each value once so a
CRLF `.env` can't leave an illegal trailing ``\\r`` in an HTTP header — the exact breakage
that was previously band-aided with a `.strip()` at each consumer.
"""

from __future__ import annotations

import os


def load_env_file(path: str, allow: set[str]) -> int:
    """Load ONLY the allowlisted ``KEY=VALUE`` lines from ``path`` into ``os.environ``; return the
    count set.

    SECURITY — leak guard: cria loads ONLY the variables it declares it needs (``allow`` = the
    Brave key + any configured cloud-provider key). EVERY other line in the file is ignored and
    never read into cria's process. So an env file that ALSO holds unrelated secrets — a shared
    home ``.env`` — cannot leak them into cria, nor into the planner's read-only gather
    subprocesses, which inherit cria's environment. An empty ``allow`` loads nothing.

    - A variable already in the environment WINS (a real systemd ``Environment=`` / operator
      export is never clobbered) — the file only fills what's missing.
    - Values are NORMALIZED: surrounding quotes stripped, trailing CR/whitespace trimmed.
    - ``export KEY=…`` and ``# comment`` / blank lines are handled. A missing file is not an
      error (the path is optional config) — returns 0.
    """
    if not allow:
        return 0
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return 0
    n = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, val = line.split("=", 1)
        key = key.strip()
        if key not in allow:  # not one of cria's OWN declared vars → never touch it (leak guard)
            continue
        if key in os.environ:  # don't clobber a value the environment already provides
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ[key] = val
        n += 1
    return n


def env_secret(name: str | None) -> str | None:
    """Read a secret/key env var, normalized: trailing CR/whitespace trimmed, empty → None.

    The ONE place a key is read, so CRLF hygiene can't diverge between consumers (the search
    key, cloud provider keys). ``None``/empty name → None."""
    if not name:
        return None
    return (os.environ.get(name) or "").strip() or None
