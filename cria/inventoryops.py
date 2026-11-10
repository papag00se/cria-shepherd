"""The initial workspace inventory through the harness primitives (docs/harness-primitives.md 8.9; docs/harness-programs.md section 7, phase 6).

One operation in the ledger that cria asks before the first coder turn and answers to nobody. Every decision is made here:

* the files are ``ls`` (the survey's walk: the whole tree in one call when it fits one frame, else directory by directory with the
  ``AFTER`` cursor for a directory a frame does not hold). The excluded directories (``groundtruth._INVENTORY_EXCLUDE``) are
  reported by ``ls`` and never entered; a link is a link (listed under ``symlinks``, never followed); anything that is not a regular
  file is not a file; a directory the harness could not read is an ``errors`` entry.
* what a file is - empty or whitespace-only text (``blank``), or not text at all (``None``) - and its ``digest`` are decided in cria from
  the bytes ``read`` returns: the first ``FACT_LEN`` bytes decide any file with something in them, a file whose first bytes are only
  whitespace is read whole. The sha-256 is the harness's own, of the whole file. This is what the unread-write rule stands on (a blank
  file may be overwritten unread, a file that is not may not), so it is gathered for the first ``FACT_FILES_MAX`` files in path order and
  is ``None`` for the rest (never guessed).
* the symbols are the real ``ctags`` run through the ``run`` stub on the files cria chose (shell text, no program): names, kinds and
  scopes, one list per file, ``None`` where the indexer gave nothing, one uniform error where it is missing or failed.

What it learned is the dictionary the loop has always been given (``files``, ``symlinks``, ``errors``, ``excluded_names``,
``symbol_indexer_error``), computed from the frames the ledger holds: a pure function of the ledger.
"""
import codecs
import hashlib
import json
import os
import shlex
import time

from . import callauth, denial, groundtruth, harnessprims
from .opsteps import Final, Issue
from .readops import LEN_FLOOR, merge
from .surveyops import INVENTORY, LEVEL_MAXES, TREE_MAX, WAVE, _Tree, _clean

WHATS = ('ils', 'iread', 'irun', 'iout', 'irm')
FACT_LEN = 512            # bytes of a file that decide whether it is text with something in it
FACT_FULL = 1 << 20       # a file whose first bytes are only whitespace is read this far (whitespace compresses to nothing)
FACT_FILES_MAX = 400      # files whose blank state and digest are gathered (path order); the rest are unknown, never guessed
FACT_FLOOR = 64           # a read the harness cut is asked again at half the length, down to this
MAX_ENTRIES = 20_000      # entries the walk takes before it says it stopped
CTAGS_NAMES = 20_000      # bytes of file names one ctags run is given
CTAGS_TIMEOUT = 300       # seconds one ctags run may take
CTAGS_WAIT = 8
CTAGS_WAITS = 40
SAFE_CTAGS = ('/usr/bin/ctags', '/bin/ctags', '/usr/local/bin/ctags')
NOT_FOUND = 'indexer not found'


def skip_names() -> list:
    return sorted(groundtruth._INVENTORY_EXCLUDE)


def _token(op: str, i: int) -> str:
    return hashlib.sha256((callauth.group(op) + 'ctags' + str(i)).encode()).hexdigest()[:20]


def ctags_script(names: list) -> str:
    """The shell text the ``run`` stub runs to index ``names`` (one per line, relative to the working directory): the real Universal
    Ctags by absolute path, with no environment and no option file, asked for the names, kinds and scopes of what it finds, in source
    order. Its first output line says whether it was there (``I\\tok`` / ``I\\tmissing``). Nothing is decided here."""
    found = ' '.join(shlex.quote(c) for c in SAFE_CTAGS)
    terminator = 'CTX_NAMES_' + hashlib.sha256('\n'.join(names).encode('utf-8', 'surrogateescape')).hexdigest()[:12]
    return (f'for c in {found}; do [ -x "$c" ] && b=$c && break; done\n'
            'v=$([ -n "$b" ] && /usr/bin/env -i "$b" --version 2>/dev/null)\n'
            'case $v in "Universal Ctags"*) ;; *) printf \'I\\tmissing\\n\'; exit 0;; esac\n'
            'printf \'I\\tok\\n\'\n'
            '/usr/bin/env -i "$b" --options=NONE --output-format=json --pattern-length-limit=1 --sort=no -f - -L - '
            f"<<'{terminator}'\n" + '\n'.join(names) + f'\n{terminator}\n')


def _indexable(rel: str) -> bool:
    return _clean(rel)


def _chunks(files: list) -> list:
    out, cur, size = [], [], 0
    for rel in files:
        width = len(rel.encode('utf-8')) + 1
        if cur and size + width > CTAGS_NAMES:
            out.append(cur)
            cur, size = [], 0
        cur.append(rel)
        size += width
    return out + ([cur] if cur else [])


