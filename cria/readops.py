"""Reads through the ``read`` primitive: what cria decides and what it composes, in this process (docs/harness-primitives.md 8.7).

The harness returns bytes and the file's identity; everything else happens here. A read is one operation in the ledger
(:mod:`cria.ledger`) that cria carries out as one ``read`` call or a few:

* the first frame names the file's size and sha-256, so cria knows how many pages remain before it fetches any, answers a
  read that cannot fit the model's measured window without transporting the file, and asks for the remaining pages as
  parallel byte ranges (at most ``WAVE`` calls per reply). A frame the harness cut is asked again at half the size.
* every frame of one read carries the sha-256 of the whole file as that call saw it. Frames that disagree, or whose
  assembled bytes do not hash to it, mean the file changed under the read: it is read again once, then the model is told
  so. There is no private copy of the file anywhere: equal hashes are one file state.
* a numbered window (``start_line``/``end_line``) is cut from the bytes cria holds, with today's ``N: text`` numbering and
  today's answers for an inverted range and a range past the end of the file.
* a refused path (a link below the workspace, ``ELOOP``/``ENOTDIR``) is resolved by cria itself and judged by the same
  guards as the path the model named, then read again; a missing, unreadable or non-regular file is answered in cria's own
  words, the same words as before.

The text the model reads, and the facts the model's wire binds to it (the verified source identity and the exact body), are
fields of the ledger's ``final`` record. Nothing here parses a marker out of text for authority.
"""
import errno as errno_
import hashlib
import json
import os
import stat
from dataclasses import dataclass

from . import denial, filecache, harnessprims, prompts, readshape
from .ledger import LedgerError
from .opspath import OpsUnavailable, split
from .opsteps import Final, Issue
from .toolargs import patch_paths, tool_path

READ = 'read'
# Raw bytes one frame is asked to carry: sized from the compression the last sizable frame showed (the first page assumes
# text that compresses 2.7x, docs/harness-primitives.md 4); a frame whose result the harness cut (over ~10,000 bytes on the
# wire) is asked again at half the size, each rung halving, down to LEN_FLOOR.
ROOM_CHARS = harnessprims.PAGE_BYTES - 1_000      # wire characters one frame's payload may use beside the header and the harness's own lines
OVERHEAD_CHARS = 500                              # what a frame's header and the harness's envelope add to its payload
DEFAULT_RATE = 0.5625                             # payload characters per raw byte before any frame has been seen (16,000 raw bytes per page)
LEN_FLOOR = 250
MAX_PAGE_LEN = 64_000
WAVE = 8                    # pages asked for in one reply
ROUNDS = 2                  # reads of one path before a file that keeps changing is reported as such
MAX_HOPS = 8
TRANSPORT_MAX = filecache.CAP_BYTES               # a file beyond what cria will hold in memory is not transported
_PAST = '(no lines in that range — %s has %%N%% lines; line %d is past the end of the file)\n'


@dataclass(frozen=True)
class ReadFact:
    """A verified read the model's wire must keep whole until it has been delivered: the call, the source (size, sha-256),
    the exact body, whether it answers a held write, and the prose that precedes the body."""
    call_id: str
    source: tuple
    exact_body: bytes
    read_instead: bool
    pre: str


@dataclass(frozen=True)
class LedgerRead:
    """What ``represent_inbound`` needs to treat a projected read as the lowered call it was: the model's call, how it ended,
    and the verified body (None when no body was returned)."""
    name: str
    arguments: str
    kind: str
    text: str | None
    pre: str
    observe: str
    hold: bool


def display_path(path: str) -> str:
    return path if len(path.encode('utf-8', 'surrogateescape')) <= 1024 else 'the requested path'


def want(name: str, args: dict, instead: bool) -> tuple[int, int]:
    """The 1-based inclusive line window a call asks for, ``(0, 0)`` for the whole file (today's alias rules: an end alone is a
    prefix; anything but a positive integer start is a whole read)."""
    if instead:
        return 0, 0
    start, end = args.get('start_line', 0), args.get('end_line', 0)
    if 'start_line' not in args and type(end) is int and end > 0:
        start = 1
    if not isinstance(start, int) or start <= 0:
        return 0, 0
    return int(start), int(end) if isinstance(end, int) and end > 0 else 0


