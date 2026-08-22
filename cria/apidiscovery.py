"""Discovery for APIs that publish no fetchable description document.

OpenAPI, Swagger and an RFC 9727 api-catalog are DOCUMENTS: cria GETs them and reads them
(:mod:`cria.webfetch`). MCP and GraphQL are PROTOCOLS — there is no manifest to fetch, and the only
standard way to learn what a server offers is to ask it, over POST. A GET of an MCP endpoint typically
answers 405; a GET of a GraphQL endpoint answers 400 or a playground page. Either way the model is left
with a URL it was told exists and nothing about how to call it, which is the same "has the endpoint,
guesses the shape" failure the spec outline exists to prevent.

Measured on the very task this repo drives: api.handle.me's front page advertises an MCP endpoint, cria's
own route list carries `/mcp`, and both were dead ends — the entry appeared and nothing was ever learned
from it.

POSTING, and its bounds. cria only ever sends the two fixed, read-only discovery payloads below, only to
a URL the MODEL already asked cria to fetch, and only when that URL answers like the protocol in
question. There is no path by which a model's prose becomes an arbitrary POST body: the bodies are
constants in this file. MCP's `tools/list` and GraphQL's introspection query are both defined as
read-only by their specifications — this never CALLS a tool or runs a mutation.

What comes back is rendered through webfetch's EXISTING markers (`ROUTES_MARKER` / `SHAPE_MARKER`), which
is what makes it durable: loop's fetch ledger reconstructs session facts by parsing those markers out of
rendered tool results, so a new marker here would produce a fact that evaporates at the first compaction.
Arguments therefore ride INSIDE the routes entry (`resolve_handle(handle: string)`) rather than in the
shape block, whose ledger label states the entries are what an endpoint RETURNS — true for a GraphQL
field's type, false for a tool's inputs.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

from . import brave   # the browser UA only; importing webfetch here would be a cycle
from . import content_reduce, prompts

# The MCP revision cria speaks. A server that does not support it answers with an error and cria
# surfaces nothing rather than guessing at a shape it did not receive.
MCP_PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "cria"
CLIENT_VERSION = "1"

PROBE_TIMEOUT_S = 10          # a discovery probe is a side quest; it must never hold up the model. The
                              # MCP path makes at most five requests, so a server that accepts the
                              # connection and then hangs costs a bounded ~50s, not an open-ended stall.
# The probe reads a MACHINE-READ answer, not model context: what the model is shown is bounded
# separately by MAX_ITEMS/MAX_ARGS and disclosed there. This used to cut the read at 2 MB, and a cut
# JSON does not parse — so a real MCP server or a large GraphQL schema (Shopify's introspection is
# several megabytes) came back as `None`, which webfetch renders as an endpoint that offers nothing.
# PARSE FIRST, BOUND SECOND: read far enough that a real schema fits, and when the bound is genuinely
# hit, SAY SO rather than reporting an empty surface (#5b).
MAX_PROBE_BYTES = 32 * 1024 * 1024
MAX_PROBE_LABEL = "32 MB"


class ProbeTooLarge(Exception):
    """The endpoint's own answer ran past MAX_PROBE_BYTES — a bound cria hit, not a fact about the API."""
MAX_ITEMS = 40                # tools / root fields listed; the cap is DISCLOSED, never silent
MAX_ARGS = 12                 # arguments shown per item, likewise disclosed
MAX_FIELDS = 24               # return-type fields shown per GraphQL root field

# A GET that answers like a protocol endpoint rather than a document. 405 is the canonical MCP answer
# to GET; 400 is GraphQL's answer to a query-less request. The body test keeps an unrelated 400 from
# triggering a probe.
_PROTOCOL_STATUSES = (400, 404, 405, 406, 415, 501)


