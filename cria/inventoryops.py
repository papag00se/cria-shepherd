"""The initial workspace inventory through the harness primitives (docs/harness-primitives.md 8.9; docs/harness-programs.md section 7, phase 6).

One operation in the ledger that cria asks before the first coder turn and answers to nobody. Every decision is made here:

* the files are ``ls`` (the survey's walk: the whole tree in one call when it fits one frame, else directory by directory with the
  ``AFTER`` cursor for a directory a frame does not hold). The excluded directories (``groundtruth._INVENTORY_EXCLUDE``) are
  reported by ``ls`` and never entered; a link is a link (listed under ``symlinks``, never followed); anything that is not a regular
  file is not a file; a directory the harness could not read is an ``errors`` entry.
* what a file *is* (empty or whitespace-only text, something, or not text) and its hash are NOT gathered here: a file read per file is a call per file
  in the harness's transcript (a 2,500-file tree was 160 calls, 455 KB of commands, against 43 calls and 60 KB before). The unread-write rule asks the
  file when a write names it and nothing known settles it (:mod:`cria.probeops`), so every item carries ``blank: None`` here, never guessed.
* the symbols are the real ``ctags`` run through the ``run`` stub on the files cria chose (shell text, no program): names, kinds and
  scopes, one list per file, ``None`` where the indexer gave nothing, one uniform error where it is missing or failed. cria chooses
  BEFORE it runs ctags, from the size and the name ``ls`` already gave it: a data file (``DATA_SUFFIXES``: ctags emits a tag per key of a
  JSON, YAML or TOML document, which are not starting points; an 8 MB ``tokenizer.json`` was 79 MB of output, 3,464 calls and 218 s) and a file over
  ``[harness] symbols_max_file_bytes`` are not handed to it. A file's symbol list is ALL OR NOTHING (the model is never shown part of a list):
  one with more than ``symbols_max_per_file`` symbols, and every file whose output lies beyond the ``symbols_max_output_bytes`` that one inventory
  reads back (chunks and files in path order, so the same tree gives the same answer), has ``symbols: None``, the convention the inventory
  already states for "unavailable or no tags returned". The inventory text carries no label for it.

What it learned is the dictionary the loop has always been given (``files``, ``symlinks``, ``errors``, ``excluded_names``,
``symbol_indexer_error``), computed from the frames the ledger holds: a pure function of the ledger.
"""
import hashlib
import json
import os
import shlex
import time

from . import callauth, denial, groundtruth, harnessprims
from .config import HarnessConfig
from .opsteps import Final, Issue
from .readops import LEN_FLOOR
from .readfacts import error as _error
from .surveyops import INVENTORY, LEVEL_MAXES, TREE_MAX, WAVE, _Tree, _clean

WHATS = ('ils', 'irun', 'iout', 'irm')
CTAGS_OUTPUT = ('irun', 'iout')     # the steps whose frames hold ctags output: recorded condensed (`condense`), never as the page
MAX_ENTRIES = 20_000      # entries the walk takes before it says it stopped
CTAGS_NAMES = 20_000      # bytes of file names one ctags run is given
CTAGS_TIMEOUT = 300       # seconds one ctags run may take
CTAGS_WAIT = 8
CTAGS_WAITS = 40
HEAD_BYTES = 6000         # what the `run` stub answers of a finished run's output in its own frame (the first page of the output)
PAGE_BYTES = 16_000       # raw bytes one `read` of the output asks for (a fixed number: where the reading stops must not depend on what was learned)
SAFE_CTAGS = ('/usr/bin/ctags', '/bin/ctags', '/usr/local/bin/ctags')
NOT_FOUND = 'indexer not found'
# Universal Ctags 6.2.1's libxml2/XPath parsers (measured: the only ones of its 164 languages killed by the `--_interactive=sandbox` seccomp
# filter, SIGSYS, on any input: libxml2 2.15's one-time setup calls getrandom, which the filter does not allow). The indexer is never run in
# that mode (it takes file contents over a protocol, not a name list), but its XML symbols are also the least useful ones (generated `nsprefix`
# names, every `id` of an SVG) and parsing untrusted XML is the parsers' attack surface, so they are never asked for.
XML_PARSERS = ('Ant', 'DBusIntrospect', 'Glade', 'Maven2', 'PlistXML', 'RelaxNG', 'SVG', 'XML', 'XRC', 'XSLT')
# Parsers whose tags are not what the inventory lists (headings of a document, keys and sections of a data file, hunks of a patch): never asked for.
DOC_PARSERS = ('Markdown', 'ReStructuredText', 'Asciidoc', 'Iniconf', 'JSON', 'Yaml', 'TOML', 'Diff', 'Tex')
# Per language, the kinds the inventory lists (long names: classes, functions, methods, types; `ctags --list-kinds-full=<language>`). ctags takes no
# kind list for all languages (`--kinds-all` accepts only `*`), so the languages most projects are written in are named and every other language
# keeps its own default kinds.
KINDS = ('Python=cfm', 'Go=fist', 'Rust=Pfgist', 'JavaScript=cfmg', 'TypeScript=acfgim', 'Ruby=cfmS', 'Java=cgim', 'C=fgstu', 'C++=cfgstu',
         'C#=cgimst', 'PHP=cfit', 'Kotlin=Tcimo')


