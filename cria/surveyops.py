"""The workspace survey through the harness primitives (docs/harness-primitives.md 8.9; docs/harness-programs.md section 7, phase 6).

A survey is one operation in the ledger (:mod:`cria.ledger`) that cria asks on its own cadence and answers to nobody: no model call
stands behind it and the model never sees it. It is a few calls to the primitives, and every decision is made here:

* the tree is ``ls`` — the whole workspace in one call when it fits one frame, else directory by directory, up to ``WAVE`` calls in
  a reply. ``.git`` is reported and never entered; a directory a toolchain writes (``wsview.BUILD_ARTIFACT_DIRS``) is named
  (``outputs``) only on the proof of its ecosystem's manifest beside it, and walked otherwise; a directory with more than
  ``FOLD_AT`` files is named and folded (its interior is UNKNOWN, never absent); the walk stops after ``TREE_MAX_ENTRIES``
  entries and says it is not complete. A name that cannot be one line of UTF-8 is not listed and its directory is not complete.
* the bodies a reader asked for are ``read`` calls (parallel pages, at most ``BLOB_FILES_MAX`` files and ``BLOB_BYTES_MAX`` bytes,
  none over ``BLOB_FILE_MAX``); what could not be handed back is said (the size, or absent, or unreadable), never skipped silently.
* which programs the coder's shell resolves, and which paths outside the workspace exist, are one ``run`` of a short script of
  shell text whose output cria reads (no decision is made in it).

What the survey learned is a :class:`cria.wsview.Survey`, computed from the frames the ledger holds (a pure function of the
ledger: a restart between two steps loses nothing).
"""
import errno as errno_
import hashlib
import json
import re
import shlex
from dataclasses import dataclass

from . import callauth, denial, harnessprims, wsview
from .opsteps import Final, Issue

SURVEY = 'survey'
INVENTORY = 'inventory'
SURVEY_GAP = 2          # model turns between two surveys that nothing landed for (a question waiting, the gate's checks): a question nobody can answer never makes one per request
SURVEY_EVERY = 4        # landed file mutations between surveys once the view is populated: four is often enough to see the file the coder wrote two turns ago without re-listing the repo every turn
WHATS = ('vls', 'vread', 'vrun', 'vrm')
WAVE = 16               # calls in one reply
TREE_MAX = 300          # records the whole-tree call asks for (a frame holds roughly 350-650 real entries)
LEVEL_MAXES = (1000, 400, 150, 50, 20)      # records a one-directory call asks for, largest first: a frame the harness cut is asked again smaller
RUN_TIMEOUT = 30        # seconds the probe script may run
RUN_WAIT = 8
RUN_WAITS = 3
HEAD = 6_000            # the output a `run` frame returns inline: a script answer larger than this is not taken
_VERSION = re.compile(r'[0-9][0-9.]*\Z')


@dataclass(frozen=True)
class SurveyAsk:
    """Where a survey would run: the harness's shell tool and the workspace root (both known from the request)."""
    shell: dict
    root: str


def skip_names() -> list:
    """Directory names ``ls`` reports and does not enter: ``.git``, and every name a build-output rule could fold (cria walks the ones
    the proof does not cover with a call of their own)."""
    return sorted(set(wsview.PRUNE_DIRS) | wsview.build_output_names())


def probe_script(progs: list, outside: list) -> str:
    """The shell text the ``run`` stub runs: for each asked program name which directory of ``$PATH`` holds it (a name followed by a
    version is the fallback, as before), and for each asked path outside the workspace whether it is a directory or a file. It prints
    one line per question, by number; the names are quoted data. Nothing is decided here."""
    lines = ['LC_ALL=C; export LC_ALL', 'shopt -s extglob nullglob', 'IFS=:']
    for i, name in enumerate(progs):
        q = shlex.quote(name)
        lines += [f'n={q}; r=-',
                  'for d in $PATH; do [ -n "$d" ] && [ -f "$d/$n" ] && [ -x "$d/$n" ] && { r=D; break; }; done',
                  'if [ "$r" = - ]; then for d in $PATH; do [ -n "$d" ] || continue; '
                  'for e in "$d/$n"+([0-9])*([0-9.]); do [ -f "$e" ] && [ -x "$e" ] && { s=${e##*/}; r=V${s#"$n"}; break 2; }; done; done; fi',
                  f"printf 'P\\t%s\\t%s\\n' {i} \"$r\""]
    for i, path in enumerate(outside):
        lines += [f'p={shlex.quote(path)}',
                  'case "$p" in "~") t=$HOME;; "~/"*) t=$HOME/${p#??};; *) t=$p;; esac',
                  'if [ -d "$t" ]; then k=d; elif [ -f "$t" ]; then k=f; else k=-; fi',
                  f"printf 'O\\t%s\\t%s\\n' {i} \"$k\""]
    return '\n'.join(lines) + '\n'


