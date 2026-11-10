"""The gate's checks that cria evaluates itself: the config-file syntax floor (TOML, JSON, XML), decided from files read through the ``read`` primitive.

A completion gate (``cria.gateops``) runs the project's own checks in the harness. A check whose whole job is "does this file parse" needs no program there:
the gate's plan names it (``cria.configfloor.HEADS``, a check of kind SyntaxCheck cria composed, the files in its argv), the harness script does not contain
it, and this mixin reads the files once the run is done (pages of ``read``, asked in parallel, a page the harness cut asked again smaller, every file
assembled from its pages and checked against the hash the harness reported for it), parses them in this process (``cria.configfloor``) and gives the
section the text and exit status the one-liner used to print. Nothing about it runs where the project is.

It extends the gate operation from outside it: ``_g_after`` asks for the pages before the gate reads its own files, and ``_g_result`` adds the sections.
The state is the ledger (the pages are steps of the gate's own operation), so a restart loses nothing. A check that cannot be evaluated (a file larger
than ``configfloor.FILE_MAX``, a page that cannot be made small enough, a file that changed while it was read, a file reached through a link) has no
section: the gate reports it as not run (never as clean).
"""
import errno as errno_
import hashlib
import stat

from . import configfloor, harnessprims
from .gateops import text_of
from .opsteps import Issue
from .opspath import split
from .readops import LEN_FLOOR, merge, uncovered

WHATS = ('fread',)
WAVE = 16                    # pages in one reply
MAX_PAGES = 400              # pages of one file: a file that keeps answering and never completes is not read


def command(op: str, ctx: dict, s: int, what: str, args: dict, blobs: dict) -> str:
    """The harness command of a page: a plain ``read`` (a pure function of what the ledger recorded)."""
    from . import callauth
    return harnessprims.compose('read', callauth.nonce(op, s), [args['root'], args['rel'], args['off'], args['len'], 0],
                                comment='repository checks (config)', safe_path=ctx['safe'])


def _specs(op) -> dict:
    """``{section index: (format, [files])}`` of the checks of this gate that cria evaluates, from the checks the gate recorded."""
    out = {}
    for i, fact in enumerate(op.ctx.get('facts') or ()):
        fmt = configfloor.format_of(fact['kind'], fact['cria'], fact['cmd'])
        if fmt:
            out[i] = (fmt, list(fact['cmd'][1:]))
    return out


class _File:
    """One file of a check as the frames of its pages say: its bytes, or why they are not known."""

    def __init__(self, steps: list, path: str, workspace: str):
        self.path = path
        self.root, self.rel = split(path, workspace)
        self.pieces, self.error, self.size, self.sha, self.cut, self.mixed, self.pages = [], None, None, None, 0, False, 0
        for st in steps:
            if st.what != 'fread' or (st.args['root'], st.args['rel']) != (self.root, self.rel):
                continue
            self.pages += 1
            if st.frame is None:
                continue
            header = st.frame['hdr']
            if header.get('ok') == 1:
                if self.sha not in (None, header['fsha']) or header['size'] != header['fsize']:
                    self.mixed = True
                self.size, self.sha = header['fsize'], header['fsha']
                self.pieces.append((header.get('off') or 0, st.frame['text'].encode('utf-8', 'surrogateescape')))
            elif header.get('ok') == 0:
                self.error = header
            else:
                self.cut += 1                   # a frame the harness cut or that never came: the same page, asked again smaller

    def errno(self):
        """The errno the harness reported for a file it could not read (a directory is EISDIR, as the one-liner's ``open`` said); 0 for what is not a failure of
        the file itself (a link on the way, a device or a pipe: not judged)."""
        code = self.error.get('errno')
        if self.error.get('err') == 'notfile':
            return errno_.EISDIR if stat.S_ISDIR(self.error.get('mode') or 0) else 0
        return 0 if code in (errno_.ELOOP, errno_.ENOTDIR) or not code else code

    def whole(self):
        """The whole file when its pages hold it and it hashes to what the harness reported for it, else None."""
        if self.size is None or self.mixed:
            return None
        prefix, _ = merge(self.pieces)
        return prefix[:self.size] if len(prefix) >= self.size and hashlib.sha256(prefix[:self.size]).hexdigest() == self.sha else None

    def state(self, length_of) -> str:
        """``ok`` (the bytes are in hand), ``error`` (the harness said why it could not read it), ``unknown`` (it cannot be read whole: too large, changed under
        the read, reached through a link, pages that cannot be made small enough) or ``open`` (pages are still to ask)."""
        if self.error is not None:
            return 'error' if self.errno() else 'unknown'
        if self.mixed or self.pages > MAX_PAGES or (self.size or 0) > configfloor.FILE_MAX or (self.cut and length_of(self.cut) <= LEN_FLOOR):
            return 'unknown'
        return 'ok' if self.whole() is not None else 'open'

    def wanted(self, length_of) -> list:
        """The pages still to ask for: the first (smaller after each one the harness cut), then the gaps of what is held."""
        length = length_of(self.cut)
        if self.size is None:
            return [{'off': 0, 'len': length}]
        return [{'off': off, 'len': length} for a, b in uncovered(merge(self.pieces)[1], self.size) for off in range(a, b, length)]