def canonical_read_args(args: dict) -> dict | None:
    """The precise read identity of an alias read: ``{path, start_line?, end_line?}`` (an end alone is a prefix), or None without a path."""
    path = tool_path(args)
    if not path:
        return None
    original = {'path': path}
    start, end = args.get('start_line'), args.get('end_line')
    if 'start_line' not in args and type(end) is int and end > 0:
        start = 1
    if isinstance(start, int) and start > 0:
        original['start_line'] = start
        if isinstance(end, int) and end > 0:
            original['end_line'] = end
    return original


def target_path(name: str, call: dict, args: dict) -> str | None:
    if name == 'apply_patch':
        paths = patch_paths(call)
        return paths[0] if len(paths) == 1 else None
    return tool_path(args)


def window(raw: bytes, start: int, end: int, shown: str, whole: bool) -> tuple[bytes, bool]:
    """``(body, past)``: the numbered window of ``raw`` (``N: text`` per line), or the answer for a start past the last line.
    ``raw`` is the whole file, or only a prefix of it that holds at least ``end`` newlines (``whole`` False)."""
    lines = raw.split(b'\n')
    if whole and lines and lines[-1] == b'':
        lines.pop()
    if start > len(lines):
        head, _, tail = (_PAST % (shown, start)).rpartition('%N%')
        return (head + str(len(lines)) + tail).encode(), True
    chosen = lines[start - 1:end] if end else lines[start - 1:]
    return b''.join(b'%d: %s\n' % (start + i, line) for i, line in enumerate(chosen)), False


def merge(frames: list) -> tuple[bytes, list]:
    """``(prefix, ranges)``: the bytes contiguous from offset 0 that ``frames`` ``[(offset, data)]`` cover, and the covered
    ranges ``[(start, end)]``."""
    spans = sorted((off, off + len(data), data) for off, data in frames if data)
    prefix, ranges = bytearray(), []
    for a, b, data in spans:
        if ranges and a <= ranges[-1][1]:
            if b > ranges[-1][1]:
                ranges[-1] = (ranges[-1][0], b)
        else:
            ranges.append((a, b))
        if a <= len(prefix) < b:
            prefix += data[len(prefix) - a:]
    return bytes(prefix), ranges