def _token(op: str) -> str:
    return hashlib.sha256((callauth.group(op) + 'survey').encode()).hexdigest()[:20]


def command(op: str, ctx: dict, s: int, what: str, args: dict, blobs: dict) -> str:
    """The harness command of step ``s``: a pure function of what the ledger recorded (a retried request composes the same bytes)."""
    nonce, safe = callauth.nonce(op, s), ctx['safe']
    if what == 'vls':
        tree = args['mode'] == 'tree'
        words = [ctx['root'], args['dir'], 0 if tree else 1, min(TREE_MAX, wsview.TREE_MAX_ENTRIES) if tree else LEVEL_MAXES[args['rung']], wsview.FOLD_AT,
                 json.dumps(skip_names(), separators=(',', ':')), '']
        return harnessprims.compose('ls', nonce, words, comment='workspace survey ' + (args['dir'] or '.'), safe_path=safe)
    if what == 'vread':
        return harnessprims.compose('read', nonce, [ctx['root'], args['rel'], args['off'], args['len'], 0],
                                    comment='workspace survey ' + args['rel'], safe_path=safe)
    if what == 'vrm':
        parent, _, name = args['dir'].rpartition('/')
        return harnessprims.compose('rm', nonce, [parent or '/', name, 't', '*'], comment='workspace survey', safe_path=safe)
    text = probe_script(ctx['progs'], ctx['outside']) if args['mode'] == 'start' else None
    return harnessprims.compose('run', nonce, [args['mode'], harnessprims.TMPDIR, _token(op), RUN_TIMEOUT, RUN_WAIT, '', 0],
                                text=text, comment='workspace survey (programs on PATH)', safe_path=safe)


# ---------------------------------------------------------------- the tree, from the frames

def _listable(name: str) -> bool:
    """One line of UTF-8: the only names the view carries (anything else is UNKNOWN, not absent and not invented)."""
    try:
        name.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return name.splitlines() == [name]


def _clean(path: str) -> bool:
    return all(_listable(part) for part in path.split('/'))


