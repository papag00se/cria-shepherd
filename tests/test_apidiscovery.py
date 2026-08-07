"""Discovery for APIs with no fetchable description: MCP and GraphQL (cria.apidiscovery), plus the
document-side dialects webfetch reads (Swagger 2 / JSON Schema $defs, base paths, RFC 9727 catalogues).

Everything here is offline: the probes are driven through a stubbed _post_json, so no test opens a
socket.
"""
import json
import unittest

from cria import apidiscovery as ad
from cria import webfetch as wf


class ProbeKindTests(unittest.TestCase):
    """WHEN to probe. A plain document that GETs fine must never be POSTed to."""

    def test_path_convention(self):
        self.assertEqual(ad.probe_kind("https://api.handle.me/mcp", 405, "", None), "mcp")
        self.assertEqual(ad.probe_kind("https://x.com/graphql", 400, "", None), "graphql")
        self.assertEqual(ad.probe_kind("https://x.com/gql/", 400, "", None), "graphql")

    def test_status_and_body_when_the_path_is_unconventional(self):
        self.assertEqual(ad.probe_kind("https://x.com/rpc", 405,
                                       '{"jsonrpc":"2.0","error":{"code":-32000}}', None), "mcp")
        self.assertEqual(ad.probe_kind("https://x.com/api", 400,
                                       "Must provide query string.", None), "graphql")

    def test_an_ordinary_document_is_never_probed(self):
        self.assertIsNone(ad.probe_kind("https://api.handle.me/openapi.json", 200,
                                        '{"openapi":"3.0"}', "application/json"))
        self.assertIsNone(ad.probe_kind("https://example.com/", 200, "<html>hi</html>", "text/html"))
        # a 404 that is just a 404 — no protocol signature in the body
        self.assertIsNone(ad.probe_kind("https://x.com/nope", 404, "Not Found", "text/plain"))


class RpcResultTests(unittest.TestCase):
    """MCP's Streamable HTTP transport may answer the SAME request as JSON or as SSE."""

    def test_plain_json(self):
        self.assertEqual(ad._rpc_result('{"jsonrpc":"2.0","id":1,"result":{"a":1}}'), {"a": 1})

    def test_sse_stream(self):
        body = ('event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n')
        self.assertEqual(ad._rpc_result(body), {"tools": []})

    def test_an_error_or_junk_yields_nothing(self):
        self.assertIsNone(ad._rpc_result('{"jsonrpc":"2.0","id":1,"error":{"code":-1}}'))
        self.assertIsNone(ad._rpc_result("not json at all"))
        self.assertIsNone(ad._rpc_result(""))


def _mcp_server(tools, *, resources=(), prompts=(), session="s-1"):
    """A stub MCP server: returns (posts, fn) where fn replaces ad._post_json."""
    posts = []

    def fake(url, payload, headers):
        posts.append((payload.get("method"), headers.copy()))
        method = payload.get("method")
        if method == "initialize":
            return 200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": {
                "protocolVersion": ad.MCP_PROTOCOL_VERSION,
                "serverInfo": {"name": "handle-mcp", "version": "1"}}}), {"mcp-session-id": session}
        if method == "tools/list":
            return 200, json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": list(tools)}}), {}
        if method == "resources/list":
            return 200, json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"resources": list(resources)}}), {}
        if method == "prompts/list":
            return 200, json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"prompts": list(prompts)}}), {}
        return 200, "{}", {}
    return posts, fake


