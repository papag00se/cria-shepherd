#!/usr/bin/env python3
"""Explicit local walk/fix closure; no automatic judgment, scan, archive or registry.

The operator supplies the complete settled fix list, attributable scratch paths,
necessary source/test copies and active/call-log exclusions. See suite/README.md.
This validates that declaration; it cannot discover an omitted active dependency
or classify arbitrary bytes as a model call, nor constrain independent rm commands.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys

REPOSITORY = Path(__file__).resolve().parents[1]


def _path(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'invalid path: {value!r}')
    p = Path(value)
    if not p.is_absolute() or '..' in p.parts:
        raise ValueError(f'path must be absolute without ..: {p}')
    for part in (p, *p.parents):
        if part.is_symlink():
            raise ValueError(f'symlink path denied: {part}')
    return p


def _overlap(path, known, ancestors):
    return path in ancestors or any(p in known for p in (path, *path.parents))


def _walk_error(error):
    raise error


def _writable_directory(name, parent_fd, expected=None):
    """Prepare only admitted owned directories; never change hard-linked file modes."""
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        if expected is not None and (info.st_dev, info.st_ino) != expected:
            raise ValueError(f'cleanup directory changed after admission: {name}')
        if info.st_uid != os.geteuid():
            raise ValueError(f'cleanup directory not owned by this process: {name}')
        if not info.st_mode & stat.S_IWUSR:
            os.fchmod(fd, stat.S_IMODE(info.st_mode) | stat.S_IWUSR)
        with os.scandir(fd) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    _writable_directory(entry.name, fd)
    finally:
        os.close(fd)


def _digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def eligible(record, *, repo=REPOSITORY, scratch_roots=None):
    """Validate the whole batch before deletion; return exact paths and inode pins."""
    if not isinstance(record, dict):
        raise ValueError('closure must be an object')
    for key in ('unit', 'owner', 'closure'):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError(f'missing explicit {key}')
    if record.get('closed') is not True:
        raise ValueError('unit has not explicitly closed')
    fixes = record.get('fixes')
    if not isinstance(fixes, list) or (not fixes and record.get('no_findings') is not True):
        raise ValueError('complete settled fixes required; empty is not closure')
    ids = set()
    secured = []
    repo = _path(str(repo))
    for fix in fixes:
        if not isinstance(fix, dict) or not isinstance(fix.get('id'), str) or not fix['id'].strip() or fix['id'] in ids:
            raise ValueError('missing/duplicate fix identity')
        ids.add(fix['id'])
        if fix.get('disposition') not in ('ACCEPTED', 'REJECTED'):
            raise ValueError(f'unsettled fix: {fix["id"]}')
        changes = fix.get('changes')
        if not isinstance(changes, list):
            raise ValueError(f'necessary changes not declared: {fix["id"]}')
        for change in changes:
            if not isinstance(change, dict):
                raise ValueError('invalid secured change')
            source = _path(change.get('source'))
            target = _path(change.get('worktree'))
            if target == repo or repo not in target.parents:
                raise ValueError(f'change not secured in worktree: {target}')
            if not source.is_file() or not target.is_file() or _digest(source) != _digest(target):
                raise ValueError(f'necessary source/test not secured: {source} -> {target}')
            secured.append(target)
    home = Path.home()
    roots = tuple(_path(str(p)) for p in (scratch_roots if scratch_roots is not None else
                  (Path('/tmp'), home / '.cria/validation', home / '.cria/walk-findings')))
    protected = {REPOSITORY, repo, home / '.cria/calls', home / '.cria/logs', home / 'Documents', *secured}
    for key in ('protected_paths', 'call_logs'):
        if not isinstance(record.get(key), list):
            raise ValueError(f'explicit {key} list required (including known-empty)')
        protected.update(_path(v) for v in record[key])
    protected_ancestors = {parent for p in protected for parent in p.parents}
    values = record.get('scratch')
    if not isinstance(values, list) or not values:
        raise ValueError('nonempty attributable scratch paths required')
    paths = [_path(v) for v in values]
    pins = []
    previous, previous_ancestors = set(), set()
    for path in paths:
        if not any(root in path.parents for root in roots):
            raise ValueError(f'outside scratch roots or broad root: {path}')
        if _overlap(path, protected, protected_ancestors):
            raise ValueError(f'protected path overlaps cleanup: {path}')
        if _overlap(path, previous, previous_ancestors):
            raise ValueError(f'duplicate/overlapping scratch paths: {path}')
        s = path.lstat()  # Absent is an error, not a successful past deletion.
        tree = [path]
        if not os.access(path.parent, os.W_OK | os.X_OK):
            raise ValueError(f'cleanup parent not writable: {path.parent}')
        if stat.S_ISDIR(s.st_mode):
            for base, dirs, files in os.walk(path, onerror=_walk_error, followlinks=False):
                tree.extend(Path(base) / name for name in (*dirs, *files))
        for item in tree:
            info = item.lstat()
            mode = info.st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError(f'symlink/special entry denied: {item}')
            if stat.S_ISDIR(mode) and info.st_uid != os.geteuid():
                raise ValueError(f'cleanup directory not owned by this process: {item}')
        previous.add(path)
        previous_ancestors.update(path.parents)
        pins.append((path, s.st_dev, s.st_ino))
    return pins


def close(record, *, repo=REPOSITORY, scratch_roots=None, dry_run=False):
    pins = eligible(record, repo=repo, scratch_roots=scratch_roots)
    if not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError('platform lacks symlink-safe directory deletion')
    if dry_run:
        return [str(p) for p, _, _ in pins]
    # Open every ancestor without following links; pin the parent for the operation.
    removed = []
    for path, dev, ino in pins:
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parent.parts[1:]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            s = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            if (s.st_dev, s.st_ino) != (dev, ino):
                raise ValueError(f'cleanup target changed after admission: {path}')
            if stat.S_ISDIR(s.st_mode):
                _writable_directory(path.name, fd, (dev, ino))
                current = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (dev, ino):
                    raise ValueError(f'cleanup target changed during preparation: {path}')
                shutil.rmtree(path.name, dir_fd=fd)
            elif stat.S_ISREG(s.st_mode):
                os.unlink(path.name, dir_fd=fd)
            else:
                raise ValueError(f'cleanup target type changed: {path}')
            removed.append(str(path))
        finally:
            os.close(fd)
    return removed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('closure', type=Path, help='complete operator closure JSON; - reads stdin')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if str(args.closure) == '-' else args.closure.read_text()
        removed = close(json.loads(text), dry_run=args.dry_run)
    except (ValueError, OSError, TypeError) as e:
        parser.exit(1, f'cleanup denied/failed: {e}\n')
    print(json.dumps({'eligible' if args.dry_run else 'removed': removed}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
