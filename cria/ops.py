"""The engine that runs cria's operations through the harness primitives (docs/harness-primitives.md sections 6 and 8).

An operation is one model call (here: ``list_dir``) that cria carries out as one or more primitive calls. cria decides every
step in this process; the harness only runs the fixed stubs of :mod:`cria.harnessprims`. The model sees its own call and the
text cria composed, never the primitive calls.

* ``issue_list_dir`` records the operation in the :mod:`cria.ledger` and returns the first primitive call, whose tool-call id
  is a MAC over its exact command (:mod:`cria.callauth`).
* ``incoming`` runs on every request. It verifies each ``ctx_`` call in the history against the key and the ledger, reads the
  result of each verified call only as the frame carrying that call's nonce, decides the next step from the ledger alone
  (so a restart between issue and result loses nothing), and answers with the primitive calls the harness has not yet seen.
  It then projects the history: a finished operation is its original call and the ledger's final text, nothing else.
* Calls with a ``ctx_`` id that does not verify, or verified ones whose ledger entry is missing, are never re-presented as
  anything: they stay the honest commands they are, labelled, with no outcome claimed.
"""
import errno as errno_
import hashlib
import json
import os
import threading
from dataclasses import dataclass, field

from . import callauth, denial, externalization, harnessprims, prompts, readops, resultpacket, writeops
from .content_reduce import COMMAND_ARG_BUDGET, INLINE_RESULT_MAX_BYTES
from .filecache import FileCache
from .ledger import Ledger, LedgerError, Op
from .opspath import OpsUnavailable, split
from .opsteps import Final, Issue, Wait
from .readops import LedgerRead, ReadFact, ReadOps
from .writeops import LedgerWrite, WriteOps
from .toolwire import _command_of, _refusal_command, _shell_call

LIST_DIR = 'list_dir'
# Records one ls frame asks for, largest first: a frame the harness cut (more than ~10,000 bytes) is asked again smaller.
# Measured: a frame holds about 2,500 records of regular names, 350-650 of real ones (15-29 bytes each on this repository's
# directories and /usr/lib). A directory one frame does not hold is `done:0` (unknown beyond): cria asks for the next page with
# `AFTER` = the last name it received, one call per frame, and the rung that fitted is kept for the next page.
LS_MAX = (1000, 400, 150, 50, 20)
LS_MAX_PAGES = 50     # pages of one listing (50,000 entries at the first rung): beyond it the listing is labelled incomplete
MAX_HOPS = 8          # symbolic links followed while resolving a path (ELOOP beyond)
_TYPE = {'f': '-', 'd': 'd', 'l': 'l', 'o': '?'}


@dataclass
class Incoming:
    messages: list
    calls: list = field(default_factory=list)       # primitive calls the harness has not seen: answer with these, skip the model
    outcomes: dict = field(default_factory=dict)    # original call id -> denial kind, from the ledger
    reads: dict = field(default_factory=dict)       # original call id -> LedgerRead, for each finished read
    facts: tuple = ()                               # ReadFact of each verified read the model's wire has not yet accepted
    writes: dict = field(default_factory=dict)      # original call id -> LedgerWrite, for each finished file mutation


def _reason(header: dict) -> str:
    code = header.get('errno')
    return os.strerror(code) if isinstance(code, int) and code else str(header.get('err') or 'unknown error')


def _entry(record: list, shown: str | None = None) -> str:
    kind, path, size, mtime, mode = record[:5]
    name = path.rsplit('/', 1)[-1] if shown is None else shown
    bits = ''.join(('r' if mode & (4 << s) else '-') + ('w' if mode & (2 << s) else '-') + ('x' if mode & (1 << s) else '-')
                   for s in (6, 3, 0))
    line = f'{_TYPE.get(kind, "?")}{bits} {size:>10} {_utc(mtime)} {_name(name)}'
    return line + (f' -> {_name(record[5])}' if kind == 'l' and len(record) > 5 else '')