# What ctags cannot usefully index: tags that are the keys of a data document, and generated or minified output (docs/harness-programs.md, "The
# ctags inventory's bound"). By name only: a data file with an unusual name is left to the size and symbol limits.
DATA_SUFFIXES = ('.json', '.jsonc', '.json5', '.jsonl', '.ndjson', '.geojson', '.yaml', '.yml', '.toml', '.csv', '.tsv', '.lock', '.ini', '.conf', '.cfg',
                 '.properties', '.map', '.min.js', '.min.mjs', '.min.css')


def limits_of(harness: HarnessConfig) -> dict:
    return {'file_bytes': harness.symbols_max_file_bytes, 'symbols': harness.symbols_max_per_file, 'output_bytes': harness.symbols_max_output_bytes,
            'tokens': harness.symbols_budget_tokens}


DEFAULT_LIMITS = limits_of(HarnessConfig())


def skip_names() -> list:
    return sorted(groundtruth._INVENTORY_EXCLUDE)


def _token(op: str, i: int) -> str:
    return hashlib.sha256((callauth.group(op) + 'ctags' + str(i)).encode()).hexdigest()[:20]


def ctags_script(names: list) -> str:
    """The shell text the ``run`` stub runs to index ``names`` (one per line, relative to the working directory): the real Universal
    Ctags by absolute path, with no environment but a temporary directory and no option file, without its XML-family parsers
    (``XML_PARSERS``), asked for the names, long-form kinds and scopes of the classes, functions, methods and types it finds (the terse one-line-per-tag format:
    ``name<TAB>path<TAB>line;"<TAB>kind[<TAB>scopekind:scope]``, no pattern, no other field), in source order. The temporary directory is this script's
    own run directory (``${0%/*}``, removed by the ``run`` stub's cleanup): ``-f -`` still makes a temporary file, and ``/tmp`` is read-only
    in a sandboxed harness (without it the indexer failed in the Codex sandbox). Its first output line says whether it was there
    (``I\\tok`` / ``I\\tmissing``). Nothing is decided here."""
    found = ' '.join(shlex.quote(c) for c in SAFE_CTAGS)
    terminator = 'CTX_NAMES_' + hashlib.sha256('\n'.join(names).encode('utf-8', 'surrogateescape')).hexdigest()[:12]
    return (f'for c in {found}; do [ -x "$c" ] && b=$c && break; done\n'
            'v=$([ -n "$b" ] && /usr/bin/env -i "$b" --version 2>/dev/null)\n'
            'case $v in "Universal Ctags"*) ;; *) printf \'I\\tmissing\\n\'; exit 0;; esac\n'
            'printf \'I\\tok\\n\'\n'
            '/usr/bin/env -i "TMPDIR=${0%/*}" "$b" --options=NONE --output-format=u-ctags --sort=no --excmd=number --fields=-k+K-t-f-T '
            + ' '.join('--kinds-' + k for k in KINDS) + f" --languages={','.join('-' + p for p in XML_PARSERS + DOC_PARSERS)} -f - -L - "
            f"<<'{terminator}'\n" + '\n'.join(names) + f'\n{terminator}\n')


