"""Automatic document advice, separate from requested retrieval and factual support.

Source-only extraction: original public renderers are not yet bound to these definitions.
No delivery memory: a result belongs to its invocation, is discarded on cancellation,
and is recomputed on retry/reset. Providers must not fetch, spill or mutate caches.
"""
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from . import prompts
from .assistcontract import Policy, Reference


@dataclass(frozen=True)
class GuidanceInput:
    mode: Literal['inline', 'spill', 'planner_fetch', 'planner_search']
    parsed: Any = None
    target: str = ''
    offset: int = 0
    more: bool = False
    facts: Mapping | None = None


@dataclass(frozen=True)
class GuidanceResult:
    text: str = ''


@dataclass(frozen=True)
class GuidanceServices:
    catalog: Callable
    routes: Callable
    keys: Callable
    shapes: Callable
    shape_block: Callable
    load: Callable = prompts.load_map


def guidance(value: GuidanceInput, services: GuidanceServices) -> GuidanceResult:
    """Render existing automatic advice; mandatory response framing is caller-owned."""
    if value.mode in ('planner_fetch', 'planner_search'):
        if value.facts is None or (value.mode == 'planner_fetch' and value.parsed is not None):
            return GuidanceResult()
        if any((e[1] if len(e) > 1 else '') for e in value.facts.values()):
            return GuidanceResult()
        key = 'fetch_no_structure' if value.mode == 'planner_fetch' else 'search_no_structure'
        return GuidanceResult(services.load('planner_steers')[key])
    if value.mode not in ('inline', 'spill'):
        raise ValueError(value.mode)
    if value.mode == 'inline' and (value.offset != 0 or value.parsed is None):
        return GuidanceResult()
    lines = services.load('document_guidance_outline')

    def fill(key: str, **kwargs: str) -> str:
        return prompts.fill(lines[key], **kwargs)

    catalog = services.catalog(value.parsed)
    text = ''
    if catalog:
        text = fill('catalog', count=str(len(catalog)), links='\n'.join('  ' + c for c in catalog))
        if value.mode == 'spill':
            return GuidanceResult(text)
    if value.mode == 'inline' and not value.more:
        return GuidanceResult(text)
    if value.mode == 'inline':
        keys = services.keys(value.parsed)
        if keys:
            text += fill('inline_keys', keys=', '.join(keys))
    routes = services.routes(value.parsed)
    if routes:
        text += fill('routes', count=str(len(routes)), routes=', '.join(routes))
        text += services.shape_block(services.shapes(value.parsed))
        if value.mode == 'inline':
            return GuidanceResult(text + lines['inline_hint'])
        example = next((r for r in routes if '{' in r), next((r for r in routes if len(r) > 1), None))
        return GuidanceResult(text + fill('route_hint' if example else 'plain_hint', example=example or '', target=value.target))
    if value.mode == 'spill':
        keys = [k for k in services.keys(value.parsed) if k != '[array]']
        if keys:
            text += fill('keys', count=str(len(keys)), keys=', '.join(keys))
            text += fill('key_hint', example=keys[0], target=value.target)
    return GuidanceResult(text)


@dataclass(frozen=True)
class GuidanceDefinition:
    policy: Policy
    execute: Callable = guidance


DEFINITION = GuidanceDefinition(Policy(
    id='automatic-document-guidance', stage='document-guidance', default_level=0,
    family_id='F62', prompts=('document_guidance_outline', 'planner_steers'),
    services=('parsed document navigation facts', 'prompt loader'),
    state='none; invocation-local result, discard on cancel and recompute on retry',
    hooks=(Reference('cria/documentguidance.py', 'guidance'),),
    regressions=(Reference('tests/test_document_guidance_policy.py', 'test_spill_literal'),),
    migrated=False,
))


def selected_guidance(definition: GuidanceDefinition | None, value: GuidanceInput,
                      services: GuidanceServices) -> GuidanceResult:
    """Use the exact captured selection, never ambient state; absence is lazy."""
    if definition is None:
        return GuidanceResult()
    return definition.execute(value, services)
