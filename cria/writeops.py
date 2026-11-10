"""File mutations through the harness ``write`` primitive: what cria decides and what it composes, in this process (docs/harness-primitives.md 8.1-8.5).

The harness returns bytes and the file's identity and lands bytes atomically; everything else happens here. The model's calls of one
turn that name one file are a GROUP and one operation in the ledger (:mod:`cria.ledger`):

* cria has the file's bytes from its own cache or reads them (``read``), applies the calls in the model's order
  (:mod:`cria.mutplan`: exact-match edit, syntax guard, safety review, shrink protection), answers each call truthfully on its own, and
  lands the combined result with ONE ``write`` whose ``EX`` is the sha-256 of the bytes it applied the edits to: a change by anything
  else in between is detected (``stale``), the file is read again and the calls are applied again (compare-and-swap). An edit sends
  only the bytes it changes (splices of the bytes read); a whole write sends its content once; a payload past one command is staged
  by parallel ``put`` calls and committed by one ``write`` that checks the assembled bytes against their hash.
* a reply that never came back is resolved by asking the file what it holds (an identity ``read``): the hash of the result means
  it landed, anything else means it did not, and the write is sent again (it is idempotent).
* a link anywhere in the path is refused by the stub and resolved by cria itself, then judged by the same guards as the path the model
  named; a file in place of a directory, a directory in place of a file and an unwritable place are answered in cria's own words.
* the languages whose checker lives where the files are are checked by the harness ``run`` stub (``syntaxcheck``): one script per
  candidate, asked in parallel; a checker that is not there is UNKNOWN, which never refuses.

The model's calls are what the model sees: one result per call, composed here and kept in the ledger's ``final`` record. A call
that did not apply a unified edit carries the facts of the miss (``ef``); the directive is composed from them where the history is
(:mod:`cria.editrecovery`, ``represent_inbound``). Nothing here parses a marker out of text for authority.
"""
import errno as errno_
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Callable
from pathlib import PurePosixPath

from . import callauth, denial, editapply, harnessprims, mutplan, prompts, readops, stagesweep, syntaxcheck
from .callliterals import _repair_double_escaped
from .filecommands import _WRITE_NAMES, _prepare_file_mutation
from .ledger import LedgerError
from .mutplan import UNREAD, Call
from .opspath import OpsUnavailable, split
from .opsteps import Final, Issue
from .toolargs import parse_args as _parse

MUTATE = 'mutate'
WHATS = ('mwrite', 'mput', 'check', 'cread', 'mclean', 'noop', 'mrm', 'msweep', 'msrm')
REPLAN_MAX = 3          # times the file changed under one group (stale) before the group says so
LOST_MAX = 2            # times one write is sent again after its reply was lost, before its fate is declared unconfirmed
CHECK_WAIT = 8          # seconds the harness waits for a checker before it answers "running" (under the harness's own yield)
CHECK_WAITS = 3         # waits for a checker that is still running, before its verdict is UNKNOWN
CHECK_RESERVE = 6_000   # room one command keeps for everything but a candidate's base64
CHECK_OUT_MAX = 1 << 20    # a checker's words past this many bytes are not fetched: its verdict is UNKNOWN (never refuses)
HOLD = 3_000            # the bytes of a command that are not payload (the stub and its arguments)


@dataclass(frozen=True)
class MutationRequest:
    """One cleared file mutation of a model turn, as :meth:`WriteOps.issue_mutations` takes it."""
    call: dict
    args: dict
    kind: str                  # write | edit
    path: str                  # as the model named it
    shrink: dict | None = None  # the measured finding for a whole write: {text, land, sha}
    review: dict | None = None  # the candidate-safety terms: {permission, ws}
    echo: bool = False


@dataclass(frozen=True)
class LedgerWrite:
    """What ``represent_inbound`` needs to treat a projected mutation as the lowered call it was: the model's call, how it ended, the
    text the coder is shown (for an edit that did not apply, the facts of the miss instead)."""
    name: str
    arguments: str
    kind: str
    text: str
    rep: dict


def _shown(label: str) -> str:
    """A display comment: one line of printable characters, at most as long as the primitives' own (harnessprims.compose)."""
    line = label.splitlines()[0] if label.strip() else ''
    return ''.join(c for c in line if c.isprintable())[:harnessprims._COMMENT_MAX]


def _bytes(blobs: dict, h: str) -> bytes:
    return blobs[h].encode('utf-8', 'surrogateescape')


def _blob(data: bytes) -> tuple[str, str]:
    return hashlib.sha256(data).hexdigest(), data.decode('utf-8', 'surrogateescape')


def calls_of(op) -> list:
    """The group's calls as the planner takes them, re-derived from what the model sent (the ledger keeps the model's own calls)."""
    out = []
    for i, c in enumerate(op.calls):
        args = _parse(c['arguments'])
        m = _prepare_file_mutation(c['name'], args)
        if c['name'] in _WRITE_NAMES:
            out.append(Call(i, 'write', c['name'], str(m.path), content=_repair_double_escaped(m.content)))
        else:
            out.append(Call(i, 'edit', c['name'], str(m.path), old=m.old, new=m.new))
    return out


