"""Compose a read-only workspace inventory for execution by the harness.

This module never accesses the workspace on the server. The program's JSON uses
escaped path strings, including names containing newlines or undecodable bytes.
"""
from __future__ import annotations

import base64
import json
import shlex

from . import groundtruth, jsontext, probegate, prompts


_PROGRAM = r'''
import ast, base64, json, os, stat, sys
root = sys.argv[1]
parameters = json.loads(base64.b64decode(sys.argv[2]))
excluded = set(parameters['excluded'])
result = {'files': [], 'symlinks': [], 'errors': [], 'excluded_names': parameters['shown']}
def failed(path, exc):
    result['errors'].append({'path': path, 'error': str(exc)})
def onerror(exc):
    failed(exc.filename or '.', exc)
root_fd = None
try:
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    for base, dirs, files, fd in os.fwalk('.', topdown=True, onerror=onerror, follow_symlinks=False, dir_fd=root_fd):
        relbase = os.path.relpath(base, '.')
        rel = lambda name: name if relbase == '.' else os.path.join(relbase, name)
        for name in list(dirs):
            path = rel(name)
            try:
                mode = os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    result['symlinks'].append(path)
                    dirs.remove(name)
                elif name in excluded:
                    dirs.remove(name)
            except OSError as exc:
                dirs.remove(name)
                failed(path, exc)
        for name in files:
            path = rel(name)
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    result['symlinks'].append(path)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    continue
                item = {'path': path, 'size': info.st_size, 'symbols': None}
                result['files'].append(item)
                if not name.endswith('.py'):
                    continue
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(descriptor, 'rb') as source:
                    opened = os.fstat(source.fileno())
                    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise OSError('file changed during survey')
                    tree = ast.parse(source.read(), filename=path)
                symbols = []
                def visit(node, prefix=''):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        qualified = prefix + node.name
                        symbols.append(qualified)
                        prefix = qualified + '.'
                    for child in ast.iter_child_nodes(node):
                        visit(child, prefix)
                visit(tree)
                item['symbols'] = symbols
            except (OSError, SyntaxError, ValueError, UnicodeError, RecursionError) as exc:
                failed(path, exc)
except OSError as exc:
    failed('.', exc)
result['files'].sort(key=lambda item: item['path'])
result['symlinks'].sort()
raw = json.dumps(result, ensure_ascii=True, separators=(',', ':')).encode('ascii')
if root_fd is not None:
    os.close(root_fd)
output = json.dumps(result, ensure_ascii=True, separators=(',', ':'))
if len(sys.argv) > 3 and sys.argv[3] == 'encoded':
    output = __import__('base64').b64encode(output.encode('ascii')).decode('ascii')
print(output)
'''


def command(root: str, *, encoded: bool = False) -> str:
    """Return a shell command; all path operations occur on the harness."""
    excluded = sorted(groundtruth._INVENTORY_EXCLUDE)
    shown = [name for name in excluded if 'cria' not in name.lower()]
    parameters = base64.b64encode(json.dumps({'excluded': excluded, 'shown': shown}).encode()).decode()
    return ('python3 -I -c ' + shlex.quote(_PROGRAM) + ' ' + shlex.quote(root) + ' '
            + shlex.quote(parameters) + (' encoded' if encoded else ''))


UNAVAILABLE = '__CTX_INVENTORY_SCRATCH_UNAVAILABLE__'

_SCRATCH_CHECK = r'''
import os, sys
try:
    root = os.path.realpath(sys.argv[1])
    fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.close(fd)
    scratch = os.path.realpath(os.environ.get('TMPDIR') or '/tmp')
    if '\n' in scratch or '\r' in scratch or not os.path.isdir(scratch) or os.path.commonpath((root, scratch)) == root:
        raise ValueError('no external scratch')
    print(scratch)
except (OSError, ValueError):
    sys.exit(1)
'''


def plan(root: str, *, poll_wait_s: float = probegate.GATE_POLL_WAIT_S) -> probegate.GatePlan:
    """Use the existing authenticated, lossless harness paging transport, with no project checks."""
    result = probegate.GatePlan(workspace=root, transport_required=True, transport_poll_wait_s=poll_wait_s)
    result.transport_deadline_s = probegate._gate_deadline_s(0)
    spool = f'"${{TMPDIR:-/tmp}}/{probegate.gatecleanup.PRIVATE_PREFIX}{result.transport_id}/.ctx-gate-{result.transport_id}.spool"'
    def compose(budget=probegate.TRANSPORT_CHUNK_BYTES):
        return '\n'.join([
            probegate._gate_sentinel([]),
            f'if __ctx_scratch=$(python3 -I -c {shlex.quote(_SCRATCH_CHECK)} {shlex.quote(root)}); then',
            'TMPDIR="$__ctx_scratch"; export TMPDIR',
            f'__ctx_gate_file={spool}',
            probegate._helper_install_leg().rstrip('\n'),
            *probegate._gate_launch_guard(result.transport_id, root, [command(root, encoded=True)], '',
                                           poll_wait_s, (), budget=budget),
            f'else printf "%s\\n" {shlex.quote(UNAVAILABLE)}; fi',
        ])
    result.script = compose()
    result.transport_compose = compose
    return result


