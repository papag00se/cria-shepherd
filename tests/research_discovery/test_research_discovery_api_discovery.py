"""APIs with no fetchable description (MCP, GraphQL) and the spec dialects webfetch reads: surface is read from the server, never invented."""
import io
import json
from unittest import mock

import pytest

from cria import apidiscovery as ad, webfetch as wf

TOOLS = [{"name": "resolve_handle", "description": "Resolve an Ada Handle to its address.",
          "inputSchema": {"type": "object", "required": ["handle"], "properties": {"handle": {"type": "string"}, "verbose": {"type": "boolean"}}}},
         {"name": "get_holder", "inputSchema": {"type": "object", "required": ["address"], "properties": {"address": {"type": "string"}}},
          "outputSchema": {"type": "object", "properties": {"total_handles": {"type": "integer"}}}}]
SCHEMA = {"data": {"__schema": {
    "queryType": {"name": "Query", "fields": [{"name": "handle", "description": "Look up one handle.", "args": [{"name": "name", "type": {
        "kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "String"}}}], "type": {"kind": "OBJECT", "name": "Handle", "ofType": None}}]},
    "mutationType": {"name": "Mutation", "fields": [{"name": "mint", "args": [], "type": {"kind": "LIST", "name": None, "ofType": {"kind": "OBJECT", "name": "Handle"}}}]},
    "types": [{"name": "Handle", "kind": "OBJECT", "fields": [{"name": "holder", "type": {"kind": "SCALAR", "name": "String"}},
                                                             {"name": "length", "type": {"kind": "SCALAR", "name": "Int"}}]}]}}}
SWAGGER2 = {"swagger": "2.0", "basePath": "/v1", "paths": {
    "/handles/{handle}": {"get": {"responses": {"200": {"schema": {"$ref": "#/definitions/Handle"}}}}},
    "/holders/{address}": {"get": {"responses": {"200": {"schema": {"$ref": "#/definitions/Holder"}}}}}},
    "definitions": {"Handle": {"type": "object", "properties": {"holder": {"type": "string"}, "resolved": {"type": "object", "properties": {"ada": {"type": "string"}}}}},
                    "Holder": {"type": "object", "properties": {"total_handles": {"type": "integer"}}}}}

@pytest.mark.parametrize("url,status,body,ct,kind", [
    ("https://api.handle.me/mcp", 405, "", None, "mcp"), ("https://x.com/graphql", 400, "", None, "graphql"),
    ("https://x.com/rpc", 405, '{"jsonrpc":"2.0","error":{"code":-32000}}', None, "mcp"),
    ("https://x.com/api", 400, "Must provide query string.", None, "graphql"),
    # a document that GETs fine is never POSTed to
    ("https://x.com/docs", 200, "<p>our graphql api</p>", "text/html", None), ("https://api.handle.me/openapi.json", 200, '{"openapi":"3.0"}', "application/json", None), ("https://x.com/nope", 404, "Not Found", "text/plain", None)])
def test_a_server_is_probed_only_when_it_says_it_speaks_the_protocol(url, status, body, ct, kind):
    assert ad.probe_kind(url, status, body, ct) == kind

def test_mcp_tools_are_listed_with_required_arguments_and_only_declared_outputs(monkeypatch):
    """Full handshake, the session id echoed on every later request, SSE or JSON; a server that never initializes yields nothing."""
    posts = []
    def fake(url, payload, headers):
        m = payload.get("method")
        posts.append((m, dict(headers)))
        result = {"initialize": {"protocolVersion": ad.MCP_PROTOCOL_VERSION, "serverInfo": {"name": "handle-mcp"}}, "tools/list": {"tools": TOOLS},
                  "resources/list": {"resources": [{"name": "spec", "uri": "file:///spec.json"}]}, "prompts/list": {"prompts": [{"name": "explain"}]}}.get(m)
        return 200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}) if result else "{}", {"mcp-session-id": "abc123"} if m == "initialize" else {}
    monkeypatch.setattr(ad, "_post_json", fake)
    d = ad._mcp_discover("https://api.handle.me/mcp")
    assert [m for m, _ in posts][:3] == ["initialize", "notifications/initialized", "tools/list"]
    assert all(h.get("Mcp-Session-Id") == "abc123" for m, h in posts if m != "initialize")
    assert "mcp tool resolve_handle(handle: string, verbose?: boolean) — Resolve an Ada Handle to its address." in d.routes
    assert "mcp resource file:///spec.json" in d.routes and "mcp prompt explain" in d.routes and "tools/call" in d.note
    assert d.shapes == ["get_holder → total_handles: integer"]   # arguments are not return shapes
    assert ad._rpc_result('event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n') == {"tools": []}
    assert ad._rpc_result('{"jsonrpc":"2.0","id":1,"error":{"code":-1}}') is None and ad._rpc_result("junk") is None
    monkeypatch.setattr(ad, "_post_json", lambda u, p, h: (400, '{"jsonrpc":"2.0","error":{"code":-1}}', {}))
    assert ad._mcp_discover("https://x/mcp") is None

def test_graphql_root_fields_and_return_shapes_and_a_non_graphql_reply(monkeypatch):
    reply = lambda payload: monkeypatch.setattr(ad, "_post_json", lambda u, p, h: (200, json.dumps(payload), {}))
    reply(SCHEMA)
    d = ad._graphql_discover("https://x.com/graphql")
    assert "Query.handle(name: String!) -> Handle — Look up one handle." in d.routes and "Mutation.mint() -> [Handle]" in d.routes
    assert "Query.handle → holder(String), length(Int)" in d.shapes and "no REST paths" in d.note
    for payload in ({"errors": [{"message": "introspection disabled"}]}, {"data": {}}):
        reply(payload)
        assert ad._graphql_discover("https://x.com/graphql") is None
    # a depth-limited server stops sending nesting before the name: '…' not '?' (which reads like a type)
    assert ad._gql_type_name({"kind": "NON_NULL", "ofType": {"kind": "LIST", "ofType": {"kind": "NON_NULL"}}}) == "[…!]!"

def test_a_reply_too_big_to_read_is_disclosed_never_reported_as_an_empty_api():
    """The read was cut at 2 MB and cut JSON does not parse, so a real MCP server reported an empty surface."""
    class Resp(io.BytesIO):
        status, headers = 200, {"Content-Type": "application/json"}
        __enter__ = lambda self: self
        __exit__ = lambda self, *a: False
    with mock.patch("urllib.request.urlopen", return_value=Resp(b"x" * (ad.MAX_PROBE_BYTES + 5))), pytest.raises(ad.ProbeTooLarge):
        ad._post_json("https://x/mcp", {"a": 1}, {})
    d = ad._unread("https://api.example.com/mcp", "mcp")
    assert d and d.routes == [] and "tools/list" in d.unread and "cria" not in d.unread.lower()
    assert "routes(" not in wf._render_discovery("https://x/graphql", 400, "application/json", ad._unread("https://x/graphql", "graphql"))

def test_spec_dialects_are_dereferenced_and_routes_carry_the_declared_base():
    """Swagger 2 surfaced endpoints with NO response fields; bare `paths` keys said /handles/{h} where the route is /v1/handles/{h}."""
    shapes = wf._endpoint_response_fields(SWAGGER2)
    assert wf._endpoint_routes(SWAGGER2) == ["/v1/handles/{handle}", "/v1/holders/{address}"]
    assert any("holder?: string;" in s and "ada?: string;" in s for s in shapes) and any("total_handles?: number;" in s for s in shapes)
    assert all(s.split()[1].startswith("/v1/") for s in shapes)
    viaref = {"paths": {"/a": {"get": {"responses": {"200": {"$ref": "#/responses/Ok"}}}}}, "responses": {"Ok": {"schema": {"$ref": "#/$defs/A"}}},
              "$defs": {"A": {"type": "object", "properties": {"y": {"type": "integer"}}}}}
    assert any("y?: number;" in s for s in wf._endpoint_response_fields(viaref))
    assert wf._base_path({"servers": [{"url": "https://api.x.com/v2"}]}) == "/v2"
    assert all(wf._base_path(s) == "" for s in ({}, {"servers": [{"url": "https://api.x.com/"}]}, {"basePath": "/"}))