def command(op: str, ctx: dict, s: int, what: str, args: dict, blobs: dict) -> str:
    """The harness command of step ``s``: a pure function of what the ledger recorded (a retried request composes the same bytes)."""
    nonce, safe = callauth.nonce(op, s), ctx['safe']
    if what == 'ils':
        tree = args['mode'] == 'tree'
        words = [ctx['root'], args['dir'], 0 if tree else 1, min(TREE_MAX, MAX_ENTRIES) if tree else LEVEL_MAXES[args['rung']], 0,
                 json.dumps(skip_names(), separators=(',', ':')), os.fsencode(args.get('after', '')).hex()]
        return harnessprims.compose('ls', nonce, words, comment='workspace inventory ' + (args['dir'] or '.'), safe_path=safe)
    if what == 'iread':
        return harnessprims.compose('read', nonce, [ctx['root'], args['rel'], 0, args['len'], 0],
                                    comment='workspace inventory ' + args['rel'], safe_path=safe)
    if what == 'iout':
        return harnessprims.compose('read', nonce, [args['dir'], 'out', args['off'], args['len'], 0],
                                    comment='workspace inventory (symbols)', safe_path=safe)
    if what == 'irm':
        parent, _, name = args['dir'].rpartition('/')
        return harnessprims.compose('rm', nonce, [parent or '/', name, 't', '*'], comment='workspace inventory', safe_path=safe)
    text = ctags_script(args['names']) if args['mode'] == 'start' else None
    return harnessprims.compose('run', nonce, [args['mode'], harnessprims.TMPDIR, _token(op, args['chunk']), CTAGS_TIMEOUT, CTAGS_WAIT,
                                               ctx['root'], 0], text=text, comment='workspace inventory (symbols)', safe_path=safe)


def _bytes(frame: dict) -> bytes:
    return frame['text'].encode('utf-8', 'surrogateescape')


def _error(code) -> str:
    return f'[Errno {code}] {os.strerror(code)}' if isinstance(code, int) and code else 'unreadable'


class _Facts:
    """What the file reads say, folded in step order."""

    def __init__(self, steps: list):
        self.first: dict = {}       # rel -> (header, bytes) of the first read
        self.whole: dict = {}       # rel -> (header, bytes) of the whole-file read
        self.error: dict = {}       # rel -> the header of a read that failed
        self.cut: dict = {}         # rel -> how many first reads of it the harness cut
        self.cut_whole: set = set() # files whose whole-file read the harness cut (their blank state stays unknown)
        for st in sorted((x for x in steps if x.what == 'iread' and x.frame is not None), key=lambda x: x.s):
            rel, header = st.args['rel'], st.frame['hdr']
            if header.get('ok') == 1:
                (self.whole if st.args['len'] > FACT_LEN else self.first)[rel] = (header, _bytes(st.frame))
            elif header.get('ok') == 0:
                self.error[rel] = header
            elif st.args['len'] > FACT_LEN:
                self.cut_whole.add(rel)
            else:
                self.cut[rel] = self.cut.get(rel, 0) + 1

    def of(self, rel: str) -> tuple:
        """``(blank, digest, error, needs the whole file)`` for a file: blank is True/False for text, None for anything else."""
        if rel in self.error:
            header = self.error[rel]
            return None, None, None if header.get('err') == 'notfile' else _error(header.get('errno')), False
        got = self.whole.get(rel) or self.first.get(rel)
        if got is None:
            return None, None, None, False
        header, data = got
        if header['fsize'] != header['size']:
            return None, None, 'file changed during survey', False
        complete = len(data) >= header['fsize']
        if b'\0' in data:
            return None, None, None, False                                    # binary
        try:
            text = codecs.getincrementaldecoder('utf-8')('strict').decode(data, final=complete)
        except UnicodeError:
            return None, None, None, False                                    # not UTF-8
        blank = not text or text.isspace()
        if blank and not complete:
            return None, None, None, rel not in self.whole                    # only whitespace so far: the rest decides (once)
        return blank, header['fsha'], None, False


