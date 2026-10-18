"""Automatic protocol discovery, not explicit protocol adapters or HTTP transport.

Source-only: webfetch/apidiscovery still use their original dispatch. Callers capture
one definition and supply the existing pure classifier, read-only MCP/GraphQL
adapters, oversized-answer disclosure and factual renderer. No Root import, prompt,
answer cache, session clock, pending receipt or reset obligation lives here.

A result is offered to its caller, not claimed delivered. Only a truthy observed
contract substitutes the GET body; failure leaves requested document navigation
untouched. Cancellation propagates and a retry performs a new invocation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from .assistcontract import Policy, Reference


class ObservedDiscovery(Protocol):
    kind: str
    note: str
    routes: list[str]
    shapes: list[str]
    unread: str

    def __bool__(self) -> bool: ...


@dataclass(frozen=True)
class DiscoveryInput:
    """Actual requested URL and reduced GET evidence, including cached evidence.

    find/cursor/raw are retained for adapter transparency, not admission gates.
    They never disable existing automatic discovery or change the requested URL.
    """
    url: str
    status: int | None
    body: str
    content_type: str | None
    find: str | None = None
    cursor: str | None = None
    raw: bool = False


@dataclass(frozen=True)
class DiscoveryResult:
    """Invocation-local replacement; None means continue ordinary GET rendering."""
    text: str | None = None
    observed: ObservedDiscovery | None = None

    @property
    def discovered(self) -> bool:
        return self.observed is not None


Classifier = Callable[[str, int | None, str, str | None], str | None]
Adapter = Callable[[str], ObservedDiscovery | None]
Renderer = Callable[[str, int | None, str | None, ObservedDiscovery], str]


@dataclass(frozen=True)
class ObservationServices:
    """Protocol facts/adapters needed without any model-facing rendering."""
    classify: Classifier
    mcp: Adapter
    graphql: Adapter
    unread: Callable[[str, str], ObservedDiscovery]
    too_large: type[Exception]


@dataclass(frozen=True)
class DiscoveryServices(ObservationServices):
    render: Renderer


@dataclass(frozen=True)
class AsyncDiscoveryServices:
    """Async transport adapters, with the same pure classification/rendering facts."""
    classify: Classifier
    mcp: Callable[[str], Awaitable[ObservedDiscovery | None]]
    graphql: Callable[[str], Awaitable[ObservedDiscovery | None]]
    unread: Callable[[str, str], ObservedDiscovery]
    too_large: type[Exception]
    render: Renderer


def _result(value: DiscoveryInput, found: ObservedDiscovery | None,
            render: Renderer) -> DiscoveryResult:
    if not found:
        return DiscoveryResult()
    return DiscoveryResult(render(value.url, value.status, value.content_type, found), found)


def observation(value: DiscoveryInput,
                services: ObservationServices) -> ObservedDiscovery | None:
    """The single synchronous admission/request policy, without rendering.

    The classifier stays outside the best-effort adapter boundary, as in discover.
    Return the original truthy observed object, never a reconstructed schema.
    """
    kind = services.classify(value.url, value.status, value.body, value.content_type)
    if not kind:
        return None
    try:
        found = (services.mcp if kind == 'mcp' else services.graphql)(value.url)
    except services.too_large:
        found = services.unread(value.url, kind)
    except Exception:
        return None
    return found if found else None


def discovery(value: DiscoveryInput, services: DiscoveryServices) -> DiscoveryResult:
    """Observed admission followed by the actual caller-supplied factual renderer.

    Rendering remains outside the best-effort adapter boundary, as in webfetch.
    """
    return _result(value, observation(value, services), services.render)


async def discovery_async(value: DiscoveryInput,
                          services: AsyncDiscoveryServices) -> DiscoveryResult:
    """No detached work or retained state; cancellation is not an adapter failure."""
    kind = services.classify(value.url, value.status, value.body, value.content_type)
    if not kind:
        return DiscoveryResult()
    try:
        found = await (services.mcp if kind == 'mcp' else services.graphql)(value.url)
    except services.too_large:
        found = services.unread(value.url, kind)
    except Exception:
        return DiscoveryResult()
    return _result(value, found, services.render)


@dataclass(frozen=True)
class DiscoveryDefinition:
    policy: Policy
    execute: Callable[[DiscoveryInput, DiscoveryServices], DiscoveryResult] = discovery
    execute_async: Callable[[DiscoveryInput, AsyncDiscoveryServices], Awaitable[DiscoveryResult]] = discovery_async
    observe: Callable[[DiscoveryInput, ObservationServices], ObservedDiscovery | None] = observation


DEFINITION = DiscoveryDefinition(Policy(
    id='automatic-protocol-discovery', stage='protocol-discovery', default_level=0,
    family_id='F62', prompts=('api_discovery',),
    services=('protocol admission facts', 'read-only protocol adapters',
              'oversized-answer disclosure', 'observed contract renderer'),
    state='none; invocation-local observed answer, retry recomputes',
    hooks=(Reference('cria/discoverypolicy.py', 'discovery'),),
    regressions=(Reference('tests/test_protocol_discovery_policy.py', 'test_literal_substitution'),),
    migrated=False,
))


def selected_discovery(definition: DiscoveryDefinition | None, value: DiscoveryInput,
                       services: DiscoveryServices) -> DiscoveryResult:
    """Use exact captured selection. Absence does not even classify the GET."""
    if definition is None:
        return DiscoveryResult()
    return definition.execute(value, services)


def selected_observation(definition: DiscoveryDefinition | None, value: DiscoveryInput,
                         services: ObservationServices) -> ObservedDiscovery | None:
    """Observed-object public adapter: same selected identity, no dummy renderer.

    This callback is distinct from the rendered execute entrypoint. Replacements
    of one entrypoint do not implicitly replace the other or cause a reselection.
    """
    if definition is None:
        return None
    return definition.observe(value, services)


async def selected_discovery_async(definition: DiscoveryDefinition | None,
                                   value: DiscoveryInput,
                                   services: AsyncDiscoveryServices) -> DiscoveryResult:
    if definition is None:
        return DiscoveryResult()
    return await definition.execute_async(value, services)
