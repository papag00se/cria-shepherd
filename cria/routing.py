"""Router — turn a classified ``task_type`` into the concrete (provider, model) to
call, by walking the configured failover chain and taking the first *resolvable*
role.

A role resolves to:
* a **local** model (a name in ``[models.local]``, served by ``[upstream]``), or
* a **cloud** pool (``cloud.<name>``) — a weighted pick, resolvable only when the
  provider's key is present in the environment AND ``local_only`` is off.

``local_only`` (the default research posture) makes every cloud role unresolvable,
so a chain like ``["coder", "cloud.coder"]`` collapses to just the local link.
When nothing resolves (or there is no routing config at all), ``route`` returns
``None`` and the caller falls back to a plain passthrough on the local upstream.
"""

from __future__ import annotations

import os
import random
import shutil
from dataclasses import dataclass

from . import reasoning
from .claude_cli import ClaudeCliProvider
from .config import CloudEntry, ProviderConfig, RoutingConfig
from .envfile import env_secret
from .upstream import Upstream


@dataclass
class Route:
    provider: object  # Upstream (HTTP) or ClaudeCliProvider — both expose stream_chat/chat
    model: str | None  # None = the role omitted its alias; the upstream fills the server's loaded model
    role: str
    reason: str
    # A CLOUD entry's reasoning setting + the endpoint's reasoning convention, so the send site can
    # translate on/off into the backend's shape (reasoning.apply_reasoning). None for local routes —
    # a local role's reasoning is applied separately via LocalRole.apply.
    reasoning: str | None = None
    reasoning_style: str | None = None


class Router:
    def __init__(
        self,
        cfg: RoutingConfig,
        local_provider: Upstream,
        *,
        timeout: int = 600,
        rng=None,
        provider_factory=None,
        claude_factory=None,
    ) -> None:
        self._cfg = cfg
        self._local = local_provider
        self._timeout = timeout
        self._rng = rng or random.random  # weighted cloud pick; injectable for tests
        self._provider_factory = provider_factory or (
            lambda base_url, key: Upstream(base_url, timeout, api_key=key)
        )
        self._claude_factory = claude_factory or (
            lambda pc: ClaudeCliProvider(pc.binary, pc.cwd, timeout)
        )
        self._cloud_cache: dict[tuple, object] = {}

    def route(self, task_type: str, rlog) -> Route | None:
        chain = self._chain_for(task_type)
        if not chain:
            return None  # no routing config → caller does passthrough
        for role in chain:
            resolved = self._resolve(role, rlog)
            if resolved is not None:
                provider, model, rsn, style = resolved
                rlog.decide("route", role, f"task_type={task_type}", model=model)
                return Route(provider, model, role, f"chain[{task_type}] -> {role}", rsn, style)
            rlog.emit("route.skip", role=role, reason="unresolvable")
        rlog.emit("route.exhausted", level="warn", task_type=task_type, chain=list(chain))
        return None

    def _chain_for(self, task_type: str) -> tuple[str, ...]:
        fo = self._cfg.failover
        if task_type in fo:
            return fo[task_type]
        if task_type == "question":  # answer a question with the reasoner, else the coder
            return fo.get("reasoning") or fo.get("coding") or ()
        return fo.get("coding") or ()

    def route_chain(self, task_type: str, rlog) -> list[Route]:
        """The ORDERED list of resolvable routes for a task_type — the input to the failover
        executor. Unresolvable links (cloud off under local_only, missing key) are skipped and
        logged; an empty list means no routing config / nothing resolved."""
        routes: list[Route] = []
        for role in self._chain_for(task_type):
            resolved = self._resolve(role, rlog)
            if resolved is not None:
                provider, model, rsn, style = resolved
                routes.append(Route(provider, model, role, f"chain[{task_type}] -> {role}", rsn, style))
            else:
                rlog.emit("route.skip", role=role, reason="unresolvable")
        return routes

    def _local_endpoint(self, lr) -> Upstream:
        """The Upstream a local role runs on — the shared [upstream] one, or the role's OWN base_url
        (cria does not assume every role is on the same host/port). Cached per endpoint."""
        if not lr.base_url:
            return self._local
        return self._cached(("local", lr.base_url.rstrip("/")),
                            lambda: self._provider_factory(lr.base_url, None))

    def endpoint_for(self, role: str) -> Upstream:
        """The local Upstream a role runs on — its OWN base_url when the role sets one, else the shared
        endpoint. The always-local roles (classifier / reasoner / planner / compactor) resolve THROUGH
        this so a per-role base_url is honored for EVERY role, not only the coder (which already routed
        per-role via route()). A role with no [models.local.<role>] table → the shared endpoint."""
        lr = self._cfg.local_roles.get(role)
        return self._local_endpoint(lr) if lr is not None else self._local

    def _resolve(self, role: str, rlog) -> tuple[object, str | None] | None:
        if role in self._cfg.local_roles:
            # There are no local aliases — cria always uses the server's loaded model. Resolve it now
            # so the wire model + banner + density key carry the real name. None if the server is
            # unreachable; the upstream fills it (or leaves the request's own model) at call time.
            provider = self._local_endpoint(self._cfg.local_roles[role])
            return provider, provider.loaded_model(rlog), None, None
        if role in self._cfg.cloud_pools:
            if self._cfg.local_only:
                return None
            entry = self._pick(self._cfg.cloud_pools[role])
            if entry is None:
                return None
            provider_cfg = self._cfg.providers.get(entry.provider)
            if provider_cfg is None:
                return None
            provider = self._build_cloud(provider_cfg, rlog)
            if provider is None:
                return None
            style = provider_cfg.reasoning_style or reasoning.infer_style(provider_cfg.base_url)
            return provider, entry.model, entry.reasoning, style
        return None

    def _build_cloud(self, pc: ProviderConfig, rlog=None) -> object | None:
        """Build the provider for a cloud entry, or ``None`` if it's unresolvable
        (missing key for HTTP, missing binary for the Claude CLI)."""
        if pc.kind == "claude_cli":
            if not _claude_available(pc.binary):
                return None
            return self._cached(("claude", pc.binary, pc.cwd), lambda: self._claude_factory(pc))
        key = env_secret(pc.api_key_env)  # normalized (CRLF-safe), same hygiene as the search key
        if pc.api_key_env and not key:
            if rlog is not None:  # name the missing var — a credentials gap should not look like "local by choice"
                rlog.emit("routing.cloud_skipped", level="warn", provider=pc.base_url, missing=pc.api_key_env)
            return None  # no credentials in the environment → unresolvable
        return self._cached(("http", pc.base_url, key), lambda: self._provider_factory(pc.base_url, key))

    def _cached(self, key: tuple, build):
        provider = self._cloud_cache.get(key)
        if provider is None:
            provider = build()
            self._cloud_cache[key] = provider  # persist session state across requests
        return provider

    def _pick(self, entries: tuple[CloudEntry, ...]) -> CloudEntry | None:
        live = [e for e in entries if e.weight > 0]
        if not live:
            return None
        if len(live) == 1:
            return live[0]
        total = sum(e.weight for e in live)
        target = self._rng() * total
        acc = 0
        for e in live:
            acc += e.weight
            if target < acc:
                return e
        return live[-1]

def _claude_available(binary: str) -> bool:
    """Whether the ``claude`` binary is on PATH (or an executable absolute path), so
    a Claude-CLI role that can't run is skipped in the failover chain rather than
    failing at call time."""
    if os.sep in binary or (os.altsep and os.altsep in binary):
        return os.path.isfile(binary) and os.access(binary, os.X_OK)
    return shutil.which(binary) is not None