class _Tree:
    """What the walk steps' frames say, folded in step order. ``what`` names the walk's steps (the survey's or the inventory's);
    ``paging`` asks for the next page of a directory a frame did not hold (a listing without a fold bound is whole or it is paged),
    ``walk_skipped`` walks a directory ``ls`` reported and did not enter when nothing proves it a build output (the survey does; the
    inventory never enters what it excludes), ``strict_names`` leaves out what is not one line of UTF-8 (the survey's rule; the inventory
    carries every name as the JSON records give it). ``start`` is the directory the walk begins in (the workspace for a survey; the path a search
    was asked about), ``prune(dir)`` says that nothing below a listed directory is to be listed (a directory the search proves generated)."""

    def __init__(self, steps: list, what: str = 'vls', paging: bool = False, walk_skipped: bool = True, strict_names: bool = True,
                 start: str = '', prune=None):
        self.what, self.paging, self.walk_skipped, self.strict_names = what, paging, walk_skipped, strict_names
        self.start, self.prune = start, prune
        self.more: dict = {}            # directory -> the name its next page starts after
        self.records: dict = {}         # path -> ls record
        self.listed: set = set()        # directories whose entries are all in `records`
        self.folded: set = set()        # directories named only as a count
        self.partial: set = set()       # directories whose listing is not whole (a bound, an error, a frame that never fit)
        self.tried: dict = {}           # (dir, mode) -> the latest step for it
        self.failed_tree: set = set()   # directories whose whole-tree call did not answer whole: walked directory by directory
        cut: dict = {}                  # (dir, mode) -> the latest step whose frame the harness cut, while a smaller ask is still possible
        for st in sorted((x for x in steps if x.what == what), key=lambda x: x.s):
            key = (st.args['dir'], st.args['mode'])
            self.tried[key] = st
            if st.frame is None:
                continue
            header, d, tree = st.frame['hdr'], st.args['dir'], st.args['mode'] == 'tree'
            cut.pop(key, None)
            if header.get('ok') != 1:
                if header.get('ok') == -1 and not tree and st.args['rung'] + 1 < len(LEVEL_MAXES):
                    cut[key] = st                   # a frame the harness cut: asked again smaller (a later step)
                    continue
                (self.failed_tree if tree else self.partial).add(d)
                continue
            records = [json.loads(line) for line in st.frame['text'].split('\n') if line]
            whole = header.get('done') == 1
            if tree and not whole:
                self.failed_tree.add(d)             # the walk asked a bound it did not fit: directory by directory
                continue
            for r in records:
                self.records[r[1]] = r
                if r[0] == 'x':
                    self.folded.add(r[1])
            if tree:
                self.listed.add(d)
                self.listed |= {r[1] for r in records if r[0] == 'd' and not self._skipped(r)}
            elif d in self.folded:
                pass
            elif whole:
                self.listed.add(d)
                self.more.pop(d, None)
            elif paging and records:
                self.more[d] = records[-1][1].rpartition('/')[2]       # the page ended here: the next one starts after this name
            else:
                self.partial.add(d)
        self.retry = list(cut.values())

    @staticmethod
    def _skipped(record) -> bool:
        return len(record) > 5 and record[5] == 1

    def children(self, d: str) -> list:
        prefix = d + '/' if d else ''
        return [r for p, r in self.records.items() if p.startswith(prefix) and '/' not in p[len(prefix):] and r[0] != 'x']

    def output_proof(self, record) -> str | None:
        """The manifest beside a skipped directory that proves it a toolchain's output (``wsview.BUILD_ARTIFACT_DIRS``), or None."""
        parent = record[1].rpartition('/')[0]
        name = record[1].rpartition('/')[2]
        beside = {r[1].rpartition('/')[2] for r in self.children(parent) if r[0] != 'd'}
        proofs = wsview._build_output_proofs().get(name, ())
        return next((m for m in proofs if m in beside), None)

    def todo(self) -> list:
        """The directories nobody has listed yet, as ``(dir, mode)``, in the order the walk meets them (breadth first). A directory
        reached by a whole-tree call is listed; one reached by a directory-by-directory call is listed by a call of its own."""
        out = []
        if (self.start, 'tree') not in self.tried:
            return [(self.start, 'tree')]
        for d in sorted(self.failed_tree, key=lambda x: (x.count('/') if x else -1, x)):
            if (d, 'level') not in self.tried:
                out.append((d, 'level'))
        asking = {st.args['dir'] for st in self.retry}
        for d, after in sorted(self.more.items()):
            if d not in asking:
                out.append((d, 'level', after))
        for p in sorted(self.records, key=lambda x: (x.count('/'), x)):
            r = self.records[p]
            if r[0] != 'd' or (self.strict_names and not _clean(p)) or p in self.listed or p in self.folded or (p, 'level') in self.tried or (p, 'tree') in self.tried:
                continue
            parent = p.rpartition('/')[0]
            if parent not in self.listed and parent not in self.partial:
                continue                                    # its parent is not listed yet: nothing named it
            if self.prune is not None and self.prune(parent):
                continue                                    # its parent is a directory nothing below which is wanted
            if self._skipped(r):
                if not self.walk_skipped or p.rpartition('/')[2] in wsview.PRUNE_DIRS or self.output_proof(r):
                    continue                                # reported, never entered
                out.append((p, 'tree'))                     # a skipped name nothing proves a build output: walked
            else:
                out.append((p, 'level'))
        return out


def survey_tree(t: _Tree, todo: list) -> dict:
    """The tree fields of a :class:`wsview.Survey`: what was listed, what was folded and why the listing is or is not whole. ``todo`` is
    what the bound left unlisted."""
    dirs, files, folded, outputs = [], {}, set(), {}
    complete = True
    for p, r in sorted(t.records.items()):
        if not _clean(p):
            # A NAME THE TREE CANNOT CARRY IS UNKNOWN, NOT ABSENT AND NOT INVENTED: left out, and the directory that held it is not whole.
            held = []
            for part in p.split('/'):
                if not _listable(part):
                    break
                held.append(part)
            folded.add('/'.join(held))
            complete = False
            continue
        name = p.rpartition('/')[2]
        if r[0] == 'x':
            folded.add(p)                  # the fold record stands for the directory itself: named, interior unknown
            if p:
                dirs.append(p)
            continue
        if r[0] == 'd':
            if name in wsview.PRUNE_DIRS and _Tree._skipped(r):
                continue
            if _Tree._skipped(r) and (proof := t.output_proof(r)):
                outputs[p] = proof
            dirs.append(p)
        else:
            files[p] = (r[2], round(r[3] / 1e9))
    for d in t.partial | {d for d in t.failed_tree if (d, 'level') in t.tried and d not in t.listed}:
        folded.add(d)
        complete = False
    for d, _mode in todo:
        folded.add(d)
        complete = False
    if '' in folded:
        complete = False
    return {'dirs': tuple(dirs), 'files': files, 'folded': tuple(sorted(folded)), 'outputs': outputs, 'complete': complete,
            'listed': '' in t.listed or '' in t.folded}


