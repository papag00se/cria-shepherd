"""The completion gate through the harness primitives (docs/harness-programs.md section 7, Phase 7; docs/harness-primitives.md 8.11).

One operation in the ledger per gate. The harness runs only what it must run where the project is: the project's own checks, as one shell
text through the ``run`` stub (detached, a timeout, killable by it, every probe's output and exit status written to a file of the run's
private directory). Everything else is decided here, in this process:

* which checks to run and how (``cria.probegate.plan_gate`` composes the text: the project's own argv, nothing of cria's logic);
* waiting (``run wait`` until the run is done, one request at a time, the model not asked), the deadline (cria's clock, recorded in the
  operation), a poll that came back with nothing (asked again, twice), a start whose reply was lost (a ``wait`` for the same token);
* reading the results: ``read`` pages of ``meta`` and of each probe's output file (a page the harness cut asked again smaller, every file
  assembled from its pages and checked against the hash the harness reported for the whole file), the private scratch directory listed
  by ``ls`` for the report of what the gate reclaimed, then the run's directory removed by ``rm`` (the name is derived from the token cria
  chose, so a lost reply needs no answer to remove it);
* what a section is: the output of ``p<i>.out`` and the status ``meta`` recorded for it. No section is found by searching a stream for a
  header, a checker that prints header-shaped lines supplies nothing, and nothing is authenticated by what the output says.

A result is accepted only as a frame for a call cria issued (``cria.ops``): the harness's own words are data. The gate's state is the ledger:
``gate_of`` computes everything the loop needs from the frames, so a restart between any two steps loses nothing.
"""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field

from . import callauth, denial, harnessprims
from .opsteps import Final, Issue
from .readops import LEN_FLOOR, merge
from .readfacts import error as _error

GATE = 'gate'
WHATS = ('grun', 'gpoll', 'gread', 'gls', 'grm')
RUNS = ('grun', 'gpoll')           # the steps that ask whether the run is done
STARTS = ('start', 'fg')           # the modes that begin a run: detached, or in the foreground of the call so that the harness keeps it alive in its own session
WAVE = 16                          # calls in one reply
OPENERLESS_MAX = 2                 # polls in a row that came back with nothing before the poll itself is called broken
TOTAL_MAX = 32 * 1024 * 1024       # bytes of check output cria will hold for one gate: a gate larger than that is UNKNOWN, never a part of it
LS_MAX = 5000                      # entries of the private scratch directory a report names
MAX_PAGES = 400                    # pages of one file: a file that keeps answering and never completes is not read
RUN_RETRIES = 1                    # starts asked again when the harness has no run directory for a token (the first start never ran)
_REFUSAL_PHRASES = ('not permitted', 'rejected:', 'is not allowed', 'permission denied', 'operation not permitted', 'sandbox')
_SECTION_FILE = {'offline': 'offline.out'}
# The harness's own line for a call it yielded while the command still runs (Codex 0.159: `Process running with session ID 85745`). It names the session cria
# continues; it is read only in the result of a call cria issued and verified, and nothing about it is authority (the run's own frame is what ends a gate).
_RUNNING_SESSION = re.compile(r'^Process running with session ID (\d+)\s*$', re.M)
OUTLIVED = ("the check was still running when the harness ended the command that started it, and this harness offers no way to continue a command after "
            "it yields, so a check that takes longer than one command cannot complete here")
STILL_RUNNING = "the check was still running when cria's deadline came: it is stopped, its directory removed, and what it printed is not read"


def running_session(text: str) -> int | None:
    """The session the harness says it kept for the call whose result this is, or None (the call finished, or the harness names none)."""
    found = _RUNNING_SESSION.search(text or '')
    return int(found.group(1)) if found else None


def refusal_reason(result_text: str) -> str:
    """The harness's own words for why it would not run the gate - '' if it does not look like a refusal. Only consulted when nothing came back:
    a gate that ran and merely failed is not a refusal."""
    text = (result_text or '').strip()
    if not text:
        return ''
    low = text.lower()
    for phrase in _REFUSAL_PHRASES:
        i = low.find(phrase)
        if i >= 0:
            return ' '.join(text[max(0, i - 80):i + 160].split())
    return ''


def section_file(sid: str) -> str:
    return _SECTION_FILE.get(sid) or 'p' + sid.rpartition('-')[2] + '.out'