def _indexable(rel: str, size: int, limits: dict) -> bool:
    """Whether ctags is handed this file: a name it can carry, not a data file, not over the size limit (decided from what ``ls`` said)."""
    return _clean(rel) and size <= limits['file_bytes'] and not rel.lower().endswith(DATA_SUFFIXES)


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


def _limits(ctx: dict) -> dict:
    """The limits the operation was issued with (recorded in its ledger, so a restarted cria decides what the first process did); an
    operation recorded before they existed has the defaults."""
    return ctx.get('limits') or DEFAULT_LIMITS


def _indexable_names(files: dict, ctx: dict) -> list:
    """The files ctags is handed, in path order: the order every bound below is applied in."""
    limits = _limits(ctx)
    return [rel for rel in sorted(files) if _indexable(rel, files[rel], limits)]


def _runs(steps: list) -> dict:
    """chunk -> the latest ctags run step for it."""
    return {st.args['chunk']: st for st in sorted((x for x in steps if x.what == 'irun'), key=lambda x: x.s)}


def _rooms(steps: list, count: int, budget: int) -> list:
    """Per chunk, how many bytes of its run's output this inventory reads: the run's own size, as far as the budget of the whole inventory
    reaches when the chunks are taken in order (so the same tree always gives the same answer), never less than the first frame the run
    answered with (it comes with the run) while any budget is left, and 0 when none is. 0 for a run that failed (nothing in its output is
    used); None for a chunk that comes after a run still going (the budget it will find is not known yet)."""
    runs, left, rooms, known = _runs(steps), budget, [], True
    for i in range(count):
        st = runs.get(i)
        header = st.frame['hdr'] if st is not None and st.frame is not None else {}
        if header.get('ok') == 1 and header.get('state') == 'done':
            if header.get('exit') != 0 or header.get('timeout') or left <= 0:
                room = 0
            else:
                room = max(min(header['size'], left), header.get('head') or 0)
        elif header.get('ok') == 1 and header.get('state') == 'running' and st.args['n'] <= CTAGS_WAITS or st is None or st.frame is None:
            known, room = False, None
        else:
            room = 0
        rooms.append(room if known else None)
        left -= room or 0
    return rooms


# ---------------------------------------------------------------- what the ledger keeps of ctags output
# The ledger holds the harness's answers (an append-only file per session). A ctags output is paged back through `read` and can be megabytes of text
# nobody reads twice: what is recorded of each page is what cria decides from, in a few bytes per symbol: the tags of its whole lines (path, name, kind,
# scope, grouped by path), and the two broken lines at its ends (the end of the line the previous page began, the start of the line the next one ends),
# which are joined with their neighbours when the pages are put together. The line numbers and the pattern, and the page itself, are not kept.

def _tag(line: str):
    """``(path, name, kind, scope)`` of one line of ctags's terse format, else None."""
    f = line.split('\t')
    if len(f) < 4 or not f[2].endswith(';"') or not f[0] or not f[1] or not f[3]:
        return None
    return f[1], f[0], f[3], f[4].partition(':')[2] if len(f) > 4 and ':' in f[4] else ''


def condense(data: bytes) -> str:
    """What the ledger records of one page of a ctags output (JSON text: ``h`` the page's first line, to its end if it ends there or the whole
    page, ``t`` the text after its last line break, ``g`` the tags of the lines between as ``[path, ["name<TAB>kind[<TAB>scope]", ...]]``, ``n`` whether
    the page holds a line break)."""
    text = data.decode('utf-8', 'surrogateescape')
    if not text:
        return ''
    first, last = text.find('\n'), text.rfind('\n')
    if first < 0:
        return json.dumps({'h': text, 'n': 0}, separators=(',', ':'))
    groups = []
    for line in text[first + 1:last].split('\n') if last > first else ():
        tag = _tag(line)
        if tag is None:
            continue
        entry = '\t'.join((tag[1], tag[2], tag[3]) if tag[3] else (tag[1], tag[2]))
        if groups and groups[-1][0] == tag[0]:
            groups[-1][1].append(entry)
        else:
            groups.append([tag[0], [entry]])
    return json.dumps({'h': text[:first], 't': text[last + 1:], 'g': groups, 'n': 1}, separators=(',', ':'))


