"""Is a URL in text cria AUTHORED actually supported by the evidence cria composed?

cria writes text that the coder then treats as instruction: a steer that redirects it, a plan step it
follows verbatim. Every prompt that authors such text already forbids inventing concrete external
details — the steer author is told "NEVER invent a file path, directory, command, value, or error that
does not appear above", the living replanner is told "DON'T CODIFY A GUESS: never bake into a step a
concrete external detail the coder has NOT confirmed from the real source". A prompt is a request, not
an enforcement, and small models break both rules. This module is the enforcement.

It can be deterministic because cria COMPOSED the evidence: the claim is checked against it exactly,
never judged. Deterministic code gathers, and here there is nothing left to judge.

MEASURED, three sites, two runs:
  * a steer told the coder to fetch `https://api.handle.me/api/` — a host all over the evidence with a
    path in none of it. The coder obeyed and ran `curl` against the invented route.
  * an initial PLAN step said "send a POST request to the resolve endpoint at
    `https://api.handle.me/resolve`", submitted after 17 real `web_fetch` rounds. The coder built to it
    and got a 404, then thrashed on error handling for an endpoint that does not exist.
  * in the same session a steer told the coder to fetch `<host>/handles` after reading
    `GET /handles/{handle}` in the fetched spec — a correct route SYNTHESIZED from real facts, and
    exactly the steer that must SURVIVE. Grounding is a test for invention, not for novelty.
"""
from __future__ import annotations

import re
import urllib.parse

# `}` stays excluded so a URL inside prose or JSON ends cleanly — but a BALANCED `{…}` is a path
# TEMPLATE and part of the route: `https://api.handle.me/holders/{address}`. Truncating at the brace
# left `/holders/{address` and `/holders/{holder_address`, which can never match each other.
URL_RE = re.compile(r"https?://(?:\{[^{}\s]*\}|[^\s\"'<>)\]},;])+")

# A path template's VARIABLE NAME is not part of the route. `/holders/{address}` and
# `/holders/{holder_address}` are the same endpoint; comparing them literally declared a route the
# session had genuinely fetched "UNVERIFIED", and the resulting steer told the model to go and fetch
# it — in a phase whose only tool was submit_plan. Measured on both zaya1 runs (2026-08-01), one
# wasted planner round each, on a model decoding at 40 tok/s against a 15-minute wall.
_PATH_TEMPLATE = re.compile(r"\{[^{}/]*\}")


def _normalize_template(url: str) -> str:
    """A URL with every path variable's NAME erased, so two spellings of one route compare equal."""
    return _PATH_TEMPLATE.sub("{}", url)
_TRAIL = "`\\.,:;'\"*)]}> "


def _seen_bounded(needle: str, hay: str) -> bool:
    """``needle`` occurs in ``hay`` and is not merely the PREFIX of a longer name. Without the boundary
    the invented route `/resolve` counted as grounded, because the planner's evidence happened to hold
    `./path/to/your/resolveOpenApiReferences` and `endpoint/resolver` (both measured, in the very
    evidence that produced the POST-to-`/resolve` plan step)."""
    return re.search(re.escape(needle) + r"(?![\w-])", hay) is not None


def host_is_grounded(url: str, evidence: str) -> bool:
    """Is this url's HOST one the session actually named or touched? Path not considered.

    The weaker sibling of :func:`ungrounded_urls`, for the one caller whose JOB is to propose a route
    nobody has fetched yet: the outgoing-search judge recommends "fetch <the domain the task named>'s
    spec" and cria substitutes that fetch for the coder's search. Requiring the PATH to have been seen
    would defeat the whole recommendation (if it had been seen, there would be nothing to recommend),
    but the HOST must still be one the work is actually about — the failure to stop is the judge
    sending the coder to an unrelated site it invented."""
    try:
        host = urllib.parse.urlsplit(url).netloc.lower()
    except ValueError:
        return False
    return bool(host) and host in (evidence or "").lower()


_METHOD_ROUTE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[^\s\"'`,;)\]}]*)")