@dataclass
class Discovery:
    """What a probe learned, in the shape webfetch renders."""
    kind: str                                  # "mcp" | "graphql"
    note: str = ""                             # one line: what this endpoint is and how it is called
    routes: list[str] = field(default_factory=list)   # the callable surface, arguments inline
    shapes: list[str] = field(default_factory=list)   # what a call RETURNS, when the server declares it
    unread: str = ""                           # set INSTEAD of routes when a bound stopped the probe

    def __bool__(self) -> bool:
        return bool(self.routes or self.unread)


# --------------------------------------------------------------------------- transport

def _post_json(url: str, payload: dict, headers: dict) -> tuple[int, str, dict]:
    """One POST. Returns ``(status, body_text, response_headers)``; a non-2xx still yields its body
    (an MCP/JSON-RPC error carries the reason cria wants to read)."""
    data = json.dumps(payload).encode("utf-8")
    # The SAME browser User-Agent the GET path sends. Measured against the real api.handle.me: the GET
    # returned 405 with a readable body while the probe's default `Python-urllib/3.x` was refused by
    # Cloudflare with "Error 1010: Access denied" — so discovery failed on precisely the endpoint it
    # was written for, and no offline stub could have shown it.
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": brave.USER_AGENT, **headers})
    try:
        resp = urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S)  # noqa: S310 (scheme guarded by caller)
    except urllib.error.HTTPError as e:
        resp = e
    with resp:
        status = int(getattr(resp, "status", 0) or getattr(resp, "code", 0) or 0)
        raw = resp.read(MAX_PROBE_BYTES + 1)  # +1 so a body AT the cap is distinguishable from one over it
        if len(raw) > MAX_PROBE_BYTES:
            raise ProbeTooLarge(url)
        hdrs = {k.lower(): v for k, v in dict(resp.headers).items()}
    return status, raw.decode("utf-8", "replace"), hdrs


def _rpc_result(body: str) -> Optional[dict]:
    """The JSON-RPC ``result`` from a response body that may be plain JSON or an SSE stream.

    MCP's Streamable HTTP transport lets a server answer either way for the SAME request, so a reader
    that understands only one of them works against half the servers in existence."""
    text = (body or "").strip()
    if not text:
        return None
    if text.startswith("{") or text.startswith("["):
        candidates = [text]
    else:
        # SSE: one event per blank-line-separated block, payload on `data:` lines.
        candidates = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
    for c in reversed(candidates):          # the last data event is the reply to the last request
        try:
            msg = json.loads(c)
        except ValueError:
            continue
        if isinstance(msg, dict) and isinstance(msg.get("result"), dict):
            return msg["result"]
    return None


# --------------------------------------------------------------------------- MCP

def _json_schema_args(schema: Any, mark_optional: bool = True) -> list[str]:
    """``name: type`` for each property of a JSON Schema, required ones first and unmarked, optional
    ones suffixed ``?`` — a caller needs to know which arguments it may omit. Bounded and disclosed.

    ``mark_optional=False`` for a RESPONSE schema: "you may omit this" is a statement about a call's
    inputs, and carrying it onto output fields would tell the model a field it will actually receive is
    somehow optional to supply."""
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    required = schema.get("required")
    required = set(required) if isinstance(required, list) else set()
    ordered = ([k for k in props if k in required] + [k for k in props if k not in required])
    out = []
    for name in ordered[:MAX_ARGS]:
        spec = props.get(name)
        t = spec.get("type") if isinstance(spec, dict) else None
        if isinstance(t, list):
            t = "|".join(str(x) for x in t)
        mark = "" if (name in required or not mark_optional) else "?"
        out.append(f"{name}{mark}: {t}" if t else f"{name}{mark}")
    if len(props) > MAX_ARGS:
        out.append(f"…+{len(props) - MAX_ARGS} more arg(s)")
    return out


