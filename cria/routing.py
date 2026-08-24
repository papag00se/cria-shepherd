"""Router — turn a classified ``task_type`` into the concrete (provider, model) to call, by
walking the configured failover chain and taking the first *resolvable* role.

A role names a backend, and a backend resolves to:
* a **served** http endpoint (keyless — cria uses the model the server reports loaded), or
* a **keyed** http endpoint (a remote provider — resolvable only when its ``api_key_env`` key is
  present in the environment), or
* a **cli** subprocess (resolvable only when its binary is on PATH).

A role whose backend can't resolve (missing key/binary) is SKIPPED, so a chain like
``["coder", "reasoner"]`` collapses to whatever resolves. When nothing resolves (or there is no
routing config), ``route`` returns ``None`` and the caller falls back to a plain passthrough on the
shared endpoint. Reasoning/sampling is NOT applied here — the caller applies ``role.apply(body)``,
which translates the role's one portable reasoning value into its backend's convention.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from .claude_cli import ClaudeCliProvider
from .config import Backend, RoutingConfig
from .envfile import env_secret
from .upstream import Upstream


@dataclass
class Route:
    provider: object  # Upstream (HTTP) or ClaudeCliProvider — both expose stream_chat/chat
    model: str | None  # None = a served role with no alias; the upstream fills the server's loaded model
    role: str
    reason: str


class Router:
    def __init__(
        self,
        cfg: RoutingConfig,
        local_provider: Upstream,
        *,
        timeout: int = 600,
        context_window: int = 0,
        provider_factory=None,
        claude_factory=None,
    ) -> None:
        self._cfg = cfg
        self._local = local_provider  # the shared [defaults] endpoint
        self._timeout = timeout
        # A pinned window applies to every HTTP backend that inherits [defaults] — same server.
        self._context_window = context_window
        self._provider_factory = provider_factory or (
            # The ladder level rides to EVERY backend, not just [defaults]: a level-0 run that
            # routed one role to a second endpoint would otherwise get the full treatment there and
            # the arm would be contaminated by the thing it exists to isolate.
            lambda base_url, key: Upstream(base_url, timeout, api_key=key,
                                           context_window=context_window or None,
                                           engagement_level=cfg.engagement_level)
        )
        self._claude_factory = claude_factory or (
            lambda b: ClaudeCliProvider(b.binary, b.cwd, timeout)
        )
        self._cache: dict[tuple, object] = {}

    def route(self, task_type: str, rlog) -> Route | None:
        chain = self._chain_for(task_type)
        if not chain:
            return None  # no routing config → caller does passthrough
        for role in chain:
            resolved = self._resolve(role, rlog)
            if resolved is not None:
                provider, model = resolved
                rlog.decide("route", role, f"task_type={task_type}", model=model)
                return Route(provider, model, role, f"chain[{task_type}] -> {role}")
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
        executor. Unresolvable links (missing key/binary) are skipped and logged; an empty list
        means no routing config / nothing resolved."""
        routes: list[Route] = []
        for role in self._chain_for(task_type):
            resolved = self._resolve(role, rlog)
            if resolved is not None:
                provider, model = resolved
                routes.append(Route(provider, model, role, f"chain[{task_type}] -> {role}"))
            else:
                rlog.emit("route.skip", role=role, reason="unresolvable")
        return routes

    def endpoint_for(self, role: str) -> Upstream:
        """The http Upstream a role runs on, for the loop's OWN internal calls (coder/reasoner/
        compactor/classifier). A served backend → the shared endpoint or its own base_url; a KEYED
        http backend → an authed Upstream (so a loop role hosted on groq/openrouter is reachable, not
        just the proxy-routed coder). A cli backend can't be a raw chat endpoint, so it falls back to
        the shared endpoint. Unknown role → the shared endpoint."""
        r = self._cfg.roles.get(role)
        if r is None:
            return self._local
        b = self._cfg.backends.get(r.backend)
        if b is None or b.transport == "cli":
            return self._local
        if b.api_key_env:  # keyed remote — build the authed endpoint
            authed = self._build_http_keyed(b)
            return authed if authed is not None else self._local
        return self._served_endpoint(b)

    def _resolve(self, role: str, rlog) -> tuple[object, str | None] | None:
        r = self._cfg.roles.get(role)
        if r is None:
            return None
        b = self._cfg.backends.get(r.backend)
        if b is None:
            return None
        if b.transport == "cli":
            provider = self._build_cli(b)
            return (provider, b.model) if provider is not None else None
        if b.api_key_env:  # keyed remote http
            provider = self._build_http_keyed(b, rlog)
            return (provider, b.model) if provider is not None else None
        # served (keyless) http — cria uses whatever model the server reports loaded. Resolve it now
        # so the wire model + banner + density key carry the real name.
        provider = self._served_endpoint(b)
        return provider, provider.loaded_model(rlog)

    def _served_endpoint(self, b: Backend) -> Upstream:
        """The http Upstream a served (keyless) backend runs on — the shared [defaults] one, or the
        backend's OWN base_url. Cached per endpoint."""
        if not b.base_url or b.base_url == self._cfg.defaults_base_url:
            return self._local
        return self._cached(("served", b.base_url), lambda: self._provider_factory(b.base_url, None))

    def _build_http_keyed(self, b: Backend, rlog=None) -> object | None:
        """Build an authed Upstream for a keyed http backend, or None if its key is absent."""
        key = env_secret(b.api_key_env)  # normalized (CRLF-safe), same hygiene as the search key
        if b.api_key_env and not key:
            if rlog is not None:  # name the missing var — a credentials gap should not look like "offline by choice"
                rlog.emit("routing.backend_skipped", level="warn", backend=b.name, missing=b.api_key_env)
            return None
        return self._cached(("keyed", b.base_url, key), lambda: self._provider_factory(b.base_url, key))

    def _build_cli(self, b: Backend) -> object | None:
        """Build the CLI provider for a cli backend, or None if its binary isn't on PATH."""
        if not _cli_available(b.binary):
            return None
        return self._cached(("cli", b.binary, b.cwd), lambda: self._claude_factory(b))

    def _cached(self, key: tuple, build):
        provider = self._cache.get(key)
        if provider is None:
            provider = build()
            self._cache[key] = provider  # persist session state across requests
        return provider


def _cli_available(binary: str) -> bool:
    """Whether the CLI binary is on PATH (or an executable absolute path), so a cli-backed role
    that can't run is skipped in the failover chain rather than failing at call time."""
    if os.sep in binary or (os.altsep and os.altsep in binary):
        return os.path.isfile(binary) and os.access(binary, os.X_OK)
    return shutil.which(binary) is not None
