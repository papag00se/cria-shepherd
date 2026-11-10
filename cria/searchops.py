"""``grep`` and ``glob`` through the harness primitives (docs/harness-primitives.md 8.9; docs/harness-programs.md section 7, Phase 6b).

A search is one operation in the ledger (:mod:`cria.ledger`). The harness lists directories and finds matching lines in the files it is told to look
at; every decision is made here:

* the tree is ``ls`` (the whole path in one call when it fits one frame, else directory by directory), and what is searched is decided in this process:
  a directory is searched unless it is proven generated (:func:`cria.ignore.generated`, from the listing of the directory itself), a symbolic link is never
  followed (it is named, with the other things not searched), the reference directory cria saves into is named and not searched, and ``include_generated``
  turns the proofs off. Names are visited in the order the walk always visited them: a directory's files in name order, then its subdirectories.
* a ``glob`` is decided here on the listing alone. A ``grep`` sends the files it chose to the ``search`` stub in batches, with the pattern as the
  harness's Python ``re`` reads it (the stub runs it, bounded by a timer); a batch the harness cut is asked again smaller, and a batch that reached its
  cap is re-asked from the file it stopped in.
* what the model reads is composed here, in the words it always read: one line per match (``file:line:text``) or per name, then what was not searched,
  then what could not be read (or ``No matches.``). A result over the harness's bound is saved whole through ``write``/``put`` and the model gets the pointer.

What it learned is a function of the frames the ledger holds: a restart between two steps loses nothing.
"""
import errno as errno_
import functools
import hashlib
import json
import os
import re
from dataclasses import dataclass, field

from . import callauth, denial, externalization, harnessprims, ignore, prompts
from .content_reduce import COMMAND_ARG_BUDGET
from .ledger import LedgerError
from .opsteps import Final, Issue, reason as _reason
from .surveyops import LEVEL_MAXES, TREE_MAX, WAVE, _Tree

SEARCH = 'search'
WHATS = ('sls', 'ssearch', 'sread')
MAX_ENTRIES = 20_000          # entries the walk takes before it says it stopped
BATCH = 200                   # files one `search` call is given
MATCH_MAXES = (4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8)      # matches one `search` page holds, largest first: a page the harness cut is asked again as two halves
PAGES = 8                     # pages of one batch asked together once the first has come back full
MAX_FILE = 32 << 20           # a file larger than this is not searched (the stub reads a file whole)
MAX_HOPS = 8
_RESERVED = 3000              # bytes of a command that are not the pattern or the path (the stub, the nonce, the framing)
PRIVATE_OR_OUTSIDE = ('private', 'outside')


@dataclass
class Visit:
    """What the walk found, in the order the search is made: ``events`` are ``('file', path under ROOT, name shown)`` and ``('err', text)`` (a
    directory that could not be listed); ``skipped`` the things not searched, in order."""
    events: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


# ---------------------------------------------------------------- what the arguments mean

def validate_glob(pattern: str, messages: dict) -> None:
    """A character class must be closed (the pattern as the old program checked it, so the same patterns are refused)."""
    index = 0
    while index < len(pattern):
        if pattern[index] == '[':
            end = index + 1
            if end < len(pattern) and pattern[end] == '!':
                end += 1
            if end < len(pattern) and pattern[end] == ']':
                end += 1
            end = pattern.find(']', end)
            if end < 0:
                raise ValueError(messages['invalid_pattern'])
            index = end
        index += 1


