"""The unread-write probe: cria asks the file, when a write names it and nothing known settles whether it may be overwritten (docs/harness-programs.md section 7,
Phase 6b; docs/harness-primitives.md 8.10).

The rule that stands on this (``Loop.unread_target_check``): credit first (a file the coder read, or wrote, and whose retained history still shows it is not
asked); else what the view and the initial inventory know (a missing file, a blank one); else the file. The inventory is names, sizes and symbols - no per-file
read - so the question is asked at the one moment it matters, in the way the harness can answer it: one ``read`` of the first ``FACT_LEN`` bytes (a second, of the
whole file, only when those are whitespace), decided here (:mod:`cria.readfacts`).

A probe is an operation in the ledger that cria asks on its own, in place of the model's call, and answers to nobody:

* ``issue_probe`` takes the model's write (and the calls that follow it in the same reply, so nothing overtakes it) out of the reply, records them in the
  operation and returns the ``read`` call instead. The model never sees the probe: its call comes back, lowered, when the answer is known.
* the operation ends with what the file said (``blank``, ``digest``, ``size``, or that it is missing, or that nothing could be learned). ``release`` hands the
  held calls back - once: it records that it did - together with those facts, to the loop, which lowers the calls again with the facts in hand.

A restart between the probe and its release loses nothing (the held calls and the frames are in the ledger); a reply that never reached the harness after the
release is the model asking again, as for any call.
"""
import errno as errno_
import time

from . import callauth, denial, readfacts
from .ledger import LedgerError
from .opsteps import Final, Issue
from .opspath import OpsUnavailable, split

from dataclasses import dataclass

PROBE = 'probe'
WHATS = ('pread',)


@dataclass(frozen=True)
class UnreadProbe:
    """What the unread-write rule answers when it cannot decide: the file at ``path`` is to be asked."""
    path: str


def command(op: str, ctx: dict, s: int, what: str, args: dict, blobs: dict) -> str:
    """The harness command of step ``s``: a pure function of what the ledger recorded (a retried request composes the same bytes)."""
    from . import harnessprims
    return harnessprims.compose('read', callauth.nonce(op, s), [args['root'], args['rel'], 0, args['len'], 0], comment='unread-write check ' + ctx['path'],
                                safe_path=ctx['safe'])


class ProbeOps:
    """The probe half of the engine; ``Ops`` inherits it (``_step``, ``_next`` and the ledger live there)."""

    def issue_probe(self, session: str, shell_tool: dict, path: str, held: list, *, workspace_root: str | None, level: str, roots=()) -> dict:
        """Record a probe of ``path`` holding the model's calls ``held`` (dicts with an id, a name and arguments) and return its first primitive call."""
        from .toolwire import _shell_call
        root, rel = split(path, workspace_root)
        with self._lock:
            op = callauth.new_op()
            ctx = {'path': path, 'shell': shell_tool, 'safe': self.safe_path, 'ws': workspace_root or '.', 'wsroot': workspace_root, 'level': level,
                   'roots': list(roots), 'root': root, 'rel': rel, 'held': held, 'at': time.time()}
            record = {'t': 'op', 'op': op, 'kind': PROBE, 'ctx': ctx, 'call': {}}
            try:
                step = self._step(op, ctx, 0, 'pread', {'wave': 0, 'root': root, 'rel': rel, 'len': readfacts.FACT_LEN, 'whole': False, 'hop': 0})
                self.ledger.append(session, record, step[0])
            except (LedgerError, callauth.KeyUnavailable) as exc:
                raise OpsUnavailable(str(exc)) from exc
            return _shell_call(step[0]['id'], shell_tool, step[1])

    def release(self, session: str) -> tuple:
        """``(the held calls, the facts)`` of every finished probe not yet released, and the record that they were: a call is handed back once."""
        with self._lock:
            done = [o for o in self.ledger.ops(session).values() if o.kind == PROBE and o.final is not None and not o.settled]
            if not done:
                return [], []
            self.ledger.append(session, *({'t': 'settle', 'op': o.op} for o in done))
            return [call for o in done for call in o.ctx['held']], [o.final['facts'] for o in done]

    # ---------------------------------------------------------------- deciding
    def _p_after(self, op, wave: list, steps: list):
        st = wave[0]
        header, args = st.frame['hdr'], st.args
        rel = op.ctx['rel']
        facts = {'rel': op.ctx['path'], 'path': rel, 'at': op.ctx['at']}
        if header.get('ok') == 1:
            data = st.frame['text'].encode('utf-8', 'surrogateescape')
            blank, digest, changed, more = readfacts.decide(header, data, args['whole'])
            if more:
                return Issue(self._next(steps, 'pread', {**args, 'len': min(readfacts.FACT_FULL, header['fsize']), 'whole': True}))
            if changed:
                return Final(denial.RAN, '', {'facts': {**facts, 'blank': None, 'digest': None, 'size': header['fsize'], 'unavailable': 'changed'}})
            return Final(denial.RAN, '', {'facts': {**facts, 'blank': blank, 'digest': digest, 'size': header['fsize'],
                                                     'unavailable': None if blank is not None else 'not_text'}})
        if header.get('ok') == 0:
            code = header.get('errno')
            if header.get('err') == 'notfile':
                return Final(denial.RAN, '', {'facts': {**facts, 'blank': None, 'digest': None, 'size': None, 'unavailable': 'not_a_file'}})
            if code == errno_.ENOENT:
                return Final(denial.RAN, '', {'facts': {**facts, 'blank': None, 'digest': None, 'size': None, 'missing': True, 'unavailable': None}})
            return Final(denial.RAN, '', {'facts': {**facts, 'blank': None, 'digest': None, 'size': None, 'unavailable': 'unreadable'}})
        # a frame that did not come back whole: asked again at half the size, then said (the write is then admitted and the event says why)
        length = args['len'] >> 1
        if length >= readfacts.FACT_FLOOR:
            return Issue(self._next(steps, 'pread', {**args, 'len': length}))
        return Final(denial.RAN, '', {'facts': {**facts, 'blank': None, 'digest': None, 'size': None, 'unavailable': 'no_answer'}})
