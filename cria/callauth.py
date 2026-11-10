"""Authentication of cria's own harness calls without text markers (docs/harness-primitives.md section 6).

One 32-byte key lives in ``~/.cria/harness-call.key`` (0600, created whole by link on first use) and never leaves this
process: not in a command, a body, a log or a capture. For an operation ``op`` (12 random hex digits cria chooses) and its
step number ``s``:

* ``nonce(op, s)`` anchors the result frame the stub prints; it sits in the command and is unguessable;
* ``group(op)`` names staging files and is the same after a restart;
* ``call_id(op, s, command)`` is the tool-call id the harness history carries; it is a MAC over the exact command bytes, so a
  command that differs by one byte (a rewriting harness, a hand-edited transcript) does not verify.

All three are pure functions of ``(key, op, s, command)``: a retried request, or one replayed after a restart, composes the
identical command and id. Nothing the model, a file, a command's output or a fetched page can contain is authority.
"""
import hashlib
import hmac
import os
import re
import secrets
import stat

from . import privatepaths

ID = re.compile(r'ctx_([0-9a-f]{12})_([0-9]{1,4})_([0-9a-f]{16})\Z')
PREFIX = 'ctx_'
_cache: dict = {}


class KeyUnavailable(RuntimeError):
    """The key cannot be created or is not private. Nothing is issued without it, and nothing verifies."""


def _key(create: bool = True) -> bytes:
    path = privatepaths.CRIA_HOME / 'harness-call.key'
    if (cached := _cache.get(path)) is not None:
        return cached
    try:
        if create:
            directory = privatepaths.mkdir_private(path.parent)
            # Written whole to a private temporary name and linked into place: the key file never exists half written (a crash, or a
            # concurrent reader, between create and write), and the first link wins.
            temp = directory / f'.{path.name}.{secrets.token_hex(8)}'
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(secrets.token_bytes(32))
                    f.flush()
                    os.fsync(f.fileno())
                try:
                    os.link(temp, directory / path.name)
                except FileExistsError:
                    pass
            finally:
                try:
                    os.unlink(temp)
                except FileNotFoundError:
                    pass
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as f:
            info = os.fstat(f.fileno())
            value = f.read(33)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or len(value) != 32:
            raise KeyUnavailable('harness call key is not a private 32-byte file')
    except OSError as exc:
        raise KeyUnavailable('harness call key unavailable') from exc
    _cache[path] = value
    return value


def secret_values() -> list[str]:
    """The key as a redaction value, when it already exists: captures must never hold it, though nothing writes it there.
    Asking never creates it (only issuing or verifying an operation does)."""
    try:
        return [_key(create=False).hex()]
    except KeyUnavailable:
        return []


def _mac(*parts: str, create: bool = True) -> bytes:
    return hmac.new(_key(create), '|'.join(parts).encode(), hashlib.sha256).digest()


def op_of(cid) -> str | None:
    """The operation a verified-shaped id belongs to (its shape only: nothing is verified here)."""
    match = ID.match(cid) if isinstance(cid, str) else None
    return match.group(1) if match else None


def display_id(op: str) -> str:
    """The id the model's history shows for a call cria made on its own that the model is allowed to see (the gate's checks): derived from the
    operation alone, neutral (no ``ctx_``), the same after a restart."""
    return 'call_' + hashlib.sha256(('display|' + op).encode()).hexdigest()[:16]


def new_op() -> str:
    return secrets.token_hex(6)


def nonce(op: str, step: int) -> str:
    return _mac('nonce', op, str(step))[:16].hex()


def group(op: str) -> str:
    return _mac('group', op)[:16].hex()


def call_id(op: str, step: int, command: str, create: bool = True) -> str:
    digest = hashlib.sha256(command.encode()).hexdigest()
    return f'{PREFIX}{op}_{step}_' + _mac('call', op, str(step), digest, create=create)[:8].hex()


def verify(cid, command: str) -> tuple[str, int] | None:
    """``(op, step)`` when ``cid`` is the id cria derived for exactly this command, else None. A forged, reused-elsewhere or
    one-byte-changed command never verifies; an unavailable key verifies nothing."""
    match = ID.match(cid) if isinstance(cid, str) else None
    if match is None:
        return None
    op, step = match.group(1), int(match.group(2))
    try:
        expected = call_id(op, step, command, create=False)      # verifying never creates the key
    except KeyUnavailable:
        return None
    return (op, step) if hmac.compare_digest(expected, cid) else None


def neutralize(completion: dict) -> dict:
    """Give every model-authored tool call whose id begins ``ctx_`` a neutral new id, so the verified namespace is only ever
    cria's. A call whose id is the MAC of its exact command (one cria issued itself, as the loop does for the inventory) is cria's and is left
    as it is: only the key makes one, and the model never holds it."""
    from .toolwire import _command_of
    for choice in completion.get('choices') or []:
        for call in (choice.get('message') or {}).get('tool_calls') or []:
            if (isinstance(call, dict) and isinstance(call.get('id'), str) and call['id'].startswith(PREFIX)
                    and verify(call['id'], _command_of((call.get('function') or {}).get('arguments'))) is None):
                call['id'] = 'call_' + secrets.token_hex(12)
    return completion
