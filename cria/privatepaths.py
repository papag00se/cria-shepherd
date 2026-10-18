"""Canonical private artifact root; independent of configuration and policy catalogs."""
from pathlib import Path

# Config, credentials, logs and plan mirrors live outside the driven workspace.
CRIA_HOME = Path('~/.cria').expanduser()