def token(op: str) -> str:
    return hashlib.sha256((callauth.group(op) + 'gate').encode()).hexdigest()[:20]


def text_of(output: str) -> str:
    """A section's text as the checks have always been read: the output's lines, a final newline kept as the empty line it makes, leading line
    breaks of the whole removed (the stream the old transport carried was read that way, and every renderer is written for it)."""
    lines = [ln.rstrip('\r\n') for ln in (output + '\nEXIT:0\n').splitlines(keepends=True)]
    body = '\n'.join(lines).strip('\r\n').splitlines()
    body.pop()                                  # the sentinel line
    return '\n'.join(body)


@dataclass(frozen=True)
class SectionFact:
    """What a rendered section needs to know of the check that made it, once the plan that held it is gone (docs: kind, who composed it, argv)."""
    kind: object
    composed_by_cria: bool
    command: tuple


@dataclass
class GateResult:
    """What one gate learned, computed from its frames (``Ops.gate_of``)."""
    op: str
    workspace: str
    status: str                                  # 'complete': the sections below are what the checks produced; 'unknown': they are not
    reason: str = ''                             # why not, in cria's words (a log line)
    reported: str = ''                           # the harness's own last line about why, verbatim
    refusal: str = ''                            # the harness refused to run it: its own words
    sections: dict = field(default_factory=dict)  # section id -> (text, exit status or None when the check never reported one)
    removed: "list | None" = None                # the private scratch the run reclaimed, relative to it (None: the result carries no report; never so for a gate cria ran)
    failed: "list | None" = None                 # [{path, error}]: what could not be settled (scratch, or the original workspace's identity)
    facts: tuple = ()                            # SectionFact of each candidate, in section order
    scope_known: bool = True

    @property
    def complete(self) -> bool:
        return self.status == 'complete'

    def __deepcopy__(self, memo):
        """A result is read, never changed: a copy of a request body (which can carry megabytes of check output) shares it."""
        return self

    def cleanup(self) -> "tuple | None":
        return None if self.removed is None or self.failed is None else (list(self.removed), list(self.failed))


# ------------------------------------------------------------------------------ the commands
def command(op: str, ctx: dict, s: int, what: str, args: dict, blobs: dict) -> str:
    """The harness command of step ``s``: a pure function of what the ledger recorded (a retried request composes the same bytes)."""
    nonce, safe = callauth.nonce(op, s), ctx['safe']
    if what == 'gpoll':        # a call of the harness's own continuation tool: no command, its content is its session
        return callauth.poll_content(args['session'])
    if what == 'grun':
        script = blobs[ctx['script']] if args['mode'] in STARTS else None
        return harnessprims.compose('run', nonce, [args['mode'], harnessprims.TMPDIR, token(op), ctx['timeout'], ctx['wait'], ctx['root'], 1],
                                    text=script, comment='repository checks', safe_path=safe)
    if what == 'gread':
        return harnessprims.compose('read', nonce, [args['dir'], args['file'], args['off'], args['len'], 0], comment='repository checks (output)', safe_path=safe)
    if what == 'gls':
        return harnessprims.compose('ls', nonce, [args['dir'], 'aux', 0, LS_MAX, 0, '[]', ''], comment='repository checks (scratch)', safe_path=safe)
    return harnessprims.compose('rm', nonce, [harnessprims.TMPDIR, '.ctx-run-' + token(op), 't', '*'], comment='repository checks', safe_path=safe)


def _bytes(frame: dict) -> bytes:
    return frame['text'].encode('utf-8', 'surrogateescape')


