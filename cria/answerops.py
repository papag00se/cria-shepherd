"""Answers cria composes itself, carried out through the harness primitives (docs/harness-programs.md section 7, Phase 6b; docs/harness-primitives.md 8.8).

``web_fetch`` and ``web_search`` are made in this process (cria holds the page, the Brave answer, the reduced text, the gates); what the harness is for is
to be a place where the model's call visibly ran and where a file can be saved. An answer is one operation in the ledger (:mod:`cria.ledger`):

* an answer that stands on its own is one ``say`` call (the shell builtin that prints cria's words, so the harness shows and records what the model is
  told) and the ledger holds the same words as the final text;
* an answer that comes with a file (a fetched document too large to inline, a search's full results, a result larger than the harness returns whole) is the
  file written through ``write`` (``put`` waves for a text past one command, the same as a listing's spill), no-follow and atomic, and the answer is true
  only once the harness confirmed the landing: the final text is the pointer, the stored fact (target, byte count, sha-256) is a field of the final record
  cria computed from the bytes it sent, and the externalization offer settles from the ledger (:func:`cria.writeproxy.settle_externalizations`), never from
  a record a harness program printed.

Nothing is cut: the file holds the whole text (the 46,080-byte cut of the shell-and-base64 spill is gone with the command that needed it).
"""
import hashlib
from dataclasses import dataclass

from . import denial, harnessprims, prompts
from .ledger import LedgerError
from .opsteps import Final, reason as _reason
from .toolwire import _shell_call

ANSWER = 'answer'


@dataclass(frozen=True)
class LedgerAnswer:
    """An answer cria composed and carried out (a fetch, a search, a grep, a glob), as the history readers see it: the model's own call, how it ended,
    the text the model is told and the typed facts (``rep``) its readers ask for."""
    name: str
    arguments: str
    kind: str
    text: str
    rep: dict | None


class AnswerOps:
    """The answer half of the engine; ``Ops`` inherits it (``_step``, ``_next`` and the ledger live there)."""

    def issue_answer(self, session: str, shell_tool: dict, call: dict, answer, *, workspace_root: str | None, level: str, roots=()) -> dict:
        """Record the answer to ``call`` and return its first primitive call. ``answer`` is a :class:`cria.toolcontracts.AnswerIntent`."""
        from . import callauth
        from .opspath import OpsUnavailable
        fn = call.get('function') or {}
        save = answer.save
        ctx = {'tool': answer.tool, 'path': answer.label, 'shell': shell_tool, 'safe': self.safe_path, 'ws': workspace_root or '.', 'wsroot': workspace_root,
               'level': level, 'roots': list(roots), 'text': answer.text, 'outcome': answer.outcome, 'rep': answer.rep or {}}
        with self._lock:
            op = callauth.new_op()
            record = {'t': 'op', 'op': op, 'kind': ANSWER, 'ctx': ctx, 'call': {'id': call.get('id'), 'name': fn.get('name'), 'arguments': fn.get('arguments')}}
            try:
                if save is None:
                    step = self._step(op, ctx, 0, 'say', {'wave': 0, 'text': answer.text, 'ok': answer.outcome != denial.REFUSED})
                    final = {'t': 'final', 'op': op, 'outcome': answer.outcome, 'text': answer.text, **({'rep': answer.rep} if answer.rep else {})}
                    self.ledger.append(session, record, step[0], final)
                    return _shell_call(step[0]['id'], shell_tool, step[1])
                data = save.content.encode('utf-8', 'surrogateescape')
                digest = hashlib.sha256(data).hexdigest()
                ctx['save'] = {'target': save.target, 'operation': save.operation, 'size': len(data), 'sha': digest}
                args = {'root': ctx['ws'], 'rel': save.target.removeprefix('./'), 'blob': digest, 'try': 0}
                if len(data) <= harnessprims.CHUNK_BYTES:
                    steps = [self._step(op, ctx, 0, 'write', {'wave': 0, **args}, {digest: save.content})]
                else:
                    offsets = range(0, len(data), harnessprims.CHUNK_BYTES)
                    steps = [self._step(op, ctx, i, 'put', {'wave': 0, **args, 'off': off}, {digest: save.content})
                             for i, off in enumerate(offsets[:harnessprims.PUT_WAVE])]
                self.ledger.append(session, record, {'t': 'blob', 'op': op, 'h': digest, 'text': save.content}, *(s[0] for s in steps))
            except (LedgerError, callauth.KeyUnavailable) as exc:
                raise OpsUnavailable(str(exc)) from exc
            return _shell_call(steps[0][0]['id'], shell_tool, steps[0][1])

    # ---------------------------------------------------------------- deciding
    def _answer_final(self, op, how: str, header: dict | None = None):
        """How an answer that saved a file ended. ``how`` is ``landed`` (the harness confirmed the bytes cria sent: the answer is true), ``unknown`` (no
        confirmation) or ``failed`` (the harness refused: ``header`` says why)."""
        ext = self._ext(op)
        if how == 'landed':
            return Final(op.ctx['outcome'], op.ctx['text'], {'rep': {**op.ctx['rep'], **({'st': ext['stored']} if ext.get('stored') else {})}, 'ext': ext})
        if how == 'unknown':
            return Final(denial.UNKNOWN, prompts.render('answer_unknown', target=op.ctx['save']['target']), {'ext': {**ext, 'stored': None}})
        return Final(denial.REFUSED, prompts.load('stdout_spill_failed') + ' ' + _reason(header or {}), {'ext': {**ext, 'stored': None}})

    @staticmethod
    def _ext(op) -> dict:
        """What the externalization offer settles on: the offer's operation, the target and, once the bytes landed, the stored fact (the
        byte count and sha-256 of the bytes cria sent, which the harness confirmed by the hash it computed over what it wrote)."""
        save = op.ctx['save']
        return {'operation': save['operation'], 'target': save['target'],
                'stored': ({'operation': save['operation'], 'target': save['target'], 'byte_count': save['size'], 'sha256': save['sha']}
                           if save['operation'] else None)}
