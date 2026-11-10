"""Explicit, operator-run cleanup of cria's private retained state.

    python -m cria.retention list  [--home DIR] [--kind image|transient|all] [--tmp DIR] [--json]
    python -m cria.retention prune [--home DIR] [--kind ...] [--tmp DIR] [--older-than 14d]
                                   [--session ID] [--apply]

cria has no trusted harness session-close signal (measured against real Codex: it sends
none on exit, /clear, compaction or cancel), so deletion authority is always the
OPERATOR's: either this command, or the explicit `[retention] auto_prune_after` setting,
which runs the same selection and removal code (`AutoPruner` below) on the operator's
behalf. Unset (the default) means cria never deletes anything itself. Idleness, LRU,
eviction, compaction and "history stopped mentioning it" remain forbidden inferences;
the configured age is the operator's judgment, not cria's. `prune` is a dry run unless `--apply` is given and it
needs `--older-than` and/or `--session` so a bare invocation can never select
everything. Same-UID forgery is not authentication: any process of this user can
fake or remove these files; the checks below stop mistakes and hostile names, not a
hostile same-user process.

Safety rules: every filesystem step is relative to a directory fd opened without
following symlinks, names must match the exact shapes cria writes, entries that are
symlinks/non-regular are refused, an entry whose lock is held by a live cria process
is skipped (fail closed), a corrupt entry is reported and removed only when selected
by `--session` with `--apply`, and a failed removal is retryable.

Deletion reuses the owners' machinery instead of a second path: image sessions go
through `ImageSession.confirm_close` / `cleanup_descriptor` / `ImageStore.release`
or `retry_closed` (closed-seal marker outside the payload directory, removed last).

`--kind transient` (also never part of `all`, same temp directory) lists and prunes the credentialed scratch directories the
lowered gate program (and, before the write/edit migration, the write/edit programs) leave under the harness temp directory when they
were killed or never finished: gate scratch (`.ctx-private-<token>`, earlier `.gate-private-`) and what the earlier releases' write/edit
programs left, which nothing creates now - completion marks (`.ctx-done-<credential>`, earlier `.cria-done-`) and edit-sequence markers
(`.ctx-edits-`, earlier `.cria-edits-`). Never a prefix sweep: a directory is listed as removable only if it is
owned by this user, mode 0700, holds a regular `.owner` certificate whose JSON names exactly this directory's prefix, credential and
inode, and nothing but regular files (the gate's `aux/` may also hold regular files and plain subdirectories). Anything else with the
prefix is listed refused and never touched. The age is the operator's judgment.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import threading
import time
import uuid
import fcntl
from dataclasses import dataclass, field
from pathlib import Path

from . import imagepersist, privatepaths
from .imagestore import ImageStore
from .imageprotocol import ImageUnavailable

_SHA = r'[0-9a-f]{64}'
_IMG_DIR = re.compile(r'image-session-[A-Za-z0-9_-]+')
_IMG_MARKER = re.compile(r'(image-session-[A-Za-z0-9_-]+)\.owner\.json')
_UNITS = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}


@dataclass
class Entry:
    kind: str                 # 'image' | 'transient'
    id: str
    label: str = ''           # session identity when it can be read, else ''
    names: list = field(default_factory=list)   # files/dirs relative to the kind's root
    size: int = 0
    mtime: float = 0.0
    state: str = 'unknown'    # active | closed | unknown | corrupt
    detail: str = ''
    refused: bool = False     # never deletable (symlink / non-regular / foreign owner)
    raw: dict = field(default_factory=dict)


def parse_age(text):
    m = re.fullmatch(r'(\d+)([smhdw])', text.strip())
    if not m:
        raise ValueError('age must look like 90s, 30m, 12h, 14d or 2w')
    return int(m.group(1)) * _UNITS[m.group(2)]


def _fmt_age(seconds):
    for unit, n in (('d', 86400), ('h', 3600), ('m', 60)):
        if seconds >= n:
            return f'{int(seconds // n)}{unit}'
    return f'{int(max(seconds, 0))}s'


def _size_text(n):
    value = float(n)
    for unit in ('B', 'K', 'M', 'G'):
        if value < 1024 or unit == 'G':
            return f'{int(value)}B' if unit == 'B' else f'{value:.1f}{unit}'
        value /= 1024


class RootRefused(OSError):
    """A retention root that is not a private directory of this user, or has a link in its path."""


def _open_root(path):
    """Directory fd for a retention root: no symlink component, owned, private."""
    parts = os.path.abspath(path).split(os.sep)[1:]
    fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise RootRefused('retention root is not private')
        return fd
    except Exception:
        os.close(fd)
        raise


def _du(dirfd):
    total = 0
    newest = os.fstat(dirfd).st_mtime
    for name in os.listdir(dirfd):
        try:    # a live session replaces its state file atomically: a name listed a moment ago may be gone
            st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
            total += st.st_size
            newest = max(newest, st.st_mtime)
            if stat.S_ISDIR(st.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dirfd)
                try:
                    size, mtime = _du(child)
                finally:
                    os.close(child)
                total += size
                newest = max(newest, mtime)
        except FileNotFoundError:
            continue
    return total, newest


def _read_regular(dirfd, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dirfd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise ValueError('not a private regular file owned by this user')
        with os.fdopen(fd, encoding='utf-8') as f:
            fd = None
            return json.load(f), st
    finally:
        if fd is not None:
            os.close(fd)



# -------------------------------------------------------------------- images

def _scan_images(dirfd, root, *, spare_newer_than=None, now=None):
    """``spare_newer_than`` (seconds): a live-free, unsealed session touched more recently is NOT opened and re-hashed - it cannot
    be selected by that age anyway (`select`), so validating it would only cost time linear in its retained bytes every pass."""
    entries, ignored = {}, []
    store = ImageStore(root, close_authority=object())
    for name in sorted(os.listdir(dirfd)):
        mm = _IMG_MARKER.fullmatch(name)
        if _IMG_DIR.fullmatch(name):
            pass
        elif mm:
            if mm.group(1) not in entries and not os.path.lexists(os.path.join(root, mm.group(1))):
                st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
                e = Entry('image', mm.group(1), names=[name], size=st.st_size, mtime=st.st_mtime)
                e.refused = not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                try:
                    marker = _read_regular(dirfd, name)[0] if not e.refused else None
                    if isinstance(marker, dict) and isinstance(marker.get('closed'), str) and marker['closed']:
                        e.state, e.detail = 'closed', 'payload already removed; marker left by an interrupted cleanup'
                        e.raw = {'marker': marker}
                    else:
                        e.state, e.detail = 'corrupt', 'unsealed owner marker without a session directory'
                        if isinstance(marker, dict):
                            e.raw = {'marker': marker}      # an explicit --session can seal it and clear it
                except (ValueError, OSError) as exc:
                    e.state, e.detail = 'corrupt', f'owner marker unreadable: {exc}'
                entries[e.id] = e
            continue
        else:
            ignored.append(name)
            continue
        try:
            st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        except FileNotFoundError:    # its owner finished closing it since the listing: nothing left to select
            continue
        e = Entry('image', name, names=[name], mtime=st.st_mtime)
        entries[name] = e
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
            e.refused, e.state = True, 'corrupt'
            e.detail = 'not an owned private directory (symlink, file or wrong mode); never touched'
            continue
        try:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dirfd)
        except FileNotFoundError:
            del entries[name]
            continue
        try:
            e.size, e.mtime = _du(child)
        finally:
            os.close(child)
        marker_name = name + '.owner.json'
        try:
            marker = _read_regular(dirfd, marker_name)[0]
            e.names.append(marker_name)
            st_m = os.stat(marker_name, dir_fd=dirfd, follow_symlinks=False)
            e.size += st_m.st_size
            e.mtime = max(e.mtime, st_m.st_mtime)
        except FileNotFoundError:
            marker = None
        except (ValueError, OSError) as exc:
            e.state, e.detail = 'corrupt', f'owner marker unreadable: {exc}'
            e.names.append(marker_name)
            continue
        if marker is None:
            e.state, e.detail = 'corrupt', 'no owner generation marker'
            continue
        if not isinstance(marker, dict):
            e.state, e.detail = 'corrupt', 'owner marker is not a JSON object'
            continue
        handle = {'owner': 'session-images', 'directory': name, 'generation': marker.get('generation')}
        e.raw = {'marker': marker, 'handle': handle}
        if imagepersist.held_by_live_process(os.path.join(root, name)):
            e.state, e.detail = 'active', 'held by a live cria process'
            continue
        if isinstance(marker.get('closed'), str) and marker['closed']:
            e.state, e.detail = 'closed', 'sealed for cleanup (an earlier cleanup did not finish)'
            try:
                e.label = imagepersist.read_state(os.path.join(root, name)).get('key') or ''
            except ImageUnavailable:
                pass
            continue
        if spare_newer_than is not None and now - e.mtime < spare_newer_than:
            e.state, e.detail = 'unknown', 'newer than the requested age; not validated'
            continue
        try:   # the store's own validator; the throwaway store retains nothing
            session = store.restore_session(handle, recovered_leases=())
            e.label = session._key
            e.detail = f'{len(session._records)} image(s); not closed, no live holder'
            session._hold.close()
            store._sessions.clear()
            store._all.clear()
        except (ImageUnavailable, OSError, ValueError, KeyError, TypeError) as exc:
            e.state, e.detail = 'corrupt', f'record validation failed: {exc}'
    return list(entries.values()), ignored


def _delete_image(root, entry, authority, *, force):
    """Seal first (marker outside the payload), then payload, marker last; retryable."""
    store = ImageStore(root, close_authority=authority)
    name = entry.id
    path = Path(root) / name
    marker = (entry.raw or {}).get('marker')
    if not path.is_dir() or path.is_symlink():          # orphan marker: sealed, or (explicitly selected) sealed now
        if not isinstance(marker, dict) or 'generation' not in marker:
            raise ImageUnavailable('no generation marker: cannot use the store cleanup path')
        closed = marker.get('closed')
        if not (isinstance(closed, str) and closed):
            if not force:
                raise ImageUnavailable('unsealed owner marker without a session directory')
            closed = uuid.uuid4().hex
            imagepersist.seal_marker(path, marker['generation'], closed)
        descriptor = {'owner': 'session-images', 'directory': name,
                      'generation': marker['generation'], 'closed': closed}
        store.retry_closed(descriptor)
        return
    if marker is None:
        raise ImageUnavailable('no generation marker: cannot use the store cleanup path')
    handle = entry.raw['handle']
    if isinstance(marker.get('closed'), str) and marker['closed']:
        store.retry_closed({**handle, 'closed': marker['closed']})
        return
    try:
        session = store.restore_session(handle, recovered_leases=())
    except ImageUnavailable:
        if not force:
            raise
        # Explicitly selected corrupt entry: seal the marker, then use the same retry path.
        seal = uuid.uuid4().hex
        imagepersist.seal_marker(path, handle['generation'], seal)
        store.retry_closed({**handle, 'closed': seal})
        return
    session.confirm_close(authority)
    session.cleanup_descriptor()
    store.release(session)



# ------------------------------------------------------------------ transient scratch

_TRANSIENT_SHAPES = (   # (prefix, what it is, may hold an `aux` directory); earlier release first
    ('.cria-done-', 'completion marks', False), ('.ctx-done-', 'completion marks', False),
    ('.cria-edits-', 'edit-sequence markers', False), ('.ctx-edits-', 'edit-sequence markers', False),
    ('.gate-private-', 'gate scratch', True), ('.ctx-private-', 'gate scratch', True))
_TRANSIENT_CREDENTIAL = r'[A-Za-z0-9_-]{1,128}'
_TRANSIENT_DIR = re.compile('(' + '|'.join(re.escape(p) for p, _, _ in _TRANSIENT_SHAPES) + ')(' + _TRANSIENT_CREDENTIAL + ')')
_TRANSIENT_WHAT = {p: (what, aux) for p, what, aux in _TRANSIENT_SHAPES}
_TRANSIENT_DEPTH = 8


def _walk_aux(dirfd, depth=0):
    """(bytes, newest mtime, count) of a gate `aux` tree; ValueError on anything but plain owned files and directories."""
    if depth > _TRANSIENT_DEPTH:
        raise ValueError('aux is nested too deeply')
    total, newest, count = 0, 0.0, 0
    for name in os.listdir(dirfd):
        st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        if st.st_uid != os.getuid() or not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
            raise ValueError(f'aux/{name} is not a plain file or directory of this user')
        total, newest, count = total + st.st_size, max(newest, st.st_mtime), count + 1
        if stat.S_ISDIR(st.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dirfd)
            try:
                size, mtime, n = _walk_aux(child, depth + 1)
            finally:
                os.close(child)
            total, newest, count = total + size, max(newest, mtime), count + n
    return total, newest, count


def _certified(child, name, prefix, credential, st):
    """The directory's own `.owner` certificate (what `ownedfiles._owned_open` writes) names exactly this prefix, credential and inode."""
    cert, marker = _read_regular(child, '.owner')
    identity = [st.st_dev, st.st_ino]
    if not isinstance(cert, dict) or cert.get('namespace') != prefix or cert.get('credential') != credential \
            or cert.get('root') != identity or cert.get('owner') != [marker.st_dev, marker.st_ino]:
        raise ValueError('the .owner certificate does not name this directory')
    return marker