class McpDiscoveryTests(unittest.TestCase):
    TOOLS = [{"name": "resolve_handle", "description": "Resolve an Ada Handle to its address.",
              "inputSchema": {"type": "object", "required": ["handle"],
                              "properties": {"handle": {"type": "string"},
                                             "verbose": {"type": "boolean"}}}},
             {"name": "get_holder",
              "inputSchema": {"type": "object", "required": ["address"],
                              "properties": {"address": {"type": "string"}}},
              "outputSchema": {"type": "object", "properties": {"total_handles": {"type": "integer"}}}}]

    def _run(self, **kw):
        posts, fake = _mcp_server(self.TOOLS, **kw)
        orig = ad._post_json
        ad._post_json = fake
        try:
            return posts, ad._mcp_discover("https://api.handle.me/mcp")
        finally:
            ad._post_json = orig

    def test_full_handshake_then_the_tool_menu(self):
        posts, d = self._run()
        self.assertEqual([m for m, _h in posts][:3],
                         ["initialize", "notifications/initialized", "tools/list"])
        self.assertEqual(d.kind, "mcp")
        self.assertIn("handle-mcp", d.note)
        self.assertIn("tools/call", d.note)             # HOW to call one, not just that it exists

    def test_arguments_ride_in_the_routes_entry_with_required_marked(self):
        _posts, d = self._run()
        self.assertIn("mcp tool resolve_handle(handle: string, verbose?: boolean)"
                      " — Resolve an Ada Handle to its address.", d.routes)
        # ...and NOT in the shape block, whose ledger label states its entries are what a call RETURNS.
        self.assertFalse(any('"handle?": "string"' in s for s in d.shapes))

    def test_only_a_declared_output_schema_becomes_a_shape(self):
        _posts, d = self._run()
        self.assertEqual(d.shapes, ["get_holder → total_handles: integer"])

    def test_the_session_id_is_echoed_on_every_later_request(self):
        posts, _d = self._run(session="abc123")
        later = [h for m, h in posts if m != "initialize"]
        self.assertTrue(later)
        for h in later:
            self.assertEqual(h.get("Mcp-Session-Id"), "abc123")

    def test_resources_and_prompts_are_listed_when_the_server_has_them(self):
        _posts, d = self._run(resources=[{"name": "spec", "uri": "file:///spec.json"}],
                              prompts=[{"name": "explain"}])
        self.assertIn("mcp resource file:///spec.json", d.routes)
        self.assertIn("mcp prompt explain", d.routes)

    def test_a_server_that_never_completes_initialize_yields_nothing(self):
        orig = ad._post_json
        ad._post_json = lambda url, payload, headers: (400, '{"jsonrpc":"2.0","error":{"code":-1}}', {})
        try:
            self.assertIsNone(ad._mcp_discover("https://x/mcp"))
        finally:
            ad._post_json = orig

    def test_a_transport_failure_is_not_raised_at_the_caller(self):
        orig = ad._post_json

        def boom(*a, **k):
            raise OSError("connection refused")
        ad._post_json = boom
        try:
            self.assertIsNone(ad.discover("https://x/mcp", 405, "", None))
        finally:
            ad._post_json = orig


class GraphQlDiscoveryTests(unittest.TestCase):
    SCHEMA = {"data": {"__schema": {
        "queryType": {"name": "Query", "fields": [
            {"name": "handle", "description": "Look up one handle.",
             "args": [{"name": "name", "type": {"kind": "NON_NULL", "name": None,
                                                "ofType": {"kind": "SCALAR", "name": "String"}}}],
             "type": {"kind": "OBJECT", "name": "Handle", "ofType": None}}]},
        "mutationType": {"name": "Mutation", "fields": [
            {"name": "mint", "args": [], "type": {"kind": "LIST", "name": None,
                                                  "ofType": {"kind": "OBJECT", "name": "Handle"}}}]},
        "types": [{"name": "Handle", "kind": "OBJECT", "fields": [
            {"name": "holder", "type": {"kind": "SCALAR", "name": "String"}},
            {"name": "length", "type": {"kind": "SCALAR", "name": "Int"}}]}]}}}

    def _run(self, payload=None):
        orig = ad._post_json
        ad._post_json = lambda url, p, h: (200, json.dumps(payload if payload is not None else self.SCHEMA), {})
        try:
            return ad._graphql_discover("https://x.com/graphql")
        finally:
            ad._post_json = orig

    def test_root_fields_become_the_callable_surface(self):
        d = self._run()
        self.assertIn("Query.handle(name: String!) -> Handle — Look up one handle.", d.routes)
        self.assertIn("Mutation.mint() -> [Handle]", d.routes)

    def test_the_return_type_s_fields_become_the_shape(self):
        d = self._run()
        self.assertIn("Query.handle → holder(String), length(Int)", d.shapes)

    def test_the_note_says_there_are_no_rest_paths(self):
        self.assertIn("no REST paths", self._run().note)

    def test_a_non_graphql_reply_yields_nothing(self):
        self.assertIsNone(self._run({"errors": [{"message": "introspection disabled"}]}))
        self.assertIsNone(self._run({"data": {}}))

    def test_type_name_unwrapping(self):
        self.assertEqual(ad._gql_type_name({"kind": "NON_NULL", "ofType": {"kind": "SCALAR", "name": "ID"}}), "ID!")
        self.assertEqual(ad._gql_type_name(
            {"kind": "NON_NULL", "ofType": {"kind": "LIST", "ofType": {"kind": "OBJECT", "name": "H"}}}), "[H]!")
        # "…" not "?": a server with a depth limiter stops sending nesting before the name, and a
        # `?` in a type position reads like a type. Measured on countries.trevorblades.com, which
        # refuses the canonical 7-level introspection with HTTP 413.
        self.assertEqual(ad._gql_type_name(None), "…")
        self.assertEqual(ad._gql_type_name(
            {"kind": "NON_NULL", "ofType": {"kind": "LIST", "ofType": {"kind": "NON_NULL"}}}), "[…!]!")


