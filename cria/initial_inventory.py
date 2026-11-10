"""Compose a read-only workspace inventory for execution by the harness.

This module never accesses the workspace on the server. The program's JSON uses
escaped path strings, including names containing newlines or undecodable bytes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shlex

from . import groundtruth, probegate, prompts


_PROGRAM = r'''
import base64, json, os, stat, sys
# __CTX_INDEX_SETUP__
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
                # __CTX_SYMBOLS__
            except (OSError, SyntaxError, ValueError, UnicodeError, RecursionError) as exc:
                failed(path, exc)
except OSError as exc:
    failed('.', exc)
# __CTX_INDEX_CLOSE__
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


_INDEX_SETUP = r'''
import codecs, hashlib, selectors, shutil, subprocess, time
CHUNK = 65536
class Indexer:
    def __init__(self):
        self.proc = None
        self.ready = False
        self.error = None
        binary = shutil.which('ctags', path=os.defpath + ':/usr/local/bin')
        if not binary:
            self.error = 'indexer not found'
        if binary:
            try:
                # Pattern text is never returned; limiting it bounds discarded protocol data,
                # not source sent to the indexer or any symbol field.
                self.proc = subprocess.Popen([binary, '--options=NONE', '--pattern-length-limit=1', '--_interactive=sandbox'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
                os.set_blocking(self.proc.stdin.fileno(), False)
                os.set_blocking(self.proc.stdout.fileno(), False)
            except OSError as exc:
                self.error = 'indexer start failed: ' + type(exc).__name__
                self.close()
    def close(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait()
            self.proc.stdin.close()
            self.proc.stdout.close()
            self.proc = None
    def tags(self, name, source, size):
        if self.proc is None:
            return None
        try:
            # A filename is data, never a shell argument or a filesystem path to open.
            pending = json.dumps({'command': 'generate-tags', 'filename': name, 'size': size}, ensure_ascii=False).encode('utf-8') + b'\n'
            sent, remaining, reply, tags = 0, size, bytearray(), []
            deadline = time.monotonic() + 30
            with selectors.DefaultSelector() as sel:
                sel.register(self.proc.stdout, selectors.EVENT_READ)
                sel.register(self.proc.stdin, selectors.EVENT_WRITE)
                while True:
                    wait = deadline - time.monotonic()
                    if wait <= 0:
                        raise TimeoutError('indexer timed out')
                    events = sel.select(wait)
                    if not events:
                        raise TimeoutError('indexer timed out')
                    for key, _ in events:
                        if key.fileobj is self.proc.stdin:
                            if sent == len(pending):
                                pending = source.read(min(CHUNK, remaining))
                                if not pending:
                                    raise OSError('file shortened during indexing')
                                remaining -= len(pending)
                                sent = 0
                            try:
                                count = os.write(key.fd, memoryview(pending)[sent:])
                            except BlockingIOError:
                                continue
                            deadline = time.monotonic() + 30
                            sent += count
                            if sent == len(pending) and remaining == 0:
                                sel.unregister(self.proc.stdin)
                        else:
                            try:
                                chunk = os.read(key.fd, CHUNK)
                            except BlockingIOError:
                                continue
                            if not chunk:
                                raise OSError('indexer closed its output')
                            deadline = time.monotonic() + 30
                            reply.extend(chunk)
                            while b'\n' in reply:
                                line, _, tail = reply.partition(b'\n')
                                reply = bytearray(tail)
                                record = json.loads(line)
                                if not isinstance(record, dict):
                                    raise ValueError('invalid indexer record')
                                kind = record.get('_type')
                                if kind == 'program':
                                    if record.get('name') != 'Universal Ctags':
                                        raise ValueError('not Universal Ctags')
                                    self.ready = True
                                elif not self.ready:
                                    raise ValueError('missing indexer greeting')
                                elif kind == 'tag':
                                    if not isinstance(record.get('name'), str) or not isinstance(record.get('kind'), str):
                                        raise ValueError('invalid tag')
                                    tag = {k: record[k] for k in ('name', 'kind', 'scope') if isinstance(record.get(k), str)}
                                    tags.append(tag)
                                elif kind == 'completed':
                                    if remaining or sent != len(pending) or record.get('command') != 'generate-tags':
                                        raise ValueError('invalid completion')
                                    return tags or None
                                elif kind == 'error':
                                    raise ValueError('indexer error')
        except (OSError, ValueError, TypeError, UnicodeError, TimeoutError) as exc:
            self.error = 'indexer failed: ' + type(exc).__name__
            self.close()
            return None
indexer = Indexer()
'''

_SYMBOLS = r'''                item['blank'] = None
                item['observed_at'] = time.time()
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(descriptor, 'rb') as source:
                    opened = os.fstat(source.fileno())
                    if (not stat.S_ISREG(opened.st_mode)
                            or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                            != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)):
                        raise OSError('file changed during survey')
                    def unchanged():
                        current = os.fstat(source.fileno())
                        return (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) == (current.st_size, current.st_mtime_ns, current.st_ctime_ns)
                    try:
                        name.encode('utf-8')
                        decoder = codecs.getincrementaldecoder('utf-8')('strict')
                        binary = False
                        blank = True
                        total = 0
                        digest = hashlib.sha256()
                        while total < opened.st_size:
                            chunk = source.read(min(CHUNK, opened.st_size - total))
                            if not chunk:
                                break
                            total += len(chunk)
                            digest.update(chunk)
                            binary = binary or b'\0' in chunk
                            text = decoder.decode(chunk)
                            blank = blank and (not text or text.isspace())
                        text = decoder.decode(b'', final=True)
                        blank = blank and (not text or text.isspace())
                    except UnicodeError:
                        continue
                    if total != opened.st_size or not unchanged():
                        raise OSError('file changed during survey')
                    if binary:
                        continue
                    symbols = None
                    if indexer.proc is not None:
                        source.seek(0)
                        symbols = indexer.tags(name, source, opened.st_size)
                        if not unchanged():
                            raise OSError('file changed during survey')
                    item['blank'] = blank
                    item['digest'] = digest.hexdigest()
                    item['symbols'] = symbols'''


def command(root: str, *, encoded: bool = False, _browse: bool = False) -> str:
    """Return a shell command; all path operations occur on the harness."""
    excluded = sorted(groundtruth._INVENTORY_EXCLUDE)
    shown = [name for name in excluded if 'cria' not in name.lower()]
    parameters = base64.b64encode(json.dumps({'excluded': excluded, 'shown': shown}).encode()).decode()
    program = (_PROGRAM.replace('# __CTX_INDEX_SETUP__', '' if _browse else _INDEX_SETUP)
               .replace('                # __CTX_SYMBOLS__', '' if _browse else _SYMBOLS)
               .replace('# __CTX_INDEX_CLOSE__', '' if _browse else "indexer.close()\nresult['symbol_indexer_error'] = indexer.error"))
    return ('python3 -I -c ' + shlex.quote(program) + ' ' + shlex.quote(root) + ' '
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
            *probegate._gate_launch_guard(result.transport_id, root, [command(root, encoded=True)],
                                           poll_wait_s, (), budget=budget),
            f'else printf "%s\\n" {shlex.quote(UNAVAILABLE)}; fi',
        ])
    result.script = compose()
    result.transport_compose = compose
    return result


def call_identity(call: dict) -> str | None:
    """Identify the issued function and JSON arguments, independent of JSON formatting."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    try:
        function = call['function']
        if call.get('type') != 'function' or not isinstance(function['name'], str):
            return None
        arguments = function['arguments']
        if isinstance(arguments, str):
            arguments = json.loads(arguments, object_pairs_hook=unique,
                                   parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if not isinstance(arguments, dict):
            return None
        canonical = json.dumps([function['name'], arguments], sort_keys=True, ensure_ascii=True,
                               separators=(',', ':'), allow_nan=False).encode()
        return hashlib.sha256(canonical).hexdigest()
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        return None


def strip_calls(messages: list[dict], issued: dict[str, str]) -> list[dict]:
    """Remove only uniquely paired calls matching this session's issued survey calls."""
    calls, results = {}, {}
    for index, message in enumerate(messages):
        if message.get('role') == 'assistant':
            for call in message.get('tool_calls') or ():
                if isinstance(call, dict) and isinstance(call.get('id'), str) and call['id'] in issued:
                    calls.setdefault(call['id'], []).append((index, call_identity(call)))
        elif (message.get('role') == 'tool' and isinstance(message.get('tool_call_id'), str)
              and message['tool_call_id'] in issued):
            results.setdefault(message['tool_call_id'], []).append(index)
    def paired(cid, identity):
        if not identity or len(calls.get(cid, ())) != 1 or len(results.get(cid, ())) != 1:
            return False
        start, actual = calls[cid][0]
        end = results[cid][0]
        if actual != identity or end <= start:
            return False
        batch = [call.get('id') if isinstance(call, dict) else None
                 for call in messages[start].get('tool_calls') or ()]
        if any(not isinstance(call_id, str) for call_id in batch) or len(batch) != len(set(batch)):
            return False
        seen = set()
        for message in messages[start + 1:end + 1]:
            mid = message.get('tool_call_id')
            if message.get('role') != 'tool' or not isinstance(mid, str) or mid not in batch or mid in seen:
                return False
            seen.add(mid)
        return True
    ids = {cid for cid, identity in issued.items() if paired(cid, identity)}
    out = []
    for message in messages:
        if (message.get('role') == 'tool' and isinstance(message.get('tool_call_id'), str)
                and message['tool_call_id'] in ids):
            continue
        if message.get('role') == 'assistant' and message.get('tool_calls'):
            calls = [call for call in message['tool_calls']
                     if not isinstance(call, dict) or not isinstance(call.get('id'), str) or call['id'] not in ids]
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


def candidate(item: dict) -> str:
    """Render only observed names; escape control characters in untrusted filenames/tags."""
    def safe(value):
        return json.dumps(value, ensure_ascii=True)[1:-1].replace('|', r'\u007c').replace(',', r'\u002c')
    symbols = item.get('symbols')
    names = [tag['name'] for tag in symbols or [] if isinstance(tag, dict) and isinstance(tag.get('name'), str)]
    status = 'symbols available' if names else 'symbols unavailable'
    return safe(item['path']) + ' | ' + status + (' | ' + ', '.join(map(safe, names)) if names else '')


def verdict(completion: dict) -> str | None:
    """Accept exactly the scored tool protocol, without repairing ambiguous responses."""
    try:
        choices = completion['choices']
        if len(choices) != 1 or choices[0]['finish_reason'] != 'tool_calls':
            return None
        calls = choices[0]['message']['tool_calls']
        if len(calls) != 1 or calls[0]['function']['name'] != 'verdict':
            return None
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate key')
                result[key] = value
            return result
        args = json.loads(calls[0]['function']['arguments'], object_pairs_hook=unique)
        if isinstance(args, dict) and set(args) == {'decision'} and args['decision'] in ('RELEVANT', 'UNRELATED'):
            return args['decision']
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    return None


def select(files: list[dict], ask) -> tuple[list[int], bool]:
    """One judgment per observed file; an unreadable answer is not an exclusion."""
    selected, complete = [], True
    for index, item in enumerate(files):
        try:
            answer = ask(item)
        except Exception:
            answer = None
        if answer == 'RELEVANT':
            selected.append(index)
        elif answer != 'UNRELATED':
            complete = False
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
    return command(root, _browse=True) + ' | python3 -I -c ' + shlex.quote(_PAGE)


def render(data: dict, ask=None, *, root: str = '.', budget_chars: int = 12000) -> str:
    """Show whole small inventories or a labelled bounded selection, with a re-survey route."""
    # Classification is a private workspace fact, not part of the coder's inventory.
    files = [{k: v for k, v in item.items() if k not in ('blank', 'digest', 'observed_at')} for item in data['files']]
    labels = prompts.load_map('initial_inventory_labels')
    dump = lambda value: json.dumps(value, ensure_ascii=True, separators=(',', ':'))
    issues = {'symlinks': data.get('symlinks', []), 'errors': data.get('errors', [])}
    indexer_error = data.get('symbol_indexer_error')
    large = len(dump(files)) + len(dump(issues)) > budget_chars
    selected, complete = (select(files, ask) if large and ask else ([], False))
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
    parts = [labels['scope'], dump(excluded), labels['issues_spilled' if large else 'issues'], dump(issues)]
    if indexer_error:
        parts.extend([labels['indexer_unavailable'], dump(indexer_error)])
    parts.extend([heading, dump(visible)])
    if large:
        parts.extend(['Selection is from the earlier survey; its complete snapshot is not retained. '
                      'Browse the current inventory with the read-only command below followed by offset 0; symbols unavailable in this names-and-sizes listing. '
                      'The header gives start, next offset and total; repeat with the next offset until it equals total. '
                      'Each page re-surveys, so changes between pages may shift results:', browse_command(root)])
    return prompts.render('initial_inventory', inventory='\n'.join(parts))