def command(op: str, ctx: dict, s: int, what: str, args: dict, blobs: dict) -> str:
    """The harness command of step ``s``: a pure function of what the ledger recorded (a retried request composes the same bytes)."""
    nonce = callauth.nonce(op, s)
    if what == 'noop':
        return f"# {_shown(ctx['labels'][s])}\ntrue"
    if what == 'mwrite':
        staged = bool(args.get('staged'))
        sp = '-' if args['sp'] is None else json.dumps(args['sp'], separators=(',', ':'))
        words = [args['root'], args['rel'], args['ex'], sp, args['nw'], 1 if staged else 0, args['mk'], callauth.group(op), ctx['ws']]
        return harnessprims.compose('write', nonce, words, None if staged else _bytes(blobs, args['blob']),
                                    comment=ctx['label'], safe_path=ctx['safe'])
    if what == 'mput':
        data = _bytes(blobs, args['blob'])[args['off']:args['off'] + harnessprims.CHUNK_BYTES]
        return harnessprims.compose('put', nonce, [ctx['ws'], callauth.group(op), args['off']], data, comment=ctx['label'], safe_path=ctx['safe'])
    if what == 'msweep':      # the folder the staging files are in, listed in the wave of the first chunks
        return harnessprims.compose('ls', nonce, [ctx['ws'], stagesweep.DIR, 1, stagesweep.LIST_MAX, 0, '[]', ''],
                                    comment='staging folder ' + stagesweep.DIR, safe_path=ctx['safe'])
    if what == 'msrm':        # one stale staging file of an earlier operation of cria's own
        return harnessprims.compose('rm', nonce, [ctx['ws'], f"{stagesweep.DIR}/{args['name']}", 'f', '*'],
                                    comment='stale staging file ' + args['name'], safe_path=ctx['safe'])
    if what == 'mrm':
        return harnessprims.compose('rm', nonce, [args['root'], args['rel'], 'f', '*'], comment=ctx['label'], safe_path=ctx['safe'])
    if what == 'cread':       # the rest of a checker's output, a page of `<run dir>/out`: the run directory is named by the token cria derived
        return harnessprims.compose('read', nonce, [harnessprims.TMPDIR, f".ctx-run-{args['tok']}/out", args['off'], args['len'], 0],
                                    comment='check output ' + mutplan.name_of(args['path']), safe_path=ctx['safe'])
    if what == 'mclean':      # the run directory of a checker: removed whole, whatever became of the reply that would have said it was
        return harnessprims.compose('rm', nonce, [harnessprims.TMPDIR, f".ctx-run-{args['tok']}", 't', '*'],
                                    comment='check cleanup ' + mutplan.name_of(args['path']), safe_path=ctx['safe'])
    wait = args['mode'] == 'wait'
    text = None if wait else syntaxcheck.script(args['path'], _bytes(blobs, args['blob']))
    return harnessprims.compose('run', nonce, [args['mode'], harnessprims.TMPDIR, args['tok'], syntaxcheck.TIMEOUT, CHECK_WAIT, '', 0],
                                text=text, comment='check ' + mutplan.name_of(args['path']), safe_path=ctx['safe'])