def _mcp_discover(url: str) -> Optional[Discovery]:
    """Speak MCP well enough to read the menu: ``initialize`` → ``notifications/initialized`` →
    ``tools/list`` (then resources and prompts, which many servers do not implement — an error there
    is normal and simply yields nothing).

    The session id from ``initialize`` MUST be echoed on later requests or a conforming server rejects
    them; that header is the difference between a tool list and a 400."""
    headers = {"Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
    try:
        status, body, resp_headers = _post_json(url, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION}}}, headers)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    init = _rpc_result(body)
    if not init:
        return None
    session_id = resp_headers.get("mcp-session-id")
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    try:  # the handshake's third leg; a server may ignore it, and its reply is not read
        _post_json(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers)
    except (urllib.error.URLError, OSError, ValueError):
        pass

    def listing(method: str, key: str) -> list:
        try:
            _s, b, _h = _post_json(url, {"jsonrpc": "2.0", "id": 2, "method": method}, headers)
        except (urllib.error.URLError, OSError, ValueError):
            return []
        res = _rpc_result(b) or {}
        items = res.get(key)
        return items if isinstance(items, list) else []

    server = (init.get("serverInfo") or {}) if isinstance(init.get("serverInfo"), dict) else {}
    name = str(server.get("name") or "").strip()
    d = Discovery(kind="mcp")
    d.note = prompts.fill(prompts.load_map("api_discovery")["mcp"], url=url,
                          named=f" ({name})" if name else "",
                          protocol=init.get("protocolVersion") or MCP_PROTOCOL_VERSION)
    tools = listing("tools/list", "tools")
    for t in tools[:MAX_ITEMS]:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        # A SCHEMA CRIA CANNOT READ IS NOT A TOOL THAT TAKES NOTHING. `_json_schema_args` answers []
        # for a schema built from `$ref`, `allOf` or `oneOf` — and `name()` then renders as a
        # positive claim that the tool needs no arguments, under a header telling the coder to use
        # these EXACT names. Say what is true instead: cria could not read the arguments (#5b).
        schema = t.get("inputSchema")
        args = _json_schema_args(schema)
        if args:
            entry = f"mcp tool {t['name']}({', '.join(args)})"
        elif isinstance(schema, dict) and schema and not isinstance(schema.get("properties"), dict):
            entry = f"mcp tool {t['name']}(… arguments not readable from this schema — call it to see)"
        else:
            entry = f"mcp tool {t['name']}()"
        desc = str(t.get("description") or "").strip().replace("\n", " ")
        d.routes.append(f"{entry} — {content_reduce.clip(desc, 120)}" if desc else entry)
        # Only a declared outputSchema goes in the shape block: that block's ledger label states its
        # entries are what an endpoint RETURNS, so putting inputs there would file a false fact.
        fields = _json_schema_args(t.get("outputSchema"), mark_optional=False)
        if fields:
            d.shapes.append(f"{t['name']} → {', '.join(fields)}")
    if len(tools) > MAX_ITEMS:
        d.routes.append(f"…+{len(tools) - MAX_ITEMS} more tool(s) not shown")
    for method, key, label in (("resources/list", "resources", "mcp resource"),
                               ("prompts/list", "prompts", "mcp prompt")):
        for item in listing(method, key)[:MAX_ITEMS]:
            if isinstance(item, dict) and item.get("name"):
                ident = item.get("uri") or item["name"]
                d.routes.append(f"{label} {ident}")
    return d or None


# --------------------------------------------------------------------------- GraphQL

# Bounded on purpose: the full introspection query returns every type, directive and description in the
# schema, which on a real API is megabytes. This asks for the two ROOT types and one level of their
# fields — the callable surface and what it returns, which is the analogue of routes + response shape.
def _type_ref(depth: int = 6) -> str:
    """A GraphQL type-reference selection nested ``depth`` levels deep.

    Wrapper types nest: ``[Continent!]!`` is NON_NULL(LIST(NON_NULL(OBJECT))) — four levels before the
    real name appears. Asking two levels deep and unwrapping what came back printed ``[?!]!`` against a
    live schema: the query, not the unwrapper, was the limit. Seven levels is what GraphQL's own
    canonical IntrospectionQuery uses."""
    inner = "kind name"
    for _ in range(depth):
        inner = "kind name ofType { " + inner + " }"
    return inner