def _scan_transient(tmp):
    """Credentialed scratch directories of the lowered programs under the harness temp directory (an fd). Exact shape only."""
    entries, ignored = [], []
    for name in sorted(os.listdir(tmp)):
        if not name.startswith(tuple(p for p, _, _ in _TRANSIENT_SHAPES)):
            continue
        match = _TRANSIENT_DIR.fullmatch(name)
        if match is None:
            ignored.append(name)
            continue
        prefix, credential = match.groups()
        what, has_aux = _TRANSIENT_WHAT[prefix]
        entry = Entry('transient', name, label=what, state='unknown',
                      detail='credentialed scratch of a lowered program (finished work leaves none; a running one is not distinguishable)')
        entries.append(entry)
        try:
            st = os.stat(name, dir_fd=tmp, follow_symlinks=False)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
                raise ValueError('not a 0700 directory owned by this user')
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=tmp)
            try:
                marker = _certified(child, name, prefix, credential, st)
                entry.mtime, entry.size = max(st.st_mtime, marker.st_mtime), marker.st_size
                entry.names.append(name + '/.owner')
                for f in sorted(set(os.listdir(child)) - {'.owner'}):
                    fst = os.stat(f, dir_fd=child, follow_symlinks=False)
                    if fst.st_uid != os.getuid():
                        raise ValueError(f'{f} belongs to another user')
                    if stat.S_ISREG(fst.st_mode):
                        entry.size += fst.st_size
                    elif has_aux and f == 'aux' and stat.S_ISDIR(fst.st_mode):
                        sub = os.open('aux', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=child)
                        try:
                            size, mtime, _n = _walk_aux(sub)
                        finally:
                            os.close(sub)
                        entry.size, entry.mtime = entry.size + size, max(entry.mtime, mtime)
                    else:
                        raise ValueError(f'unexpected entry {f}')
                    entry.mtime = max(entry.mtime, fst.st_mtime)
                    entry.names.append(name + '/' + f)
            finally:
                os.close(child)
            entry.raw = {'identity': (st.st_dev, st.st_ino), 'aux': has_aux}
        except (OSError, ValueError) as exc:
            entry.refused, entry.detail, entry.names = True, str(exc), []
    return entries, ignored