class WriteOps:
    """The mutation half of the engine; ``Ops`` inherits it (``_step``, ``_next``, ``_reguard``, the cache, the ledger live there)."""

    # ---------------------------------------------------------------- issuing
    def issue_mutations(self, session: str, shell_tool: dict, requests: list, *, workspace_root: str | None, level: str,
                        roots=(), log=None) -> list:
        """Carry out the cleared file mutations of one model turn: one primitive call for each, in order. The calls of one file are one
        operation; their first step is a read, a checker, or the landing write itself (when cria already holds what it needs)."""
        with self._lock:
            self._rlog = log
            self._staging_closed = stagesweep.closed_names(self.ledger.ops(session))
            groups: dict = {}
            for i, req in enumerate(requests):
                groups.setdefault(split(req.path, workspace_root), []).append(i)
            out = [None] * len(requests)
            for (root, rel), idxs in groups.items():
                calls = self._issue_group(session, shell_tool, [requests[i] for i in idxs], root, rel, workspace_root, level, roots)
                for i, call in zip(idxs, calls):
                    out[i] = call
            return out

    def _issue_group(self, session, shell_tool, reqs, root, rel, workspace_root, level, roots) -> list:
        from .toolwire import _shell_call
        op = callauth.new_op()
        k = len(reqs)
        shrink = next(({'i': i, **r.shrink} for i, r in enumerate(reqs) if r.shrink is not None), None)
        ctx = {'path': reqs[0].path, 'tool': reqs[0].call['function']['name'], 'shell': shell_tool, 'safe': self.safe_path,
               'ws': workspace_root or '.', 'wsroot': workspace_root, 'level': level, 'roots': list(roots), 'start': 0, 'end': 0,
               'instead': False, 'echo': any(r.echo for r in reqs), 'review': next((r.review for r in reqs if r.review), None),
               'shrink': shrink, 'root': root, 'rel': rel,
               'label': f"{reqs[0].call['function']['name']} {reqs[0].path}",
               'labels': [f"{r.call['function']['name']} {r.path} (carried out with the first call for this file)" if i else
                          f"{r.call['function']['name']} {r.path}" for i, r in enumerate(reqs)]}
        calls = [{'id': r.call.get('id'), 'name': r.call['function']['name'], 'arguments': r.call['function'].get('arguments')} for r in reqs]
        record = {'t': 'op', 'op': op, 'kind': MUTATE, 'ctx': ctx, 'call': calls[0], 'calls': calls}
        try:
            fake = _Group(op, ctx, calls)
            plan = self._m_first(fake, root, rel)
            blobs = dict(plan.blobs)
            steps = [(what, {'wave': 0, **a}) for what, a in plan.steps]
            while len(steps) < k:
                steps.append(('noop', {'wave': 0}))
            built = [self._step(op, ctx, s, what, a, blobs) for s, (what, a) in enumerate(steps)]
            if any(len(cmd.encode()) > self.command_budget for _, cmd in built):
                steps = [('noop', {'wave': 0}) for _ in range(k)]
                built = [self._step(op, ctx, s, what, a, {}) for s, (what, a) in enumerate(steps)]
                blobs = {}
                plan = _Plan([], {}, self._m_finish(fake, self._m_all(fake, denial.REFUSED, lambda c: denial.mark(prompts.render(
                    'mutation_path_too_long', size=len(c.path.encode('utf-8', 'surrogateescape')), limit=self.command_budget - HOLD)))))
            records = [record, *({'t': 'blob', 'op': op, 'h': h, 'text': t} for h, t in blobs.items()), *(b[0] for b in built)]
            if plan.final is not None:
                records.append({'t': 'final', 'op': op, **self._final_record(fake, plan.final)})
            self.ledger.append(session, *records)
        except (LedgerError, callauth.KeyUnavailable) as exc:
            raise OpsUnavailable(str(exc)) from exc
        return [_shell_call(built[i][0]['id'], shell_tool, built[i][1]) for i in range(k)]

    def _m_first(self, op, root, rel) -> '_Plan':
        """The first step of a group: with what cria already holds, the landing write; else the read or the checks it must ask for."""
        calls = calls_of(op)
        base, sha = UNREAD, ''
        held = self.cache.get(root, rel) if any(c.kind == 'edit' for c in calls) else None
        if held is not None and len(held[2]) == held[1] and hashlib.sha256(held[2]).hexdigest() == held[0]:
            base, sha = held[2], held[0]
        sim = self._simulate(op, calls, base, {}, sha)
        # What cria remembers of a file may be older than the file (a command the coder ran, an editor): it is trusted to LAND an edit
        # (the write compares the file's hash, so a stale copy is caught and read again) but never to say that an edit does NOT apply, nor
        # that a file parses: any call it cannot land, and any check it cannot make here, is decided on the file as it is now.
        if base is not UNREAD and (not sim.complete or any(r.kind != denial.LANDED for r in sim.results)):
            sim = self._simulate(op, calls, UNREAD, {}, '')
        return self._m_continue(op, sim, root, rel, 0, 0)

    def _simulate(self, op, calls, base, verdicts, sha) -> 'mutplan.Sim':
        ctx = op.ctx
        review = _terms(ctx['review'])
        shrink = ctx['shrink'] if ctx['shrink'] and ctx['shrink']['i'] == 0 else None
        return mutplan.simulate(calls, base, verdicts, echo=ctx['echo'], review=review, shrink=shrink, base_sha=sha, log=self._rlog,
                                check_budget=self.command_budget - CHECK_RESERVE)

    # ---------------------------------------------------------------- deciding what to do with a plan
    def _m_continue(self, op, sim, root, rel, hop, replans) -> '_Plan':
        """The next steps of a group given what the planner could decide (and, for a complete plan, the landing)."""
        ctx = op.ctx
        if sim.needs_base:
            return _Plan([(readops.READ, self._m_read_args(op, root, rel, hop, replans))], {})
        if sim.needs:
            blobs, out = {}, []
            for n in sim.needs:
                h, text = _blob(n.data)
                blobs[h] = text
                out.append(('check', {'key': n.key, 'path': n.path, 'blob': h, 'mode': 'start', 'tok': self._tok(op, n.key), 'n': 1}))
            return _Plan(out, blobs)
        results = [self._result_of(r) for r in sim.results]
        if not sim.changed:
            return _Plan([], {}, self._m_finish(op, results))
        final = sim.final
        nw = hashlib.sha256(final).hexdigest()
        if sim.whole:
            payload, sp = final, None
        else:
            parts = sim.rope.splices()
            payload, sp = b''.join(p[2] for p in parts), [[a, b, len(new)] for a, b, new in parts]
        digest, text = _blob(payload)
        edits_only = all(c['name'] not in _WRITE_NAMES for c in op.calls)
        args = {'root': root, 'rel': rel, 'ex': sim.ex, 'sp': sp, 'nw': nw, 'blob': digest, 'mk': 0 if edits_only else 1,
                'results': results, 'hop': hop, 'replans': replans, 'lost': 0, 'size': len(final)}
        self._carry[(op.op, nw)] = final
        if len(payload) > harnessprims.CHUNK_BYTES:
            offsets = range(0, len(payload), harnessprims.CHUNK_BYTES)
            return _Plan([('mput', {**args, 'off': off}) for off in offsets[:harnessprims.PUT_WAVE]]
                         + [('msweep', {'closed': self._staging_closed, 'own': stagesweep.name_of(op.op)})], {digest: text})
        blobs = {digest: text}
        return _Plan([('mwrite', args)], blobs)

    def _m_read_args(self, op, root, rel, hop, replans) -> dict:
        """The first read of the file's bytes for a group (its round is numbered by how often the file already changed under it)."""
        return {'root': root, 'rel': rel, 'off': 0, 'len': self._first_len(op.ctx), 'sk': 0, 'hop': hop, 'rung': 0,
                'round': 1 + 2 * replans, 'for': 'base', 'replans': replans}

    @staticmethod
    def _tok(op, key: str) -> str:
        return hashlib.sha256((callauth.group(op.op) + key).encode()).hexdigest()[:20]

    @staticmethod
    def _result_of(r: 'mutplan.Result') -> dict:
        out = {'o': r.kind}
        for key, value in (('text', r.text), ('ev', r.ev), ('rm', r.rm), ('ef', r.ef)):
            if value:
                out[key] = value
        return out

    # ---------------------------------------------------------------- finishing
    def _m_all(self, op, kind: str, text) -> list:
        """The same refusal (``kind``, ``text(call)``) for every call of the group."""
        return [{'o': kind, 'text': text(c)} for c in calls_of(op)]

    def _m_finish(self, op, results: list) -> Final:
        """Every call answered: the coder's text for each, kept in the ledger beside its typed outcome."""
        out, calls = [], calls_of(op)
        for i, r in enumerate(results):
            path = calls[i].path
            if r['o'] == denial.LANDED:
                text = editapply.render_landed(path, r.get('ev'), r.get('rm', ''))
            else:
                text = r.get('text', '')
            out.append({k: v for k, v in {'o': r['o'], 'text': text, 'ef': r.get('ef')}.items() if v or k == 'text'})
        return Final(out[0]['o'], out[0]['text'], {'results': out})

    @staticmethod
    def _final_record(op, final: Final) -> dict:
        return {'outcome': final.outcome, 'text': final.text, **final.extra}

    def _landed(self, op, args: dict, steps: list) -> Final:
        root, rel, nw = args['root'], args['rel'], args['nw']
        data = self._carry.pop((op.op, nw), None)
        if data is not None:
            self.cache.put(root, rel, nw, len(data), data)
        else:
            self.cache.drop(root, rel)
        return self._m_finish(op, args['results'])

    def _unwritable(self, op, args: dict, reason: str, steps: list):
        """The write did not land and nothing changed: every call that was to land is answered as not run; the others keep their answer.
        A payload staged beside the target is removed first (cria removes only the name it derived from its own ledger)."""
        results = []
        for i, r in enumerate(args['results']):
            if r['o'] == denial.LANDED:
                call = op.calls[i]
                template = prompts.load('write_unwritable' if call['name'] in _WRITE_NAMES else 'edit_unwritable')
                r = {'o': denial.REFUSED, 'text': denial.mark(mutplan._fill(template, NAME=mutplan.name_of(calls_of(op)[i].path), ERR=reason))}
            results.append(r)
        return self._cleaned(op, args, steps, results)

    def _uncertain(self, op, args: dict, reason: str, steps: list):
        """The write may or may not have landed and the file cannot say: the call is answered honestly, never as landed or not run."""
        results = []
        for i, r in enumerate(args['results']):
            if r['o'] == denial.LANDED:
                name = mutplan.name_of(calls_of(op)[i].path)
                r = {'o': denial.UNCERTAIN, 'text': mutplan._fill(prompts.load('edit_mutation_unknown'), NAME=name, ERR=reason)}
            results.append(r)
        return self._cleaned(op, args, steps, results)

    def _cleaned(self, op, args: dict, steps: list, results: list):
        self._carry.pop((op.op, args['nw']), None)
        ws, where = op.ctx['ws'], stagesweep.rel_of(op.op)
        if any(st.what == 'mput' for st in steps) and not any(st.what == 'mrm' and (st.args['root'], st.args['rel']) == (ws, where) for st in steps):
            return Issue(self._next(steps, 'mrm', {'root': ws, 'rel': where, 'results': results}))
        return self._m_finish(op, results)

    # ---------------------------------------------------------------- the decisions, after each wave
    def _m_after(self, op, wave: list, steps: list):
        """The decision after a wave, then the checkers' run directories swept: none is ever left behind, whichever way the group ends."""
        if {st.what for st in wave} == {'mclean'}:           # the sweep that was all this wave held: the group's answer was decided before it
            done = wave[0].args['final']
            return Final(done['outcome'], done['text'], done['extra'])
        return self._m_swept(op, self._m_decided(op, [st for st in wave if st.what != 'mclean'], steps), steps)

    def _m_swept(self, op, decision, steps: list):
        """``decision`` with the removal of every checker directory it no longer needs: beside the steps it issues, or (when it is the
        group's answer) before it is given. A directory is needed while a checker still runs or its output is still being read."""
        if not isinstance(decision, (Issue, Final)):
            return decision
        swept = {st.args['key'] for st in steps if st.what == 'mclean'}
        live = {a['key'] for _, what, a in decision.steps if what in ('check', 'cread')} if isinstance(decision, Issue) else set()
        latest = {st.args['key']: st for st in steps if st.what == 'check' and st.frame is not None}
        dirs = [{'key': key, 'path': st.args['path'], 'tok': st.args['tok']} for key, st in latest.items()
                if key not in swept | live and not (st.frame['hdr'].get('ok') == 1 and st.frame['hdr'].get('removed') == 1)]
        if not dirs:
            return decision
        base, wave = steps[-1].s + 1, steps[-1].args['wave'] + 1
        if isinstance(decision, Final):
            answer = {'outcome': decision.outcome, 'text': decision.text, 'extra': decision.extra}
            return Issue(tuple((base + i, 'mclean', {**d, 'wave': wave, 'final': answer}) for i, d in enumerate(dirs)))
        first = decision.steps[0][0] if decision.steps else base
        wave = decision.steps[0][2]['wave'] if decision.steps else wave
        return Issue((*decision.steps, *((first + len(decision.steps) + i, 'mclean', {**d, 'wave': wave}) for i, d in enumerate(dirs))), decision.blobs)

    def _m_decided(self, op, wave: list, steps: list):
        kinds = {st.what for st in wave}
        if 'mwrite' in kinds:
            return self._m_wrote(op, next(st for st in wave if st.what == 'mwrite'), steps)
        if 'mput' in kinds:
            return self._m_staged(op, wave, steps)
        if 'mrm' in kinds:
            return self._m_finish(op, wave[0].args['results'])
        if 'stat' in kinds:
            return self._m_resolved(op, wave, steps)
        if any(st.what == readops.READ and st.args.get('for') == 'verify' for st in wave):
            return self._m_verified(op, wave, steps)
        if any(st.what == readops.READ and st.args.get('for') == 'notfile' for st in wave):
            return self._m_notfile(op, wave, steps)
        return self._m_planned(op, wave, steps)

    def _m_planned(self, op, wave: list, steps: list):
        """After reads and checks: gather what came back, plan again from the start with it, and ask for what is still missing."""
        ctx = op.ctx
        base_steps = [st for st in steps if st.what == readops.READ and st.args.get('for') == 'base']
        root, rel, hop = ctx['root'], ctx['rel'], 0
        for st in base_steps:
            root, rel, hop = st.args['root'], st.args['rel'], st.args['hop']
        replans = max((st.args.get('replans', 0) for st in steps), default=0)
        base, sha = UNREAD, ''
        if base_steps:
            gathered = self._m_gather(op, wave, steps, base_steps)
            if isinstance(gathered, (Issue, Final)):
                return gathered
            if gathered[0] == 'bytes':
                base, sha = gathered[1], gathered[2]
            elif gathered[0] == 'absent':
                base = None
            else:
                return self._m_all_final(op, gathered[0], gathered)
        return self._m_replanned(op, steps, base, sha, root, rel, hop, replans)

    def _m_replanned(self, op, steps: list, base, sha: str, root: str, rel: str, hop: int, replans: int):
        verdicts = self._verdicts(op, steps)
        if isinstance(verdicts, Issue):
            return verdicts
        sim = self._simulate(op, calls_of(op), base, verdicts, sha)
        plan = self._m_continue(op, sim, root, rel, hop, replans)
        return plan.final if plan.final is not None else Issue(self._m_issue(steps, plan), plan.blobs)

    def _m_issue(self, steps: list, plan: '_Plan') -> tuple:
        base, wave = steps[-1].s + 1, steps[-1].args['wave'] + 1
        return tuple((base + i, what, {**a, 'wave': wave}) for i, (what, a) in enumerate(plan.steps))

    # reading the base ------------------------------------------------
    def _m_gather(self, op, wave: list, steps: list, base_steps: list):
        """``('bytes', data, sha)``, ``('absent',)``, ``('dir',)``, ``('notfile',)``, ``('unreadable', errno)``, or an Issue (more pages, a
        link to resolve, a read to repeat) or Final (the file will not hold still)."""
        rnd = max(st.args['round'] for st in base_steps)
        current = [st for st in base_steps if st.args['round'] == rnd]
        args0 = current[0].args
        latest = [st for st in current if st in wave] or current
        for st in latest:
            if st.frame['hdr'].get('ok') == 0:
                return self._m_read_error(op, st, steps, any(s.frame['hdr'].get('ok') == 1 for s in current))
        good = [(st, st.frame['hdr']) for st in current if st.frame['hdr'].get('ok') == 1]
        cut = any(st.frame['hdr'].get('ok') == -1 for st in latest)
        if not good:
            return self._m_smaller(op, steps, args0, None, [])
        size, sha = good[0][1]['fsize'], good[0][1]['fsha']
        if any((h['fsha'], h['fsize'], h['size']) != (sha, size, size) for _, h in good):
            return self._m_changed(op, steps, args0)
        for st, header in good:
            self._learn(header, st.frame)
        pieces = [(h['off'], st.frame['text'].encode('utf-8', 'surrogateescape')) for st, h in good]
        prefix, ranges = readops.merge(pieces)
        if len(prefix) >= size:
            if hashlib.sha256(prefix[:size]).hexdigest() != sha:
                return self._m_changed(op, steps, args0)
            return ('bytes', prefix[:size], sha)
        if cut:
            return self._m_smaller(op, steps, args0, size, ranges)
        more = self._m_more(op, steps, {**args0, 'rung': 0}, size, ranges)
        return more

    def _m_more(self, op, steps, args, size, ranges):
        """The next wave of pages: the uncovered ranges of the file at the rung's size, at most ``WAVE`` calls."""
        length = self._length(args['rung'])
        pages = [off for a, b in readops.uncovered(ranges, size) for off in range(a, b, length)][:readops.WAVE]
        if not pages or pages[0] >= readops.TRANSPORT_MAX:
            return Final(*self._unresolved(op))
        return Issue(self._next(steps, readops.READ, *({**args, 'off': off, 'len': length} for off in pages)))

    def _m_smaller(self, op, steps, args, size, ranges):
        """A frame the harness cut: the same range again, at half the size."""
        rung = args['rung'] + 1
        if self._length(rung) <= readops.LEN_FLOOR:
            return Final(*self._unresolved(op))
        if size is None:
            return Issue(self._next(steps, readops.READ, {**args, 'rung': rung, 'len': self._length(rung)}))
        return self._m_more(op, steps, {**args, 'rung': rung}, size, ranges)

    def _m_changed(self, op, steps, args):
        """The file changed while it was being read: read it again from the start, once more; then say so."""
        tries = len({st.args['round'] for st in steps if st.what == readops.READ and st.args.get('for') == 'base'})
        if tries < 2 + args.get('replans', 0) * 2:
            return Issue(self._next(steps, readops.READ, {**args, 'round': args['round'] + 1, 'off': 0, 'len': self._first_len(op.ctx), 'rung': 0}))
        return Final(*self._unresolved(op))

    def _unresolved(self, op) -> tuple:
        """The file would not hold still, or could not be read whole: nothing was written, and the calls say so."""
        final = self._m_finish(op, self._m_all(op, denial.REFUSED, lambda c: denial.mark(mutplan._fill(
            prompts.load('mutation_changed'), NAME=mutplan.name_of(c.path)))))
        return final.outcome, final.text, final.extra

    def _m_read_error(self, op, st, steps, seen: bool):
        header, args = st.frame['hdr'], st.args
        code = header.get('errno')
        if seen:
            return self._m_changed(op, steps, args)                  # it was there a moment ago
        parts = [p for p in args['rel'].split('/') if p]
        if code in (errno_.ELOOP, errno_.ENOTDIR) and len(parts) > 0 and header.get('err') != 'notfile':
            if args['hop'] >= readops.MAX_HOPS:
                return ('unreadable', errno_.ELOOP)
            prefix, prefixes = '', []
            for part in parts:
                prefix = f'{prefix}/{part}' if prefix else part
                prefixes.append(prefix)
            return Issue(self._next(steps, 'stat', *({**args, 'rel': p, 'errno': code, 'at': i, 'full': args['rel'], 'stage': 'read'}
                                                      for i, p in enumerate(prefixes))))
        if header.get('err') == 'notfile':
            import stat as stat_
            return ('dir',) if stat_.S_ISDIR(header.get('mode') or 0) else ('notfile',)
        if code in (errno_.ENOENT, errno_.ENOTDIR):
            return ('absent',)
        return ('unreadable', code)

    def _m_all_final(self, op, kind: str, found: tuple) -> Final:
        """The file is a directory, not a regular file, or cannot be read: every call is refused in its own words."""
        def text(c):
            name = mutplan.name_of(c.path)
            if kind == 'dir':
                return denial.mark(mutplan._fill(prompts.load('write_isdir' if c.kind == 'write' else 'edit_isdir'), NAME=c.path if c.kind == 'write' else name))
            if kind == 'notfile':
                return denial.mark(mutplan._fill(prompts.load('write_not_a_file'), NAME=name))
            template = prompts.load('write_unreadable' if c.kind == 'write' else 'edit_unreadable')       # the failure was a read: say so
            return denial.mark(mutplan._fill(template, NAME=name, ERR=os.strerror(found[1]) if len(found) > 1 and found[1] else 'the harness could not read it'))
        return self._m_finish(op, self._m_all(op, denial.REFUSED, text))

    # the checkers ----------------------------------------------------
    def _verdicts(self, op, steps: list):
        """``{check key: message or None}`` from the checks that came back, or an Issue that waits for a checker still running or fetches the
        rest of an output the run stub kept (it answers the first 6,000 bytes; the rest is paged from the run's file, never cut)."""
        out, ask = {}, []
        latest: dict = {}
        for st in steps:
            if st.what == 'check' and st.frame is not None:
                latest[st.args['key']] = st
        for key, st in latest.items():
            header, args = st.frame['hdr'], st.args
            if header.get('ok') == 1 and header.get('state') == 'running':
                if args['n'] <= CHECK_WAITS:
                    ask.append(('check', {**args, 'mode': 'wait', 'n': args['n'] + 1}))
                else:
                    out[key] = None
            elif header.get('ok') == 1:
                whole = self._check_output(steps, key, st)
                if isinstance(whole, list):
                    ask += [('cread', {'key': key, 'path': args['path'], 'tok': args['tok'], **page}) for page in whole]
                else:
                    out[key] = None if whole is None else syntaxcheck.interpret(args['path'], header.get('exit'), header.get('timeout'), whole)
            else:
                out[key] = None                      # the checker did not answer: unknown stays safe
        if ask:
            base, wave = steps[-1].s + 1, steps[-1].args['wave'] + 1
            return Issue(tuple((base + i, what, {**a, 'wave': wave}) for i, (what, a) in enumerate(ask)))
        return out

    def _check_output(self, steps: list, key: str, st):
        """A finished checker's whole output (bytes), the pages still to ask for (``[{off, len, rung}]``), or None (UNKNOWN: it cannot be
        had, or would not be judged: a killed or absent checker, an output that is not worth a model's reading)."""
        header, head = st.frame['hdr'], st.frame['text'].encode('utf-8', 'surrogateescape')
        size = header.get('size')
        if header.get('timeout') or header.get('exit') in (0, 126, 127, None) or not isinstance(size, int):
            return head                              # the verdict will not read it
        if size <= len(head):
            return head
        if size > CHECK_OUT_MAX:
            return None
        pages = [p for p in steps if p.what == 'cread' and p.args['key'] == key and p.frame is not None]
        if any(p.frame['hdr'].get('ok') == 0 for p in pages):
            return None
        good = [(p.frame['hdr']['off'], p.frame['text'].encode('utf-8', 'surrogateescape')) for p in pages
                if p.frame['hdr'].get('ok') == 1 and p.frame['hdr'].get('fsha') == header.get('osha')]
        prefix, ranges = readops.merge([(0, head), *good])
        if len(prefix) >= size:
            return prefix[:size] if hashlib.sha256(prefix[:size]).hexdigest() == header.get('osha') else None
        newest = max((p.args['wave'] for p in pages), default=-1)
        rung = max((p.args['rung'] for p in pages), default=0) + (1 if any(p.args['wave'] == newest and p.frame['hdr'].get('ok') == -1 for p in pages) else 0)
        length = self._length(rung)
        if length <= readops.LEN_FLOOR and rung:
            return None                              # a frame the harness keeps cutting
        asks = [{'off': off, 'len': length, 'rung': rung} for a, b in readops.uncovered(ranges, size) for off in range(a, b, length)][:readops.WAVE]
        return asks or None

    # the landing -----------------------------------------------------
    def _m_staged(self, op, wave: list, steps: list):
        wave = [st for st in wave if st.what == 'mput']              # (the listing of the staging folder rode with them)
        args = wave[0].args
        bad = next((st for st in wave if st.frame['hdr'].get('ok') != 1), None)
        if bad is not None:
            tries = sum(1 for st in steps if st.what == 'mput' and st.args['off'] == bad.args['off'])
            if bad.frame['hdr'].get('ok') == -1 and tries < 2:
                return Issue(self._next(steps, 'mput', *({**st.args} for st in wave if st.frame['hdr'].get('ok') != 1)))
            if bad.frame['hdr'].get('ok') == -1:
                return self._uncertain(op, args, 'the harness did not confirm the content it was sent', steps)
            return self._unwritable(op, args, readops_reason(bad.frame['hdr']), steps)
        size = len(_bytes(op.blobs, args['blob']))
        staged = {st.args['off'] for st in steps if st.what == 'mput' and (st.args['root'], st.args['rel']) == (args['root'], args['rel'])}
        more = [off for off in range(0, size, harnessprims.CHUNK_BYTES) if off not in staged][:harnessprims.PUT_WAVE]
        base = {k: v for k, v in args.items() if k != 'off'}
        if more:
            return Issue(stagesweep.with_sweep(op.op, steps, self._next(steps, 'mput', *({**base, 'off': off} for off in more)), 'msweep', 'msrm'))
        return Issue(stagesweep.with_sweep(op.op, steps, self._next(steps, 'mwrite', {**base, 'staged': True}), 'msweep', 'msrm'))

    def _m_wrote(self, op, st, steps: list):
        header, args = st.frame['hdr'], st.args
        if header.get('ok') == 1:
            return self._landed(op, args, steps)
        if header.get('ok') == 0:
            err, code = header.get('err'), header.get('errno')
            if err == 'stale':
                if header.get('sha') == args['nw']:
                    return self._landed(op, args, steps)           # an earlier attempt of this very write landed: the file is the result
                return self._replan(op, args, steps)
            if err == 'newsha':
                return self._cleaned(op, args, steps, self._garbled(op, args))
            if err == 'notfile':           # a directory, or something that is not a regular file: the read says which
                return Issue(self._next(steps, readops.READ, {'root': args['root'], 'rel': args['rel'], 'off': 0, 'len': 0, 'sk': 0,
                                                               'hop': args['hop'], 'rung': 0, 'round': 1, 'for': 'notfile', 'write': st.s}))
            if code in (errno_.ELOOP, errno_.ENOTDIR) and args['rel']:
                return self._m_walk(op, args, steps, code)
            if code == errno_.ENOENT and not args['mk'] and not args.get('staged'):
                return self._m_all_final_with(op, args, steps, 'absent')
        return Issue(self._next(steps, readops.READ, {'root': args['root'], 'rel': args['rel'], 'off': 0, 'len': 0, 'sk': 0, 'hop': args['hop'],
                                                       'rung': 0, 'round': 1, 'for': 'verify', 'write': st.s, 'verified': 0}))

    def _m_walk(self, op, args: dict, steps: list, code):
        """A link somewhere in the path the stub was asked to write: ask what each part of the path is (one `ls` of each), to resolve it here."""
        if args['hop'] >= readops.MAX_HOPS:
            return self._unwritable(op, args, os.strerror(errno_.ELOOP), steps)
        prefix, prefixes = '', []
        for part in (p for p in args['rel'].split('/') if p):
            prefix = f'{prefix}/{part}' if prefix else part
            prefixes.append(prefix)
        return Issue(self._next(steps, 'stat', *({**args, 'rel': p, 'errno': code or 0, 'at': i, 'full': args['rel'], 'stage': 'write',
                                                   'rel0': args['rel']} for i, p in enumerate(prefixes))))

    def _garbled(self, op, args: dict) -> list:
        results = []
        for i, r in enumerate(args['results']):
            if r['o'] == denial.LANDED:
                r = {'o': denial.REFUSED, 'text': denial.mark(mutplan._fill(prompts.load('mutation_garbled'), NAME=mutplan.name_of(calls_of(op)[i].path)))}
            results.append(r)
        return results

    def _m_all_final_with(self, op, args: dict, steps: list, kind: str):
        results = []
        for i, r in enumerate(args['results']):
            if r['o'] == denial.LANDED:
                results.append({'o': denial.REFUSED, 'text': denial.mark(mutplan._fill(prompts.load('edit_missing_file'),
                                                                                       NAME=mutplan.name_of(calls_of(op)[i].path)))})
            else:
                results.append(r)
        return self._cleaned(op, args, steps, results)

    def _replan(self, op, args: dict, steps: list):
        """The file changed between the read and the write (compare-and-swap): read it as it is now and apply the calls again."""
        replans = args['replans'] + 1
        if replans >= REPLAN_MAX or args.get('staged') or any(st.what == 'mput' for st in steps):
            return self._cleaned(op, args, steps, self._m_all(op, denial.REFUSED, lambda c: denial.mark(mutplan._fill(
                prompts.load('mutation_changed'), NAME=mutplan.name_of(c.path)))))
        self._carry.pop((op.op, args['nw']), None)
        # the group is planned again from the file as it is now; a measured shrink finding is about the bytes that were, so it is not carried over
        return Issue(self._next(steps, readops.READ, self._m_read_args(op, args['root'], args['rel'], args['hop'], replans)))

    def _m_notfile(self, op, wave: list, steps: list):
        """The write found something that is not a regular file: a directory (the coder is told so) or a device, a pipe, a socket."""
        st = wave[0]
        write = next(s for s in steps if s.s == st.args['write'])
        header = st.frame['hdr']
        import stat as stat_
        kind = 'd' if header.get('err') == 'notfile' and stat_.S_ISDIR(header.get('mode') or 0) else 'o'
        if header.get('err') != 'notfile':                          # it is not what it was a moment ago: say what the stub said
            return self._unwritable(op, write.args, readops_reason(header), steps)
        return self._m_stat_final(op, {**write.args, 'stage': 'write'}, steps, kind)

    def _m_verified(self, op, wave: list, steps: list):
        st = wave[0]
        write = next(s for s in steps if s.s == st.args['write'])
        args, header = write.args, st.frame['hdr']
        if header.get('ok') == 1 and header.get('fsha') == args['nw']:
            return self._landed(op, args, steps)
        if header.get('ok') == -1:
            if st.args['verified'] < 1:
                return Issue(self._next(steps, readops.READ, {**st.args, 'verified': st.args['verified'] + 1}))
            return self._uncertain(op, args, 'the harness did not confirm the result', steps)
        wh = write.frame['hdr'] if write.frame else {'ok': -1}
        if wh.get('ok') == 0:                                       # the stub said it could not: nothing changed
            code = wh.get('errno')
            return self._unwritable(op, args, _why(code, wh.get('err')), steps)
        if args['lost'] < LOST_MAX:
            # A reply that never came: the write is idempotent, so the same write goes out again (a new step: the id and nonce are one
            # call's). The attempt that was lost may have died holding a temporary name beside the target, which only its own nonce
            # derives: cria removes exactly that name (the stub removes its own on every other path).
            parent = args['rel'].rpartition('/')[0]
            tmp = f".ctx{callauth.nonce(op.op, write.s)[:16]}.tmp"
            base, wave = steps[-1].s + 1, steps[-1].args['wave'] + 1
            return Issue(((base, 'mrm', {'root': args['root'], 'rel': f'{parent}/{tmp}' if parent else tmp, 'results': args['results'], 'wave': wave}),
                          (base + 1, 'mwrite', {**args, 'lost': args['lost'] + 1, 'wave': wave})))
        return self._uncertain(op, args, 'the harness never confirmed the result', steps)

    # links and the parts of a path ------------------------------------
    def _m_resolved(self, op, wave: list, steps: list):
        ctx = op.ctx
        for st in sorted(wave, key=lambda x: x.args['at']):
            header, args = st.frame['hdr'], st.args
            if header.get('ok') != 1:
                return self._m_stat_failed(op, st, steps)
            records = [json.loads(line) for line in st.frame['text'].split('\n') if line]
            if not records or records[0][1] != args['rel']:
                continue                                           # a directory: the walk went through it
            parts = [p for p in args['full'].split('/') if p]
            if records[0][0] != 'l':
                if args['at'] + 1 < len(parts):                    # a file where a directory has to be
                    return self._m_parent_is_file(op, args, steps)
                return self._m_stat_final(op, args, steps, records[0][0])
            here = os.path.join(args['root'], args['rel'])
            resolved = os.path.normpath(os.path.join(os.path.dirname(here), records[0][5], *parts[args['at'] + 1:]))
            refusal = self._reguard(resolved, ctx, write=True)
            if refusal:
                return self._m_refuse_all(op, steps, denial.mark(refusal), args)
            new_root, new_rel = split(resolved, ctx.get('wsroot'))
            hop = args['hop'] + 1
            if args['stage'] == 'read':
                return Issue(self._next(steps, readops.READ, {'root': new_root, 'rel': new_rel, 'off': 0, 'len': self._first_len(ctx), 'sk': 0,
                                                               'hop': hop, 'rung': 0, 'round': args['round'] + 1, 'for': 'base',
                                                               'replans': args.get('replans', 0)}))
            moved = {k: v for k, v in args.items() if k not in ('errno', 'at', 'full', 'stage', 'rel0', 'wave')}
            return Issue(self._next(steps, 'mwrite', {**moved, 'root': new_root, 'rel': new_rel, 'hop': hop, 'lost': 0}))
        return self._m_stat_failed(op, wave[0], steps)

    def _m_refuse_all(self, op, steps: list, text: str, args: dict):
        if args.get('stage') == 'write':
            return self._cleaned(op, args, steps, [{'o': denial.REFUSED, 'text': text} if r['o'] == denial.LANDED else r for r in args['results']])
        return self._m_finish(op, self._m_all(op, denial.REFUSED, lambda c: text))

    def _m_stat_failed(self, op, st, steps: list):
        args = st.args
        code = st.frame['hdr'].get('errno') or args.get('errno') or errno_.EIO
        if args['stage'] == 'write':
            if code == errno_.ENOENT and not args['mk']:
                return self._m_all_final_with(op, args, steps, 'absent')
            return self._unwritable(op, args, os.strerror(code), steps)
        if code in (errno_.ENOENT, errno_.ENOTDIR):
            return self._m_gather_absent(op, steps)
        return self._m_all_final(op, 'unreadable', ('unreadable', code))

    def _m_gather_absent(self, op, steps: list):
        """A part of the path is not there: for a read of the base, the file is absent (and for a whole write, that is the answer)."""
        ctx = op.ctx
        return self._m_replanned(op, steps, None, '', ctx['root'], ctx['rel'], 0, 0)

    def _m_stat_final(self, op, args: dict, steps: list, kind: str):
        """The path is not a link and not what a write needs: a directory, or something that is not a regular file."""
        if args['stage'] == 'write':
            results = []
            for i, r in enumerate(args['results']):
                if r['o'] == denial.LANDED:
                    c = calls_of(op)[i]
                    template = prompts.load('write_isdir' if kind == 'd' and c.kind == 'write' else 'edit_isdir' if kind == 'd' else 'write_not_a_file')
                    r = {'o': denial.REFUSED, 'text': denial.mark(mutplan._fill(template, NAME=c.path if c.kind == 'write' else mutplan.name_of(c.path)))}
                results.append(r)
            return self._cleaned(op, args, steps, results)
        return self._m_all_final(op, 'dir' if kind == 'd' else 'notfile', (kind,))

    def _m_parent_is_file(self, op, args: dict, steps: list):
        block_rel = args['rel']
        results = []
        for i, call in enumerate(calls_of(op)):
            block = _block_named(call.path, args['root'], block_rel, op.ctx.get('wsroot'))
            results.append((i, denial.mark(mutplan._fill(prompts.load('write_parent_is_file'), NAME=call.path, BLOCK=block))))
        texts = dict(results)
        if args['stage'] == 'write':
            return self._cleaned(op, args, steps, [{'o': denial.REFUSED, 'text': texts[i]} if r['o'] == denial.LANDED else r
                                                  for i, r in enumerate(args['results'])])
        return self._m_finish(op, [{'o': denial.REFUSED, 'text': texts[i]} for i in range(len(op.calls))])


