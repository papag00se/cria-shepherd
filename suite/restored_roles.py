"""Cell-scoped canonical role sampling; preserve all non-sampling configuration bytes."""
from contextlib import contextmanager
import hashlib
import os
import re
import subprocess
import tomllib
from pathlib import Path
try:
    from .sampling_adapter import KNOBS, validate_knobs
except ImportError:
    from sampling_adapter import KNOBS, validate_knobs


def render(text, roles):
    if set(roles) != {'coder', 'reasoner', 'classifier', 'compactor'}:
        raise ValueError('canonical four-role sampling required')
    for role, knobs in roles.items():
        validate_knobs(knobs)
        pattern = rf'(?m)^\[roles\.{role}\][^\n]*(?:\n|$)'
        match = re.search(pattern, text)
        if not match:
            raise ValueError('missing role config: ' + role)
        following = re.search(r'(?m)^\[', text[match.end():])
        end = match.end() + following.start() if following else len(text)
        block = text[match.end():end]
        kept = [line for line in block.splitlines(keepends=True)
                if line.split('=', 1)[0].strip() not in KNOBS or line.lstrip().startswith('#')]
        replacement = ''.join(kept)
        if replacement and not replacement.endswith('\n'):
            replacement += '\n'
        replacement += ''.join(f'{key} = {value!r}\n' for key, value in knobs.items())
        text = text[:match.end()] + replacement + text[end:]
    parsed = tomllib.loads(text)
    for role, knobs in roles.items():
        actual = {k: v for k, v in parsed['roles'][role].items() if k in KNOBS}
        if actual != knobs:
            raise ValueError('canonical role sampling did not round-trip')
    return text


def restart():
    subprocess.run(['sudo', '-n', 'systemctl', 'restart', 'cria.service'], check=True)


@contextmanager
def scoped(path, roles, evidence, *, restart_service=restart):
    path, evidence = Path(path), Path(evidence)
    original = path.read_bytes()
    original_stat = path.stat()
    active = render(original.decode(), roles).encode()
    evidence.mkdir(parents=True, exist_ok=True)
    before, during = evidence / 'config-before.toml', evidence / 'config-active.toml'
    before.write_bytes(original)
    during.write_bytes(active)
    receipt = dict(before=str(before), active=str(during),
                   before_sha256=hashlib.sha256(original).hexdigest(),
                   active_sha256=hashlib.sha256(active).hexdigest(), roles=roles)
    try:
        path.write_bytes(active)
        restart_service()
        yield receipt
    finally:
        if path.read_bytes() != active:
            raise ValueError('live config changed during cell; refusing to overwrite newer edits; original preserved')
        path.write_bytes(original)
        os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        restart_service()