def _remove_tree(dirfd, depth=0):
    for name in os.listdir(dirfd):
        st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        if stat.S_ISDIR(st.st_mode):
            if depth >= _TRANSIENT_DEPTH:
                raise OSError(f'{name}: nested too deeply; left in place')
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dirfd)
            try:
                _remove_tree(child, depth + 1)
            finally:
                os.close(child)
            os.rmdir(name, dir_fd=dirfd)
        elif stat.S_ISREG(st.st_mode):
            os.unlink(name, dir_fd=dirfd)
        else:
            raise OSError(f'{name}: not a plain file or directory; left in place')


def _delete_transient(tmp, entry):
    """Re-prove the shape at the moment of removal (same inode as the listing, certificate intact), then files, `aux`, directory."""
    match = _TRANSIENT_DIR.fullmatch(entry.id)
    if match is None or not entry.raw:
        raise OSError('not a certified scratch directory; left in place')
    prefix, credential = match.groups()
    child = os.open(entry.id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=tmp)
    try:
        st = os.fstat(child)
        if (st.st_dev, st.st_ino) != tuple(entry.raw['identity']) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
            raise OSError('the directory is no longer the one that was listed; left in place')
        try:
            _certified(child, entry.id, prefix, credential, st)
        except (OSError, ValueError) as exc:
            raise OSError(f'certificate check failed ({exc}); left in place') from exc
        for f in os.listdir(child):
            fst = os.stat(f, dir_fd=child, follow_symlinks=False)
            if stat.S_ISDIR(fst.st_mode) and f == 'aux' and entry.raw['aux']:
                sub = os.open('aux', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=child)
                try:
                    _remove_tree(sub)
                finally:
                    os.close(sub)
                os.rmdir('aux', dir_fd=child)
            elif stat.S_ISREG(fst.st_mode) and fst.st_uid == os.getuid():
                os.unlink(f, dir_fd=child)
            else:
                raise OSError(f'{f}: unexpected entry; left in place')
    finally:
        os.close(child)
    os.rmdir(entry.id, dir_fd=tmp)