# ---------------------------------------------------------------- the bodies, from the frames

def _bytes(frame: dict) -> bytes:
    return frame['text'].encode('utf-8', 'surrogateescape')


class _Body:
    """One wanted file: its pages as the frames returned them."""

    def __init__(self, rel: str, steps: list):
        self.rel, self.pieces, self.error, self.size, self.sha, self.mixed, self.unknown = rel, [], None, None, None, False, 0
        for st in steps:
            if st.what != 'vread' or st.args['rel'] != rel or st.frame is None:
                continue
            header = st.frame['hdr']
            if header.get('ok') == 1:
                if self.sha not in (None, header['fsha']):
                    self.mixed = True
                self.size, self.sha = header['fsize'], header['fsha']
                if header['size'] != header['fsize']:
                    self.mixed = True
                self.pieces.append((header.get('off') or 0, _bytes(st.frame)))
            elif header.get('ok') == 0:
                self.error = header
            else:
                self.unknown += 1

    def refused(self):
        """``(size or ABSENT/UNSTATABLE)`` for a file the survey cannot hand back, or None."""
        if self.error is not None:
            code = self.error.get('errno')
            return wsview.ABSENT if code in (errno_.ENOENT, errno_.ENOTDIR) else wsview.UNSTATABLE
        if self.size is not None and self.size > wsview.BLOB_FILE_MAX:
            return self.size
        return None

    def bytes_or_none(self):
        from .readops import merge
        if self.size is None or self.mixed:
            return None
        prefix, _ = merge(self.pieces)
        if len(prefix) >= self.size and hashlib.sha256(prefix[:self.size]).hexdigest() == self.sha:
            return prefix[:self.size]
        return None


# ---------------------------------------------------------------- the programs and the outside paths, from the frame

def _answers(steps: list, ctx: dict):
    """``(progs, outside, waiting)`` from the probe script's frame: dicts of what it answered, or what is still to ask (a run still
    going, or its directory to remove)."""
    runs = sorted((st for st in steps if st.what == 'vrun'), key=lambda x: x.s)
    if not runs:
        return {}, {}, None
    last = runs[-1]
    if last.frame is None:
        return None, None, 'frame'
    header = last.frame['hdr']
    if header.get('ok') == 1 and header.get('state') == 'running':
        return None, None, 'running' if last.args['n'] <= RUN_WAITS else None
    if header.get('ok') != 1 or header.get('exit') != 0 or header.get('timeout') or header.get('size', 0) > header.get('head', 0):
        return {}, {}, ('rm' if header.get('dir') and not header.get('removed') else None)
    progs, outside = {}, {}
    for line in last.frame['text'].split('\n'):
        kind, _, rest = line.partition('\t')
        i, _, value = rest.partition('\t')
        if not i.isdigit():
            continue
        i = int(i)
        if kind == 'P' and i < len(ctx['progs']):
            name = ctx['progs'][i]
            if value == 'D':
                progs[name] = name
            elif value == '-':
                progs[name] = ''
            elif value.startswith('V') and _VERSION.match(value[1:]):
                progs[name] = name + value[1:]
        elif kind == 'O' and i < len(ctx['outside']) and value in ('d', 'f', '-'):
            outside[ctx['outside'][i]] = '' if value == '-' else value
    return progs, outside, ('rm' if header.get('dir') and not header.get('removed') else None)