class FloorOps:
    """The gate's cria-evaluated sections; ``Ops`` inherits it before ``GateOps`` (its ``_g_after`` and ``_g_result`` are extended here)."""

    def _f_done(self, steps: list) -> bool:
        return any(st.what in ('grun', 'gpoll') and st.frame is not None and st.frame['hdr'].get('ok') == 1 and st.frame['hdr'].get('state') == 'done'
                   for st in steps)

    def _f_files(self, op, steps: list, specs: dict) -> dict:
        root = op.ctx.get('wsroot') or ''
        return {path: _File(steps, path, root) for _, files in specs.values() for path in files}

    def _g_after(self, op, wave: list, steps: list):
        specs = _specs(op)
        if specs and not any(st.what == 'grm' for st in steps) and self._f_done(steps):
            issue = []
            for path, got in self._f_files(op, steps, specs).items():
                if got.state(self._length) == 'open':
                    issue += [('fread', {'root': got.root, 'rel': got.rel, 'off': w['off'], 'len': w['len']})
                              for w in got.wanted(self._length)]
            if issue:
                return Issue(self._next_many(steps, issue[:WAVE]))
        return super()._g_after(op, wave, steps)

    def _g_result(self, op):
        result = super()._g_result(op)
        specs = _specs(op)
        if not specs or not result.complete:
            return result
        facts = op.ctx.get('facts') or ()
        harness = [i for i in range(len(facts)) if i not in specs]           # the checks the harness ran, by their number in the plan
        sections = {}
        for sid, value in result.sections.items():
            number = sid[len('probe-'):] if sid.startswith('probe-') else ''
            sections[f'probe-{harness[int(number)]}' if number.isdigit() and int(number) < len(harness) else sid] = value
        steps = sorted(op.steps.values(), key=lambda st: st.s)
        files = self._f_files(op, steps, specs)
        for i, (fmt, paths) in specs.items():
            lines, known = [], True
            for path in paths:
                got = files[path]
                state = got.state(self._length)
                if state == 'ok':
                    line = configfloor.error(fmt, got.whole(), path)
                    lines += [line] if line else []
                elif state == 'error':
                    lines.append(configfloor.unreadable(path, got.errno()))
                else:
                    known = False
            if known:
                sections[f'probe-{i}'] = (text_of(''.join(line + '\n' for line in lines)), 1 if lines else 0)
        # in the order of the plan (the checks' findings are read in it), and what is not a check of the plan (the offline re-run) after them
        number = lambda sid: int(sid[len('probe-'):]) if sid.startswith('probe-') else len(facts)      # noqa: E731
        result.sections = dict(sorted(sections.items(), key=lambda item: number(item[0])))
        return result
