"""A chat endpoint that walks its failover chain when a call FAILS (not only when a role fails to resolve).

``Router`` hands this out wherever a role is called: the proxied coder/question turn (``Router.route``)
and the loop's own role calls (``Router.endpoint_for``: coder, reasoner, compactor, classifier). It is
the ONE call-site wiring of ``failover`` — callers keep calling ``chat`` / ``chat_watched`` /
``stream_chat`` exactly as on an ``Upstream`` and everything else (``loaded_model``, ``props``,
``_resolve_window`` …) is the PRIMARY hop's, so a pre-floor window question still asks the endpoint
the call goes to first.

The policy is not here: ``classify_exception`` says what a failure is,
``transientpolicy.choose`` says retry / walk / stop, ``failover.run`` executes it. This module only
turns "one request" into an ordered list of attempts, one per hop:

* The FIRST hop gets the caller's body untouched. Each later hop gets a copy whose ``model`` is that
  hop's own (never the previous server's name: ``base_url`` says where, not which) and is sent
  through THAT hop's ``Upstream`` — so the final-wire fit, the learned density and the window cap are
  the target's, never a body fitted for another window. Sampling, reasoning and instruction placement are
  the TARGET role's: ``Role.apply`` records the body as it was before it touched it (``bodykeys.ROLE_ORIGIN``,
  stripped at the wire) and a walked hop restores that and applies its own role. A body no role touched
  (pure proxy) walks as it is. A call that carries a coder route/observer binding (image-bound) is never walked.
* A stream is walked only BEFORE its first frame: the attempt opens the stream and pulls the first
  frame, so a refused connection / 5xx / dead silence is retried or walked, and once a frame exists
  the generator belongs to the caller and a later failure is the ordinary truthful failure.
* A buffered ``chat_watched`` whose text already left for the harness (``on_content`` ran) is not
  walked either: the harness has bytes.
* An image-bound request (``bodykeys.CODER_ROUTE``) is not walked: vision is the operator's explicit
  per-role declaration and the other hop was never declared for it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from . import bodykeys, config, failover, transientpolicy, windowcaps
from .upstream import UpstreamError


def classify_exception(e: BaseException) -> Optional[failover.Failure]:
    """What a raised upstream exception means for the chain: a transport/availability ``Failure``, or
    ``None`` when the exception is NOT a chain-walking failure and must surface unchanged.

    Not walked, each for a stated reason: a typed capacity rejection (``ContextRefitNoChange`` /
    ``InputOverflow`` / ``ReadFit*`` — the window owner's refit path settles those, a bigger window
    elsewhere is not its answer), a typed generation/protocol error (the reply arrived and was bad:
    a QUALITY matter, not transport), a request-shaped rejection (HTTP 400/413/422 — the same body is
    rejected the same way elsewhere), and anything that is not an upstream error at all
    (``ImageUnavailable``, a bug). The status/text → ``Failure`` mapping stays ``failover.classify_failure``'s."""
    if isinstance(e, UpstreamError):
        if type(e) is not UpstreamError:
            return None  # a typed subclass (protocol / capacity / read-fit / no-change) has its own owner
    elif not isinstance(e, OSError):
        return None
    code = getattr(e, "code", None)
    resp = getattr(e, "response_error", None)
    overflow = isinstance(resp, dict) and resp.get("code") == "context_length_exceeded"
    failure = failover.classify_failure(code, str(e), is_context_overflow=overflow)
    if failure is failover.Failure.CONTEXT_OVERFLOW or code in (400, 413, 422):
        return None
    return failure


@dataclass
class Hop:
    role: str
    provider: object
    model: Callable[[object], Optional[str]]  # lazy: a served hop's loaded model is probed only when walked to
    config: Optional[config.Role] = None  # the hop's OWN role: what a walked-to hop applies instead of the first role's settings