def _utc(ns: int) -> str:
    import time
    return time.strftime('%Y-%m-%d %H:%M', time.gmtime(ns // 1_000_000_000))


def _name(name: str) -> str:
    """One line per entry whatever the name holds: a control character becomes its escape, a lone surrogate (an undecodable
    byte) becomes ``\\xNN``."""
    out = []
    for ch in name:
        if ch == '\\':
            out.append('\\\\')
        elif ch.isprintable() and not '\udc80' <= ch <= '\udcff':
            out.append(ch)
        elif '\udc80' <= ch <= '\udcff':
            out.append('\\x%02x' % (ord(ch) - 0xdc00))
        else:
            out.append(ch.encode('unicode_escape').decode())
    return ''.join(out)


def render_listing(records: list, shown_path: str, done: bool, single: bool = False) -> str:
    """The listing the model reads, one line per entry (docs/harness-primitives.md section 9, item 5): type and permission
    bits, size, UTC modification time, name and a link's target. Nothing is dropped; a listing that is not complete says so.
    ``single`` is a path that is itself not a directory: one line, named as the model named it."""
    if not records:
        return prompts.render('list_dir_empty', path=shown_path) if done else prompts.render('list_dir_unknown', path=shown_path)
    text = '\n'.join(_entry(r, shown_path if single else None) for r in records)
    return text if done else text + '\n' + prompts.render('list_dir_incomplete', count=len(records), path=shown_path)


class Ops(ReadOps, WriteOps):
    def __init__(self, ledger: Ledger | None = None, safe_path: str = harnessprims.SAFE_PATH):
        self.ledger = ledger or Ledger()
        self.safe_path = safe_path
        self.cache = FileCache()
        self.command_budget = COMMAND_ARG_BUDGET
        self.menu = None            # the harness's tool menu and the room one result may take in the model's measured window,
        self.room = None            # as of the request being handled (read answers name routes from the menu and decide fit)
        self._rate = readops.DEFAULT_RATE
        self._carry: dict = {}      # (operation, sha-256) -> the bytes a planned write will leave, for the cache once it lands
        self._rides: dict = {}      # operation -> composes the workspace survey that rides with its landing write (process memory: lost on restart, harmlessly)
        self._rlog = None
        self._lock = threading.RLock()      # the ledger's folded state is shared: one request at a time advances operations

    # ---------------------------------------------------------------- issuing
    def issue_list_dir(self, session: str, shell_tool: dict, call: dict, args: dict, *, workspace_root: str | None,
                       level: str, roots=()) -> dict:
        """Record ``list_dir`` and return its first primitive call. The model's call (id, name, arguments) is kept in the
        ledger; the harness is only ever shown the ``ls`` call."""
        with self._lock:
            return self._issue_list_dir(session, shell_tool, call, args, workspace_root, level, roots)

    def _issue_list_dir(self, session, shell_tool, call, args, workspace_root, level, roots) -> dict:
        path = str(args.get('path') or args.get('dir') or args.get('directory') or '.')
        root, rel = split(path, workspace_root)
        op = callauth.new_op()
        fn = call.get('function') or {}
        ctx = {'path': path, 'shell': shell_tool, 'safe': self.safe_path, 'ws': workspace_root or '.', 'wsroot': workspace_root,
               'level': level, 'roots': list(roots), 'trail': path.rstrip('/') != '' and path.endswith('/')}
        record = {'t': 'op', 'op': op, 'kind': LIST_DIR, 'ctx': ctx,
                  'call': {'id': call.get('id'), 'name': fn.get('name'), 'arguments': fn.get('arguments')}}
        try:
            step = self._step(op, ctx, 0, 'ls', {'wave': 0, 'root': root, 'rel': rel, 'max_i': 0, 'hop': 0, 'after': ''})
            if len(step[1].encode()) > COMMAND_ARG_BUDGET:
                # An argument the kernel would refuse (E2BIG) is answered here, without sending it: one short refusal call.
                text = prompts.render('list_dir_path_too_long', size=len(path.encode()), limit=COMMAND_ARG_BUDGET - 3000)
                step = self._step(op, ctx, 0, 'say', {'wave': 0, 'text': text})
                self.ledger.append(session, record, step[0], {'t': 'final', 'op': op, 'outcome': denial.REFUSED, 'text': denial.mark(text)})
            else:
                self.ledger.append(session, record, step[0])
        except (LedgerError, callauth.KeyUnavailable) as exc:
            raise OpsUnavailable(str(exc)) from exc
        return _shell_call(step[0]['id'], shell_tool, step[1])

    def _step(self, op: str, ctx: dict, s: int, what: str, args: dict, blobs: dict | None = None) -> tuple[dict, str]:
        """``(ledger record, command)`` for step ``s``: both pure functions of the operation's recorded facts."""
        command = self._command(op, ctx, s, what, args, blobs or {})
        return {'t': 'step', 'op': op, 's': s, 'id': callauth.call_id(op, s, command),
                'cmd': hashlib.sha256(command.encode()).hexdigest(), 'what': what, 'args': args}, command

    @staticmethod
    def _command(op: str, ctx: dict, s: int, what: str, args: dict, blobs: dict | None = None) -> str:
        nonce = callauth.nonce(op, s)
        label = f"{ctx.get('tool', LIST_DIR)} {ctx['path']}"
        if what in writeops.WHATS:
            return writeops.command(op, ctx, s, what, args, blobs or {})
        if what == 'ls':
            # AFTER travels as the hex of the name's bytes: a name that is not UTF-8 (a lone surrogate here) must not enter a command
            words, payload, comment = [args['root'], args['rel'], 1, LS_MAX[args['max_i']], 0, '[]', os.fsencode(args.get('after', '')).hex()], None, label
        elif what == readops.READ:
            words, payload, comment = [args['root'], args['rel'], args['off'], args['len'], args.get('sk', 0)], None, label
        elif what == 'stat':
            words, payload, comment = [args['root'], args['rel'], 1, 1, 0, '[]', ''], None, label
            what = 'ls'
        elif what == 'say':
            return _refusal_command(args['text'])
        elif what == 'put':
            data = blobs[args['blob']].encode('utf-8', 'surrogateescape')[args['off']:args['off'] + harnessprims.CHUNK_BYTES]
            words, payload, comment = [args['root'], args['rel'], callauth.group(op), args['off'], 1], data, label
        else:
            data = blobs[args['blob']].encode('utf-8', 'surrogateescape')
            staged = args.get('staged', False)
            words = [args['root'], args['rel'], '*', '-', hashlib.sha256(data).hexdigest(), 1 if staged else 0, 1, callauth.group(op)]
            payload, comment, what = None if staged else data, label, 'write'
        return harnessprims.compose(what, nonce, words, payload, comment=comment, safe_path=ctx['safe'])

    # ---------------------------------------------------------------- every request
    def incoming(self, session: str, messages: list, log=None, *, tools=None, room: int | None = None) -> Incoming:
        """Ingest results, advance operations, hand back what the harness has not seen, project the history. ``tools`` is the
        harness's tool menu and ``room`` the tokens one tool result may take in the model's measured window (None: unknown; a callable is asked only when a read's first frame is in hand)."""
        with self._lock:
            self.menu, self.room = tools, room
            self._rlog = log if log is not None else self._rlog
            return self._incoming(session, messages, log)

    def _incoming(self, session: str, messages: list, log) -> Incoming:
        if not any(isinstance(c, dict) and str(c.get('id') or '').startswith(callauth.PREFIX)
                   for m in messages if isinstance(m, dict) and m.get('role') == 'assistant' for c in m.get('tool_calls') or ()):
            return Incoming(messages)
        ledger_ops = self.ledger.ops(session)
        verified = self._verified(messages, ledger_ops)
        results = self._results(messages)
        try:
            frames = []
            for cid, (op, s) in verified.items():
                step = ledger_ops[op].steps[s]
                if step.frame is None and ledger_ops[op].final is None:
                    if cid in results and step.what == 'noop':      # a call that only keeps the model's call and its result paired: nothing to read
                        frames.append({'t': 'frame', 'op': op, 's': s, 'hdr': {'ok': 1}, 'text': ''})
                    elif cid in results:
                        frames.append(self._frame_record(op, s, results[cid], step))
                    else:      # none or several results: UNKNOWN (never "did not run", never "ran"), so the retry ladder or the final takes over
                        frames.append({'t': 'frame', 'op': op, 's': s, 'text': '', 'hdr': {'ok': -1, 'unknown': (
                            'no result for this call' if not self._result_count(messages, cid) else 'several results for this call')}})
            if frames:
                self.ledger.append(session, *frames)
            calls = self._advance(session, {op for op, _ in verified.values()}, set(verified), log)
        except (LedgerError, callauth.KeyUnavailable) as exc:
            if log is not None:
                log.emit('ops.unavailable', level='error', error=str(exc))
            return Incoming(messages)
        return self._project(session, messages, verified, calls, log)

    @staticmethod
    def _verified(messages: list, ledger_ops: dict) -> dict:
        """``{call id: (op, step)}`` for each assistant call whose id is cria's MAC over its exact command AND whose step the
        ledger recorded with the same id and command hash. The id must name exactly one call."""
        seen: dict = {}
        for m in messages:
            if isinstance(m, dict) and m.get('role') == 'assistant':
                for c in m.get('tool_calls') or ():
                    if isinstance(c, dict):
                        seen[c.get('id')] = seen.get(c.get('id'), 0) + 1
        out = {}
        for m in messages:
            if isinstance(m, dict) and m.get('role') == 'assistant':
                for c in m.get('tool_calls') or ():
                    cid = c.get('id') if isinstance(c, dict) else None
                    command = _command_of((c.get('function') or {}).get('arguments'))
                    found = callauth.verify(cid, command) if seen.get(cid) == 1 else None
                    if found is None:
                        continue
                    op, s = found
                    step = ledger_ops.get(op) and ledger_ops[op].steps.get(s)
                    if step is not None and step.id == cid and step.cmd == hashlib.sha256(command.encode()).hexdigest():
                        out[cid] = found
        return out

    @staticmethod
    def _result_count(messages: list, cid: str) -> int:
        return sum(1 for m in messages if isinstance(m, dict) and m.get('role') == 'tool' and m.get('tool_call_id') == cid)

    @staticmethod
    def _results(messages: list) -> dict:
        """``{call id: result text}`` for ids with exactly one result in the history."""
        texts: dict = {}
        for m in messages:
            if isinstance(m, dict) and m.get('role') == 'tool':
                texts.setdefault(m.get('tool_call_id'), []).append(m.get('content'))
        out = {}
        for cid, found in texts.items():
            if len(found) == 1:
                content = found[0]
                if isinstance(content, list):
                    content = ''.join(p.get('text', '') for p in content if isinstance(p, dict))
                if isinstance(content, str):
                    out[cid] = content
        return out

    @staticmethod
    def _frame_record(op: str, s: int, text: str, step=None) -> dict:
        nonce = callauth.nonce(op, s)
        try:
            frame = harnessprims.read_frame(text, nonce)
        except harnessprims.FrameUnknown as exc:
            return {'t': 'frame', 'op': op, 's': s, 'hdr': {'ok': -1, 'unknown': str(exc)}, 'text': '', 'wire': len(text)}
        record = {'t': 'frame', 'op': op, 's': s, 'hdr': frame.header, 'text': frame.data.decode('utf-8', 'surrogateescape'),
                  'wire': len(text)}
        if step is not None and step.args.get('ride'):
            survey = Ops._survey_after(text, nonce, writeops.survey_token(op))
            if survey:
                record['sv'] = survey
        return record

    @staticmethod
    def _survey_after(text: str, nonce: str, token: str) -> str:
        """The workspace survey that rode home on the line after a frame (the typed survey record, read at that position only), or ''."""
        clean = text.replace('\r', '')
        end = clean.find('CTX1 ' + nonce + ' END')
        if end < 0:
            return ''
        at = clean.find('\n', end) + 1
        record = resultpacket.read_record(clean, at, token, survey=True) if at else None
        if record is None or record.body is None:
            return ''
        try:
            return record.body.decode('utf-8')
        except UnicodeDecodeError:
            return 

    def _advance(self, session: str, op_ids: set, present: set, log) -> list:
        """Decide each operation's next step from the ledger alone. Returns the primitive calls the harness has not seen:
        a step just issued, or one an earlier request issued whose reply never reached the harness."""
        calls = []
        for op_id in sorted(op_ids):
            op = self.ledger.ops(session).get(op_id)
            if op is None or op.final is not None:
                continue
            action = self._plan(op)
            if isinstance(action, Final):
                self.ledger.append(session, {'t': 'final', 'op': op_id, 'outcome': action.outcome, 'text': action.text, **action.extra})
                if log is not None:
                    log.emit('ops.final', operation=op.kind, outcome=action.outcome, steps=len(op.steps))
            elif isinstance(action, Issue):
                blobs = {**op.blobs, **action.blobs}
                records = [self._step(op_id, op.ctx, s, what, args, blobs) for s, what, args in action.steps]
                self.ledger.append(session, *({'t': 'blob', 'op': op_id, 'h': h, 'text': t} for h, t in action.blobs.items()),
                                   *(r[0] for r in records))
                calls += [_shell_call(r[0]['id'], op.ctx['shell'], r[1]) for r in records]
            else:                  # still waiting for a result; a step an earlier request issued and the harness never saw goes out again
                wave = max(st.args['wave'] for st in op.steps.values())
                calls += [_shell_call(st.id, op.ctx['shell'], self._command(op_id, op.ctx, st.s, st.what, st.args, op.blobs))
                          for st in sorted(op.steps.values(), key=lambda x: x.s) if st.args['wave'] == wave and st.id not in present]
        return calls

    # ---------------------------------------------------------------- the decisions
    def _plan(self, op: Op):
        steps = sorted(op.steps.values(), key=lambda st: st.s)
        wave = [st for st in steps if st.args['wave'] == steps[-1].args['wave']]
        if any(st.frame is None for st in wave):
            return Wait
        if op.kind == writeops.MUTATE:
            return self._m_after(op, wave, steps)
        table = ({readops.READ: self._after_read, 'stat': self._after_read_stat} if op.kind == readops.READ
                 else {'ls': self._after_ls, 'stat': self._after_stat, 'put': self._after_put, 'write': self._after_write})
        return table[wave[0].what](op, wave, steps)

    @staticmethod
    def _next(steps: list, what: str, *args: dict) -> tuple:
        """The steps of the next wave: consecutive numbers after the last step, one wave number for all."""
        base, wave = steps[-1].s + 1, steps[-1].args['wave'] + 1
        return tuple((base + i, what, {**a, 'wave': wave}) for i, a in enumerate(args))

    def _after_ls(self, op: Op, wave: list, steps: list):
        st = wave[0]
        header, args = st.frame['hdr'], st.args
        shown = op.ctx['path']
        if header.get('ok') == 1:
            records = [json.loads(line) for line in st.frame['text'].split('\n') if line]
            pages = [st2 for st2 in steps if st2.what == 'ls' and st2.s < st.s and st2.frame['hdr'].get('ok') == 1
                     and (st2.args['root'], st2.args['rel']) == (args['root'], args['rel'])]      # pages of THIS path, not of a link resolved from
            single = bool(records and args['rel'] and not pages and records[0][1] == args['rel'])
            if single and records[0][0] == 'l' and op.ctx.get('trail'):
                # `link/` names what the link points to (as `ls -la link/` did): cria resolves it itself and judges the target.
                if args['hop'] >= MAX_HOPS:
                    return Final(denial.REFUSED, prompts.render('list_dir_failed', path=shown, reason=os.strerror(errno_.ELOOP)))
                resolved = os.path.normpath(os.path.join(os.path.dirname(os.path.join(args['root'], args['rel'])), records[0][5]))
                if (refusal := self._reguard(resolved, op.ctx)):
                    return Final(denial.REFUSED, denial.mark(refusal))
                root, rel = split(resolved, op.ctx.get('wsroot'))
                return Issue(self._next(steps, 'ls', {**args, 'root': root, 'rel': rel, 'max_i': 0, 'hop': args['hop'] + 1, 'after': ''}))
            done = header.get('done') == 1
            if not done and records and len(pages) + 1 < LS_MAX_PAGES:
                # More entries follow this page: ask for those after the last name received, at the size that fitted.
                return Issue(self._next(steps, 'ls', {**args, 'after': records[-1][1].rsplit('/', 1)[-1]}))
            records = [json.loads(line) for st2 in pages for line in st2.frame['text'].split('\n') if line] + records
            text = render_listing(records, shown, done, single)
            if externalization.stdout_size(text.encode('utf-8', 'surrogateescape')) <= INLINE_RESULT_MAX_BYTES:
                return Final(denial.RAN, text)
            return self._spill(op, steps, text, done, len(records))
        if header.get('ok') == 0:
            code = header.get('errno')
            parts = [p for p in args['rel'].split('/') if p]
            if code in (errno_.ELOOP, errno_.ENOTDIR) and len(parts) > 1:
                if args['hop'] >= MAX_HOPS:
                    return Final(denial.REFUSED, prompts.render('list_dir_failed', path=shown, reason=os.strerror(errno_.ELOOP)))
                # Which component is a link is never guessed: stat each directory prefix, all in one reply.
                prefix, prefixes = '', []
                for part in parts[:-1]:
                    prefix = f'{prefix}/{part}' if prefix else part
                    prefixes.append(prefix)
                return Issue(self._next(steps, 'stat', *({**args, 'rel': p, 'errno': code, 'at': i, 'full': args['rel']}
                                                          for i, p in enumerate(prefixes))))
            return Final(denial.REFUSED, prompts.render('list_dir_failed', path=shown, reason=_reason(header)))
        if args['max_i'] + 1 < len(LS_MAX):
            return Issue(self._next(steps, 'ls', {**args, 'max_i': args['max_i'] + 1}))
        return Final(denial.UNKNOWN, prompts.render('list_dir_unknown', path=shown))

    def _after_stat(self, op: Op, wave: list, steps: list):
        shown, ctx = op.ctx['path'], op.ctx
        for st in sorted(wave, key=lambda x: x.args['at']):
            header, args = st.frame['hdr'], st.args
            if header.get('ok') != 1:
                text = prompts.render('list_dir_unknown', path=shown) if header.get('ok') == -1 else prompts.render(
                    'list_dir_failed', path=shown, reason=_reason(header))
                return Final(denial.UNKNOWN if header.get('ok') == -1 else denial.REFUSED, text)
            records = [json.loads(line) for line in st.frame['text'].split('\n') if line]
            if not records or records[0][1] != args['rel']:
                continue                                                   # a directory: the walk went through it
            kind = records[0][0]
            if kind != 'l':
                return Final(denial.REFUSED, prompts.render('list_dir_failed', path=shown, reason=os.strerror(errno_.ENOTDIR)))
            here = os.path.join(args['root'], args['rel'])
            tail = [p for p in args['full'].split('/') if p][args['at'] + 1:]
            resolved = os.path.normpath(os.path.join(os.path.dirname(here), records[0][5], *tail))
            refusal = self._reguard(resolved, ctx)
            if refusal:
                return Final(denial.REFUSED, denial.mark(refusal))
            root, rel = split(resolved, ctx.get('wsroot'))
            return Issue(self._next(steps, 'ls', {'root': root, 'rel': rel, 'max_i': 0, 'hop': args['hop'] + 1, 'after': ''}))
        return Final(denial.REFUSED, prompts.render('list_dir_failed', path=shown, reason=os.strerror(wave[0].args['errno'])))

    @staticmethod
    def _reguard(path: str, ctx: dict, write: bool = False) -> str | None:
        """A link cria resolved leads somewhere new; the guards that judged the model's own path judge that one too."""
        from . import dirguard
        from .filecommands import _targets_cria_home
        if (refusal := dirguard.path_refusal(path, write, ctx['level'], ctx.get('wsroot'), tuple(ctx['roots']))):
            return refusal
        return prompts.load('cria_home_refusal') if _targets_cria_home(path) else None

    def _spill(self, op: Op, steps: list, text: str, done: bool, count: int):
        """A listing over the inline limit is saved whole beside the workspace's other reference files, not shortened. One
        command carries CHUNK_BYTES of it; a larger listing is staged as parallel `put` calls and landed by one `write`."""
        from . import webfetch
        data = text.encode('utf-8', 'surrogateescape')
        digest = hashlib.sha256(data).hexdigest()
        rel = webfetch.SPILL_DIR.removeprefix('./') + '/stdout-' + digest + '.txt'
        args = {'root': op.ctx['ws'], 'rel': rel, 'blob': digest, 'try': 0, 'done': done, 'count': count}
        if len(data) <= harnessprims.CHUNK_BYTES:
            return Issue(self._next(steps, 'write', args), {digest: text})
        offsets = range(0, len(data), harnessprims.CHUNK_BYTES)
        return Issue(self._next(steps, 'put', *({**args, 'off': off} for off in offsets[:harnessprims.PUT_WAVE])), {digest: text})

    def _after_put(self, op: Op, wave: list, steps: list):
        bad = next((st for st in wave if st.frame['hdr'].get('ok') != 1), None)
        if bad is None:
            # At most PUT_WAVE chunks go out in one reply (docs/harness-primitives.md section 7): the rest follow, then the landing write.
            args = wave[0].args
            size = len(op.blobs[args['blob']].encode('utf-8', 'surrogateescape'))
            staged = {st.args['off'] for st in steps if st.what == 'put'}
            more = [off for off in range(0, size, harnessprims.CHUNK_BYTES) if off not in staged][:harnessprims.PUT_WAVE]
            if more:
                return Issue(self._next(steps, 'put', *({**args, 'off': off} for off in more)))
            return Issue(self._next(steps, 'write', {**args, 'staged': True}))
        if bad.frame['hdr'].get('ok') == -1:
            return Final(denial.UNKNOWN, prompts.render('list_dir_unknown', path=op.ctx['path']))
        return Final(denial.REFUSED, prompts.load('stdout_spill_failed') + ' ' + _reason(bad.frame['hdr']))

    def _after_write(self, op: Op, wave: list, steps: list):
        from . import webfetch
        st, header = wave[0], wave[0].frame['hdr']
        if header.get('ok') == 1:
            target = webfetch.SPILL_DIR + '/' + st.args['rel'].rsplit('/', 1)[-1]
            if st.args.get('done', True):
                return Final(denial.RAN, webfetch.stdout_spill_pointer(target, listing=True))
            return Final(denial.RAN, prompts.render('list_dir_spill_incomplete', target=target, count=st.args['count'], path=op.ctx['path']))
        if header.get('ok') == -1 and st.args['try'] < 1:
            return Issue(self._next(steps, 'write', {**st.args, 'try': st.args['try'] + 1}))
        if header.get('ok') == -1:
            return Final(denial.UNKNOWN, prompts.render('list_dir_unknown', path=op.ctx['path']))
        return Final(denial.REFUSED, prompts.load('stdout_spill_failed') + ' ' + _reason(header))

    # ---------------------------------------------------------------- what the model sees
    def _project(self, session: str, messages: list, verified: dict, calls: list, log) -> Incoming:
        ops = self.ledger.ops(session)
        finished = {cid: (op, s) for cid, (op, s) in verified.items() if ops[op].final is not None}
        outcomes, reads, writes, facts, out, emitted = {}, {}, {}, [], [], set()

        def answers(cid):
            """The model's call this primitive call stands for: the first step of each of the operation's calls, in order."""
            op, s = finished[cid]
            step = ops[op].steps[s]
            return s if s < len(ops[op].calls) and step.args.get('wave') == 0 else None

        for m in messages:
            if not isinstance(m, dict):
                out.append(m)
                continue
            role = m.get('role')
            if role == 'assistant' and m.get('tool_calls'):
                kept = []
                for c in m['tool_calls']:
                    cid = c.get('id') if isinstance(c, dict) else None
                    if cid in finished and answers(cid) is not None:
                        original = ops[finished[cid][0]].calls[answers(cid)]
                        kept.append({'id': original['id'], 'type': 'function',
                                     'function': {'name': original['name'], 'arguments': original['arguments']}})
                    elif cid not in finished:
                        kept.append(c)
                if len(kept) == len(m['tool_calls']) and kept == m['tool_calls']:
                    out.append(m)
                elif kept or m.get('content'):
                    out.append({**{k: v for k, v in m.items() if k != 'tool_calls'}, **({'tool_calls': kept} if kept else {})})
            elif role == 'tool' and m.get('tool_call_id') in finished:
                op, _ = finished[m['tool_call_id']]
                here = answers(m['tool_call_id'])
                # Each call's answer sits where its own first step's result sits; the answers of calls whose own step never
                # returned a result (a lost reply the operation went on from) sit at the first later result of the operation.
                for i in ([here] if here is not None else range(len(ops[op].calls))):
                    if (op, i) not in emitted:
                        emitted.add((op, i))
                        out.append(self._model_result(ops[op], outcomes, reads, facts, writes, i))
            else:
                out.append(m)
        unrecorded = {cid for cid in self._unrecorded(messages, verified)}
        if unrecorded:
            out = self._label(out, unrecorded, log)
        return Incoming(out, calls, outcomes, reads, tuple(facts), writes)

    def _model_result(self, op: Op, outcomes: dict, reads: dict, facts: list, writes: dict, i: int = 0) -> dict:
        """The tool result the model is shown for one call of a finished operation, and what the wire and the history readers are
        told about it: the outcome, and for a read the verified body, for a file mutation the typed result."""
        from . import resultnotes
        final, original = op.final, op.calls[i]
        if op.kind == writeops.MUTATE:
            r = final['results'][i]
            outcomes[original['id']] = r['o']
            survey = next((st.frame.get('sv', '') for st in op.steps.values() if st.s == 0 and st.frame), '') if i == 0 else ''
            writes[original['id']] = LedgerWrite(original['name'], original['arguments'], r['o'], r.get('text', ''),
                                                 {'ef': r['ef']} if r.get('ef') else {}, survey)
            return {'role': 'tool', 'tool_call_id': original['id'], 'content': r.get('text', '')}
        text, note, outcome = final['text'], final.get('note'), final['outcome']
        body = final.get('src') is not None and op.withheld is None
        if op.kind == readops.READ and op.withheld:
            text, note, outcome, body = '', self.withheld(op), denial.UNKNOWN, False
        message = {'role': 'tool', 'tool_call_id': original['id'], 'content': text}
        if note:
            resultnotes.append_note(message, note)
        outcomes[original['id']] = outcome
        if op.kind == readops.READ:
            pre = final.get('pre', '')
            shown = text[len(pre):] if body else None
            reads[original['id']] = LedgerRead(original['name'], original['arguments'], outcome, shown, pre if body else '',
                                               final.get('observe', '') if body else '', bool(op.ctx.get('instead')))
            if body and not op.settled:
                facts.append(ReadFact(original['id'], tuple(final['src']), shown.encode('utf-8'), bool(op.ctx.get('instead')), pre))
        return message

    def settle(self, session: str, call_ids) -> None:
        """The model's wire accepted these verified reads: they are ordinary results from now on."""
        self._note(session, call_ids, lambda op: {'t': 'settle', 'op': op})

    def withhold(self, session: str, call_ids, kind: str) -> None:
        """The model's wire measured these verified reads and refused them (``overflow``, or ``unknown`` when fit could not be
        established): the model is told so instead of being given the file."""
        if kind not in ('overflow', 'unknown'):
            raise ValueError('invalid fit outcome')
        self._note(session, call_ids, lambda op: {'t': 'withhold', 'op': op, 'kind': kind})

    def _note(self, session: str, call_ids, record) -> None:
        with self._lock:
            ops = self.ledger.ops(session)
            wanted = set(call_ids)
            found = [o for o in ops.values() if o.kind == readops.READ and o.final is not None and o.call.get('id') in wanted]
            if found:
                self.ledger.append(session, *(record(o.op) for o in found))

    @staticmethod
    def _unrecorded(messages: list, verified: dict):
        """Calls whose id verifies against the key but which the ledger has no step for: shown as they are, labelled."""
        for m in messages:
            if isinstance(m, dict) and m.get('role') == 'assistant':
                for c in m.get('tool_calls') or ():
                    cid = c.get('id') if isinstance(c, dict) else None
                    if cid not in verified and callauth.verify(cid, _command_of((c.get('function') or {}).get('arguments'))):
                        yield cid

    @staticmethod
    def _label(messages: list, ids: set, log) -> list:
        from . import resultnotes
        out = []
        for m in messages:
            if isinstance(m, dict) and m.get('role') == 'tool' and m.get('tool_call_id') in ids and isinstance(m.get('content'), str):
                m = dict(m)
                resultnotes.append_note(m, prompts.load('ops_unrecorded'))
                if log is not None:
                    log.emit('ops.unrecorded', level='warn')
            out.append(m)
        return out