class ReadOps:
    """The read half of the engine; ``Ops`` inherits it (``_step``, ``_next``, ``_reguard``, the cache and the ledger live there)."""

    # ---------------------------------------------------------------- sizing
    def _length(self, rung: int = 0) -> int:
        """Raw bytes the next frames are asked to carry, at ``rung`` halvings."""
        return max(LEN_FLOOR, min(MAX_PAGE_LEN, int(ROOM_CHARS / self._rate)) >> rung)

    def _learn(self, header: dict, frame: dict) -> None:
        """The compression a sizable frame showed sets the size of the next ones (conservatively: a page of the same file that
        compresses worse than its neighbour is a cut frame asked again, never a wrong answer)."""
        n, wire = header.get('n') or 0, frame.get('wire') or 0
        if n >= 2_000 and wire > OVERHEAD_CHARS:
            self._rate = max(0.05, (wire - OVERHEAD_CHARS) / n * 1.15)

    # ---------------------------------------------------------------- issuing
    def issue_read(self, session: str, shell_tool: dict, call: dict, args: dict, *, workspace_root: str | None, level: str,
                   roots=(), instead: dict | None = None) -> dict | None:
        """Record a read and return its first primitive call; None when the call names no path. ``instead`` is a held write
        answered with this read: ``{'fact': ...}``."""
        with self._lock:
            return self._issue_read(session, shell_tool, call, args, workspace_root, level, roots, instead)

    def _issue_read(self, session, shell_tool, call, args, workspace_root, level, roots, instead) -> dict | None:
        from . import callauth
        from .toolwire import _shell_call
        fn = call.get('function') or {}
        name = fn.get('name')
        path = target_path(name, call, args)
        if not path:
            return None
        start, end = want(name, args, bool(instead))
        root, rel = split(path, workspace_root)
        op = callauth.new_op()
        pre, not_read = '', ''
        if instead:
            from .filecommands import read_instead_prose
            pre, not_read = read_instead_prose(instead['fact'], name)
        ctx = {'path': path, 'shell': shell_tool, 'safe': self.safe_path, 'ws': workspace_root or '.', 'wsroot': workspace_root,
               'level': level, 'roots': list(roots), 'tool': name, 'start': start, 'end': end,
               'instead': bool(instead), 'pre': pre, 'not_read': not_read}
        record = {'t': 'op', 'op': op, 'kind': READ, 'ctx': ctx,
                  'call': {'id': call.get('id'), 'name': name, 'arguments': fn.get('arguments')}}
        try:
            if instead and instead.get('again'):
                # A second held write to one path in a batch: the first read answers for them all, this one says only that it did not run.
                with denial.unframed():
                    again = Final(denial.REFUSED, denial.mark(not_read), {'hold': True})
                return self._say(session, record, op, ctx, '', again)
            if start and end and end < start:
                shown = lambda n: str(n) if n.bit_length() < 400 else None
                return self._say(session, record, op, ctx, prompts.render(
                    'inverted_range', path=display_path(path), start=shown(start) or 'the requested start',
                    end=shown(end) or 'the requested end'))
            warm = self.cache.get(root, rel) is not None
            step = self._step(op, ctx, 0, READ, {'wave': 0, 'root': root, 'rel': rel, 'off': 0, 'hop': 0, 'rung': 0, 'round': 1,
                                                  'len': 0 if warm else self._length()})
            if len(step[1].encode()) > self.command_budget:
                return self._say(session, record, op, ctx, prompts.render(
                    'read_path_too_long', size=len(path.encode('utf-8', 'surrogateescape')), limit=self.command_budget - 3000))
            self.ledger.append(session, record, step[0])
        except (LedgerError, callauth.KeyUnavailable) as exc:
            raise OpsUnavailable(str(exc)) from exc
        return _shell_call(step[0]['id'], shell_tool, step[1])

    def _say(self, session: str, record: dict, op: str, ctx: dict, text: str, final: Final | None = None) -> dict:
        """A read cria refuses before asking the harness anything: one short call prints cria's own words (the harness shows and
        records what the model is told), and the ledger holds the same words as the final text."""
        from .toolwire import _shell_call
        final = final or self._refusal(ctx, text)
        step = self._step(op, ctx, 0, 'say', {'wave': 0, 'text': final.text})
        self.ledger.append(session, record, step[0], {'t': 'final', 'op': op, 'outcome': final.outcome, 'text': final.text, **final.extra})
        return _shell_call(step[0]['id'], ctx['shell'], step[1])

    @staticmethod
    def _refusal(ctx: dict, text: str) -> Final:
        """cria's words, marked as a call that did not run (after the held write's own words), and the logical exit status the
        model has always been told beside a refusal."""
        with denial.unframed():
            marked = (denial.mark(ctx['not_read']) if ctx['instead'] else '') + denial.mark(text)
        return Final(denial.REFUSED, marked, {'note': prompts.render('read_status', code=1), 'hold': ctx['instead']})

    # ---------------------------------------------------------------- deciding
    def _after_read(self, op, wave: list, steps: list):
        ctx, args0 = op.ctx, wave[0].args
        current = [st for st in steps if st.what == READ and st.args['round'] == args0['round']]
        for st in wave:
            if st.frame['hdr'].get('ok') == 0:
                return self._read_error(op, st, steps, any(s.frame['hdr'].get('ok') == 1 for s in current))
        good = [(st, st.frame['hdr']) for st in current if st.frame['hdr'].get('ok') == 1]
        cut = any(st.frame['hdr'].get('ok') == -1 for st in wave)
        if not good:
            return self._ask_smaller(op, steps, args0, None, [])
        size, sha = good[0][1]['fsize'], good[0][1]['fsha']
        if any((h['fsha'], h['fsize'], h['size']) != (sha, size, size) for _, h in good):
            return self._changed(op, steps, args0)
        for st, header in good:
            self._learn(header, st.frame)
        pieces = [(h['off'], st.frame['text'].encode('utf-8', 'surrogateescape')) for st, h in good]
        held = self.cache.prefix(args0['root'], args0['rel'], sha, size)
        prefix, ranges = merge(pieces + ([(0, held)] if held else []))
        complete = len(prefix) >= size
        if complete and hashlib.sha256(prefix[:size]).hexdigest() != sha:
            return self._changed(op, steps, args0)
        if complete or (ctx['start'] and ctx['end'] and prefix.count(b'\n') >= ctx['end']):
            return self._deliver(op, prefix[:size] if complete else prefix, size, sha, complete, args0)
        if not ctx['start'] and len(good) == 1 and good[0][1].get('off') == 0 and (verdict := self._early(op, prefix, size)) is not None:
            return verdict
        if cut:
            return self._ask_smaller(op, steps, args0, size, ranges)
        return self._more(op, steps, {**args0, 'rung': 0}, size, ranges)       # the learned rate already sizes the pages: a cut is what halves them

    def _early(self, op, prefix: bytes, size: int):
        """A whole read of a file larger than the whole of the model's measured window is not transported. The room is a strict
        lower bound (the chars/4 estimate of the file against the window less the reserve: no frame, no safety factor), so a file
        this large cannot fit however the rest of the request shrinks. A first page without a newline may be the start of one
        enormous line, whose measured shape the note needs from the whole file: that read is transported as before, unless
        the file is beyond what cria will hold at all."""
        if size > TRANSPORT_MAX:
            return self._not_delivered(op, 'overflow', size, None)
        room = self.room() if callable(self.room) else self.room           # asked only when a read's first frame is in hand
        if not room or b'\n' not in prefix or size // 4 <= room:
            return None
        return self._not_delivered(op, 'overflow', size, None)

    def _more(self, op, steps: list, args: dict, size: int, ranges: list):
        """The next wave of pages: the uncovered ranges of the file at the rung's size, at most ``WAVE`` calls (a window deep in
        a file doubles its reach each reply: it may be satisfied by the next page)."""
        length, gaps, pos = self._length(args['rung']), [], 0
        for a, b in ranges:
            if a > pos:
                gaps.append((pos, a))
            pos = max(pos, b)
        if pos < size:
            gaps.append((pos, size))
        pages = [off for a, b in gaps for off in range(a, b, length)]
        waves = len({st.args['wave'] for st in steps if st.what == READ and st.args['round'] == args['round']})
        pages = pages[:min(WAVE, 2 ** waves) if op.ctx['start'] else WAVE]
        if not pages or pages[0] >= TRANSPORT_MAX:
            return self._not_delivered(op, 'overflow', size, None) if pages else self._unverified()
        return Issue(self._next(steps, READ, *({**args, 'off': off, 'len': length} for off in pages)))

    def _ask_smaller(self, op, steps: list, args: dict, size: int | None, ranges: list):
        """A frame the harness cut: the same range again, at half the size."""
        rung = args['rung'] + 1
        if self._length(rung) <= LEN_FLOOR:
            return self._unverified()
        if size is None:
            return Issue(self._next(steps, READ, {**args, 'rung': rung, 'len': self._length(rung)}))
        return self._more(op, steps, {**args, 'rung': rung}, size, ranges)

    def _changed(self, op, steps: list, args: dict):
        """The file changed while it was being read: read it again from the start, once; a second change is reported."""
        if args['round'] < ROUNDS:
            return Issue(self._next(steps, READ, {**args, 'round': args['round'] + 1, 'off': 0, 'len': self._length(), 'rung': 0}))
        return Final(denial.UNKNOWN, '', {'note': prompts.render('read_changed', path=display_path(op.ctx['path'])),
                                          'hold': op.ctx['instead']})

    @staticmethod
    def _unverified() -> Final:
        return Final(denial.UNKNOWN, '', {'note': prompts.load('read_unverified')})

    # ---------------------------------------------------------------- the answers
    def _deliver(self, op, data: bytes, size: int, sha: str, complete: bool, args: dict):
        """The read is verified: compose what the model reads."""
        ctx = op.ctx
        self.cache.put(args['root'], args['rel'], sha, size, data)
        if ctx['start']:
            body, past = window(data, ctx['start'], ctx['end'], display_path(ctx['path']), complete)
            observe = '' if past else 'range'
        else:
            body, past, observe = data, False, 'whole'
        try:
            text = body.decode('utf-8', 'strict')
        except UnicodeDecodeError:
            return self._not_delivered(op, 'binary', size, None)
        if past:
            return Final(denial.RAN, text, {'observe': '', 'hold': ctx['instead']})
        return Final(denial.REFUSED if ctx['instead'] else denial.RAN, ctx['pre'] + text,
                     {'observe': observe, 'pre': ctx['pre'], 'src': [size, sha], 'hold': ctx['instead']})

    def _not_delivered(self, op, why: str, size: int, body: bytes | None) -> Final:
        """A verified read the model is not given: a file that is not text, or one that cannot fit its window."""
        ctx = op.ctx
        if why == 'binary':
            note = readshape.binary_note(size, ctx['path'], self.menu)
        else:
            shape = None if body is None else readshape.measure(body, numbered=bool(ctx['start']), first=ctx['start'] or 1)
            note = prompts.render('read_overflow', bytes=f'{size}', next=readshape.overflow_next(
                shape, ctx['path'], self.menu, window=bool(ctx['start'] or ctx['end'])))
        return Final(denial.UNKNOWN, '', {'note': note, 'hold': ctx['instead']})

    def withheld(self, op) -> str:
        """The note the model reads, with no content, for a verified read its wire measured and refused (``overflow`` or
        ``unknown``)."""
        ctx, final = op.ctx, op.final
        if op.withheld == 'overflow':
            body = final['text'][len(final.get('pre', '')):].encode('utf-8', 'surrogateescape')
            shape = readshape.measure(body, numbered=bool(ctx['start']), first=ctx['start'] or 1)
            return prompts.render('read_overflow', bytes=f"{final['src'][0]}", next=readshape.overflow_next(
                shape, ctx['path'], self.menu, window=bool(ctx['start'] or ctx['end'])))
        return prompts.load('read_fit_unknown')

    # ---------------------------------------------------------------- failures
    def _read_error(self, op, st, steps: list, seen: bool):
        header, args = st.frame['hdr'], st.args
        code = header.get('errno')
        if seen:
            return self._changed(op, steps, args)                  # it was there a moment ago
        if code in (errno_.ELOOP, errno_.ENOTDIR) and args['rel']:
            if args['hop'] >= MAX_HOPS:
                return self._failure(op, 'unreadable')
            # Which component is a link is never guessed: stat each prefix, the path itself included, all in one reply.
            prefix, prefixes = '', []
            for part in [p for p in args['rel'].split('/') if p]:
                prefix = f'{prefix}/{part}' if prefix else part
                prefixes.append(prefix)
            return Issue(self._next(steps, 'stat', *({**args, 'rel': p, 'errno': code, 'at': i, 'full': args['rel']}
                                                      for i, p in enumerate(prefixes))))
        if header.get('err') == 'notfile':
            return self._failure(op, 'is_directory' if stat.S_ISDIR(header.get('mode') or 0) else 'unreadable')
        if code in (errno_.ENOENT, errno_.ENOTDIR):
            return self._failure(op, 'missing')
        return self._failure(op, 'is_directory' if code == errno_.EISDIR else 'unreadable')

    def _failure(self, op, key: str) -> Final:
        return self._refusal(op.ctx, prompts.fill(prompts.load_map('read_failed')[key], path=display_path(op.ctx['path'])))

    def _after_read_stat(self, op, wave: list, steps: list):
        ctx = op.ctx
        for st in sorted(wave, key=lambda x: x.args['at']):
            header, args = st.frame['hdr'], st.args
            if header.get('ok') != 1:
                return self._failure(op, 'missing' if header.get('errno') in (errno_.ENOENT, errno_.ENOTDIR) else 'unreadable')
            records = [json.loads(line) for line in st.frame['text'].split('\n') if line]
            if not records or records[0][1] != args['rel']:
                continue                                           # a directory: the walk went through it
            parts = [p for p in args['full'].split('/') if p]
            if records[0][0] != 'l':
                return self._failure(op, 'missing' if args['at'] + 1 < len(parts) else 'unreadable')
            here = os.path.join(args['root'], args['rel'])
            resolved = os.path.normpath(os.path.join(os.path.dirname(here), records[0][5], *parts[args['at'] + 1:]))
            if (refusal := self._reguard(resolved, ctx)):
                return self._refusal(ctx, refusal)
            root, rel = split(resolved, ctx.get('wsroot'))
            return Issue(self._next(steps, READ, {'root': root, 'rel': rel, 'off': 0, 'hop': args['hop'] + 1, 'rung': 0,
                                                  'round': args['round'], 'len': self._length()}))
        return self._failure(op, 'unreadable')
