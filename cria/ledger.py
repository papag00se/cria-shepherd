"""cria's own bookkeeping for operations it ran through the harness (docs/harness-primitives.md sections 6 and 8.12).

One append-only JSON-lines file per session under ``~/.cria/ops/`` (a private directory opened without following links, files
0600, ``flock`` around every append, ``fsync`` before an append returns). Nothing else holds operation state: a restarted
cria reads the file and is where it was. Seven record types, folded in order:

* ``op``    the model's own call (id, name, arguments; the several of a group of file mutations), the kind of operation and the
            guard facts it was issued under;
* ``step``  one primitive call cria issued: its step number, tool-call id, the sha-256 of its command, what it was and the
            arguments that re-derive it (so a retried request composes the identical command);
* ``blob``  a text steps refer to by its hash (a spill's whole text), recorded once and not in every step;
* ``frame`` the authenticated result of a step (header and decoded payload, and the size of the result as the harness
            returned it, and the workspace survey that rode home with it, when one did), recorded once, the first one wins;
* ``final`` the typed outcome and the exact text the model was told (and, for a read, the facts the wire binds to it: the
            verified source identity, what the text is, the prose that precedes it, a note that follows it);
* ``settle`` a read the model's wire accepted: it is an ordinary result from then on, no longer protected;
* ``withhold`` a read whose delivery the wire measured and refused (``overflow`` or ``unknown``): the model is told so instead.

A request that dies between two appends is repaired by being asked again: every record is a pure function of what came
before, so the retried request appends what is missing and nothing twice. A torn last line (killed mid-write) is skipped.
"""
import fcntl
import hashlib
import json
import os
import re
import stat
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from . import privatepaths
from .toolargs import parse_args, tool_path


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
    extra_calls: list = field(default_factory=list)
    settled: bool = False
    withheld: str | None = None

    @property
    def calls(self) -> list:
        """The model's calls this operation answers, in the model's order (a group of file mutations answers several; an operation
        cria asked on its own, such as the workspace survey, answers none)."""
        return self.extra_calls or ([self.call] if self.call else [])


FOLDED_SESSIONS = 16            # sessions whose folded ledger is kept in memory; the least recently used is dropped (and re-read from its file when asked for)
_LEDGER_NAME = re.compile(r'[0-9a-f]{64}\.jsonl\Z')


