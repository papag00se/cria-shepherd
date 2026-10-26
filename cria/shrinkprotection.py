"""Measured whole-file shrink protection and byte-bound command settlement.

The caller supplies only live session state, the surveyed view and a closed
reader. No provider decides whether to hold or formats this policy's guidance.
The state is transient per task/session; compaction keeps it, new tasks/forks and
durable reconstruction start fresh. Only affirmative candidate judgments cache.
"""
from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass, field
import hashlib
from typing import Callable, Collection, Protocol

from . import prompts
from .assistcontract import Policy, Reference
from .toolcontracts import EventLog, MutationDefinition, ShrinkFinding, policy_log
from .wholefile import ClosedJudge, judge_whole_file

SHRINK_MIN_LINES = 8
SHRINK_OPENERS_MAX = 12


@dataclass
class ShrinkState:
    approved: dict[tuple[str, str], str] = field(default_factory=dict)

    def reset(self) -> None:
        self.approved.clear()


@dataclass(frozen=True)
class ShrinkSession:
    first_survey_files: Collection[str] | None
    state: ShrinkState


class ShrinkView(Protocol):
    surveyed: bool
    def rel(self, path: str) -> str | None: ...
    def isfile(self, path: str) -> bool | None: ...
    def read_bytes(self, path: str) -> bytes | None: ...


@dataclass(frozen=True)
class ShrinkServices:
    session: Callable[[], ShrinkSession | None]
    view: Callable[[], ShrinkView]
    ask: ClosedJudge | None
    log: EventLog


class ShrinkRequest(Protocol):
    injected: frozenset[str]
    shrink_services: ShrinkServices | None


class ShrinkCall(Protocol):
    name: str
    arguments: dict
    request: ShrinkRequest
    log: EventLog | None


def shrink_measure(current: str, candidate: str) -> dict | None:
    """Multiset lower-bound removals and indentation-only block opener facts."""
    cur = [line.strip() for line in current.splitlines() if line.strip()]
    cand = [line.strip() for line in candidate.splitlines() if line.strip()]
    if len(cur) < SHRINK_MIN_LINES:
        return None
    left = Counter(cand)
    body = [(no, raw) for no, raw in enumerate(current.splitlines(), 1) if raw.strip()]
    removed, first, openers = 0, None, []
    for i, (no, raw) in enumerate(body):
        line = raw.strip()
        if left[line] > 0:
            left[line] -= 1
            continue
        removed += 1
        first = first or (no, line)
        indent = len(raw) - len(raw.lstrip())
        if i + 1 < len(body) and len(body[i + 1][1]) - len(body[i + 1][1].lstrip()) > indent:
            openers.append((indent, no, line))
    distinct, kept = set(cur), len(set(cur) & set(cand))
    fragment = len(cand) * 2 <= len(cur) and kept * 2 < len(distinct)
    if removed * 2 < len(cur) and not fragment:
        return None
    shown = sorted(sorted(openers)[:SHRINK_OPENERS_MAX], key=lambda item: item[1])
    return dict(current_lines=len(cur), distinct=len(distinct), cand_lines=len(cand), kept=kept,
                removed_at_least=removed, first_removed=first, fragment=fragment,
                openers=[(no, line) for _, no, line in shown], openers_total=len(openers))


def openers_fact(labels: dict, measure: dict) -> str:
    return prompts.fill(labels['openers'], shown=len(measure['openers']), total=measure['openers_total'],
                        listing='; '.join(f'line {no}: `{line}`' for no, line in measure['openers']))