class SurveyOps:
    """The survey half of the engine; ``Ops`` inherits it (``_step``, ``_next`` and the ledger live there)."""

    # ---------------------------------------------------------------- issuing
    def issue_survey(self, session: str, shell_tool: dict, root: str, wants: dict) -> list:
        """Record a survey and return its first primitive calls: the walk, the bodies asked for (first pages) and the probe script."""
        from .ledger import LedgerError
        from .opspath import OpsUnavailable
        from .toolwire import _shell_call
        with self._lock:
            op = callauth.new_op()
            ctx = {'shell': shell_tool, 'safe': self.safe_path, 'root': root, 'ws': root, 'wsroot': root,
                   'bodies': list(wants['bodies']), 'progs': list(wants['progs']), 'outside': list(wants['outside'])}
            record = {'t': 'op', 'op': op, 'kind': SURVEY, 'ctx': ctx, 'call': {}}
            try:
                steps = self._first_wave(ctx)
                built = [self._step(op, ctx, s, what, {'wave': 0, **args}) for s, (what, args) in enumerate(steps)]
                self.ledger.append(session, record, *(b[0] for b in built))
            except (LedgerError, callauth.KeyUnavailable) as exc:
                raise OpsUnavailable(str(exc)) from exc
            return [_shell_call(b[0]['id'], shell_tool, b[1]) for b in built]

    def _first_wave(self, ctx: dict) -> list:
        steps = [('vls', {'dir': '', 'mode': 'tree', 'rung': 0})]
        steps += [('vread', {'rel': rel, 'off': 0, 'len': self._length(), 'rung': 0}) for rel in ctx['bodies']]
        if ctx['progs'] or ctx['outside']:
            steps.append(('vrun', {'mode': 'start', 'n': 1}))
        return steps

    def _v_step(self, op, steps, what, **args):
        return self._next(steps, what, args)

    def _survey_due(self, session: str, messages: list) -> bool:
        """Whether a survey should be asked now, on cria's own cadence (the one the survey always had, no longer carried by another call):

        * a question the view could not answer is waiting (a body, a program, a path outside the workspace; an absence a survey reported
          is not a new question) or the completion gate's checks have run, and ``SURVEY_GAP`` turns have passed since the last survey;
        * or a file mutation landed since the last survey, and either no survey has ever run, or ``SURVEY_EVERY`` calls have landed,
          or any question waits (an absence a survey reported is re-asked at the next one).
        Never while a survey is in flight."""
        ledger_ops = list(self.ledger.ops(session).values())
        surveys = [i for i, o in enumerate(ledger_ops) if o.kind in (SURVEY, INVENTORY)]
        if any(ledger_ops[i].final is None for i in surveys):
            return False
        last = surveys[-1] if surveys else -1
        landed = sum(1 for o in ledger_ops[last + 1:] if o.kind == 'mutate' and o.final is not None
                     for r in o.final.get('results') or () if r.get('o') == 'landed')
        asked = {st.id for i in surveys for st in ledger_ops[i].steps.values()}
        turns = 99 if last < 0 else self._turns_since(messages, asked)
        waiting = any(wsview.pending(session))
        if wsview.fresh_demands(session) and turns >= SURVEY_GAP:
            return True
        return bool(landed and turns >= 1 and (last < 0 or landed >= SURVEY_EVERY or waiting))

    @staticmethod
    def _turns_since(messages: list, asked: set) -> int:
        """How many turns of calls (assistant messages with tool calls) came after the last survey call in the history."""
        turns = 0
        for m in reversed(messages):
            if isinstance(m, dict) and m.get('role') == 'assistant':
                ids = [c.get('id') for c in m.get('tool_calls') or () if isinstance(c, dict)]
                if any(i in asked for i in ids):
                    return turns
                turns += bool(ids)
        return turns

    # ---------------------------------------------------------------- deciding
    def _v_after(self, op, steps: list):
        ctx = op.ctx
        issue = []
        # the walk -------------------------------------------------------
        tree = _Tree(steps)
        issue += [('vls', {**st.args, 'rung': st.args['rung'] + 1}) for st in tree.retry]     # a frame the harness cut: the same directory, asked smaller
        todo = tree.todo()
        if len(tree.records) < wsview.TREE_MAX_ENTRIES:
            issue += [('vls', {'dir': d, 'mode': mode, 'rung': 0}) for d, mode in todo]
            todo = []
        # the bodies ------------------------------------------------------
        wanted = self._v_wanted(steps, ctx)
        for body, take in wanted:
            if take:
                issue += self._v_pages(body)
        # the probe script ---------------------------------------------------
        progs, outside, waiting = _answers(steps, ctx)
        last_run = max((st for st in steps if st.what == 'vrun'), key=lambda x: x.s, default=None)
        if waiting == 'running':
            issue.append(('vrun', {'mode': 'wait', 'n': last_run.args['n'] + 1}))
        elif waiting == 'rm' and not any(st.what == 'vrm' for st in steps):
            issue.append(('vrm', {'dir': last_run.frame['hdr']['dir']}))
        if issue:
            return Issue(self._next_many(steps, issue[:WAVE]))
        survey = self._build(op, tree, todo, wanted, progs or {}, outside or {})
        self._surveys[op.op] = survey
        return Final(denial.RAN, '', {'listed': survey.listed, 'complete': survey.complete})

    @staticmethod
    def _next_many(steps: list, items: list) -> tuple:
        base, wave = steps[-1].s + 1, steps[-1].args['wave'] + 1
        return tuple((base + i, what, {**args, 'wave': wave}) for i, (what, args) in enumerate(items))

    @staticmethod
    def _v_wanted(steps: list, ctx: dict) -> list:
        """``[(body, taken)]``: the wanted files in order, with the budget applied as the survey always applied it (at most
        ``BLOB_FILES_MAX`` files, and no more once ``BLOB_BYTES_MAX`` bytes are in). A file the harness could not hand back is
        reported (``refused``), never skipped."""
        out, taken, spent = [], 0, 0
        for rel in ctx['bodies']:
            body = _Body(rel, steps)
            if taken >= wsview.BLOB_FILES_MAX or spent >= wsview.BLOB_BYTES_MAX:
                out.append((body, False))
            elif body.refused() is not None and body.size is None:
                out.append((body, True))                                # absent / unreadable: said, and not counted against the budget
            elif body.size is not None and body.size > wsview.BLOB_FILE_MAX:
                out.append((body, True))
            else:
                taken += 1
                spent += body.size or 0
                out.append((body, True))
        return out

    def _v_pages(self, body: _Body) -> list:
        """The pages of a wanted body still to ask for: the first page (smaller after each one the harness cut), then the gaps of what is
        held. Nothing for a body that is whole, refused, changed under the read, or whose pages cannot be made small enough."""
        from .readops import LEN_FLOOR, merge
        if body.error is not None or body.mixed or body.bytes_or_none() is not None or (body.size or 0) > wsview.BLOB_FILE_MAX:
            return []
        length = self._length(body.unknown)
        if body.unknown and length <= LEN_FLOOR:
            return []
        if body.size is None:
            return [('vread', {'rel': body.rel, 'off': 0, 'len': length, 'rung': body.unknown})] if body.unknown else []
        _, ranges = merge(body.pieces)
        gaps, pos = [], 0
        for a, b in ranges:
            if a > pos:
                gaps.append((pos, a))
            pos = max(pos, b)
        if pos < body.size:
            gaps.append((pos, body.size))
        return [('vread', {'rel': body.rel, 'off': off, 'len': length, 'rung': body.unknown}) for a, b in gaps for off in range(a, b, length)]

    @staticmethod
    def _build(op, tree: _Tree, todo: list, wanted: list, progs: dict, outside: dict) -> 'wsview.Survey':
        facts = survey_tree(tree, todo[:wsview.FOLD_DRAIN_MAX] if todo else [])
        if len(todo) > wsview.FOLD_DRAIN_MAX:
            facts['complete'] = False
        bodies, refused = {}, {}
        for body, take in wanted:
            if not take:
                continue
            gone = body.refused()
            if gone is not None:
                refused[body.rel] = gone
            elif (data := body.bytes_or_none()) is not None:
                bodies[body.rel] = data
        return wsview.Survey(op.ctx['root'], bodies=bodies, refused=refused, outside=outside, progs=progs, **facts)

    # ---------------------------------------------------------------- what the survey learned
    def survey_of(self, op) -> 'wsview.Survey | None':
        """The :class:`wsview.Survey` of a finished survey operation, computed from its frames (a pure function of the ledger)."""
        if op.kind != SURVEY or op.final is None:
            return None
        if op.op not in self._surveys:
            steps = sorted(op.steps.values(), key=lambda x: x.s)
            tree = _Tree(steps)
            todo = tree.todo() if len(tree.records) >= wsview.TREE_MAX_ENTRIES else []
            progs, outside, _ = _answers(steps, op.ctx)
            self._surveys[op.op] = self._build(op, tree, todo, self._v_wanted(steps, op.ctx), progs or {}, outside or {})
            while len(self._surveys) > 64:
                self._surveys.pop(next(iter(self._surveys)))
        return self._surveys[op.op]