def _block_named(path: str, root: str, rel: str, wsroot: str | None) -> str:
    """The nearest existing ancestor of ``path`` that is a file, spelled as the model spelled the path."""
    for parent in PurePosixPath(path).parents:
        if split(str(parent), wsroot) == (root, rel):
            return str(parent)
    return rel


def readops_reason(header: dict) -> str:
    return _why(header.get('errno'), header.get('err'))


def _why(code, err=None) -> str:
    """The reason a write could not land, in words: the kernel's for its errno, and for a destination on another filesystem than the staging
    folder (``errno.EXDEV``: the staged file cannot be renamed onto it) a plain statement that nothing was written."""
    if code == errno_.EXDEV:
        return prompts.load('write_cross_device').strip()
    return os.strerror(code) if isinstance(code, int) and code else str(err or 'unknown error')


def _terms(review):
    from .toolcontracts import ReviewTerms
    return ReviewTerms(review['permission'], review.get('ws')) if review else None


@dataclass
class _Plan:
    steps: list
    blobs: dict
    final: Final | None = None


class _Group:
    """The part of an operation the issue-time planner needs before the ledger knows it."""
    def __init__(self, op, ctx, calls):
        self.op, self.ctx, self.calls, self.blobs = op, ctx, calls, {}
        self.extra_calls = calls