class DiscoveryRendersThroughTheExistingMarkersTests(unittest.TestCase):
    """The whole point of reusing webfetch's markers: loop's durable ledger reconstructs session facts
    by PARSING them out of rendered tool results. A bespoke marker would render fine and then vanish at
    the first compaction — a fact that looks delivered and isn't."""

    def _rendered(self):
        d = ad.Discovery(kind="mcp", note="This is an MCP server …",
                         routes=["mcp tool resolve_handle(handle: string)"],
                         shapes=["get_holder → total_handles: integer"])
        return wf._render_discovery("https://api.handle.me/mcp", 200, "application/json", d)

    def test_uses_the_routes_and_shape_markers(self):
        out = self._rendered()
        self.assertIn(wf.ROUTES_MARKER, out)
        self.assertIn(wf.SHAPE_MARKER, out)
        self.assertIn("HTTP 200 OK · https://api.handle.me/mcp", out)   # the ledger's url+status shape

    def test_the_durable_fetch_ledger_picks_it_up(self):
        from cria.loop import _extract_fetches, _fetch_facts
        entry = _extract_fetches([{"role": "tool", "content": self._rendered()}])
        status, routes, shapes, _cat = _fetch_facts(entry["https://api.handle.me/mcp"])
        self.assertEqual(status, "HTTP 200")
        self.assertIn("resolve_handle", routes)
        self.assertIn("total_handles", shapes)


class SwaggerAndBasePathTests(unittest.TestCase):
    """Dialects webfetch reads itself. Only components/schemas was consulted, so a SWAGGER 2 spec
    surfaced endpoints with NO response fields at all — the g15-g18 "guesses the response shape"
    failure, total instead of partial."""

    SWAGGER2 = {"swagger": "2.0", "basePath": "/v1", "paths": {
        "/handles/{handle}": {"get": {
            "parameters": [{"name": "handle", "in": "path", "description": "The Handle name"}],
            "responses": {"200": {"schema": {"$ref": "#/definitions/Handle"}}}}},
        "/holders/{address}": {"get": {"responses": {"200": {"schema": {"$ref": "#/definitions/Holder"}}}}}},
        "definitions": {
            "Handle": {"type": "object", "properties": {
                "holder": {"type": "string"},
                "resolved_addresses": {"type": "object", "properties": {"ada": {"type": "string"}}}}},
            "Holder": {"type": "object", "properties": {"total_handles": {"type": "integer"}}}}}

    def test_swagger2_definitions_are_dereferenced(self):
        shapes = wf._endpoint_response_fields(self.SWAGGER2)
        self.assertTrue(any('holder?: string;' in s and 'ada?: string;' in s for s in shapes),
                        shapes)
        self.assertTrue(any('total_handles?: number;' in s for s in shapes), shapes)

    def test_json_schema_defs_are_dereferenced(self):
        spec = {"paths": {"/a": {"get": {"responses": {"200": {"schema": {"$ref": "#/$defs/A"}}}}},
                          "/b": {"get": {"responses": {"200": {"schema": {"$ref": "#/$defs/A"}}}}}},
                "$defs": {"A": {"type": "object", "properties": {"x": {"type": "string"}}}}}
        self.assertTrue(any('x?: string;' in s for s in wf._endpoint_response_fields(spec)))

    def test_the_declared_base_path_prefixes_routes_AND_shapes(self):
        # Listing a spec's bare `paths` keys said /handles/{handle} where the real route is
        # /v1/handles/{handle} — cria stating a false fact about how to call the API.
        self.assertEqual(wf._endpoint_routes(self.SWAGGER2),
                         ["/v1/handles/{handle}", "/v1/holders/{address}"])
        self.assertTrue(all(s.split()[1].startswith("/v1/") for s in wf._endpoint_response_fields(self.SWAGGER2)))

    def test_an_openapi3_server_url_supplies_the_base_too(self):
        self.assertEqual(wf._base_path({"servers": [{"url": "https://api.x.com/v2"}]}), "/v2")
        self.assertEqual(wf._base_path({"servers": [{"url": "/v3"}]}), "/v3")

    def test_no_declared_base_leaves_routes_exactly_as_they_were(self):
        for spec in ({}, {"servers": [{"url": "https://api.x.com"}]}, {"servers": [{"url": "https://api.x.com/"}]},
                     {"basePath": "/"}):
            self.assertEqual(wf._base_path(spec), "")

    def test_a_response_that_is_itself_a_ref_resolves(self):
        spec = {"paths": {"/a": {"get": {"responses": {"200": {"$ref": "#/responses/Ok"}}}},
                          "/b": {"get": {"responses": {"200": {"$ref": "#/responses/Ok"}}}}},
                "responses": {"Ok": {"schema": {"$ref": "#/definitions/A"}}},
                "definitions": {"A": {"type": "object", "properties": {"y": {"type": "integer"}}}}}
        self.assertTrue(any('y?: number;' in s for s in wf._endpoint_response_fields(spec)))


