"""Inference-free review of inert candidate source; never executes it.

PROVEN means every represented target violates a supported rule, conditional on
execution under the adapter's documented assumptions. This is not a sandbox.
"""
from dataclasses import asdict
from pathlib import PurePosixPath
from . import prompts, dirguard
from .cleanupfacts import Analysis, Finding


def analyze(path: str, source: str, workspace: str | None, permission: str = 'none') -> Analysis:
    suffix = PurePosixPath(path).suffix.lower()
    try:
        if suffix in ('.py', '.pyw'):
            from .cleanup_python import inspect_source
            result = inspect_source(source, workspace, permission)
            from .cleanup_languages import inspect_source as universal_scan
            leads = universal_scan(source, 'universal', workspace, permission)
            resolved = {(f.line, f.evidence) for f in result.findings}
            return Analysis(result.language, result.findings + tuple(
                f for f in leads.findings if (f.line, f.evidence) not in resolved), result.coverage)
        from .cleanup_extra import LANGUAGES as EXTRA_LANGUAGES, inspect_source as extra_scan
        if suffix in EXTRA_LANGUAGES:
            return extra_scan(source, EXTRA_LANGUAGES[suffix], workspace, permission)
        from .cleanup_languages import LANGUAGES, inspect_source
        language = LANGUAGES.get(suffix, 'universal')
        result = inspect_source(source, language, workspace, permission)
        if language == 'shell' and dirguard.root_recursive_delete_refusal(source):
            return Analysis('shell', result.findings + (Finding('PROVEN', 'root', 1, source, ('/',)),),
                            'supported-subset')
        return result
    except (RecursionError, SyntaxError, ValueError) as exc:
        return Analysis('python' if suffix in ('.py', '.pyw') else 'universal', (),
                        'invalid-source' if isinstance(exc, SyntaxError) else 'analysis-limit')


def review(path: str, candidate: str, previous: str | None, workspace: str | None,
           rlog=None, permission: str = 'none') -> str | None:
    if candidate == previous:
        return None
    result = analyze(path, candidate, workspace, permission)
    if rlog is not None:
        rlog.emit('safety.cleanup_review', path=path, verdict='UNSAFE' if result.blocked else 'NOT_BLOCKED',
                  coverage=result.coverage, findings=[asdict(f) for f in result.findings])
    proven = [f for f in result.findings if f.confidence == 'PROVEN']
    if not proven:
        return None
    descriptions = prompts.load_map('cleanup_findings')
    return prompts.render('cleanup_refusal', evidence='\n\n'.join(f.evidence for f in proven),
                          reason='\n'.join(descriptions[f.rule] for f in proven))