def strip_calls(messages: list[dict], call_ids) -> list[dict]:
    """Remove only this session's own survey calls and their paired results."""
    wanted = set(call_ids)
    calls, results = {}, {}
    for index, message in enumerate(messages):
        if message.get('role') == 'assistant':
            for call in message.get('tool_calls') or ():
                if call.get('id') in wanted:
                    calls.setdefault(call['id'], []).append(index)
        elif message.get('role') == 'tool' and message.get('tool_call_id') in wanted:
            results.setdefault(message['tool_call_id'], []).append(index)
    ids = {cid for cid in wanted if len(calls.get(cid, ())) == 1
           and len(results.get(cid, ())) <= 1
           and (not results.get(cid) or calls[cid][0] < results[cid][0])}
    out = []
    for message in messages:
        if message.get('role') == 'tool' and message.get('tool_call_id') in ids:
            continue
        if message.get('role') == 'assistant' and message.get('tool_calls'):
            calls = [call for call in message['tool_calls'] if call.get('id') not in ids]
            if len(calls) != len(message['tool_calls']):
                if not calls and not message.get('content'):
                    continue
                message = dict(message)
                if calls:
                    message['tool_calls'] = calls
                else:
                    message.pop('tool_calls', None)
        out.append(message)
    return out


def select(files: list[dict], ask, *, chunk_chars: int) -> tuple[list[int], bool]:
    """Ask about every whole record; accept only IDs present in that question.

    An unreadable answer is not an exclusion judgment. The returned completeness
    bit allows callers to label a partial selection or abstain entirely.
    """
    chunks, chunk, size = [], [], 0
    for index, item in enumerate(files):
        record = {'id': index, 'path': item['path'], 'symbols': item.get('symbols')}
        length = len(json.dumps(record, ensure_ascii=True))
        if chunk and size + length > chunk_chars:
            chunks.append(chunk)
            chunk, size = [], 0
        chunk.append(record)
        size += length
    if chunk:
        chunks.append(chunk)
    selected, complete = [], True
    for chunk in chunks:
        try:
            answer = jsontext.extract_json_object(jsontext.strip_think(ask(chunk) or ''))
            ids = answer['selected']
            if not isinstance(ids, list):
                raise ValueError('invalid selection')
        except Exception:  # an unavailable reasoner is not an exclusion judgment
            complete = False
            continue
        available = {record['id'] for record in chunk}
        selected.extend(i for i in ids if type(i) is int and i in available and i not in selected)
    return selected, complete


_PAGE = r'''
import sys
raw = sys.stdin.read()
offset = int(sys.argv[1])
if offset < 0 or offset > len(raw):
    raise SystemExit('invalid inventory offset')
end = min(offset + 1024, len(raw))
print('current-inventory', offset, end, len(raw))
print(raw[offset:end])
'''


def browse_command(root: str) -> str:
    """Re-survey without artifacts and page its ASCII JSON; append a character offset."""
    return command(root) + ' | python3 -I -c ' + shlex.quote(_PAGE)


def render(data: dict, ask=None, *, chunk_chars: int = 12000, root: str = '.', budget_chars: int = 12000) -> str:
    """Show whole small inventories or a labelled bounded selection, with a re-survey route."""
    files = data['files']
    labels = prompts.load_map('initial_inventory_labels')
    dump = lambda value: json.dumps(value, ensure_ascii=True, separators=(',', ':'))
    issues = {'symlinks': data.get('symlinks', []), 'errors': data.get('errors', [])}
    large = len(dump(files)) + len(dump(issues)) > budget_chars
    selected, complete = (select(files, ask, chunk_chars=chunk_chars) if large and ask else ([], False))
    if not large:
        heading, visible = labels['incomplete' if data.get('errors') else 'complete'], files
    elif not complete:
        heading, visible = (labels['partial'] if selected else labels['unavailable']), [files[i] for i in selected]
    else:
        heading, visible = labels['selected' if selected else 'none'], [files[i] for i in selected]
    if large and len(dump(visible)) > budget_chars:
        heading, visible = 'The reasoner selection exceeds the orientation budget; no selected paths are shown.', []
    excluded = [name for name in data.get('excluded_names', []) if 'cria' not in name.lower()]
    if large:
        issues = {key: len(value) for key, value in issues.items()}
    parts = [labels['scope'], dump(excluded), labels['issues_spilled' if large else 'issues'], dump(issues), heading, dump(visible)]
    if large:
        parts.extend(['Selection is from the earlier survey; its complete snapshot is not retained. '
                      'Browse the current inventory with the read-only command below followed by offset 0. '
                      'The header gives start, next offset and total; repeat with the next offset until it equals total. '
                      'Each page re-surveys, so changes between pages may shift results:', browse_command(root)])
    return prompts.render('initial_inventory', inventory='\n'.join(parts))