# ------------------------------------------------------------------ selection

class AmbiguousSession(Exception):
    """A session prefix that names more than one retained entry and no entry exactly."""
    def __init__(self, wanted, entries):
        super().__init__(f'session prefix {wanted!r} is ambiguous: it matches {len(entries)} entries; give the full id')
        self.wanted, self.entries = wanted, entries


def _exact_session(entry, wanted):
    return _matches_session(entry, wanted, prefix=False)


def _matches_session(entry, wanted, prefix=True):
    if entry.kind == 'transient':
        return entry.id == wanted
    return entry.id == wanted or entry.label == wanted


def select(entries, *, older_than, session, now):
    chosen = []
    if session is not None and not any(_exact_session(e, session) for e in entries):
        prefixed = [e for e in entries if _matches_session(e, session)]
        if len({e.id for e in prefixed}) > 1:      # a prefix is a convenience for ONE entry, never a pattern
            raise AmbiguousSession(session, prefixed)
    for e in entries:
        if session is not None and not _matches_session(e, session):
            continue
        # A sealed entry is a cleanup already begun (sealing refreshes mtimes): retry it
        # regardless of age instead of stranding a half-removed generation.
        if older_than is not None and e.state != 'closed' and now - e.mtime < older_than:
            continue
        chosen.append(e)
    return chosen


