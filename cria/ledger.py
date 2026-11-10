"""cria's own bookkeeping for operations it ran through the harness (docs/harness-primitives.md sections 6 and 8.12).

One append-only JSON-lines file per session under ``~/.cria/ops/`` (a private directory opened without following links, files
0600, ``flock`` around every append, ``fsync`` before an append returns). Nothing else holds operation state: a restarted
cria reads the file and is where it was. Five record types, folded in order:

* ``op``    the model's own call (id, name, arguments), the kind of operation and the guard facts it was issued under;
* ``step``  one primitive call cria issued: its step number, tool-call id, the sha-256 of its command, what it was and the
            arguments that re-derive it (so a retried request composes the identical command);
* ``blob``  a text steps refer to by its hash (a spill's whole text), recorded once and not in every step;
* ``frame`` the authenticated result of a step (header and decoded payload), recorded once, the first one wins;
* ``final`` the typed outcome and the exact text the model was told.

A request that dies between two appends is repaired by being asked again: every record is a pure function of what came
before, so the retried request appends what is missing and nothing twice. A torn last line (killed mid-write) is skipped.
"""
import fcntl
import hashlib
import json
import os
import stat
import threading
from dataclasses import dataclass, field

from . import privatepaths


class LedgerError(RuntimeError):
    """The store cannot be opened privately or written. An operation that cannot be recorded is not issued."""


@dataclass
class Step:
    s: int
    id: str
    cmd: str
    what: str
    args: dict
    frame: dict | None = None


@dataclass
class Op:
    op: str
    kind: str
    call: dict
    ctx: dict
    steps: dict = field(default_factory=dict)
    blobs: dict = field(default_factory=dict)
    final: dict | None = None


class Ledger:
    def __init__(self, directory=None):
        self._directory = directory
        self._lock = threading.RLock()
        self._folded: dict = {}

    def _path(self):
        return self._directory if self._directory is not None else privatepaths.CRIA_HOME / 'ops'

    def _open_dir(self) -> int:
        """The ledger directory, private and opened without following a link *at* it. The path to cria's own home may run through a
        symlink (``/home`` -> ``/var/home`` on an immutable distribution): it is resolved once, then the directory is opened by name."""
        target = os.path.abspath(self._path())
        try:
            privatepaths.mkdir_private(os.path.dirname(target))
            fd = os.open(os.path.realpath(os.path.dirname(target)), os.O_RDONLY | os.O_DIRECTORY)
        except OSError as exc:
            raise LedgerError('operation ledger directory unavailable') from exc
        try:
            name = os.path.basename(target)
            try:
                os.mkdir(name, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise LedgerError('operation ledger directory is not private')
            return fd
        except OSError as exc:
            os.close(fd)
            raise LedgerError('operation ledger directory unavailable') from exc
        except LedgerError:
            os.close(fd)
            raise

    @staticmethod
    def _name(session: str) -> str:
        return hashlib.sha256(session.encode()).hexdigest() + '.jsonl'

    def append(self, session: str, *records: dict) -> None:
        line = ''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in records).encode()
        with self._lock:
            directory = self._open_dir()
            try:
                fd = os.open(self._name(session), os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                        raise LedgerError('operation ledger is not a private file')
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    if info.st_size and os.pread(fd, 1, info.st_size - 1) != b'\n':
                        line = b'\n' + line          # a torn last line stays its own (skipped) line
                    view = memoryview(line)
                    while view:                      # a short write is written on, never dropped
                        view = view[os.write(fd, view):]
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.fsync(directory)
            except OSError as exc:
                raise LedgerError('operation ledger unavailable') from exc
            finally:
                os.close(directory)

    def ops(self, session: str) -> dict:
        """Every operation recorded for ``session``, folded from the file (read incrementally; the file only grows)."""
        with self._lock:
            try:
                directory = self._open_dir()
            except LedgerError:
                return {}
            try:
                try:
                    fd = os.open(self._name(session), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                except FileNotFoundError:
                    self._folded.pop((self._path(), session), None)
                    return {}
                with os.fdopen(fd, 'rb') as f:
                    info = os.fstat(f.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                        return {}
                    key = (self._path(), session)
                    pos, ident, ops = self._folded.get(key, (0, None, {}))
                    if ident != (info.st_dev, info.st_ino) or info.st_size < pos:
                        pos, ops = 0, {}
                    f.seek(pos)
                    data = f.read()
                    end = data.rfind(b'\n') + 1
                    for raw in data[:end].split(b'\n'):
                        self._fold(ops, raw)
                    self._folded[key] = (pos + end, (info.st_dev, info.st_ino), ops)
                    return ops
            except OSError:
                return {}
            finally:
                os.close(directory)

    @staticmethod
    def _fold(ops: dict, raw: bytes) -> None:
        try:
            r = json.loads(raw)
            kind, op = r['t'], r['op']
            if kind == 'op':
                ops.setdefault(op, Op(op, r['kind'], r['call'], r.get('ctx') or {}))
            elif kind == 'step' and op in ops:
                ops[op].steps.setdefault(r['s'], Step(r['s'], r['id'], r['cmd'], r['what'], r.get('args') or {}))
            elif kind == 'blob' and op in ops:
                ops[op].blobs.setdefault(r['h'], r['text'])
            elif kind == 'frame' and op in ops and r['s'] in ops[op].steps:
                ops[op].steps[r['s']].frame = ops[op].steps[r['s']].frame or {'hdr': r['hdr'], 'text': r['text']}
            elif kind == 'final' and op in ops:
                ops[op].final = ops[op].final or {'outcome': r['outcome'], 'text': r['text']}
        except (ValueError, KeyError, TypeError):
            return