# Bounded on purpose: the full introspection query returns every type, directive and description in the
# schema, which on a real API is megabytes. This asks for the two ROOT types and one level of their
# fields — the callable surface and what it returns, which is the analogue of routes + response shape.
def _introspection(depth: int) -> str:
    ref = _type_ref(depth)
    return ("query criaDiscovery { __schema { "
            f"queryType {{ name fields {{ name description args {{ name type {{ {ref} }} }} "
            f"type {{ {ref} }} }} }} "
            f"mutationType {{ name fields {{ name description args {{ name type {{ {ref} }} }} "
            f"type {{ {ref} }} }} }} "
            f"types {{ name kind fields {{ name type {{ {ref} }} }} }} }} }}")


# Depth is NEGOTIATED, not assumed. Measured against two live schemas: the canonical 7-level type
# reference is what unwraps `[Continent!]!`, and countries.trevorblades.com refuses it outright with
# HTTP 413 "Query depth limit exceeded" — while the shallow form it does answer cannot unwrap a list.
# No single depth serves both, so cria asks for the good one and accepts the server's answer about
# what it will serve. One extra POST, only when the first is refused.
_INTROSPECTION_DEPTHS = (6, 2)


def _gql_type_name(t: Any) -> str:
    """A GraphQL type reference flattened to a readable name: NON_NULL/LIST wrappers carry the real
    type underneath in ``ofType``, so the outer node's ``name`` is null and a naive read prints None.

    ``…`` means the name was NOT READ — either absent or past the nesting the server was willing to
    send. It is deliberately not a plausible type name: a `?` in a type position reads like a type."""
    if not isinstance(t, dict):
        return "…"
    kind = t.get("kind")
    if kind == "NON_NULL":
        return _gql_type_name(t.get("ofType")) + "!"
    if kind == "LIST":
        return "[" + _gql_type_name(t.get("ofType")) + "]"
    # The name is null on a wrapper node, so running out of `ofType` means the SERVER did not send us
    # enough nesting (a depth limiter). Say the shape is unread rather than printing a `?` a model can
    # mistake for a type — the wrapper brackets around it are still true.
    return str(t.get("name") or "…")