# ------------------------------------------------------------------------ CLI

def _roots(home):
    home = Path(home)
    image = privatepaths.IMAGE_HOME if home == privatepaths.CRIA_HOME else home / 'images'
    return {'image': image}


def _tmp_root(tmp):
    return os.path.realpath(tmp or os.environ.get('TMPDIR') or '/tmp')


def collect(home, kinds, *, tmp=None, older_than=None, now=None):
    """Return (entries, ignored, held_lock_fd_or_None, notes). Caller closes the fds. ``older_than``/``now``: the age the caller will
    select by, so an image session younger than it is not validated (see `_scan_images`)."""
    entries, ignored, notes, fds = [], [], [], {}
    roots = _roots(home)
    for kind in kinds:
        if kind == 'transient':
            try:
                dirfd = os.open(_tmp_root(tmp), os.O_RDONLY | os.O_DIRECTORY)
                try:
                    found, ign = _scan_transient(dirfd)
                    entries.extend(found)
                    ignored.extend(f'{kind}/{n}' for n in ign)
                    fds[kind] = os.dup(dirfd)
                finally:
                    os.close(dirfd)
            except OSError as exc:
                notes.append(f'{kind}: scan failed: {exc}')
            continue
        root = roots[kind]
        if not os.path.lexists(root):
            continue
        try:
            dirfd = _open_root(root)
        except OSError as exc:
            notes.append(f'{kind}: root {root} refused: {exc}')
            continue
        try:
            found, ign = _scan_images(dirfd, str(root), spare_newer_than=older_than, now=now)
            entries.extend(found)
            ignored.extend(f'{kind}/{n}' for n in ign)
            fds[kind] = os.dup(dirfd)
        except Exception as exc:  # noqa: BLE001 — one kind's unreadable entry must neither hide the other kind nor skip the caller's cleanup of `fds`
            notes.append(f'{kind}: scan failed: {type(exc).__name__}: {exc}')
        finally:
            os.close(dirfd)
    return entries, ignored, fds, notes


def _close(fds):
    for fd in fds.values():
        try:
            os.close(fd)
        except OSError:
            pass


def _table(entries, now):
    rows = [('KIND', 'ID', 'SESSION', 'SIZE', 'AGE', 'STATE', 'DETAIL')]
    for e in entries:
        label = e.label if len(e.label) <= 24 else e.label[:21] + '...'
        rows.append((e.kind, e.id[:24], label, _size_text(e.size), _fmt_age(now - e.mtime), e.state, e.detail))
    widths = [max(len(r[i]) for r in rows) for i in range(6)]
    return '\n'.join('  '.join(c.ljust(w) for c, w in zip(r[:6], widths)) + '  ' + r[6] for r in rows)