def match(path: str, pattern: str) -> bool:
    """``**`` matches zero or more complete path segments; every other segment is ``fnmatch``. Memoised: a pattern of many ``**`` costs the product of
    the two lengths, not their binomial."""
    import fnmatch
    parts, pats = path.split('/'), pattern.split('/')

    @functools.lru_cache(maxsize=None)
    def go(i, j):
        if j == len(pats):
            return i == len(parts)
        if pats[j] == '**':
            return go(i, j + 1) or (i < len(parts) and go(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], pats[j]) and go(i + 1, j + 1)
    return go(0, 0)


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def refusal_of(abs_root: str, permission: str, workspace: str | None, roots) -> str | None:
    """The key of the message that says why a search root may not be searched, or None: it is inside cria's private directory, or it is outside the
    workspace (and the declared roots) where the permission is ``none`` (a dependency cache is reading, not exfiltration, as for every file tool)."""
    from . import dirguard, privatepaths
    if _inside(abs_root, os.path.normpath(str(privatepaths.CRIA_HOME))):
        return 'private'
    if permission == 'none' and workspace:
        allowed = [os.path.normpath(workspace)] + [os.path.normpath(p) for p in roots]
        cache = any(marker in abs_root + '/' for marker in dirguard._DEP_CACHE_MARKERS)
        if not cache and not any(_inside(abs_root, p) for p in allowed):
            return 'outside'
    return None


def skip_names(ctx: dict) -> list:
    """Directory names ``ls`` reports and never enters: the names a tool owns, unless ``include_generated``."""
    return [] if ctx['search']['generated'] else sorted(ignore._TOOL_OWNED)


def command(op: str, ctx: dict, s: int, what: str, args: dict, blobs: dict) -> str:
    """The harness command of step ``s``: a pure function of what the ledger recorded (a retried request composes the same bytes)."""
    nonce, safe, label = callauth.nonce(op, s), ctx['safe'], f"{ctx['tool']} {ctx['path']}"
    if what == 'sls':
        tree = args['mode'] == 'tree'
        words = [args['root'], args['dir'], 0 if tree else 1, TREE_MAX if tree else LEVEL_MAXES[args['rung']], 0,
                 json.dumps(skip_names(ctx), separators=(',', ':')), os.fsencode(args.get('after', '')).hex()]
        return harnessprims.compose('ls', nonce, words, comment=label, safe_path=safe)
    if what == 'sread':
        return harnessprims.compose('read', nonce, [args['root'], args['rel'], 0, 0, 0], comment=label, safe_path=safe)
    return harnessprims.compose('search', nonce, [args['root'], ctx['search']['pattern'], 0, args['mx'], MAX_FILE, args['sk']],
                                text=json.dumps(args['files']), comment=label, safe_path=safe)


# ---------------------------------------------------------------- the walk, from the frames

def _generated(tree: _Tree, d: str, ctx: dict) -> str | None:
    """The proof that directory ``d`` (a path under ROOT) was generated by a tool, from its own listing, or None."""
    if ctx['search']['generated']:
        return None
    name = d.rpartition('/')[2]

    def children():
        if d not in tree.listed:
            return None
        return [r[1].rpartition('/')[2] for r in tree.children(d)]
    return ignore.generated(name, children)


def _tree_of(steps: list, ctx: dict, hop: int, start: str) -> _Tree:
    holder = []
    tree = _Tree([st for st in steps if st.what == 'sls' and st.args['hop'] == hop], 'sls', paging=True, walk_skipped=False, strict_names=False,
                 start=start, prune=lambda d: d != start and _generated(holder[0], d, ctx) is not None)
    holder.append(tree)
    return tree