def _page(st) -> dict | None:
    if st.frame is None or st.frame['hdr'].get('ok') != 1:
        return None
    return json.loads(st.frame['text']) if st.frame['text'] else {'h': '', 'n': 0}


def _read_output(steps: list, i: int, header: dict, room: int) -> tuple:
    """``(tags, complete)`` of the first ``room`` bytes of chunk ``i``'s output, or None when the pages do not cover them: ``tags`` maps each path to
    its ``[name, kind, scope]`` list in order, ``complete`` says the whole output was read. ``tags`` is None when ctags is missing. Where the output is
    cut the file the cut went through is dropped, so every file kept has every tag ctags found for it."""
    runs = _runs(steps)
    pages = [(0, header.get('n') or 0, _page(runs[i]))]
    for p in steps:
        if p.what == 'iout' and p.args['chunk'] == i and p.frame is not None and p.frame['hdr'].get('ok') == 1 and p.frame['hdr'].get('fsha') == header.get('osha'):
            pages.append((p.args['off'], p.frame['hdr'].get('n') or 0, _page(p)))
    pos, carry, tags, found = 0, '', {}, {}
    for off, n, page in sorted(pages, key=lambda x: x[0]):
        if off > pos:
            return None
        if off < pos or page is None:
            continue
        pos = off + n
        line = carry + page['h']
        if page['n']:
            if line.startswith('I\t'):
                found['i'] = line[2:]
            elif (tag := _tag(line)) is not None:
                tags.setdefault(tag[0], []).append([tag[1], tag[2], tag[3]])
            for path, group in page['g']:
                for entry in group:
                    name, kind, *scope = entry.split('\t')
                    tags.setdefault(path, []).append([name, kind, scope[0] if scope else ''])
            carry = page['t']
        else:
            carry = line
    if pos < room:
        return None
    if found.get('i') == 'missing':
        return None, True
    complete = room >= header['size']
    if complete and (tag := _tag(carry)) is not None:
        tags.setdefault(tag[0], []).append([tag[1], tag[2], tag[3]])
    elif tags and not complete:
        del tags[next(reversed(tags))]                      # the file the cut went through: its list is not whole
    return tags, complete


