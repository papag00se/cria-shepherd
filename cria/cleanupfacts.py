"""Language-neutral path/resource facts and confidence policy. No workspace IO."""
from dataclasses import dataclass
import posixpath
from . import dirguard


@dataclass(frozen=True)
class PathFact:
    kind: str
    text: str = ''
    parent: 'PathFact | None' = None


def parent_fact(atom):
    if atom.kind == 'path':
        return parent_fact(atom.parent)
    if atom.kind == 'literal':
        return PathFact('literal', posixpath.dirname(atom.text))
    if atom.parent is not None and atom.kind in ('temp-file', 'temp-dir', 'owned-child'):
        return atom.parent
    return PathFact('temp-parent' if atom.kind in ('temp-file', 'temp-dir') else 'unknown')


def join_fact(left, right):
    if right.kind != 'literal':
        return PathFact('unknown')
    if right.text.startswith('/'):
        return right
    if left.kind == 'literal':
        return PathFact('literal', posixpath.join(left.text, right.text))
    if left.kind in ('temp-dir', 'owned-child') and '..' not in right.text.split('/'):
        return PathFact('owned-child', parent=left)
    return PathFact('unknown')


def classify(targets, workspace, permission, recursive=False, possible=False):
    rules = []
    for atom in targets:
        if atom.kind == 'path':
            atom = atom.parent
        if recursive and atom.kind == 'temp-parent':
            rules.append('temp_parent')
        elif atom.kind == 'literal' and atom.text.startswith('/'):
            if recursive and posixpath.normpath(atom.text) == '/':
                rules.append('root')
            elif workspace and permission != 'write' and dirguard.is_external(atom.text, workspace):
                rules.append('external')
            else:
                rules.append('within' if workspace else 'unknown')
        elif atom.kind in ('temp-file', 'temp-dir', 'owned-child'):
            rules.append('within')
        else:
            rules.append('unknown')
    unsafe = [r for r in rules if r not in ('within', 'unknown')]
    confidence = ('PROVEN' if unsafe and len(unsafe) == len(rules) and not possible
                  else 'POSSIBLE' if unsafe else 'UNKNOWN' if not rules or 'unknown' in rules else 'WITHIN_SCOPE')
    rule = next((r for r in ('root', 'temp_parent', 'external') if r in unsafe),
                'unresolved' if confidence == 'UNKNOWN' else 'within')
    return confidence, rule


@dataclass(frozen=True)
class Finding:
    confidence: str  # PROVEN, POSSIBLE, UNKNOWN, WITHIN_SCOPE
    rule: str
    line: int
    evidence: str
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class Analysis:
    language: str
    findings: tuple[Finding, ...]
    coverage: str  # supported-subset, universal-lexical-only, invalid-source, analysis-limit

    @property
    def blocked(self):
        return any(f.confidence == 'PROVEN' for f in self.findings)