def _walk(tree: _Tree, ctx: dict, start: str, absolute: str) -> Visit:
    """The order of the old walk: a directory's subdirectories are judged (skipped or kept) and its files visited, then each kept subdirectory is entered
    in name order. A symbolic link is named and never followed."""
    s = ctx['search']
    out = Visit()
    private = os.path.normpath(s['private'])
    reference = os.path.normpath(s['reference']) if s['reference'] else None
    shown = lambda p: p[len(start) + 1:] if start and p != start else p
    stack = [start]
    while stack:
        d = stack.pop()
        kids = sorted(tree.children(d), key=lambda r: r[1].rpartition('/')[2])
        kept = []
        dirlike = [r for r in kids if r[0] == 'd' or (r[0] == 'l' and _points_at_directory(tree, r))]
        for r in dirlike:
            name = r[1].rpartition('/')[2]
            rel = shown(r[1])
            if r[0] == 'l':
                out.skipped.append(rel + ' (symlink)')
                continue
            here = os.path.normpath(os.path.join(absolute, rel))
            if _inside(here, private):
                out.skipped.append(rel + ' (private)')
                continue
            if not s['generated'] and reference and here == reference:
                out.skipped.append(rel + ' (reference output)')
                continue
            if _Tree._skipped(r) and not s['generated']:
                out.skipped.append(f'{rel} ({name} (a tool owns this name))')
                continue
            if r[1] in tree.partial or r[1] not in tree.listed:
                st = tree.tried.get((r[1], 'level')) or tree.tried.get((r[1], 'tree'))
                code = (st.frame['hdr'] if st is not None and st.frame is not None else {}).get('errno')
                detail = f"[Errno {code}] {os.strerror(code)}: '{name}'" if isinstance(code, int) and code else 'could not be listed'
                out.events.append(('err', f'{rel}: {detail}'))
                continue
            if proof := _generated(tree, r[1], ctx):
                out.skipped.append(f'{rel} ({proof})')
                continue
            kept.append(r[1])
        for r in (r for r in kids if r[0] in ('l', 'f') and r not in dirlike):
            if r[0] == 'l':
                out.skipped.append(shown(r[1]) + ' (symlink)')
            else:
                out.events.append(('file', r[1], shown(r[1])))
        stack.extend(reversed(kept))
    return out


def _points_at_directory(tree: _Tree, record) -> bool:
    """Does the listing itself show that a link leads to a directory? (The old walk named a link to a directory before it visited the files of the
    folder, and a link to anything else after.) A target the listing does not hold is not claimed to be anything."""
    target = os.path.normpath(os.path.join(os.path.dirname(record[1]), record[5]))
    return target in tree.records and tree.records[target][0] == 'd'


def _start_state(tree: _Tree, start: str):
    """``(kind, record)`` of the path searched, from the first call's frame: ``dir`` (listed), ``file``/``link``/``other`` (a record of its own) or
    ``None`` while nothing answered."""
    if start in tree.records:
        return {'f': 'file', 'l': 'link', 'd': 'dir'}.get(tree.records[start][0], 'other'), tree.records[start]
    if start in tree.listed or start in tree.partial:
        return 'dir', None
    return None, None


# ---------------------------------------------------------------- the matches, from the frames

@dataclass
class Found:
    """What the ``search`` steps say about the files chosen: their matches in order, what could not be searched and why, and what is still to ask."""
    records: dict = field(default_factory=dict)       # file -> [match records ['m', file, line, text]]
    failed: dict = field(default_factory=dict)        # file -> why it was not searched
    notes: dict = field(default_factory=dict)         # file -> ['s', file, size] or ['!', file, errno]
    issue: list = field(default_factory=list)         # the ``ssearch`` calls still to make (arguments)


def _page(st) -> tuple:
    return st.args['sk'], st.args['mx']


def _verified(done: dict, checks: dict, state: tuple) -> tuple:
    """A batch read as more than one page is read again where it began and where it ended: pages read at different moments of a file that was changing
    in between would otherwise be taken together. (The stub returns no identity of the file, so this is what can be known: the same questions asked
    again must be answered the same.)"""
    if len(done) < 2:
        return state
    first, last = min(done), max(k for k in done if done[k][1] or k == min(done))
    wanted = [(first, done[first][0]), (last, done[last][0])] if last != first else [(first, done[first][0])]
    missing = [(sk, mx, True) for sk, mx in wanted if (sk, mx) not in checks]
    if missing:
        return ('more', missing)
    for sk, mx in wanted:
        st = checks[(sk, mx)]
        if st.frame is None:
            return ('more', [])
        if st.frame['hdr'].get('ok') == 1:
            again = [json.loads(line) for line in st.frame['text'].split('\n') if line]
            if [r for r in again if r[0] == 'm'] != done[sk][1]:
                return ('changed',)
    return state