def command(op: str, ctx: dict, s: int, what: str, args: dict, blobs: dict) -> str:
    """The harness command of step ``s``: a pure function of what the ledger recorded (a retried request composes the same bytes)."""
    nonce, safe = callauth.nonce(op, s), ctx['safe']
    if what == 'ils':
        tree = args['mode'] == 'tree'
        words = [ctx['root'], args['dir'], 0 if tree else 1, min(TREE_MAX, MAX_ENTRIES) if tree else LEVEL_MAXES[args['rung']], 0,
                 json.dumps(skip_names(), separators=(',', ':')), os.fsencode(args.get('after', '')).hex()]
        return harnessprims.compose('ls', nonce, words, comment='workspace inventory ' + (args['dir'] or '.'), safe_path=safe)
    if what == 'iout':
        return harnessprims.compose('read', nonce, [args['dir'], 'out', args['off'], args['len'], 0],
                                    comment='workspace inventory (symbols)', safe_path=safe)
    if what == 'irm':
        parent, _, name = args['dir'].rpartition('/')
        return harnessprims.compose('rm', nonce, [parent or '/', name, 't', '*'], comment='workspace inventory', safe_path=safe)
    text = ctags_script(args['names']) if args['mode'] == 'start' else None
    return harnessprims.compose('run', nonce, [args['mode'], harnessprims.TMPDIR, _token(op, args['chunk']), CTAGS_TIMEOUT, CTAGS_WAIT,
                                               ctx['root'], 0], text=text, comment='workspace inventory (symbols)', safe_path=safe)


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
            ctx = {'shell': shell_tool, 'safe': self.safe_path, 'root': root, 'ws': root, 'wsroot': root, 'limits': self.inventory_limits}
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
        # the symbols ----------------------------------------------------------
        chunks = _chunks(_indexable_names(self._files(tree), op.ctx))
        runs = _runs(steps)
        room = _rooms(steps, len(chunks), _limits(op.ctx)['output_bytes'])
        for i, chunk in enumerate(chunks):
            st = runs.get(i)
            if st is None:
                issue.append(('irun', {'mode': 'start', 'chunk': i, 'n': 1, 'names': chunk}))
                continue
            header = st.frame['hdr'] if st.frame is not None else {}
            if header.get('ok') == 1 and header.get('state') == 'running' and st.args['n'] <= CTAGS_WAITS:
                issue.append(('irun', {'mode': 'wait', 'chunk': i, 'n': st.args['n'] + 1, 'names': chunk}))
            elif header.get('ok') == 1 and header.get('state') == 'done' and not header.get('removed'):
                issue += self._i_output(i, header, steps, room[i])
        if issue:
            return Issue(self._next_many(steps, issue[:WAVE]))
        return Final(denial.RAN, '', {'observed_at': time.time()})

    @staticmethod
    def _next_many(steps: list, items: list) -> tuple:
        base, wave = steps[-1].s + 1, steps[-1].args['wave'] + 1
        return tuple((base + i, what, {**args, 'wave': wave}) for i, (what, args) in enumerate(items))

    def _i_output(self, i: int, header: dict, steps: list, room: int | None) -> list:
        """What a ctags run's output still needs: the pages of its ``out`` file from where the first frame ended up to ``room`` bytes (read by cria,
        asked smaller after each one the harness cut), then the removal of its directory. ``room`` None: an earlier run is still going, and how
        much of the inventory's output budget is left for this one is not known yet."""
        if room is None:
            return []
        pages = [st for st in steps if st.what == 'iout' and st.args['chunk'] == i and st.frame is not None]
        cut = sum(1 for st in pages if st.frame['hdr'].get('ok') == -1)
        length = max(LEN_FLOOR, PAGE_BYTES >> cut)
        if cut and length <= LEN_FLOOR:
            return []
        have = [(0, header.get('n') or 0)] + [(st.args['off'], st.args['off'] + (st.frame['hdr'].get('n') or 0)) for st in pages if st.frame['hdr'].get('ok') == 1]
        wanted, pos = [], 0
        for a, b in sorted(have):
            if a > pos:
                wanted += [(off, min(length, a - off)) for off in range(pos, min(a, room), length)]
            pos = max(pos, b)
        wanted += [(off, min(length, room - off)) for off in range(pos, room, length)]
        if wanted:
            return [('iout', {'chunk': i, 'dir': header['dir'], 'off': off, 'len': n}) for off, n in wanted]
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
        tags, indexer = self._symbols(steps, _indexable_names(files, op.ctx), _limits(op.ctx))
        items = [{'path': rel, 'size': files[rel], 'symbols': tags.get(rel), 'blank': None, 'observed_at': observed_at} for rel in names]
        return {'files': items, 'symlinks': links, 'errors': errors,
                'excluded_names': [n for n in skip_names() if 'cria' not in n.lower()], 'symbol_indexer_error': indexer,
                'symbols_budget_tokens': _limits(op.ctx)['tokens']}

    @staticmethod
    def _symbols(steps: list, names: list, limits: dict) -> tuple:
        """``({path: [{name, kind, scope}...]}, error)`` from the ctags runs' output, read in this process (a path with no tag is absent).
        A file's list is whole or absent: one over ``limits['symbols']`` is dropped, and where the inventory's output budget cut a run's output
        the file it cut through is dropped with every file after it (they were never read)."""
        chunks = _chunks(names)
        tags, error = {}, None
        runs = _runs(steps)
        rooms = _rooms(steps, len(chunks), limits['output_bytes'])
        for i in range(len(chunks)):
            st = runs.get(i)
            header = st.frame['hdr'] if st is not None and st.frame is not None else {}
            if header.get('ok') != 1 or header.get('state') != 'done' or header.get('exit') != 0 or header.get('timeout'):
                error = error or 'indexer failed: ' + ('TimeoutError' if header.get('timeout') or header.get('state') == 'running' else 'OSError')
                continue
            if not rooms[i]:
                continue
            read = _read_output(steps, i, header, rooms[i])
            if read is None:
                error = error or 'indexer failed: OSError'
                continue
            found = read[0]
            if found is None:
                error = error or NOT_FOUND
                continue
            for path, symbols in found.items():
                if len(symbols) <= limits['symbols']:
                    tags[path] = [{k: v for k, v in zip(('name', 'kind', 'scope'), sym) if v} for sym in symbols]
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