def _parser():
    ap = argparse.ArgumentParser(prog='python -m cria.retention', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('list', 'prune'):
        p = sub.add_parser(name)
        p.add_argument('--home', default=str(privatepaths.CRIA_HOME), help='cria home (default ~/.cria)')
        p.add_argument('--kind', choices=('image', 'transient', 'all'), default='all')
        p.add_argument('--tmp', help='harness temp directory scanned for --kind transient (default $TMPDIR, else /tmp)')
        if name == 'list':
            p.add_argument('--json', action='store_true')
        else:
            p.add_argument('--older-than', help='last-touch age, e.g. 14d, 12h, 2w')
            p.add_argument('--session', help='session id, id prefix (>=8) or raw session identity')
            p.add_argument('--apply', action='store_true', help='actually delete (default is a dry run)')
    return ap


def main(argv=None, out=None, now=None):
    out = out or sys.stdout
    args = _parser().parse_args(argv)
    now = time.time() if now is None else now
    kinds = ('image',) if args.kind == 'all' else (args.kind,)
    if args.cmd == 'list':
        entries, ignored, fds, notes = collect(args.home, kinds, tmp=args.tmp)
        _close(fds)
        if args.json:
            json.dump({'entries': [{**{k: v for k, v in vars(e).items() if k not in ('raw', 'names')},
                                    'age_seconds': int(now - e.mtime)} for e in entries],
                       'notes': notes, 'ignored': ignored}, out, indent=1)
            out.write('\n')
        else:
            out.write(_table(entries, now) + '\n' if entries else 'no retained entries\n')
            for n in notes:
                out.write(f'note: {n}\n')
            if ignored:
                out.write(f'ignored {len(ignored)} unrecognized name(s); never touched\n')
        return 0
    if args.older_than is None and args.session is None:
        out.write('refusing: prune needs --older-than and/or --session\n')
        return 2
    try:
        older = None if args.older_than is None else parse_age(args.older_than)
    except ValueError as exc:
        out.write(f'refusing: {exc}\n')
        return 2
    entries, ignored, fds, notes = collect(args.home, kinds, tmp=args.tmp, older_than=older, now=now)
    code = 0
    try:
        for n in notes:
            out.write(f'note: {n}\n')
        try:
            plan, skipped = plan_prune(entries, older_than=older, session=args.session, now=now)
        except AmbiguousSession as exc:
            out.write(f'refusing: {exc}\n')
            for e in exc.entries:
                out.write(f'  {e.kind} {e.id}  {e.label}\n')
            return 2
        out.write(('APPLY: will remove' if args.apply else 'DRY RUN: would remove') + f' {len(plan)} entr{"y" if len(plan)==1 else "ies"}\n')
        for e in plan:
            out.write(f'  remove {e.kind} {e.id} [{e.state}] {_size_text(e.size)} age {_fmt_age(now - e.mtime)}: '
                      + ', '.join(e.names) + '\n')
        for e, why in skipped:
            out.write(f'  {why}: {e.kind} {e.id}\n')
        if not args.apply:
            out.write('nothing was removed; re-run with --apply to delete exactly the entries above\n')
            return 0

        def report(e, exc):
            nonlocal code
            if exc is None:
                out.write(f'removed {e.kind} {e.id}\n')
            else:
                code = 1
                out.write(f'FAILED {e.kind} {e.id}: {exc}; safe to re-run\n')
        apply_plan(args.home, plan, fds, force=args.session is not None, report=report)
        return code
    finally:
        _close(fds)


# ------------------------------------------------------- shared plan / apply

def plan_prune(entries, *, older_than, session, now):
    """The ONE selection rule for every prune (CLI and automatic): (plan, skipped[(entry, why)]).
    Refused, live-held and (unless named by `session`) corrupt entries are never planned."""
    plan, skipped = [], []
    for e in select(entries, older_than=older_than, session=session, now=now):
        if e.refused:
            skipped.append((e, 'refused: ' + (e.detail or 'unsafe entry')))
        elif e.state == 'active':
            skipped.append((e, 'skipped: held by a live cria process'))
        elif e.state == 'corrupt' and session is None:
            skipped.append((e, 'skipped: corrupt (' + e.detail + '); select it with --session ID --apply'))
        else:
            plan.append(e)
    return plan, skipped


def apply_plan(home, plan, fds, *, force, report):
    """Remove each planned entry through its owner's machinery; `report(entry, None|exception)` per entry."""
    authority = object()
    for e in plan:
        try:
            if e.kind == 'transient':
                _delete_transient(fds['transient'], e)
            else:
                _delete_image(str(_roots(home)['image']), e, authority, force=force)
        except (OSError, ImageUnavailable, KeyError, TypeError) as exc:
            report(e, exc)
        else:
            report(e, None)


# ------------------------------------------------- operator-authorized automatic prune

AUTO_MIN_AGE = _UNITS['h']      # `auto_prune_after` below an hour is refused: a typo must not be able to eat a live conversation
AUTO_MIN_EVERY = _UNITS['m']


class AutoPruner:
    """Prune retained image state older than `older` seconds, on the OPERATOR's standing
    instruction (`[retention] auto_prune_after`). It is the CLI's `prune --apply --older-than` with the same
    `collect` / `plan_prune` / `apply_plan`: symlink and escape refusal, live image holders
    skipped, corrupt entries never removed (only `--session` removes those), sealed cleanups retried.
    It never infers closure from anything a request or harness did. `run_once` never raises; `start` runs it
    once immediately and then every `every` seconds on a daemon thread that shares nothing with request handling
    except the filesystem locks the owners already use. One structured event per removal and per skip (a
    skipped entry is announced once per process and again only if the reason changes)."""

    def __init__(self, home, older, every, emit, *, clock=time.time, kinds=('image',)):
        self.home, self.older, self.every, self.emit, self.clock, self.kinds = home, older, every, emit, clock, kinds
        self._announced = {}
        self._stop = threading.Event()
        self._thread = None

    def run_once(self):
        removed = skipped = failed = 0
        seen = set()
        try:
            entries, _ignored, fds, notes = collect(self.home, self.kinds, older_than=self.older, now=self.clock())
            try:
                for n in notes:
                    seen.add(('note', n))
                    self._once(('note', n), 'retention.auto_prune.note', note=n)
                plan, skips = plan_prune(entries, older_than=self.older, session=None, now=self.clock())
                for e, why in skips:
                    skipped += 1
                    seen.add((e.kind, e.id))
                    self._once((e.kind, e.id), 'retention.auto_prune.skip', entry_kind=e.kind, entry_id=e.id, why=why,
                               age_seconds=int(self.clock() - e.mtime))

                def report(e, exc):
                    nonlocal removed, failed
                    if exc is None:
                        removed += 1
                        self.emit('retention.auto_prune.removed', entry_kind=e.kind, entry_id=e.id, label=e.label, size=e.size,
                                  age_seconds=int(self.clock() - e.mtime), names=list(e.names))
                    else:
                        failed += 1
                        self.emit('retention.auto_prune.failed', level='warn', entry_kind=e.kind, entry_id=e.id, error=str(exc))
                apply_plan(self.home, plan, fds, force=False, report=report)
            finally:
                _close(fds)
                self._announced = {k: v for k, v in self._announced.items() if k in seen}
        except Exception as exc:  # noqa: BLE001 — a background janitor must never take the service down
            failed += 1
            try:
                self.emit('retention.auto_prune.error', level='error', error=f'{type(exc).__name__}: {exc}')
            except Exception:  # noqa: BLE001 — not even a broken logger may escape
                pass
        return {'removed': removed, 'skipped': skipped, 'failed': failed}

    def _once(self, key, event, **fields):
        why = fields.get('why') or fields.get('note')
        if self._announced.get(key) != why:
            self._announced[key] = why
            self.emit(event, **fields)

    def _loop(self):
        try:
            self.emit('retention.auto_prune.enabled', older_than_seconds=self.older, every_seconds=self.every,
                      home=str(self.home), kinds=list(self.kinds))
        except Exception:  # noqa: BLE001
            pass
        while True:
            try:
                self.run_once()
            except BaseException:  # noqa: BLE001 — run_once already contains Exception; this is the last wall
                pass
            if self._stop.wait(self.every):
                return

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name='cria-retention', daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout=5.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)


if __name__ == '__main__':
    sys.exit(main())
