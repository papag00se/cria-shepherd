"""Locations and source-only snapshots for local test runs."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path.home() / '.cria' / 'test-runs'
OUTPUTS = ROOT / 'outputs'
CALLS = ROOT / 'calls'
SCRATCH = Path('/var/tmp/cria-test-runs')

# These are generated project/build artifacts, not source deliverables.
_GENERATED = {'.git', 'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache',
              '.ruff_cache', '.gradle', '.venv', 'venv', 'target', 'dist', 'build',
              '.cache', 'coverage', '.coverage', '.tox', '.bundle', 'vendor',
              '.m2', '.cargo', '.npm', '.yarn', '.pnpm-store', '.next', '.nuxt'}


def copy_workspace(source, destination):
    """Copy tracked and non-ignored task files, excluding generated dependencies and builds."""
    source = Path(source)
    allowed = None
    if (source / '.git').exists():
        listing = subprocess.run(
            ['git', '-C', str(source), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        ).stdout
        allowed = set()
        for name in listing.split(b'\0'):
            if not name:
                continue
            path = Path(name.decode('utf-8', errors='surrogateescape'))
            allowed.add(path)
            allowed.update(path.parents)

    def ignore(directory, names):
        parent = Path(directory).relative_to(source)
        return {name for name in names if name in _GENERATED or (allowed is not None and parent / name not in allowed)}

    return shutil.copytree(source, destination, symlinks=True, ignore=ignore)