class Ledger:
    def __init__(self, directory=None):
        self._directory = directory
        self._lock = threading.RLock()
        self._folded: OrderedDict = OrderedDict()       # (directory, session) -> (bytes folded, file identity, ops): a cache of the file, never the record
        self._active: dict = {}                         # ledger file name -> when this process last saw a request or an append for it
        self._flight: dict = {}                         # ledger file name -> requests being handled for it right now

    def _remember(self, key, value) -> None:
        """Keep ``value`` as the folded state of ``key``, most recently used; past ``FOLDED_SESSIONS`` the least recently used is dropped. Dropping only
        drops the cache: the next ``ops`` for that session folds its whole file again and returns the same operations."""
        self._folded[key] = value
        self._folded.move_to_end(key)
        while len(self._folded) > FOLDED_SESSIONS:
            self._folded.popitem(last=False)

    # ---------------------------------------------------------------- activity (what the retention sweep must not mistake for idleness)
    def hold(self, session: str) -> str:
        """A request for ``session`` is being handled (it may be a model call of minutes, or a check of minutes, with nothing appended meanwhile):
        its ledger is not idle until :meth:`release`. Returns the token to release."""
        name = self._name(session)
        with self._lock:
            self._flight[name] = self._flight.get(name, 0) + 1
            self._active[name] = time.time()
        return name

    def release(self, name: str) -> None:
        with self._lock:
            self._flight[name] = max(0, self._flight.get(name, 0) - 1)
            self._active[name] = time.time()

    def sweep(self, idle_after: float, *, now: float | None = None) -> list:
        """Delete the ledger files of sessions that have been inactive for ``idle_after`` seconds: WHOLE files only, never a trimmed one. A ledger is
        not swept when a request for its session is in flight or was seen (or appended to) here within ``idle_after``, when its file was written within it
        (another process's append), when another process holds it, or when it holds an operation with no ``final`` (an operation still open). A session
        whose ledger is gone starts again from nothing: its earlier calls are shown to the model as they are (docs/harness-primitives.md, decision D2).
        Returns one dict per file removed (``ledger`` a prefix of its name, ``size``, ``idle_seconds``, ``operations``)."""
        now = time.time() if now is None else now
        removed = []
        with self._lock:
            try:
                directory = self._open_dir()
            except LedgerError:
                return removed
            try:
                for name in sorted(os.listdir(directory)):
                    if not _LEDGER_NAME.match(name) or self._flight.get(name) or now - self._active.get(name, 0) < idle_after:
                        continue
                    try:
                        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                    except OSError:
                        continue
                    with os.fdopen(fd, 'rb') as f:
                        info = os.fstat(f.fileno())
                        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or now - info.st_mtime < idle_after:
                            continue
                        try:
                            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except OSError:
                            continue
                        ops: dict = {}
                        for raw in f.read().split(b'\n'):
                            self._fold(ops, raw)
                        if any(op.final is None for op in ops.values()) or os.fstat(f.fileno()).st_size != info.st_size:
                            continue
                        try:
                            os.unlink(name, dir_fd=directory)
                        except OSError:
                            continue
                    for key in [k for k in self._folded if self._name(k[1]) == name]:
                        del self._folded[key]
                    self._active.pop(name, None)
                    self._flight.pop(name, None)
                    removed.append({'ledger': name[:12], 'size': info.st_size, 'idle_seconds': int(now - info.st_mtime), 'operations': len(ops)})
                if removed:
                    os.fsync(directory)
            except OSError:
                pass
            finally:
                os.close(directory)
        return removed

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
            self._active[self._name(session)] = time.time()
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
            self._active[self._name(session)] = time.time()
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
                    self._remember(key, (pos + end, (info.st_dev, info.st_ino), ops))
                    return ops
            except OSError:
                return {}
            finally:
                os.close(directory)

    def unresolved_writes(self, session: str) -> list:
        """``[(operation, path)]`` for each file mutation the harness never confirmed and the file could not settle (a write that may or
        may not have landed): the last mutation of a path that ended that way, unless a later one landed there. A reply that was lost
        is asked of the file itself and the write sent again before anything reads this, so only an unsettled one remains."""
        open_: dict = {}
        for op in self.ops(session).values():
            if op.kind != 'mutate' or op.final is None:
                continue
            for call, result in zip(op.calls, op.final.get('results') or ()):
                path = tool_path(parse_args(call['arguments'])) or ''
                key = os.path.normpath(os.path.join(op.ctx.get('wsroot') or '', path))
                if result.get('o') == 'uncertain':
                    open_[key] = (op.op, path)
                elif result.get('o') == 'landed':
                    open_.pop(key, None)
        return list(open_.values())

    @staticmethod
    def _fold(ops: dict, raw: bytes) -> None:
        try:
            r = json.loads(raw)
            kind, op = r['t'], r['op']
            if kind == 'op':
                ops.setdefault(op, Op(op, r['kind'], r['call'], r.get('ctx') or {}, extra_calls=r.get('calls') or []))
            elif kind == 'step' and op in ops:
                ops[op].steps.setdefault(r['s'], Step(r['s'], r['id'], r['cmd'], r['what'], r.get('args') or {}))
            elif kind == 'blob' and op in ops:
                ops[op].blobs.setdefault(r['h'], r['text'])
            elif kind == 'frame' and op in ops and r['s'] in ops[op].steps:
                ops[op].steps[r['s']].frame = ops[op].steps[r['s']].frame or {'hdr': r['hdr'], 'text': r['text'], 'wire': r.get('wire', 0), **({'sv': r['sv']} if r.get('sv') else {})}
            elif kind == 'final' and op in ops:
                ops[op].final = ops[op].final or {k: v for k, v in r.items() if k not in ('t', 'op')}
            elif kind == 'settle' and op in ops:
                ops[op].settled = True
            elif kind == 'withhold' and op in ops and r['kind'] in ('overflow', 'unknown'):
                ops[op].withheld = ops[op].withheld or r['kind']
        except (ValueError, KeyError, TypeError):
            return