class GateOps:
    """The gate half of the engine; ``Ops`` inherits it (``_step``, ``_length``, the ledger and the lock live there)."""

    # ---------------------------------------------------------------- issuing
    def issue_gate(self, session: str, shell_tool: dict, *, root: str, script: str, sections: list, timeout: float, deadline: float,
                   wait: float, facts: tuple, shown: str, scope: tuple = (), continuation: "dict | None" = None) -> tuple:
        """Record a gate and return ``(operation, its first primitive call)``. ``script`` is the shell text the harness runs (the project's own
        checks); ``sections`` the ids of its checks in order; ``timeout`` the seconds after which the harness kills the whole run, ``deadline`` how
        long cria waits for it to be done; ``shown`` the command the model may see for it (the checks it could retype, '' when it has none);
        ``scope`` the directories whose identity the run's start and end are compared on. ``continuation`` is the harness's tool for continuing a call
        it yielded (``shelltool.find_continuation_tool``): the run then starts in the FOREGROUND of its call, which the harness keeps alive in its own
        session when it yields, and cria polls that session; without one the run is detached, and a check that outlives its call cannot complete."""
        from .ledger import LedgerError
        from .opspath import OpsUnavailable
        from .shelltool import shell_args
        with self._lock:
            op = callauth.new_op()
            digest = hashlib.sha256(script.encode('utf-8', 'surrogateescape')).hexdigest()
            ctx = {'shell': shell_tool, 'safe': self.safe_path, 'root': root, 'ws': root, 'wsroot': root, 'script': digest, 'timeout': timeout,
                   'deadline': deadline, 'wait': wait, 'sections': list(sections), 't0': time.time(), 'long': wait > 8, 'scope': list(scope),
                   'cont': continuation, 'fg': continuation is not None,
                   'facts': [{'kind': getattr(f.kind, 'name', str(f.kind)), 'cria': bool(f.composed_by_cria), 'cmd': list(f.command)} for f in facts],
                   'shown': shown}
            call = {'id': callauth.display_id(op), 'name': shell_tool['name'], 'arguments': json.dumps(shell_args(shell_tool, shown))}
            try:
                built = self._step(op, ctx, 0, 'grun', {'wave': 0, 'mode': self._start_mode(ctx), 'n': 0, 'try': 0}, {digest: script})
                if len(built[1].encode('utf-8', 'surrogateescape')) > self.command_budget:
                    raise OpsUnavailable('the checks are larger than one command')
                self.ledger.append(session, {'t': 'op', 'op': op, 'kind': GATE, 'ctx': ctx, 'call': call},
                                   {'t': 'blob', 'op': op, 'h': digest, 'text': script}, built[0])
            except (LedgerError, callauth.KeyUnavailable) as exc:
                raise OpsUnavailable(str(exc)) from exc
            return op, [self._gate_call(ctx, built[0]['id'], built[1], 'grun', built[0]['args'])]

    @staticmethod
    def _start_mode(ctx: dict) -> str:
        return 'fg' if ctx.get('fg') else 'start'

    def resume_gate(self, session: str, op_id: str) -> list:
        """The calls that carry an unfinished gate on after the harness's compaction took its calls out of the history: one more ``wait`` for the
        same run (the run, its directory and its output are where they were). ``[]`` when there is nothing to resume."""
        from .opspath import OpsUnavailable
        with self._lock:
            op = self.ledger.ops(session).get(op_id)
            if op is None or op.kind != GATE or op.final is not None:
                return []
            steps = sorted(op.steps.values(), key=lambda st: st.s)
            runs = [st for st in steps if st.what in RUNS]
            n = (runs[-1].args['n'] if runs else 0) + 1
            live = self._live_session(op.ctx, runs)
            args = ({'wave': steps[-1].args['wave'] + 1, 'n': n, 'try': 0, 'session': live[0], 'run': live[1]} if live
                    else {'wave': steps[-1].args['wave'] + 1, 'mode': 'wait', 'n': n, 'try': 0})
            try:
                built = self._step(op_id, op.ctx, steps[-1].s + 1, 'gpoll' if live else 'grun', args, op.blobs)
                self.ledger.append(session, built[0])
            except Exception as exc:       # noqa: BLE001 - the ledger or the key: nothing to resume with
                raise OpsUnavailable(str(exc)) from exc
            return [self._gate_call(op.ctx, built[0]['id'], built[1], built[0]['what'], args)]

    @staticmethod
    def _live_session(ctx: dict, runs: list):
        """``(session, the step that began the run)`` while the harness holds a session for the run (the last poll is outstanding, or the last answer
        named the session), else None."""
        last = max(runs, key=lambda st: st.s, default=None)
        if not ctx.get('cont') or last is None or last.args.get('mode') == 'wait':
            return None
        session = last.args['session'] if last.what == 'gpoll' and last.frame is None else (last.frame['hdr'].get('session') if last.frame is not None else None)
        started = [st.s for st in runs if st.what == 'grun' and st.args['mode'] in STARTS and st.s <= last.s]
        return (session, max(started)) if session and started else None

    @staticmethod
    def _gate_call(ctx: dict, call_id: str, command: str, what: str = 'grun', args: "dict | None" = None) -> dict:
        """The harness call of a step. A poll of the harness's own session is a call of its continuation tool (cria's, by its id); a call to run
        something that may wait longer than the harness's own yield asks for the time its tool schema offers."""
        from .shelltool import shell_args, with_time_budget
        from .toolwire import _shell_call
        if what == 'gpoll':
            tool = ctx['cont']
            return {'id': call_id, 'type': 'function', 'function': {'name': tool['name'], 'arguments': json.dumps(
                with_time_budget(tool, {'session_id': args['session'], 'chars': ''}))}}
        call = _shell_call(call_id, ctx['shell'], command)
        if ctx.get('long'):
            call['function']['arguments'] = json.dumps(with_time_budget(ctx['shell'], shell_args(ctx['shell'], command)))
        return call

    # ---------------------------------------------------------------- deciding
    def _g_after(self, op, wave: list, steps: list):
        ctx = op.ctx
        removal = next((st for st in steps if st.what == 'grm' and st.frame is not None), None)
        if removal is not None:
            return Final(**removal.args['final'])
        runs = [st for st in steps if st.what in RUNS]
        finished = next((st.frame['hdr'] for st in reversed(runs) if st.frame is not None and st.frame['hdr'].get('ok') == 1
                         and st.frame['hdr'].get('state') == 'done'), None)
        if finished is not None:
            if os.path.basename(str(finished.get('dir', ''))) != '.ctx-run-' + token(op.op):
                return self._g_final(op, steps, 'unknown', 'the checks ran in a directory cria did not name')
            return self._g_read(op, steps, finished)
        last = max(runs, key=lambda st: st.s)
        header = last.frame['hdr']
        mode = last.args.get('mode')
        late = time.time() - ctx['t0'] > ctx['deadline']
        n = max(st.args['n'] for st in runs) + 1
        outlived = lambda: self._g_final(op, steps, 'unknown', STILL_RUNNING if ctx.get('cont') else OUTLIVED)      # noqa: E731
        again = lambda **kw: Issue(self._next(steps, 'grun', {'mode': 'wait', 'n': n, 'try': 0, **kw}))      # noqa: E731
        if header.get('ok') == 1:                                  # running
            return outlived() if late else again()
        if header.get('ok') == 0:
            ran = any(st.frame is not None and st.frame['hdr'].get('ok') == 1 for st in runs)
            if mode in STARTS and header.get('err') == 'FileExistsError':          # the start a lost reply hid had run: ask for the run
                return again()
            if mode == 'wait' and not ran and header.get('errno') in (2, 13) and last.args['try'] < RUN_RETRIES:    # there is no run: the start never happened
                return Issue(self._next(steps, 'grun', {'mode': self._start_mode(ctx), 'n': 0, 'try': last.args['try'] + 1}))
            reason = _error(header.get('errno')) if header.get('errno') else str(header.get('err') or 'the run did not start')
            return self._g_final(op, steps, 'unknown', 'the harness-side check runner failed: ' + reason, reported=reason)
        # no usable frame: the call was cut, lost or refused, or the harness yielded it while the run goes on
        if header.get('said'):
            return self._g_final(op, steps, 'unknown', 'the harness declined to run the checks', refusal=header['said'])
        live = self._live_session(ctx, runs)
        if live is not None and last.frame is not None and header.get('session'):       # the harness kept the run in a session: poll it with its own tool
            if late:
                return outlived()
            return Issue(self._next(steps, 'gpoll', {'session': live[0], 'run': live[1], 'n': n, 'try': 0}))
        if mode in STARTS or last.what == 'gpoll':           # nothing came back and no session lives: the run's own directory says where it is
            return Issue(self._next(steps, 'grun', {'mode': 'wait', 'n': n, 'try': last.args['try']}))
        streak = 0
        for st in sorted(runs, key=lambda st: -st.s):
            if st.frame is not None and st.frame['hdr'].get('ok') == -1 and st.args.get('mode') == 'wait':
                streak += 1
            else:
                break
        if streak > OPENERLESS_MAX:
            return self._g_final(op, steps, 'unknown', 'transport page opener did not arrive, repeatedly - the poll itself is broken')
        if late:
            return outlived()
        return again()

    def _g_read(self, op, steps: list, header: dict):
        """The run is done: read ``meta`` and each check's output, list the private scratch, then remove the run's directory."""
        directory = header['dir']
        issue, total = [], 0
        states = {}
        for name in ['meta'] + [section_file(sid) for sid in op.ctx['sections']]:
            pages = [st for st in steps if st.what == 'gread' and st.args['file'] == name]
            if not pages:
                issue.append(('gread', {'file': name, 'dir': directory, 'off': 0, 'len': self._length(), 'rung': 0}))
                continue
            got = states[name] = self._g_file(pages)
            issue += [('gread', {'file': name, 'dir': directory, 'off': off, 'len': length, 'rung': got['rung']}) for off, length in got['wanted']]
            total += got.get('size') or 0
        if not any(st.what == 'gls' for st in steps):
            issue.append(('gls', {'dir': directory}))
        if issue:
            return Issue(self._next_many(steps, issue[:WAVE]))
        if any(got['status'] == 'failed' for got in states.values()):
            return self._g_final(op, steps, 'unknown', 'the check output could not be read whole')
        if total > TOTAL_MAX:
            return self._g_final(op, steps, 'unknown', 'the check output is larger than cria will hold')
        return self._g_final(op, steps, 'complete', '')

    def _g_file(self, pages: list) -> dict:
        """One output file from its pages: ``status`` (``ok``, ``absent``, ``failed``, ``open``), its bytes, the pages still wanted."""
        out = {'status': 'open', 'bytes': b'', 'wanted': [], 'rung': 0}
        oks = [st for st in pages if st.frame is not None and st.frame['hdr'].get('ok') == 1]
        errs = [st for st in pages if st.frame is not None and st.frame['hdr'].get('ok') == 0]
        cut = sum(1 for st in pages if st.frame is not None and st.frame['hdr'].get('ok') == -1)
        out['rung'] = cut
        if errs:
            out['status'] = 'absent' if not oks and errs[0].frame['hdr'].get('errno') == 2 else 'failed'
            return out
        if len(pages) > MAX_PAGES:
            out['status'] = 'failed'
            return out
        if not oks:
            length = self._length(cut)
            if cut and length <= LEN_FLOOR:
                out['status'] = 'failed'
            else:
                out['wanted'] = [(0, length)]
            return out
        first = oks[0].frame['hdr']
        if any((st.frame['hdr']['fsha'], st.frame['hdr']['size']) != (first['fsha'], first['size']) or st.frame['hdr']['fsize'] != first['size']
               for st in oks):
            out['status'] = 'failed'
            return out
        size = first['size']
        out['size'] = size
        if size > TOTAL_MAX:
            out['status'] = 'ok'
            return out
        length = self._length(cut)
        data, ranges = merge([(st.args['off'], _bytes(st.frame)) for st in oks])
        gaps, pos = [], 0
        for a, b in ranges:
            if a > pos:
                gaps.append((pos, a))
            pos = max(pos, b)
        if pos < size:
            gaps.append((pos, size))
        if gaps:
            if cut and length <= LEN_FLOOR:
                out['status'] = 'failed'
                return out
            out['wanted'] = [(off, length) for a, b in gaps for off in range(a, b, length)]
            return out
        whole = data[:size]
        if len(whole) != size or hashlib.sha256(whole).hexdigest() != first['fsha']:
            out['status'] = 'failed'
            return out
        out.update(status='ok', bytes=whole)
        return out

    def _g_final(self, op, steps: list, status: str, reason: str, *, reported: str = '', refusal: str = ''):
        """The gate's end: its facts are recorded in the final and the run's directory is removed first, so a gate leaves nothing in the harness's
        temporary directory on any path (a verdict, a deadline, an unreadable page, a cut or lost reply)."""
        answer = {'outcome': denial.RAN if status == 'complete' else denial.UNKNOWN, 'text': '',
                  'extra': {'gate': {'status': status, 'reason': reason, 'reported': reported, 'refusal': refusal}}}
        return Issue(self._next(steps, 'grm', {'final': answer}))

    def _next_many(self, steps: list, items: list) -> tuple:
        base, wave = steps[-1].s + 1, steps[-1].args['wave'] + 1
        return tuple((base + i, what, {**args, 'wave': wave}) for i, (what, args) in enumerate(items))

    # ---------------------------------------------------------------- what the gate learned
    def gate_of(self, session: str, op_id: str) -> GateResult | None:
        """The result of a finished gate (None while it runs, or when there is no such gate), computed from its frames."""
        with self._lock:
            op = self.ledger.ops(session).get(op_id)
            return self._gate_cached(op) if op is not None and op.kind == GATE and op.final is not None else None

    def _gate_cached(self, op) -> GateResult:
        if op.op not in self._gates:
            self._gates[op.op] = self._g_result(op)
            while len(self._gates) > 8:
                self._gates.pop(next(iter(self._gates)))
        return self._gates[op.op]

    def _g_result(self, op) -> GateResult:
        steps = sorted(op.steps.values(), key=lambda st: st.s)
        info = op.final.get('gate') or {}
        facts = tuple(self._fact(f) for f in op.ctx.get('facts') or ())
        result = GateResult(op.op, op.ctx.get('wsroot') or '', info.get('status') or 'unknown', info.get('reason') or '', info.get('reported') or '',
                            info.get('refusal') or '', facts=facts)
        if result.status != 'complete':
            return result
        files = {}
        for name in ['meta'] + [section_file(sid) for sid in op.ctx['sections']]:
            files[name] = self._g_file([st for st in steps if st.what == 'gread' and st.args['file'] == name])
        status = {}
        scope = {}
        for line in files['meta']['bytes'].decode('utf-8', 'replace').splitlines():
            parts = line.split(' ')
            if len(parts) >= 2 and parts[0].startswith('scope'):
                scope[parts[0]] = parts[1]
            elif len(parts) == 2:
                try:
                    status[parts[0]] = int(parts[1])
                except ValueError:
                    status[parts[0]] = None
        for sid in op.ctx['sections']:
            got = files[section_file(sid)]
            if got['status'] == 'ok':
                result.sections[sid] = (text_of(got['bytes'].decode('utf-8', 'replace')), status.get(sid))
        result.removed, result.failed = self._g_scratch(steps, op.ctx, scope)
        return result

    @staticmethod
    def _fact(item: dict) -> SectionFact:
        from .probediscovery import ProbeKind
        kind = getattr(ProbeKind, item['kind'], item['kind'])
        return SectionFact(kind, bool(item['cria']), tuple(item['cmd']))

    @staticmethod
    def _g_scratch(steps: list, ctx: dict, scope: dict) -> tuple:
        """What the gate reclaimed (the private scratch directory's entries, children before their directory, each directory with a trailing
        slash, the directory itself last) and what it could not settle (the scratch, and whether the original workspace is still the directory
        it was when the checks began: the same directory by device and inode)."""
        removed, failed = [], []
        listing = next((st for st in steps if st.what == 'gls' and st.frame is not None), None)
        header = listing.frame['hdr'] if listing is not None else {}
        if header.get('ok') == 1:
            records = [json.loads(line) for line in listing.frame['text'].split('\n') if line]
            children: dict = {}
            kinds = {}
            for kind, path, *_ in records:
                parent, _, name = path.rpartition('/')
                children.setdefault(parent, []).append(name)
                kinds[path] = kind

            def walk(directory: str) -> None:
                for name in sorted(children.get(directory, ())):
                    path = directory + '/' + name
                    if kinds.get(path) == 'd':
                        walk(path)
                        removed.append(path + '/')
                    else:
                        removed.append(path)
            walk('aux')
            removed.append('aux/')
            if header.get('done') != 1:
                failed.append({'path': 'aux/', 'error': 'directory listing incomplete'})
        else:
            failed.append({'path': 'aux', 'error': _error(header.get('errno')) if header.get('ok') == 0 else 'could not be listed'})
        for i, directory in enumerate(ctx.get('scope') or ()):
            before, after = scope.get(f'scope{i}-before'), scope.get(f'scope{i}-after')
            if before in (None, '', 'unknown'):
                failed.append({'path': directory, 'error': f"[Errno 2] No such file or directory: '{directory}'"})
            elif before != after:
                failed.append({'path': directory, 'error': 'workspace_identity_changed'})
        return removed, failed