def _group(files: list, steps: list, size: int) -> tuple:
    """The state of one batch from the pages asked of it. A batch is read as consecutive pages ``[sk, sk + mx)`` of its matches (the ``search`` stub's SKIP and
    MAX): a page the stub says is full is followed by the next, the first page that is not full is the last. Returns ``('done', records, notes)``,
    ``('failed', why)``, ``('changed',)`` (the pages disagree: a file changed while it was searched) or ``('more', pages to ask)`` (an empty list: still waiting)."""
    done, cut, pending, bad, checks = {}, set(), set(), None, {}
    for st in sorted(steps, key=lambda x: x.s):
        key = _page(st)
        if st.args.get('check'):
            checks[key] = st
            continue
        if st.frame is None:
            pending.add(key)
            continue
        header = st.frame['hdr']
        if header.get('ok') == 1:
            records = [json.loads(line) for line in st.frame['text'].split('\n') if line]
            full = bool(records) and records[-1] == ['#']
            done.setdefault(key[0], (key[1], [r for r in records if r[0] == 'm'], [r for r in records if r[0] in ('s', '!')], full))
        elif header.get('ok') == -1:
            cut.add(key)
        else:
            why = header.get('err') or 'could not be searched'
            bad = bad or ('the search took too long' if why == 'TimeoutError' else why)
    if bad:
        return ('failed', bad)
    issued = pending | cut | {(k, v[0]) for k, v in done.items()}
    position, records, notes = 0, [], {}
    while position in done:
        mx, got, kept, full = done[position]
        if full and len(got) != mx:
            return ('changed',)                              # a full page holds exactly its size
        records += got
        for r in kept:
            notes.setdefault(r[1], r)
        if not full:
            order = [(files.index(r[1]) if r[1] in files else -1, r[2]) for r in records]
            if -1 in [o[0] for o in order] or order != sorted(set(order)) or any(sk > position and done[sk][1] for sk in done):
                return ('changed',)                          # matches out of order, twice, or past the end: the file moved under the pages
            return _verified(done, checks, ('done', records, notes))
        position += mx
    started = [k for k in pending | cut if k[0] == position]
    if any(k in pending for k in started):
        return ('more', [])
    if started:                                              # a page the harness cut: asked again as two halves
        mx = min(k[1] for k in started)
        if mx <= MATCH_MAXES[-1]:
            return ('failed', 'result too large to return')
        halves = [(position, mx // 2), (position + mx // 2, mx // 2)]
        return ('more', [h + (False,) for h in halves if h not in issued])
    end = max([k[0] + k[1] for k in issued] or [0])
    if not issued:
        return ('more', [(0, size, False)])                  # the first page alone: most searches end there
    return ('more', [(end + i * size, size, False) for i in range(PAGES)])


def _found(steps: list, chosen: list) -> Found:
    """The matches of ``chosen`` (in order) from the ``ssearch`` steps, and the calls still to make."""
    f = Found()
    by_group: dict = {}
    for st in steps:
        if st.what == 'ssearch':
            by_group.setdefault((tuple(st.args['files']), st.args['gen']), []).append(st)
    cuts = [st.args['mx'] for sts in by_group.values() for st in sts if st.frame is not None and st.frame['hdr'].get('ok') == -1]
    size = max((min(cuts) // 2, MATCH_MAXES[-1])) if cuts else MATCH_MAXES[0]

    def settle(files: list, gen: int):
        state = _group(files, by_group.get((tuple(files), gen), []), size)
        if state[0] == 'done':
            for r in state[1]:
                f.records.setdefault(r[1], []).append(r)
            f.notes.update(state[2])
        elif state[0] == 'more':
            f.issue += [{'files': files, 'gen': gen, 'sk': sk, 'mx': mx, 'check': check} for sk, mx, check in state[1]]
        elif state[0] == 'changed' and gen == 0:
            settle(files, 1)                                 # once more, from the start
        elif len(files) > 1 and state[0] == 'failed':
            settle(files[:len(files) // 2], 0)               # a batch that fails is two smaller ones
            settle(files[len(files) // 2:], 0)
        else:
            f.failed.update({rel: state[1] if state[0] == 'failed' else 'changed while it was searched' for rel in files})
    for i in range(0, len(chosen), BATCH):
        settle(chosen[i:i + BATCH], 0)
    return f


class SearchOps:
    """The search half of the engine; ``Ops`` inherits it (``_step``, ``_next``, ``_reguard``, the spill and the ledger live there)."""

    # ---------------------------------------------------------------- issuing
    def issue_search(self, session: str, shell_tool: dict, call: dict, args: dict, *, workspace_root: str | None, level: str, roots=()) -> dict:
        """Record a ``grep`` or ``glob`` and return its first primitive call: the one that lists the path searched, or one that says in cria's words
        why nothing was searched."""
        from .opspath import OpsUnavailable, split
        from .toolwire import _shell_call
        fn = call.get('function') or {}
        name = fn.get('name')
        messages = prompts.load_map('content_search_results')
        with self._lock:
            op = callauth.new_op()
            path = args.get('path') or '.'
            include = args.get('include') if args.get('include') is not None else ''
            pattern = args.get('pattern')
            ctx = {'tool': name, 'path': path if isinstance(path, str) else '.', 'shell': shell_tool, 'safe': self.safe_path, 'ws': workspace_root or '.',
                   'wsroot': workspace_root, 'level': level, 'roots': list(roots)}
            record = {'t': 'op', 'op': op, 'kind': SEARCH, 'ctx': ctx, 'call': {'id': call.get('id'), 'name': name, 'arguments': fn.get('arguments')}}
            try:
                say = self._search_refusal(messages, path, include, pattern, name, workspace_root, level, roots)
                if isinstance(say, str):
                    return self._say_answer(session, record, op, ctx, say, shell_tool)
                root, rel = say
                from . import privatepaths, webfetch
                ctx['search'] = {'pattern': pattern if name == 'grep' else '', 'include': include, 'generated': args.get('include_generated') is True,
                                 'private': str(privatepaths.CRIA_HOME),
                                 'reference': os.path.normpath(os.path.join(workspace_root, webfetch.SPILL_DIR)) if workspace_root else '',
                                 'glob': pattern if name == 'glob' else ''}
                step = self._step(op, ctx, 0, 'sls', {'wave': 0, 'hop': 0, 'root': root, 'dir': rel, 'mode': 'tree', 'rung': 0, 'after': ''})
                self.ledger.append(session, record, step[0])
            except (LedgerError, callauth.KeyUnavailable) as exc:
                raise OpsUnavailable(str(exc)) from exc
            return _shell_call(step[0]['id'], shell_tool, step[1])

    def _say_answer(self, session: str, record: dict, op: str, ctx: dict, text: str, shell_tool: dict) -> dict:
        """The search did not run: one short call prints cria's words (the harness shows what the model is told) and the ledger holds them as the final
        text. The call ran as far as the model is concerned: the outcome is ``ran``, as the old program's refusals were."""
        from .toolwire import _shell_call
        step = self._step(op, ctx, 0, 'say', {'wave': 0, 'text': text, 'ok': True})
        self.ledger.append(session, record, step[0], {'t': 'final', 'op': op, 'outcome': denial.RAN, 'text': text})
        return _shell_call(step[0]['id'], shell_tool, step[1])

    def _search_refusal(self, messages, path, include, pattern, name, workspace_root, level, roots):
        """cria's words when the search cannot run, in the order the old program decided; else ``(ROOT, REL)`` of the path to search."""
        from .opspath import split
        error = lambda detail: messages['error'].format(detail=detail) + '\n'
        if not isinstance(path, str) or not isinstance(include, str):
            return error(messages['invalid_arguments'])
        if '\x00' in path:
            return error('embedded null byte')
        expanded = os.path.expanduser(path)
        root, rel = split(expanded, workspace_root)
        abs_root = os.path.normpath(os.path.join(root, rel)) if rel else os.path.normpath(root)
        if (key := refusal_of(abs_root, level, workspace_root, roots)) is not None:
            return messages[key] + '\n'
        try:
            if not isinstance(pattern, str) or '\x00' in pattern or '\x00' in include:
                raise ValueError(messages['invalid_pattern'])
            if include:
                validate_glob(include, messages)
            if name == 'grep':
                re.compile(pattern)                              # validated here (cria never runs it); the harness's `re` runs it
            else:
                validate_glob(pattern, messages)
        except (ValueError, re.error) as exc:
            return error(str(exc))
        if len(pattern.encode('utf-8', 'surrogateescape')) + len(path.encode('utf-8', 'surrogateescape')) > COMMAND_ARG_BUDGET - _RESERVED:
            return error(prompts.render('search_too_long', limit=COMMAND_ARG_BUDGET - _RESERVED))
        return root, rel

    # ---------------------------------------------------------------- deciding
    def _s_after(self, op, wave: list, steps: list):
        what = wave[0].what
        if what in ('put', 'write'):
            return {'put': self._after_put, 'write': self._after_write}[what](op, wave, steps)
        if what == 'stat':
            return self._s_resolved(op, wave, steps)
        ctx, s = op.ctx, op.ctx['search']
        hop = max(st.args['hop'] for st in steps if st.what in ('sls', 'stat'))
        first = min((st for st in steps if st.what == 'sls' and st.args['hop'] == hop), key=lambda st: st.s)
        start, root = first.args['dir'], first.args['root']
        tree = _tree_of(steps, ctx, hop, start)
        head = first.frame['hdr'] if first.frame is not None else {}
        absolute = os.path.normpath(os.path.join(root, start)) if start else os.path.normpath(root)
        kind, rec = _start_state(tree, start)
        level = next((st for st in steps if st.what == 'sls' and st.args['hop'] == hop and st.args['dir'] == start and st.args['mode'] == 'level'), None)
        if kind is None and head.get('ok') == 0 and (head.get('errno') in (errno_.ENOENT, errno_.ENOTDIR, errno_.ELOOP)
                                                      or (level is not None and level.frame is not None and level.frame['hdr'].get('ok') == 0)):
            # The path itself could not be listed. (A failed whole-tree call may be a directory BELOW the path that could not be read: the walk then goes
            # directory by directory, and only a failure of the path's own listing is the path's.)
            return self._s_start_failed(first if level is None else level, steps, (level.frame['hdr'] if level is not None else head), absolute)
        if kind == 'link':
            if hop >= MAX_HOPS:
                return Final(denial.RAN, self._error_text(os.strerror(errno_.ELOOP)))
            return self._s_reissue(op, steps, os.path.normpath(os.path.join(os.path.dirname(absolute), rec[5])), hop + 1)
        if kind == 'other':
            return Final(denial.RAN, self._error_text(prompts.load_map('content_search_results')['not_regular']))
        # the walk -------------------------------------------------------
        issue = [('sls', {**st.args, 'rung': st.args['rung'] + 1}) for st in tree.retry]
        if kind != 'file' and len(tree.records) < MAX_ENTRIES:
            for item in tree.todo():
                d, mode, after = (item + ('',))[:3]
                issue.append(('sls', {'hop': hop, 'root': root, 'dir': d, 'mode': mode, 'rung': 0, 'after': after}))
        if issue:
            return Issue(self._next_many(steps, issue[:WAVE]))
        if kind is None:
            return Final(denial.RAN, self._error_text(absolute))
        if kind == 'file':
            visit = Visit(events=[('file', start, os.path.basename(start))])
        else:
            visit = _walk(tree, ctx, start, absolute)
            if len(tree.records) >= MAX_ENTRIES:
                visit.events.append(('err', f'{absolute}: the walk stopped after {MAX_ENTRIES:,} entries; the rest was not listed'))
        glob = ctx['tool'] == 'glob'
        chosen = [e[1] for e in visit.events if e[0] == 'file' and self._wanted(s, e[2], glob)]
        # the matches --------------------------------------------------------
        found = Found()
        if not glob:
            found = _found(steps, chosen)
            if found.issue:
                return Issue(self._next_many(steps, [('ssearch', {'root': root, **n}) for n in found.issue][:WAVE]))
            verify = self._to_verify(chosen, found, steps)
            if verify:
                return Issue(self._next_many(steps, [('sread', {'root': root, 'rel': rel}) for rel in verify][:WAVE]))
        return self._s_answer(op, visit, set(chosen), found, steps)

    @staticmethod
    def _wanted(s: dict, name: str, glob: bool) -> bool:
        """Is the file shown as ``name`` (its path from the path searched) one the call asks for: a glob matches that path, a grep's ``include`` matches it
        (a pattern with a slash) or its base name."""
        if glob:
            return match(name, s['glob'])
        include = s['include']
        return not include or match(name if '/' in include else os.path.basename(name), include)

    @staticmethod
    def _next_many(steps: list, items: list) -> tuple:
        base, wave = steps[-1].s + 1, steps[-1].args['wave'] + 1
        return tuple((base + i, what, {**args, 'wave': wave}) for i, (what, args) in enumerate(items))

    @staticmethod
    def _error_text(detail: str) -> str:
        return prompts.load_map('content_search_results')['error'].format(detail=detail) + '\n'

    def _s_start_failed(self, first, steps, header: dict, absolute: str):
        """The path searched could not be listed. A link in its directory path is resolved by cria (which stats each prefix), anything else is said."""
        code, args = header.get('errno'), first.args
        parts = [p for p in args['dir'].split('/') if p]
        if code in (errno_.ELOOP, errno_.ENOTDIR) and len(parts) > 1:
            if args['hop'] >= MAX_HOPS:
                return Final(denial.RAN, self._error_text(os.strerror(errno_.ELOOP)))
            prefix, prefixes = '', []
            for part in parts[:-1]:
                prefix = f'{prefix}/{part}' if prefix else part
                prefixes.append(prefix)
            return Issue(self._next_many(steps, [('stat', {**args, 'rel': p, 'errno': code, 'at': i, 'full': args['dir']}) for i, p in enumerate(prefixes)]))
        if code == errno_.EACCES:
            return Final(denial.RAN, prompts.load_map('content_search_results')['errors'].format(
                paths=f"[Errno {code}] {os.strerror(code)}: '{absolute}'") + '\n')
        return Final(denial.RAN, self._error_text(absolute))

    def _s_resolved(self, op, wave: list, steps: list):
        """Each prefix of the path was statted, all in one reply: the first that is a link is resolved by cria and judged by the guards that judged the
        path the model named, then the walk starts again from where it leads."""
        for st in sorted(wave, key=lambda x: x.args['at']):
            header, args = st.frame['hdr'], st.args
            whole = os.path.normpath(os.path.join(args['root'], args['full']))
            if header.get('ok') != 1:
                return Final(denial.RAN, self._error_text(whole))
            records = [json.loads(line) for line in st.frame['text'].split('\n') if line]
            if not records or records[0][1] != args['rel']:
                continue                                           # a directory: the walk went through it
            if records[0][0] != 'l':
                return Final(denial.RAN, self._error_text(whole))
            here = os.path.join(args['root'], args['rel'])
            tail = [p for p in args['full'].split('/') if p][args['at'] + 1:]
            return self._s_reissue(op, steps, os.path.normpath(os.path.join(os.path.dirname(here), records[0][5], *tail)), args['hop'] + 1)
        return Final(denial.RAN, self._error_text(os.strerror(wave[0].args['errno'])))

    def _s_reissue(self, op, steps: list, resolved: str, hop: int):
        """Start the walk again at ``resolved`` (a link was followed by cria itself) after the guards have judged where it leads."""
        from .opspath import split
        ctx = op.ctx
        if (key := refusal_of(resolved, ctx['level'], ctx.get('wsroot'), ctx['roots'])) is not None:
            return Final(denial.RAN, prompts.load_map('content_search_results')[key] + '\n')
        if (refusal := self._reguard(resolved, ctx)):
            return Final(denial.REFUSED, denial.mark(refusal))
        root, rel = split(resolved, ctx.get('wsroot'))
        return Issue(self._next_many(steps, [('sls', {'hop': hop, 'root': root, 'dir': rel, 'mode': 'tree', 'rung': 0, 'after': ''})]))

    @staticmethod
    def _to_verify(chosen: list, found: Found, steps: list) -> list:
        """The files whose last match is an empty line: the stub splits the text on line feeds, so a file that ends with one has an empty "line" after
        it that a pattern matching nothing (``^$``, ``x*``) matches. Whether the file has that line is what its own line count says."""
        asked = {st.args['rel'] for st in steps if st.what == 'sread'}
        return [rel for rel in chosen if rel in found.records and found.records[rel][-1][3] == '' and rel not in asked]

    # ---------------------------------------------------------------- what the model reads
    def _s_answer(self, op, visit: Visit, chosen: set, found: Found, steps: list):
        """The words the model reads, as the old program printed them: a line per match or name, then what was not searched, then what could not be
        read (or ``No matches.``)."""
        messages = prompts.load_map('content_search_results')
        lines, errors, matches = [], [], 0
        counts = {st.args['rel']: st.frame['hdr'].get('ln') for st in steps if st.what == 'sread' and st.frame is not None and st.frame['hdr'].get('ok') == 1}
        for event in visit.events:
            if event[0] == 'err':
                errors.append(event[1])
                continue
            _, rel, name = event
            if rel not in chosen:
                continue
            if op.ctx['tool'] == 'glob':
                lines.append(name)
                matches += 1
                continue
            if rel in found.failed:
                errors.append(f'{name}: {found.failed[rel]}')
                continue
            note = found.notes.get(rel)
            if note and note[0] == 's':
                errors.append(f'{name}: too large to search ({note[2]:,} bytes)')
                continue
            if note and note[0] == '!':
                code = note[2]
                errors.append(f"{name}: [Errno {code}] {os.strerror(code)}: '{os.path.basename(rel)}'" if isinstance(code, int) and code else f'{name}: could not be read')
                continue
            records = list(found.records.get(rel, ()))
            if records and records[-1][3] == '' and counts.get(rel) is not None and records[-1][2] > counts[rel]:
                records.pop()                         # the empty "line" after the last line feed: the file has no such line
            for r in records:
                try:
                    r[3].encode('utf-8')
                except UnicodeEncodeError:            # a line that is not UTF-8: the file is not text, said as the old program said it
                    try:
                        (r[3].encode('utf-8', 'surrogateescape') + b'\n').decode('utf-8')
                    except UnicodeDecodeError as exc:
                        errors.append(f'{name}: {exc}')
                    break
                lines.append(f'{name}:{r[2]}:{r[3]}')
                matches += 1
        text = ''.join(line + '\n' for line in lines)
        if visit.skipped:
            text += messages['skipped'].format(paths='\n'.join(visit.skipped)) + '\n'
        if errors:
            text += messages['errors'].format(paths='\n'.join(errors)) + '\n'
        elif not matches:
            text += messages['none'] + '\n'
        return self._s_finish(op, steps, text, bool(errors))

    def _s_finish(self, op, steps: list, text: str, failed: bool):
        """The answer, whole when the harness returns it whole; else saved whole and pointed to."""
        from . import webfetch
        data = text.encode('utf-8', 'surrogateescape')
        if externalization.stdout_size(data) <= externalization.STDOUT_MAX_BYTES:
            return Final(denial.RAN, text)
        target = f'{webfetch.SPILL_DIR}/stdout-{hashlib.sha256(data).hexdigest()}.txt'
        pointer = prompts.render('content_search_spill_failed' if failed else 'content_search_spill', target=target)
        return self._spill_issue(op, steps, text, pointer, target.removeprefix('./'))

    def _search_final(self, op, how: str, st):
        """How a search whose result was saved ended: ``landed`` (the pointer is true), ``unknown`` or ``failed``."""
        if how == 'landed':
            return Final(denial.RAN, op.blobs[st.args['ans']])
        if how == 'unknown':
            return Final(denial.UNKNOWN, prompts.render('answer_unknown', target='./' + st.args['rel']))
        return Final(denial.REFUSED, prompts.load('stdout_spill_failed') + ' ' + _reason(st.frame['hdr']))