def _graphql_discover(url: str) -> Optional[Discovery]:
    """One introspection POST — the standard, read-only way to learn a GraphQL schema. Root fields
    become the callable surface (arguments inline); each field's return type contributes its own fields
    to the shape block, which is exactly what "the fields this call returns" means here."""
    schema = {}
    for depth in _INTROSPECTION_DEPTHS:
        try:
            _status, body, _h = _post_json(url, {"query": _introspection(depth),
                                                 "operationName": "criaDiscovery"},
                                           {"Accept": "application/json"})
            payload = json.loads(body)
        except (urllib.error.URLError, OSError, ValueError):
            return None
        got = (((payload or {}).get("data") or {}).get("__schema") or {}) if isinstance(payload, dict) else {}
        if isinstance(got, dict) and got.get("queryType"):
            schema = got
            break
    if not schema:
        return None
    by_name = {}
    for t in (schema.get("types") or []):
        if isinstance(t, dict) and t.get("name"):
            by_name[t["name"]] = t
    d = Discovery(kind="graphql")
    d.note = prompts.fill(prompts.load_map("api_discovery")["graphql"], url=url)
    for root_key, prefix in (("queryType", "Query"), ("mutationType", "Mutation")):
        root = schema.get(root_key)
        if not isinstance(root, dict):
            continue
        fields = root.get("fields")
        if not isinstance(fields, list):
            continue
        for f in fields[:MAX_ITEMS]:
            if not isinstance(f, dict) or not f.get("name"):
                continue
            args = [f"{a.get('name')}: {_gql_type_name(a.get('type'))}"
                    for a in (f.get("args") or [])[:MAX_ARGS] if isinstance(a, dict) and a.get("name")]
            if len(f.get("args") or []) > MAX_ARGS:
                args.append(f"…+{len(f['args']) - MAX_ARGS} more arg(s)")
            ret = _gql_type_name(f.get("type"))
            entry = f"{prefix}.{f['name']}({', '.join(args)}) -> {ret}"
            desc = str(f.get("description") or "").strip().replace("\n", " ")
            d.routes.append(f"{entry} — {content_reduce.clip(desc, 120)}" if desc else entry)
            named = ret.strip("[]!")
            sub = by_name.get(named)
            subfields = (sub or {}).get("fields")
            if isinstance(subfields, list) and subfields:
                names = [f"{s.get('name')}({_gql_type_name(s.get('type'))})"
                         for s in subfields[:MAX_FIELDS] if isinstance(s, dict) and s.get("name")]
                if len(subfields) > MAX_FIELDS:
                    names.append(f"…+{len(subfields) - MAX_FIELDS} more field(s)")
                if names:
                    d.shapes.append(f"{prefix}.{f['name']} → {', '.join(names)}")
        if len(fields) > MAX_ITEMS:
            d.routes.append(f"…+{len(fields) - MAX_ITEMS} more {prefix} field(s) not shown")
    return d or None


# --------------------------------------------------------------------------- dispatch

def probe_kind(url: str, status: Optional[int], body: str, content_type: Optional[str]) -> Optional[str]:
    """Which protocol — if any — this URL looks like, from the URL itself and how a GET answered.

    Two independent signals, because either alone is wrong: the path convention (``/mcp``,
    ``/graphql``) catches a server that answers a GET with a playground page, and the status+body test
    catches an endpoint at an unconventional path. A plain document that GETs fine is never probed."""
    try:
        path = urllib.parse.urlsplit(url or "").path
    except ValueError:
        return None
    last = (path.rstrip("/").rsplit("/", 1)[-1] or "").lower()
    text = (body or "")[:4000].lower()
    ct = (content_type or "").lower()
    if last == "mcp" or last == "mcp.json":
        return "mcp"
    if last in ("graphql", "graphiql", "gql"):
        return "graphql"
    if status in _PROTOCOL_STATUSES or "event-stream" in ct:
        if "jsonrpc" in text or "mcp-session" in text or "mcp protocol" in text:
            return "mcp"
        if "graphql" in text or "must provide query string" in text:
            return "graphql"
    return None


def discover(url: str, status: Optional[int], body: str,
             content_type: Optional[str]) -> Optional[Discovery]:
    """Probe ``url`` when it answers like a protocol endpoint. ``None`` whenever there is nothing to
    say — an unrecognised URL, an unreachable server, a schema cria could not read. Never raises: a
    failed side quest must leave the ordinary GET result exactly as it was."""
    kind = probe_kind(url, status, body, content_type)
    if not kind:
        return None
    try:
        return _mcp_discover(url) if kind == "mcp" else _graphql_discover(url)
    except ProbeTooLarge:
        return _unread(url, kind)
    except Exception:  # noqa: BLE001 — discovery is best-effort by construction
        return None


def _unread(url: str, kind: str) -> Discovery:
    """The endpoint answered and the answer was too big to read here. That is a bound cria hit, and
    saying nothing about it hands the model a dead 405 page instead — so the endpoint is named, the
    bound is named, and the model is told how to ask it directly."""
    m = prompts.load_map("api_discovery")
    d = Discovery(kind=kind)
    d.unread = prompts.fill(m["unread"], limit=MAX_PROBE_LABEL,
                            how=prompts.fill(m[f"unread_{kind}_how"], url=url))
    return d