class InventoryOps:
    """The inventory half of the engine; ``Ops`` inherits it (``_step``, ``_length`` and the ledger live there)."""

    # ---------------------------------------------------------------- issuing
    def issue_inventory(self, session: str, shell_tool: dict, root: str) -> tuple:
        """Record an inventory and return ``(operation, its first primitive calls)``."""
        from .ledger import LedgerError
        from .opspath import OpsUnavailable
        from .toolwire import _shell_call
        with self._lock:
            op = callauth.new_op()
            ctx = {'shell': shell_tool, 'safe': self.safe_path, 'root': root, 'ws': root, 'wsroot': root}
            record = {'t': 'op', 'op': op, 'kind': INVENTORY, 'ctx': ctx, 'call': {}}
            try:
                built = self._step(op, ctx, 0, 'ils', {'wave': 0, 'dir': '', 'mode': 'tree', 'rung': 0})
                self.ledger.append(session, record, built[0])
            except (LedgerError, callauth.KeyUnavailable) as exc:
                raise OpsUnavailable(str(exc)) from exc
            return op, [_shell_call(built[0]['id'], shell_tool, built[1])]

    # ---------------------------------------------------------------- deciding
    @staticmethod
    def _tree(steps: list) -> _Tree:
        return _Tree(steps, 'ils', paging=True, walk_skipped=False, strict_names=False)

    def _i_after(self, op, steps: list):
        tree = self._tree(steps)
        issue = []
        issue += [('ils', {**st.args, 'rung': st.args['rung'] + 1}) for st in tree.retry]      # a frame the harness cut: the same page, asked smaller
        if len(tree.records) < MAX_ENTRIES:
            for item in tree.todo():
                d, mode, after = (item + ('',))[:3]
                issue.append(('ils', {'dir': d, 'mode': mode, 'rung': 0, 'after': after}))
        if issue:
            return Issue(self._next_many(steps, issue[:WAVE]))
        names = sorted(self._files(tree))
        # the facts -------------------------------------------------------
        facts = _Facts(steps)
        for rel in names[:FACT_FILES_MAX]:
            if rel in facts.error or rel in facts.whole or rel in facts.cut_whole:
                continue
            if rel in facts.first:
                if facts.of(rel)[3]:
                    issue.append(('iread', {'rel': rel, 'len': min(FACT_FULL, facts.first[rel][0]['fsize'])}))
            elif FACT_LEN >> facts.cut.get(rel, 0) >= FACT_FLOOR:
                issue.append(('iread', {'rel': rel, 'len': FACT_LEN >> facts.cut.get(rel, 0)}))
        # the symbols ----------------------------------------------------------
        runs = {st.args['chunk']: st for st in sorted((x for x in steps if x.what == 'irun'), key=lambda x: x.s)}
        for i, chunk in enumerate(_chunks([rel for rel in names if _indexable(rel)])):
            st = runs.get(i)
            if st is None:
                issue.append(('irun', {'mode': 'start', 'chunk': i, 'n': 1, 'names': chunk}))
                continue
            header = st.frame['hdr'] if st.frame is not None else {}
            if header.get('ok') == 1 and header.get('state') == 'running' and st.args['n'] <= CTAGS_WAITS:
                issue.append(('irun', {'mode': 'wait', 'chunk': i, 'n': st.args['n'] + 1, 'names': chunk}))
            elif header.get('ok') == 1 and header.get('state') == 'done' and not header.get('removed'):
                issue += self._i_output(i, header, steps)
        if issue:
            return Issue(self._next_many(steps, issue[:WAVE]))
        return Final(denial.RAN, '', {'observed_at': time.time()})

    @staticmethod
    def _next_many(steps: list, items: list) -> tuple:
        base, wave = steps[-1].s + 1, steps[-1].args['wave'] + 1
        return tuple((base + i, what, {**args, 'wave': wave}) for i, (what, args) in enumerate(items))

    def _i_output(self, i: int, header: dict, steps: list) -> list:
        """What a ctags run's output still needs: the pages of its ``out`` file beyond what the frame held (read by cria, asked smaller
        after each one the harness cut), then the removal of its directory."""
        pages = [st for st in steps if st.what == 'iout' and st.args['chunk'] == i and st.frame is not None]
        cut = sum(1 for st in pages if st.frame['hdr'].get('ok') == -1)
        length = self._length(cut)
        if cut and length <= LEN_FLOOR:
            return []
        run = max((st for st in steps if st.what == 'irun' and st.args['chunk'] == i), key=lambda x: x.s)
        got = [(0, _bytes(run.frame))] + [(st.args['off'], _bytes(st.frame)) for st in pages if st.frame['hdr'].get('ok') == 1]
        _, ranges = merge(got)
        gaps, pos = [], 0
        for a, b in ranges:
            if a > pos:
                gaps.append((pos, a))
            pos = max(pos, b)
        if pos < header['size']:
            gaps.append((pos, header['size']))
        wanted = [off for a, b in gaps for off in range(a, b, length)]
        if wanted:
            return [('iout', {'chunk': i, 'dir': header['dir'], 'off': off, 'len': length}) for off in wanted]
        return [] if any(st.what == 'irm' and st.args['chunk'] == i for st in steps) else [('irm', {'chunk': i, 'dir': header['dir']})]

    # ---------------------------------------------------------------- what the inventory learned
    @staticmethod
    def _files(tree: _Tree) -> dict:
        return {p: r[2] for p, r in tree.records.items() if r[0] == 'f'}

    def _data(self, op, steps: list, observed_at: float) -> dict:
        tree = self._tree(steps)
        files = self._files(tree)
        links = sorted(p for p, r in tree.records.items() if r[0] == 'l')
        errors = []
        for d in sorted(tree.partial | {d for d in tree.failed_tree if (d, 'level') in tree.tried and d not in tree.listed}):
            st = tree.tried.get((d, 'level')) or tree.tried.get((d, 'tree'))
            header = st.frame['hdr'] if st is not None and st.frame is not None else {}
            errors.append({'path': d or '.', 'error': f"{_error(header.get('errno'))}: '{d.rpartition('/')[2] or '.'}'" if header.get('ok') == 0
                           else 'could not be listed'})
        if len(tree.records) >= MAX_ENTRIES:
            errors.append({'path': '.', 'error': 'inventory bound reached: the rest is not listed'})
        names = sorted(files)
        facts = _Facts(steps)
        tags, indexer = self._symbols(steps, [rel for rel in names if _indexable(rel)])
        items = []
        for k, rel in enumerate(names):
            item = {'path': rel, 'size': files[rel], 'symbols': tags.get(rel), 'blank': None, 'observed_at': observed_at}
            if k < FACT_FILES_MAX:
                blank, digest, error, _more = facts.of(rel)
                if error:
                    errors.append({'path': rel, 'error': error})
                item['blank'] = blank
                if blank is not None:
                    item['digest'] = digest
                else:
                    item['symbols'] = None          # not text (or unreadable): never indexed, as before
            items.append(item)
        return {'files': items, 'symlinks': links, 'errors': errors,
                'excluded_names': [n for n in skip_names() if 'cria' not in n.lower()], 'symbol_indexer_error': indexer}

    @staticmethod
    def _symbols(steps: list, names: list) -> tuple:
        """``({path: [{name, kind, scope}...]}, error)`` from the ctags runs' output, read in this process (a path with no tag is absent)."""
        chunks = _chunks(names)
        tags, error = {}, None
        runs = {st.args['chunk']: st for st in sorted((x for x in steps if x.what == 'irun'), key=lambda x: x.s)}
        for i in range(len(chunks)):
            st = runs.get(i)
            header = st.frame['hdr'] if st is not None and st.frame is not None else {}
            if header.get('ok') != 1 or header.get('state') != 'done' or header.get('exit') != 0 or header.get('timeout'):
                error = error or 'indexer failed: ' + ('TimeoutError' if header.get('timeout') or header.get('state') == 'running' else 'OSError')
                continue
            data = _bytes(st.frame)
            if header['size'] > len(data):
                pages = [(0, data)] + [(p.args['off'], _bytes(p.frame)) for p in steps if p.what == 'iout' and p.args['chunk'] == i
                                       and p.frame is not None and p.frame['hdr'].get('ok') == 1]
                data, _ = merge(pages)
                data = data[:header['size']]
                if len(data) < header['size'] or hashlib.sha256(data).hexdigest() != header.get('osha'):
                    error = error or 'indexer failed: OSError'
                    continue
            lines = data.decode('utf-8', 'replace').split('\n')
            if lines[0] == 'I\tmissing':
                error = error or NOT_FOUND
                continue
            for line in lines[1:]:
                if not line.startswith('{'):
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(record, dict) and record.get('_type') == 'tag' and isinstance(record.get('name'), str)
                        and isinstance(record.get('kind'), str) and isinstance(record.get('path'), str)):
                    tags.setdefault(record['path'], []).append({k: record[k] for k in ('name', 'kind', 'scope') if isinstance(record.get(k), str)})
        return tags, error

    def inventory_of(self, session: str, op_id: str) -> dict | None:
        """The inventory of a finished operation (None while it runs, or when there is none), computed from its frames."""
        op = self.ledger.ops(session).get(op_id)
        if op is None or op.kind != INVENTORY or op.final is None:
            return None
        if op_id not in self._inventories:
            steps = sorted(op.steps.values(), key=lambda x: x.s)
            tree = self._tree(steps)
            # A walk that never saw the workspace's root (the harness refused, or nothing answered) is no inventory: the first coder turn goes
            # without one, as it always did when the inventory could not run.
            self._inventories[op_id] = (self._data(op, steps, op.final.get('observed_at') or time.time())
                                        if '' in tree.listed or '' in tree.folded else None)
            while len(self._inventories) > 8:
                self._inventories.pop(next(iter(self._inventories)))
        return self._inventories[op_id]