class ApiCatalogTests(unittest.TestCase):
    """RFC 9727 .well-known/api-catalog, carried as an RFC 9264 linkset. Its entire content is hrefs;
    rendered as a structured doc it produced `top-level keys: linkset` — one word."""

    CATALOG = {"linkset": [
        {"anchor": "https://api.example.com/one",
         "service-desc": [{"href": "https://api.example.com/one/openapi.json",
                           "type": "application/openapi+json"}],
         "service-doc": [{"href": "https://developer.example.com/one"}]},
        {"anchor": "https://api.example.com/two",
         "service-desc": [{"href": "https://api.example.com/two/openapi.json"}]}]}

    def test_links_are_surfaced_per_api(self):
        links = wf._catalog_links(self.CATALOG)
        self.assertEqual(len(links), 2)
        self.assertIn("https://api.example.com/one → service-desc: "
                      "https://api.example.com/one/openapi.json; "
                      "service-doc: https://developer.example.com/one", links)

    def test_a_non_catalog_doc_yields_nothing(self):
        for doc in ({"openapi": "3.0", "paths": {}}, {"linkset": "not a list"}, [], None, "text"):
            self.assertEqual(wf._catalog_links(doc), [])

    def test_the_cap_is_disclosed(self):
        big = {"linkset": [{"anchor": f"https://a/{i}", "service-desc": [{"href": f"https://a/{i}/s"}]}
                           for i in range(30)]}
        links = wf._catalog_links(big, max_entries=5)
        self.assertTrue(links[-1].startswith("…+25 more catalogued API(s)"), links[-1])

    def test_rendered_even_though_a_catalog_fits_one_page(self):
        # The spec blocks render only for a doc too big to read; a catalogue is always small, so
        # gating it the same way would have surfaced it never.
        body = json.dumps(self.CATALOG)
        out = wf.render_page("https://x/.well-known/api-catalog", 200, "application/linkset+json",
                             body, self.CATALOG, 0, 100000)
        self.assertIn(wf.CATALOG_MARKER, out)
        self.assertIn("https://api.example.com/one/openapi.json", out)

    def test_the_durable_fetch_ledger_keeps_the_catalog(self):
        from cria.loop import _extract_fetches, _fetch_facts, _format_fetches
        rendered = wf.render_page("https://x/.well-known/api-catalog", 200, "application/linkset+json",
                                  json.dumps(self.CATALOG), self.CATALOG, 0, 100000)
        entry = _extract_fetches([{"role": "tool", "content": rendered}])
        _s, _r, _sh, catalog = _fetch_facts(entry["https://x/.well-known/api-catalog"])
        self.assertIn("one/openapi.json", catalog)
        # ...and it is no longer filed as "answered, but no structure could be read from it"
        out = _format_fetches(entry)
        self.assertNotIn("no endpoints or field names could be read", out)
        self.assertIn("one/openapi.json", out)


if __name__ == "__main__":
    unittest.main()