def ungrounded_routes(text: str, evidence: str) -> list[str]:
    """API routes written as ``METHOD /path`` that the evidence never showed.

    The URL check above is deliberately URL-scoped, because a bare path in authored text is ambiguous
    — "write tests/test_x.py" names a file that SHOULD NOT exist yet. A METHOD prefix removes that
    ambiguity: nothing legitimately writes `POST /handles/resolve` about a file it is creating. It is
    an assertion that an endpoint exists, and cria's own shape ledger renders endpoints in exactly
    this form, which is where a judge learns to write them.

    MEASURED (run 0727-153326): a plan step presupposed "the resolve endpoint", the step critic
    hardened it into `POST /handles/resolve` — a route in no spec — and proposed it as a concrete
    next move 12 times. The coder grepped for that literal string across 322 calls on one step.

    Only the PATH must have been seen: a spec lists paths and keys the method inside them, so
    requiring the method too would reject a correct route read straight out of the source."""
    bad = []
    for m in _METHOD_ROUTE.finditer(text or ""):
        route = m.group(2).rstrip(_TRAIL)
        if route.strip("/") and not _seen_bounded(route, evidence or ""):
            bad.append(f"{m.group(1)} {route}")
    return bad


def ungrounded_urls(text: str, evidence: str) -> list[str]:
    """The URLs ``text`` names that ``evidence`` cannot support.

    A URL is grounded when its host was seen AND its route is real. A route is real when either the
    exact ``host+path`` appears in the evidence (that URL was actually touched), or the path appears in
    the evidence's PROSE — outside every URL — meaning a fetched document DEFINES it (a spec's
    ``paths:`` block, a docs page's route table).

    Each clause was forced by a measured miss, not anticipated:

    * *host anywhere + path anywhere* passed the invented `https://api.handle.me/resolve`: `/resolve`
      was "in the evidence" only inside OTHER hosts' URLs (`reimagined.github.io/resolve`,
      `wikidiff.com/handle/resolve`). Hence the path must be found OUTSIDE urls.
    * *``host+path`` verbatim only* would have deleted the good synthesized `<host>/handles` steer,
      whose route the fetched spec defines but never spells as a full URL. Hence the prose clause.
    * plain substring matching — see :func:`_seen_bounded`.

    A bare host (no path, or ``/``) is grounded by the host alone: that is the domain-root fetch cria
    itself recommends, not a guessed route.

    Scope is URLs only, deliberately. The same prompts also forbid inventing FILE PATHS and FIELD NAMES,
    but authored text may legitimately name a file that does not exist yet ("write tests/test_x.py") or
    a key the script itself will define. Measured: `resolved_address` was poison in one re-derived step
    (asserted as the API's response field, unfindable, so the critic blocked that step forever) and
    legitimate in the very next step (the script's OWN output key). One token, both roles — no lexical
    rule separates them, and deleting on a guess is the footgun class this exists to prevent.
    """
    bad = []
    for raw in URL_RE.findall(text or ""):
        # `}` is in _TRAIL so a URL inside JSON/prose ends cleanly — but stripping it off a BALANCED
        # path template re-creates the truncation this regex was just fixed to avoid.
        url = raw if raw.endswith("}") and raw.count("{") == raw.count("}") else raw.rstrip(_TRAIL)
        try:
            parts = urllib.parse.urlsplit(url)
        except ValueError:
            continue
        host, path = parts.netloc, parts.path
        if host and host.lower() not in evidence.lower():
            bad.append(url)
            continue
        if not path.strip("/"):
            continue
        # Compare the route with path-variable NAMES erased on both sides, so `/holders/{address}`
        # and `/holders/{holder_address}` are recognised as one endpoint.
        ev_norm = _normalize_template(evidence)
        n_host_path, n_path = _normalize_template(host + path), _normalize_template(path)
        if not (_seen_bounded(host + path, evidence)
                or _seen_bounded(path, URL_RE.sub(" ", evidence))
                or _seen_bounded(n_host_path, ev_norm)
                or _seen_bounded(n_path, URL_RE.sub(" ", ev_norm))):
            bad.append(url)
    return bad
