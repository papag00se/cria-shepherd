"""Compile repository searches for execution by the harness, never on the server."""
from __future__ import annotations

import base64
import inspect
import json
import shlex

from . import dirguard, ignore, prompts, webfetch
from .privatepaths import CRIA_HOME

# This program is executed by the harness. It does not follow discovered symlinks;
# the explicitly named root is resolved and checked against the permission first.
_PROGRAM = r'''
import base64, fnmatch, json, os, re, stat, sys
from typing import Callable, Optional
s = json.loads(base64.b64decode(sys.argv[1]))
messages = s['messages']
'''
_WALK = r'''
def emit(key, **kw):
    print(messages[key].format(**kw))

def inside(path, root):
    try: return os.path.commonpath((path, root)) == root
    except ValueError: return False

try:
    if not isinstance(s['path'], str) or not isinstance(s['include'], str): raise ValueError(messages['invalid_arguments'])
    root = os.path.realpath(os.path.expanduser(s['path']))
except (ValueError, OSError) as e:
    emit('error', detail=str(e)); sys.exit(2)
private = os.path.realpath(s['private'])
if inside(root, private):
    emit('private'); sys.exit(2)
if s['permission'] == 'none' and s['workspace']:
    allowed = [os.path.realpath(s['workspace'])] + [os.path.realpath(p) for p in s['roots']]
    cache = any(marker in root + '/' for marker in s['cache_markers'])
    if not cache and not any(inside(root, p) for p in allowed):
        emit('outside'); sys.exit(2)
def validate_glob(pattern):
    index = 0
    while index < len(pattern):
        if pattern[index] == '[':
            end = index + 1
            if end < len(pattern) and pattern[end] == '!': end += 1
            if end < len(pattern) and pattern[end] == ']': end += 1
            end = pattern.find(']', end)
            if end < 0: raise ValueError(messages['invalid_pattern'])
            index = end
        index += 1

try:
    if not isinstance(s['pattern'], str): raise ValueError(messages['invalid_pattern'])
    if s['include']: validate_glob(s['include'])
    if s['name'] == 'grep': regex = re.compile(s['pattern'])
    else:
        validate_glob(s['pattern'])
        regex = None
    if not os.path.exists(root): raise FileNotFoundError(root)
    if not os.path.isdir(root) and not os.path.isfile(root): raise OSError(messages['not_regular'])
except (OSError, ValueError, re.error) as e:
    emit('error', detail=str(e)); sys.exit(2)

def match(path, pattern):
    # ** matches zero or more complete path segments.
    parts, pats = path.split('/'), pattern.split('/')
    def go(i, j):
        if j == len(pats): return i == len(parts)
        if pats[j] == '**': return go(i, j+1) or (i < len(parts) and go(i+1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], pats[j]) and go(i+1, j+1)
    return go(0, 0)

skipped, errors, matches = [], [], 0
base = root if os.path.isdir(root) else os.path.dirname(root)
def visit(path, fd=None, name=None):
    global matches
    rel = os.path.relpath(path, base).replace(os.sep, '/')
    if s['name'] == 'glob':
        if match(rel, s['pattern']): print(rel); matches += 1
    elif not s['include'] or match(rel if '/' in s['include'] else os.path.basename(rel), s['include']):
        try:
            descriptor = os.open(name if fd is not None else path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(descriptor, 'rb') as f:
                if not stat.S_ISREG(os.fstat(f.fileno()).st_mode): raise OSError(messages['not_regular'])
                for number, line in enumerate(f, 1):
                    text = line.decode('utf-8').removesuffix('\n')
                    if regex.search(text): print('%s:%d:%s' % (rel, number, text)); matches += 1
        except (OSError, UnicodeError) as e: errors.append('%s: %s' % (rel, e))

if os.path.isfile(root): visit(root)
else:
    def onerror(e): errors.append(str(e))
    for folder, dirs, files, directory_fd in os.fwalk(root, topdown=True, follow_symlinks=False, onerror=onerror):
        dirs.sort(); files.sort()
        kept = []
        for name in dirs:
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, base).replace(os.sep, '/')
            if os.path.islink(path): skipped.append(rel + ' (symlink)'); continue
            if inside(os.path.realpath(path), private): skipped.append(rel + ' (private)'); continue
            if not s['include_generated'] and s['workspace'] and os.path.realpath(path) == os.path.realpath(os.path.join(s['workspace'], s['spill'])):
                skipped.append(rel + ' (reference output)'); continue
            try:
                def children():
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try: return os.listdir(child)
                    finally: os.close(child)
                proof = None if s['include_generated'] else generated(name, children)
            except OSError as e:
                errors.append('%s: %s' % (rel, e)); continue
            if proof: skipped.append(rel + ' (' + proof + ')')
            else: kept.append(name)
        dirs[:] = kept
        for name in files:
            path = os.path.join(folder, name)
            if os.path.islink(path): skipped.append(os.path.relpath(path, base) + ' (symlink)'); continue
            try:
                if stat.S_ISREG(os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_mode): visit(path, directory_fd, name)
            except OSError as e: errors.append('%s: %s' % (path, e))
if skipped: emit('skipped', paths='\n'.join(skipped))
if errors:
    emit('errors', paths='\n'.join(errors)); sys.exit(2)
if not matches: emit('none')
'''


def command(name, args, workspace, permission, roots):
    values = {k: getattr(ignore, k) for k in ('_TOOL_OWNED', '_MARKER_FILES', '_MARKER_DIRS', '_MARKER_PREFIXES', '_MARKER_PAIRS')}
    definitions = '\n'.join(f'{key} = {value!r}' for key, value in values.items())
    source = _PROGRAM + definitions + '\nChildren = Callable[[], Optional[list[str]]]\n' + inspect.getsource(ignore.generated) + _WALK
    spec = {'name': name, 'path': args.get('path') or '.', 'pattern': args.get('pattern'),
            'include': args.get('include') if args.get('include') is not None else '', 'include_generated': args.get('include_generated') is True,
            'workspace': workspace, 'permission': permission, 'roots': roots, 'private': str(CRIA_HOME), 'spill': webfetch.SPILL_DIR,
            'cache_markers': dirguard._DEP_CACHE_MARKERS,
            'messages': prompts.load_map('content_search_results')}
    payload = base64.b64encode(json.dumps(spec, ensure_ascii=True).encode()).decode('ascii')
    return 'python3 -I -c ' + shlex.quote(source) + ' ' + shlex.quote(payload)
