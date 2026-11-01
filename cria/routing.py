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
shared endpoint.

The chain is also walked when a CALL fails: the provider ``route`` / ``endpoint_for`` hand out is a
``ChainEndpoint`` over the resolved role and every later resolvable role of its chain that runs on a
DIFFERENT endpoint (two roles on one server share a fate, so the second adds nothing and is
dropped; with nothing left the plain provider is returned and nothing changes). The lane of a loop
role is the chain named for its job: coder -> ``coding``, reasoner -> ``reasoning``,
classifier -> ``classification``, compactor -> ``compaction``. Reasoning/sampling is NOT applied here — the caller applies ``role.apply(body)``,
which translates the role's one portable reasoning value into its backend's convention.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from .claude_cli import ClaudeCliProvider
from .chainendpoint import ChainEndpoint, Hop
from .config import Backend, RoutingConfig
from .envfile import env_secret
from .upstream import Upstream
from . import receivecapture


_LANES = {"coder": "coding", "reasoner": "reasoning", "classifier": "classification",
          "compactor": "compaction"}


class _Silent:
    """Construction-time events of ``endpoint_for`` (no request logger exists yet) go nowhere."""
    @staticmethod
    def emit(*a, **k):
        return None


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
                                           engagement_level=cfg.engagement_level,
                                           capture_dir=getattr(local_provider, '_capture_dir', None),
                                           capture_rendered=getattr(local_provider, '_capture_rendered', True),
                                           open_request=(getattr(local_provider, '_receive_open', None)
                                                         or receivecapture.DefaultTransport())
                                           if getattr(local_provider, '_capture_dir', None) is not None else None)
        )
        self._claude_factory = claude_factory or (
            lambda b: ClaudeCliProvider(b.binary, b.cwd, timeout)
        )
        self._cache: dict[tuple, object] = {}

    def route(self, task_type: str, rlog) -> Route | None:
        chain = self._chain_for(task_type)
        if not chain:
            return None  # no routing config → caller does passthrough
        for k, role in enumerate(chain):
            resolved = self._resolve(role, rlog)
            if resolved is not None:
                provider, model = resolved
                rlog.decide("route", role, f"task_type={task_type}", model=model)
                provider = self._walkable(task_type, role, provider, chain[k + 1:], rlog, http_only=False)
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

    def _walkable(self, chain_name: str, role: str, provider, tail, rlog, *, http_only: bool):
        """``provider`` itself, or a ``ChainEndpoint`` that falls through to the resolvable roles of
        ``tail`` (the chain after ``role``) on other endpoints when a call fails."""
        hops = [Hop(role, provider, self._model_of(role, provider), self._cfg.roles.get(role))]
        for nxt in tail:
            found = self._provider_for(nxt, rlog)
            if found is None:
                rlog.emit("route.skip", role=nxt, reason="unresolvable")
                continue
            p, model, backend = found
            if (http_only and backend.transport == "cli") or any(p is h.provider for h in hops):
                continue
            hops.append(Hop(nxt, p, model, self._cfg.roles.get(nxt)))
        return ChainEndpoint(chain_name, hops) if len(hops) > 1 else provider

    def _model_of(self, role: str, provider):
        found = self._provider_for(role)
        return found[1] if found is not None and found[0] is provider else (lambda rlog: None)

    def endpoint_for(self, role: str) -> Upstream:
        """The http Upstream a role runs on, for the loop's OWN internal calls (coder/reasoner/
        compactor/classifier). A served backend → the shared endpoint or its own base_url; a KEYED
        http backend → an authed Upstream (so a loop role hosted on groq/openrouter is reachable, not
        just the proxy-routed coder). A cli backend can't be a raw chat endpoint: config refuses one for these
        roles at load, so the fallback to the shared endpoint is only for a hand-built config. Unknown role → the shared endpoint. When the role's lane chain (see the
        module docstring) continues on another endpoint, the result walks to it on a failed call."""
        plain = self._plain_endpoint(role)
        lane = _LANES.get(role)
        chain = self._cfg.failover.get(lane) if lane else None
        if not chain or self._cfg.roles.get(role) is None:
            return plain
        tail = chain[chain.index(role) + 1:] if role in chain else chain
        return self._walkable(lane, role, plain, tail, _Silent, http_only=True)

    def _plain_endpoint(self, role: str) -> Upstream:
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

    def _provider_for(self, role: str, rlog=None):
        """``(provider, lazy model, backend)`` of a role, or None when it cannot resolve (missing
        key / binary / backend). Never probes a server: the loaded-model lookup is the lazy part."""
        r = self._cfg.roles.get(role)
        if r is None:
            return None
        b = self._cfg.backends.get(r.backend)
        if b is None:
            return None
        if b.transport == "cli":
            provider = self._build_cli(b)
            return (provider, lambda rl: b.model, b) if provider is not None else None
        if b.api_key_env:  # keyed remote http
            provider = self._build_http_keyed(b, rlog)
            return (provider, lambda rl: b.model, b) if provider is not None else None
        # served (keyless) http — cria uses whatever model the server reports loaded
        provider = self._served_endpoint(b)
        return provider, (lambda rl, p=provider: p.loaded_model(rl)), b

    def _resolve(self, role: str, rlog) -> tuple[object, str | None] | None:
        found = self._provider_for(role, rlog)
        if found is None:
            return None
        provider, model, _ = found
        # A served role's model is resolved NOW so the wire model + banner + density key carry the real name.
        return provider, model(rlog)

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
