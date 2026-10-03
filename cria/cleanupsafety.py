"""A cheap destructive-operation tripwire, followed by a grounded semantic review.

The tripwire is not a verdict. Unknown/malformed judgments are logged and silent;
only an UNSAFE judgment quoting this candidate can refuse it. No workspace disk
access: edits use bytes previously reported by the harness through wsview.
"""
from __future__ import annotations

import json
import re
from . import dirguard, prompts

# Function/API spellings across ecosystems, not filename extensions. These are
# deliberately candidates for inspection, never proof of deletion or its scope.
_OPERATION = re.compile(
    r"\b(?:rmtree|remove_dir_all|removeAll|remove_all|RemoveAll|deleteDirectory|"
    r"deleteRecursively|DeleteDirectory|rmSync|rmdirSync|rmdir|unlink|unlinkSync|"
    r"removeRecursively|removeDirectory|rm)\s*\("
    r"|\bDirectory\s*\.\s*Delete\s*\("
    r"|\bFileUtils\s*\.\s*rm_rf(?:\s+|\()"
    r"|(?:^|[;\n&|])\s*(?:sudo\s+)?(?:rm\s+(?:-[^\s]+\s+)*|Remove-Item\s+)",
    re.MULTILINE)


def _code_only(text: str) -> str:
    """Mask common comments and string bodies without changing offsets.

Not a parser for every language. Ambiguous lexical forms may trigger a review;
that review must distinguish documentation and inert examples from execution.
"""
    pattern = r'(?s)(?:""".*?"""|\'\'\'.*?\'\'\'|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|/\*.*?\*/|//[^\n]*|\#[^\n]*)'
    return re.sub(pattern, lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), text)


def review(path: str, candidate: str, previous: str | None, workspace: str | None,
           ask, rlog=None, task: str = '') -> str | None:
    if candidate == previous:
        return None
    operations = list(_OPERATION.finditer(_code_only(candidate)))
    if not operations:
        return None
    def record(verdict, **fields):
        if rlog is not None:
            rlog.emit('safety.cleanup_review', path=path, verdict=verdict, **fields)
    if ask is None:
        record('UNKNOWN', reason='reasoner unavailable')
        return None
    literals = []
    for operation in operations:
        # Only plain first-argument string literals: no escape decoding or
        # variable evaluation. These are lexical boundary facts, NOT IO claims.
        literal = re.match(r'''\s*(['"])([^'"\\\n]*)\1''', candidate[operation.end():])
        if literal and workspace and literal[2].startswith('/'):
            literals.append(dict(target=literal[2], external=dirguard.is_external(literal[2], workspace)))
    packet = prompts.render('cleanup_review', path=path, workspace=workspace or '(unknown)',
                            literals=json.dumps(literals),
                            candidate=candidate, previous=previous if previous is not None else '(unavailable)',
                            task=task or '(unavailable; do not assume user intent)')
    try:
        answer = json.loads(ask(packet))
    except Exception:
        record('UNKNOWN', reason='judgment unavailable or unparseable')
        return None
    if not isinstance(answer, dict):
        record('UNKNOWN', reason='invalid judgment')
        return None
    if answer.get('verdict') != 'UNSAFE':
        record(answer.get('verdict') if answer.get('verdict') in ('SAFE', 'UNKNOWN') else 'UNKNOWN')
        return None
    evidence = answer.get('evidence')
    explanation = answer.get('reason')
    if not isinstance(evidence, str) or not evidence.strip() or evidence not in candidate or not _OPERATION.search(_code_only(evidence)) or not isinstance(explanation, str) or not explanation.strip():
        record('UNKNOWN', reason='ungrounded judgment')
        return None
    # Reuse the existing boundary owner for the judge's proposed concrete target.
    # This is a judgment-derived target, not a filesystem observation; never
    # promote it into a claim that a deletion ran or a path exists.
    target = answer.get('target')
    external = dirguard.is_external(target, workspace) if isinstance(target, str) and target and workspace else None
    record('UNSAFE', target=target, external=external)
    return prompts.render('cleanup_refusal', evidence=evidence, reason=explanation)
