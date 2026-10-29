"""Explicit, operator-run cleanup of cria's private retained state.

    python -m cria.retention list  [--home DIR] [--kind multipart|image|all] [--json]
    python -m cria.retention prune [--home DIR] [--kind ...] [--older-than 14d]
                                   [--session ID] [--apply]

Nothing here runs automatically and nothing in cria imports it. cria has no trusted
harness session-close signal, so the operator's deliberate invocation IS the
authority: idleness, LRU, eviction, compaction and "history stopped mentioning it"
remain forbidden inferences. `prune` is a dry run unless `--apply` is given and it
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
or `retry_closed` (closed-seal marker outside the payload directory, removed last),
multipart state uses the bridge's own record validation and the bridge's lock file;
the authoritative session record is deleted first, then its derived call
associations, so an interrupted run leaves only associations that fail closed.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
import fcntl
from dataclasses import dataclass, field
from pathlib import Path

from . import imagepersist, privatepaths
from .imagestore import ImageStore
from .imageprotocol import ImageUnavailable
from .multipart import InvalidPage, BridgeError, _pairs
from .multipart_bridge import Bridge

_SHA = r'[0-9a-f]{64}'
_MP_RECORD = re.compile(_SHA + r'\.json')
_MP_INDEX = re.compile(r'call-(' + _SHA + r')\.json')
_MP_TEMP = re.compile(r'\.(?:multipart|index)-[0-9a-f]{32}')
_IMG_DIR = re.compile(r'image-session-[A-Za-z0-9_-]+')
_IMG_MARKER = re.compile(r'(image-session-[A-Za-z0-9_-]+)\.owner\.json')
_UNITS = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}


@dataclass
class Entry:
    kind: str                 # 'multipart' | 'image'
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


def _open_root(path):
    """Directory fd for a retention root: no symlink component, owned, private."""
    return Bridge(str(path))._dirfd()


def _du(dirfd):
    total = 0
    newest = os.fstat(dirfd).st_mtime
    for name in os.listdir(dirfd):
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
    return total, newest


def _read_regular(dirfd, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dirfd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise ValueError('not a private regular file owned by this user')
        with os.fdopen(fd, encoding='utf-8') as f:
            fd = None
            return json.load(f, object_pairs_hook=_pairs), st
    finally:
        if fd is not None:
            os.close(fd)


# ---------------------------------------------------------------- multipart

def _lock_fd(dirfd, *, create):
    flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
    try:
        fd = os.open('.lock', flags, 0o600, dir_fd=dirfd)
    except FileNotFoundError:
        return None
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        os.close(fd)
        raise BridgeError('multipart lock is not private')
    return fd


def _scan_multipart(dirfd, root):
    entries, ignored = {}, []
    bridge = Bridge(str(root))

    def entry(sha):
        return entries.setdefault(sha, Entry('multipart', sha))

    names = sorted(os.listdir(dirfd))
    for name in names:
        if name == '.lock':
            continue
        record, index, temp = _MP_RECORD.fullmatch(name), _MP_INDEX.fullmatch(name), _MP_TEMP.fullmatch(name)
        if not (record or index or temp):
            ignored.append(name)
            continue
        st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        if temp:
            e = Entry('multipart', 'tmp-' + name.lstrip('.')[:20], names=[name], size=st.st_size, mtime=st.st_mtime,
                      state='unknown', detail='leftover temporary file from an interrupted write')
            e.refused = not stat.S_ISREG(st.st_mode)
            entries[e.id] = e
            continue
        if record:
            e = entry(name[:-5])
            e.names.insert(0, name)
        else:
            sha = None
            e = None
        refused = not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
        try:
            if refused:
                raise ValueError('symlink, non-regular or foreign-owned file')
            obj, _ = _read_regular(dirfd, name)
            if record:
                session = obj.get('session') if isinstance(obj, dict) else None
                if not isinstance(session, str) or hashlib.sha256(session.encode()).hexdigest() + '.json' != name:
                    raise ValueError('record is not named for its session')
                bridge._load(session)               # the bridge's own validation
                e.label = session
                e.detail = f"{len(obj['entries'])} read(s)"
            else:
                if (not isinstance(obj, dict) or set(obj) != {'v', 'call_id', 'session'} or obj['v'] != 1
                        or not isinstance(obj['call_id'], str) or not isinstance(obj['session'], str)
                        or bridge._index_name(obj['call_id']) != name):
                    raise ValueError('invalid call association')
                e = entry(hashlib.sha256(obj['session'].encode()).hexdigest())
                e.label = e.label or obj['session']
                if name not in e.names:
                    e.names.append(name)
        except (ValueError, OSError, BridgeError, InvalidPage, UnicodeError, json.JSONDecodeError) as exc:
            if e is None:
                e = Entry('multipart', 'corrupt-' + name[:20])
                entries[e.id] = e
                e.names.append(name)
            e.state, e.detail, e.refused = 'corrupt', f'{name[:20]}: {exc}', e.refused or refused
        e.size += st.st_size
        e.mtime = max(e.mtime, st.st_mtime)
    for e in entries.values():
        if e.state != 'corrupt' and not any(_MP_RECORD.fullmatch(n) for n in e.names) and e.names \
                and not e.id.startswith('tmp-'):
            e.detail = 'call associations without a session record'
    return list(entries.values()), ignored


def _delete_multipart(dirfd, entry):
    """Authoritative record first, then derived associations/temps; fsync between."""
    ordered = sorted(entry.names, key=lambda n: 0 if _MP_RECORD.fullmatch(n) else 1)
    for name in ordered:
        try:
            os.unlink(name, dir_fd=dirfd)
        except FileNotFoundError:
            pass
        os.fsync(dirfd)


# -------------------------------------------------------------------- images

def _scan_images(dirfd, root):
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
                except (ValueError, OSError) as exc:
                    e.state, e.detail = 'corrupt', f'owner marker unreadable: {exc}'
                entries[e.id] = e
            continue
        else:
            ignored.append(name)
            continue
        st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        e = Entry('image', name, names=[name], mtime=st.st_mtime)
        entries[name] = e
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
            e.refused, e.state = True, 'corrupt'
            e.detail = 'not an owned private directory (symlink, file or wrong mode); never touched'
            continue
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dirfd)
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
    if not path.is_dir() or path.is_symlink():          # orphan sealed marker only
        descriptor = {'owner': 'session-images', 'directory': name,
                      'generation': marker['generation'], 'closed': marker['closed']}
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


# ------------------------------------------------------------------ selection

def _matches_session(entry, wanted):
    digest = hashlib.sha256(wanted.encode()).hexdigest()
    if entry.kind == 'multipart':
        return entry.id == digest or (len(wanted) >= 8 and entry.id.startswith(wanted)) or entry.label == wanted
    return entry.id == wanted or entry.label == wanted


def select(entries, *, older_than, session, now):
    chosen = []
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
    return {'multipart': home / 'multipart', 'image': home / 'images'}


def collect(home, kinds, *, lock_multipart=False):
    """Return (entries, ignored, held_lock_fd_or_None, notes). Caller closes the fds."""
    entries, ignored, notes, fds = [], [], [], {}
    roots = _roots(home)
    for kind in kinds:
        root = roots[kind]
        if not os.path.lexists(root):
            continue
        try:
            dirfd = _open_root(root)
        except (BridgeError, OSError) as exc:
            notes.append(f'{kind}: root {root} refused: {exc}')
            continue
        try:
            if kind == 'multipart':
                lock = _lock_fd(dirfd, create=lock_multipart)
                locked = False
                if lock is not None:
                    try:
                        fcntl.flock(lock, (fcntl.LOCK_EX if lock_multipart else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                        if lock_multipart:
                            fds['multipart-lock'] = lock
                        else:
                            os.close(lock)
                    except OSError:
                        os.close(lock)
                        locked = True
                if locked and lock_multipart:
                    notes.append('multipart: state lock is held by a live cria process; skipped (retry later)')
                    continue
                found, ign = _scan_multipart(dirfd, root)
                if locked:
                    for e in found:
                        e.state = 'active' if e.state != 'corrupt' else e.state
                        e.detail = (e.detail + '; ' if e.detail else '') + 'state lock held by a live cria process'
            else:
                found, ign = _scan_images(dirfd, str(root))
            entries.extend(found)
            ignored.extend(f'{kind}/{n}' for n in ign)
            fds[kind] = os.dup(dirfd)
        except (OSError, ValueError, BridgeError, ImageUnavailable) as exc:
            notes.append(f'{kind}: scan failed: {exc}')
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
        p.add_argument('--kind', choices=('multipart', 'image', 'all'), default='all')
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
    kinds = ('multipart', 'image') if args.kind == 'all' else (args.kind,)
    if args.cmd == 'list':
        entries, ignored, fds, notes = collect(args.home, kinds)
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
    entries, ignored, fds, notes = collect(args.home, kinds, lock_multipart=args.apply)
    code = 0
    try:
        for n in notes:
            out.write(f'note: {n}\n')
        picked = select(entries, older_than=older, session=args.session, now=now)
        plan, skipped = [], []
        for e in picked:
            if e.refused:
                skipped.append((e, 'refused: ' + (e.detail or 'unsafe entry')))
            elif e.state == 'active':
                skipped.append((e, 'skipped: held by a live cria process'))
            elif e.state == 'corrupt' and args.session is None:
                skipped.append((e, 'skipped: corrupt (' + e.detail + '); select it with --session ID --apply'))
            else:
                plan.append(e)
        out.write(('APPLY: will remove' if args.apply else 'DRY RUN: would remove') + f' {len(plan)} entr{"y" if len(plan)==1 else "ies"}\n')
        for e in plan:
            out.write(f'  remove {e.kind} {e.id} [{e.state}] {_size_text(e.size)} age {_fmt_age(now - e.mtime)}: '
                      + ', '.join(e.names) + '\n')
        for e, why in skipped:
            out.write(f'  {why}: {e.kind} {e.id}\n')
        if not args.apply:
            out.write('nothing was removed; re-run with --apply to delete exactly the entries above\n')
            return 0
        authority = object()
        for e in plan:
            try:
                if e.kind == 'multipart':
                    _delete_multipart(fds['multipart'], e)
                else:
                    _delete_image(str(_roots(args.home)['image']), e, authority,
                                  force=args.session is not None)
                out.write(f'removed {e.kind} {e.id}\n')
            except (OSError, ImageUnavailable, BridgeError, KeyError, TypeError) as exc:
                code = 1
                out.write(f'FAILED {e.kind} {e.id}: {exc}; safe to re-run\n')
        return code
    finally:
        _close(fds)


if __name__ == '__main__':
    sys.exit(main())