class ChainEndpoint:
    def __init__(self, chain_name: str, hops: list[Hop]) -> None:
        if len(hops) < 2:
            raise ValueError("a chain endpoint needs at least two distinct hops")
        self.chain_name = chain_name
        self.hops = tuple(hops)

    @property
    def primary(self):
        return self.hops[0].provider

    def __getattr__(self, name):  # only reached for what this class does not define
        if name in ("hops", "chain_name") or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.hops[0].provider, name)

    # ------------------------------------------------------------------ executor wiring

    def _runtime(self):
        from . import assistruntime
        if assistruntime.is_bound():
            return assistruntime.current()
        return assistruntime.AssistRuntime.select(
            level=getattr(self.primary, "_engagement_level", config.MAX_ENGAGEMENT_LEVEL))

    def _body_for(self, i: int, body: dict, rlog) -> dict:
        if i == 0:
            return body
        hop = self.hops[i]
        out = {**body, "messages": [dict(m) if isinstance(m, dict) else m for m in body.get("messages") or []]}
        origin = body.get(bodykeys.ROLE_ORIGIN)
        if isinstance(origin, config.RoleOrigin) and hop.config is not None:
            # The body carries the ORIGINATING role's temperature / top_k / thinking dialect. This hop is a different
            # role on a different endpoint: put the body back as it was before any role touched it and apply THIS one.
            origin.restore(out)
            hop.config.apply(out, internal=origin.internal, rlog=rlog)
        model = hop.model(rlog)
        if model:
            out["model"] = model
        else:
            out.pop("model", None)  # the target's _prep fills ITS loaded model
        return out

    def _info(self, i: int, rlog) -> Callable[[], dict]:
        def info():
            hop = self.hops[i]
            return {"to_window": windowcaps.known_window(hop.provider, rlog), "to_model": hop.model(rlog),
                    "refit": "final wire re-fitted for the target endpoint's own window"}
        return info

    def _attempts(self, body, rlog, call, *, spent) -> list:
        if body.get(bodykeys.CODER_ROUTE) is not None:
            return [failover.Attempt(self.hops[0].role, lambda: call(self.hops[0], body), spent)]
        return [failover.Attempt(h.role, (lambda h=h, i=i: call(h, self._body_for(i, body, rlog))), spent,
                                 self._info(i, rlog) if i else None)
                for i, h in enumerate(self.hops)]

    def _execute(self, body, rlog, call, *, spent, classify=None, runtime=None):
        return failover.run(self.chain_name, self._attempts(body, rlog, call, spent=spent),
                            classify or classify_exception, rlog,
                            runtime=runtime or self._runtime())

    # ------------------------------------------------------------------ the Upstream surface

    def chat(self, body: dict, rlog) -> bytes:
        # Upstream._chat already spent its own retry-same budget before an error reaches here.
        spent = transientpolicy.Behavior().retry_same_attempts
        return self._execute(body, rlog, lambda hop, b: hop.provider.chat(b, rlog), spent=spent)

    def chat_watched(self, body: dict, rlog, watch=None, on_content=None):
        delivered = []

        def fed(text):
            delivered.append(True)  # set BEFORE the callback: bytes may already be on their way
            return on_content(text)

        def call(hop, b):
            run = getattr(hop.provider, "chat_watched", None)
            if run is None:  # a cli hop has no watcher; its buffered chat is the same answer
                return hop.provider.chat(b, rlog)
            return run(b, rlog, watch=watch, on_content=fed if on_content is not None else None)

        def classify(e):
            return None if delivered else classify_exception(e)

        return self._execute(body, rlog, call, spent=0, classify=classify)

    def stream_chat(self, body: dict, rlog):
        """Like ``Upstream.stream_chat``: the request selection is captured NOW, the work starts on
        the first ``next``."""
        runtime = self._runtime()

        def call(hop, b):
            it = iter(hop.provider.stream_chat(b, rlog))
            try:
                first = next(it)
            except StopIteration:
                it.close() if hasattr(it, "close") else None
                raise UpstreamError("upstream stream ended before any data") from None
            except BaseException:
                it.close() if hasattr(it, "close") else None
                raise
            return _joined(first, it)


        def opened():
            yield from self._execute(body, rlog, call, spent=0, runtime=runtime)

        return opened()


def _joined(first, it):
    """The primed stream, handed on whole; closing it closes the upstream response."""
    try:
        yield first
        yield from it
    finally:
        if hasattr(it, "close"):
            it.close()