def check_write(services: ShrinkServices, path: str, content: str, edit_tool: str = '') -> ShrinkFinding | None:
    if services.ask is None:
        return None
    session, view = services.session(), services.view()
    if session is None or not path or not getattr(view, 'surveyed', False):
        return None
    rel = view.rel(path)
    if not rel or view.isfile(rel) is not True:
        return None
    raw = view.read_bytes(rel)
    if raw is None:
        return None
    current = raw.decode('utf-8', 'replace')
    measure = shrink_measure(current, content)
    if measure is None:
        return None
    labels = prompts.load_map('write_shrink_facts')
    log = policy_log(services.log, DEFINITION.policy)
    if not measure['fragment']:
        if rel not in (session.first_survey_files or ()):
            return None
        text = prompts.fill(labels['removed_landed'], path=rel, removed=measure['removed_at_least'],
                            lines=measure['current_lines'], cand_lines=measure['cand_lines'])
        if measure['openers']:
            text += ' ' + openers_fact(labels, measure)
        log.emit('loop.write_removal_facts', path=rel, current_lines=measure['current_lines'],
                 cand_lines=measure['cand_lines'], removed_at_least=measure['removed_at_least'])
        return {'text': text, 'bytes': raw, 'land': True}
    key = (rel, hashlib.sha1(content.encode('utf-8', 'replace')).hexdigest())
    if session.state.approved.get(key) == 'WHOLE_FILE':
        return None
    fact = prompts.fill(labels['measured'], path=rel, bytes=len(current.encode('utf-8', 'replace')),
                        lines=measure['current_lines'], distinct=measure['distinct'],
                        cand_bytes=len(content.encode('utf-8', 'replace')),
                        cand_lines=measure['cand_lines'], kept=measure['kept'])
    verdict = judge_whole_file(services.ask,
        prompts.load('write_call_judge') + '\n\n' + prompts.render(
            'write_call_judge_user', path=rel, fact=fact, content=content), phase='write-shrink')
    log.emit('loop.write_shrink_judged', path=rel, verdict=verdict[:40], current_lines=measure['current_lines'],
             cand_lines=measure['cand_lines'], distinct=measure['distinct'], kept=measure['kept'],
             removed_at_least=measure['removed_at_least'])
    if verdict == 'WHOLE_FILE':
        session.state.approved[key] = verdict
        return None
    removed = measure['first_removed']
    text = prompts.fill(labels['held'], fact=fact, removed=measure['removed_at_least'],
                        lines=measure['current_lines'], line=removed[0], quoted=removed[1])
    if measure['openers']:
        text += ' ' + openers_fact(labels, measure)
    if edit_tool:
        text += ' ' + prompts.fill(labels['edit_on_menu'], tool=f'`{edit_tool}`')
    return {'text': text, 'bytes': raw}


def wrap_finding(path: str, finding: ShrinkFinding, command: str) -> str:
    """Settle against measured bytes; stale views never refuse or emit old facts."""
    from shlex import quote as _qbash
    from .toolwire import _b64, _refusal_command
    same = ('import base64,pathlib,sys; '
            'p=pathlib.Path(base64.b64decode(' + repr(_b64(path)) + ').decode()); '
            'sys.exit(0 if p.is_file() and p.read_bytes()==base64.b64decode('
            + repr(base64.b64encode(finding['bytes']).decode('ascii')) + ') else 1)')
    if finding.get('land'):
        # The measured facts ride into the write program, which reports them as the typed `rm` field of ITS OWN `landed`
        # record — only when it actually landed, only when the disk still held the measured bytes (the `same` check).
        return f'if python3 -c {_qbash(same)}; then\nexport CRIA_RM={_qbash(finding["text"])}\n{command}\nelse\n{command}\nfi'
    return f"if python3 -c {_qbash(same)}; then\n{_refusal_command(finding['text'])}\nelse\n{command}\nfi"


def shrinking_replacement(source: ShrinkCall, command: str) -> str:
    from .filecommands import _WRITE_NAMES, _EDIT_NAMES, _prepare_file_mutation
    from .callliterals import _repair_double_escaped
    if source.name not in _WRITE_NAMES or source.request.shrink_services is None:
        return command
    services = source.request.shrink_services
    if services.ask is None:
        return command
    mutation = _prepare_file_mutation(source.name, source.arguments)
    path, candidate = str(mutation.path), _repair_double_escaped(mutation.content)
    edit_names = source.request.injected & _EDIT_NAMES
    finding = check_write(services, path, candidate, sorted(edit_names)[0] if edit_names else '')
    if finding is None:
        return command
    result = wrap_finding(path, finding, command)
    if source.log is not None:
        event = 'writeproxy.write_removal_facts' if finding.get('land') else 'writeproxy.write_shrink_held'
        policy_log(source.log, DEFINITION.policy).emit(event, tool=source.name, path=path)
    return result


DEFINITION = MutationDefinition(
    Policy('shrinking-file-protection', 'mutation-command', 5, family_id='F15',
           prompts=('write_shrink_facts', 'write_call_judge', 'write_call_judge_user'),
           state='transient task/session affirmative path/candidate cache; reset on new task/fork/durable restore; byte-bound effects only',
           services=('live-session-state', 'surveyed-workspace-view', 'closed-whole-file-reader'),
           hooks=(Reference('cria/writeproxy.py', '_lower_synthetic'),
                  Reference('cria/server.py', 'CriaHandler._setup_translation')),
           regressions=(Reference('tests/test_shrink_protection_policy.py', 'test_fragment_hold_and_affirmative_only_cache'),
                        Reference('tests/test_shrink_protection_policy.py', 'test_byte_settlement_runs_stale_writes_and_only_emits_successful_current_facts')),
           migrated=False), shrinking_replacement)


def run_selected(definition: MutationDefinition | None, source: Callable[[], ShrinkCall], command: str) -> str:
    """Selection precedes preparation, measurements, view/state access and questions."""
    return command if definition is None else definition.execute(source(), command)
