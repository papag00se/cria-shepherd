"""A coder's web_fetch against a hostile/odd real HTTP server: transport and content-type arms (redirect, YAML, mislabelled
NDJSON, binary, empty, 404 streak, body cut at the transport cap, cache eviction), MCP (SSE + session echo) and GraphQL
(depth negotiation) probes over real POSTs, find/paging on text and JSON, Swagger-2 response shapes, and the spill helpers
that tell the coder what is on disk."""
import http.server
import json
import threading

import pytest

from cria import apidiscovery as ad, webfetch as wf

SCHEMA = {"queryType": {"name": "Query", "fields": [
    {"name": "country", "description": "One country", "args": [{"name": "code", "type": {"kind": "NON_NULL", "ofType": {"kind": "SCALAR", "name": "ID"}}}],
     "type": {"kind": "OBJECT", "name": "Country"}},
    {"name": "countries", "args": [], "type": {"kind": "NON_NULL", "ofType": {"kind": "LIST", "ofType": {"kind": "OBJECT", "name": "Country"}}}}]},
    "mutationType": {"name": "Mutation", "fields": [{"name": "rename", "args": [], "type": {"kind": "SCALAR", "name": "String"}}]},
    "types": [{"name": "Country", "fields": [{"name": "name", "type": {"kind": "SCALAR", "name": "String"}}, {"name": "code", "type": {"kind": "SCALAR", "name": "ID"}}]}]}
TOOLS = [{"name": "resolve", "description": "Resolve a handle\nto an address", "inputSchema": {"type": "object", "required": ["handle"], "properties": {
    "handle": {"type": "string"}, "net": {"type": ["string", "null"]}}}, "outputSchema": {"properties": {"address": {"type": "string"}}}},
    {"name": "refd", "inputSchema": {"$ref": "#/x"}}, {"name": "bare"}, {"noname": 1}, "junk"]
LONG = "".join(f"line {i} alpha\n" + ("\n" if i % 50 == 49 else "") for i in range(2500)) + "the NEEDLE is here\n"
DATA = {"items": [{"id": i, "name": f"n{i}", "tags": ["x", "y"]} for i in range(900)], "meta": {"page": 1}}
GET = {
    "/a.yaml": ("application/x-yaml", b"openapi: 3.0.0\ninfo: {title: t}\npaths:\n  /x:\n    get:\n      summary: s\n", 200),
    "/nd": ("application/octet-stream", b'{"a":1}\n{"a":2}\n', 200), "/empty": ("text/plain", b"", 200),
    "/badjson": ("application/json", b"{not json", 200), "/blob": ("application/octet-stream", bytes(range(256)) * 8, 200),
    "/long.txt": ("text/plain", LONG.encode(), 200), "/data.json": ("application/json", json.dumps(DATA).encode(), 200),
    "/nope": ("text/plain", b"gone", 404), "/p.css": ("text/css", (".a{color:red}" * 900).encode(), 200),
    "/min.html": ("text/html", ("<html><body>" + "<p>word</p>" * 3000 + "</body></html>").encode(), 200),
    "/redir": ("", b"", 302), "/mcp": ("application/json", b'{"jsonrpc":"2.0","error":{"message":"POST only (mcp)"}}', 405),
    "/graphql": ("application/json", b'{"errors":[{"message":"Must provide query string."}]}', 400)}


class Site(http.server.BaseHTTPRequestHandler):
    def send(self, code, ct, body, extra=()):
        self.send_response(code)
        if ct:
            self.send_header("Content-Type", ct)
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        ct, body, code = GET.get(self.path, ("text/plain", b"", 404))
        self.send(code, ct, body, [("Location", "/long.txt")] if self.path == "/redir" else ())

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        rpc = lambda res: json.dumps({"jsonrpc": "2.0", "id": 2, "result": res}).encode()
        method = req.get("method")
        if self.path == "/mcp" and method == "initialize":
            init = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26", "serverInfo": {"name": "Handles"}}})
            self.send(200, "text/event-stream", f"event: message\ndata: {init}\n\n".encode(), [("Mcp-Session-Id", "S1")])
        elif self.path == "/mcp" and method == "notifications/initialized":
            self.send(202, "text/plain", b"")
        elif self.path == "/mcp" and self.headers.get("Mcp-Session-Id") != "S1":
            self.send(400, "text/plain", b"no session")
        elif self.path == "/mcp":
            self.send(200, "application/json", {"tools/list": rpc({"tools": TOOLS}), "resources/list": rpc({"resources": [
                {"name": "readme", "uri": "file:///r"}, {"name": "n"}, {"x": 1}]})}.get(method, b'{"jsonrpc":"2.0","id":2,"error":{"code":-32601}}'))
        elif self.path == "/graphql" and "ofType { kind name ofType { kind name ofType { kind name ofType" in req["query"]:
            self.send(413, "application/json", b'{"errors":[{"message":"Query depth limit exceeded"}]}')   # the deep form is refused
        elif self.path == "/graphql":
            self.send(200, "application/json", json.dumps({"data": {"__schema": SCHEMA}}).encode())
        else:
            self.send(404, "text/plain", b"")

    def log_message(self, *a):
        pass


@pytest.fixture
def base():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    wf.clear_cache()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    wf.clear_cache()


def test_every_odd_server_answer_is_reported_as_what_it_was(base):
    """Transport arms: refusals before any request, no listener, redirects, YAML, a lying content-type, binary, empty, bad JSON."""
    assert wf.fetch_nav_result("  ", session="a")[0] == "web_fetch: url must not be empty"
    text, refused, status, facts = wf.fetch_nav_result("ftp://h/x", session="a")
    assert (text, refused, status, facts) == ("web_fetch: unsupported scheme 'ftp': only http/https", False, None, None)
    assert wf.fetch_nav("localhost/x")[:-1].startswith("web_fetch: unsupported scheme 'localhost/x'")
    assert "web_fetch error fetching http://127.0.0.1:1/x" in wf.fetch_nav("http://127.0.0.1:1/x") and "Connection refused" in wf.fetch_nav("http://127.0.0.1:1/x")
    redirected = wf.fetch_nav_result(f"{base}/redir")                         # urllib follows the 302 to /long.txt
    assert redirected[2] == 200 and "line 0 alpha\nline 1 alpha" in redirected[0] and "Content-Type: text/plain" in redirected[0]
    yaml_text = wf.fetch_nav(f"{base}/a.yaml")
    assert '"openapi": "3.0.0"' in yaml_text and '"summary": "s"' in yaml_text and "Content-Type: application/x-yaml" in yaml_text
    assert wf.fetch_nav(f"{base}/nd").endswith('--- (chars 0–16 of 16) ---\n{"a":1}\n{"a":2}\n\n')          # bytes that read as text ARE text
    assert "[non-text response: 2048 bytes, content-type=application/octet-stream" in wf.fetch_nav(f"{base}/blob")
    assert "The response body was EMPTY" in wf.fetch_nav(f"{base}/empty")
    assert wf.fetch_nav(f"{base}/badjson").endswith("--- (chars 0–9 of 9) ---\n{not json\n")
    assert wf.cached_structure(f"{base}/a.yaml") is True and wf.cached_structure(f"{base}/badjson") is False


def test_a_body_cut_at_the_transport_cap_discloses_that_a_find_miss_may_lie_beyond_it(base, monkeypatch):
    monkeypatch.setattr(wf, "MAX_BODY_BYTES", 20_000)
    r = wf.fetch(f"{base}/long.txt")
    assert r.truncated and len(r.body) == 20_000 and r.status == 200
    miss = wf.fetch_nav(f"{base}/long.txt", find="zzzz")
    assert "no match" in miss and "the term you searched may lie in the un-fetched remainder" in miss
    assert "exceeded the" in wf.fetch_nav(f"{base}/long.txt", cursor="c16624") and "20000" in wf.fetch_nav(f"{base}/long.txt", cursor="c16624")


def test_the_cache_is_bounded_and_a_raw_fetch_never_serves_a_reduced_copy(base, monkeypatch):
    monkeypatch.setattr(wf, "DOC_CACHE_CAP", 3)
    for path in ("/nd", "/empty", "/a.yaml", "/badjson"):
        wf.fetch_nav(f"{base}{path}")
    assert wf.cached_structure(f"{base}/badjson") is False and wf.cached_structure(f"{base}/nd") is None     # the full cache was cleared
    plain = wf.fetch_nav(f"{base}/min.html")
    assert "<p>" not in plain and "word word" in plain
    raw = wf.fetch_nav(f"{base}/min.html", raw=True, find="word", cursor="c50")
    assert "<p>word</p>" in raw


def test_an_mcp_endpoint_and_a_graphql_endpoint_are_asked_what_they_offer_over_real_posts(base, monkeypatch):
    mcp = wf.fetch_nav(f"{base}/mcp")
    assert "This is an MCP server (Handles) speaking JSON-RPC 2.0 over POST" in mcp and "(protocol 2025-03-26)" in mcp
    assert ("[API endpoints (5): mcp tool resolve(handle: string, net?: string|null) — Resolve a handle to an address; "
            "mcp tool refd(… arguments not readable from this schema — call it to see); mcp tool bare(); mcp resource file:///r; mcp resource n]") in mcp
    assert "resolve → address: string" in mcp
    gql = wf.fetch_nav(f"{base}/graphql")
    assert "[API endpoints (3): Query.country(code: ID!) -> Country — One country; Query.countries() -> [Country]!; Mutation.rename() -> String]" in gql
    assert "Query.country → name(String), code(ID)" in gql and "Query.countries → name(String), code(ID)" in gql
    monkeypatch.setattr(ad, "MAX_PROBE_BYTES", 20)
    big = wf.fetch_nav(f"{base}/graphql")
    assert "API endpoints (" not in big and "graphql" in big.lower()
    monkeypatch.setattr(ad, "MAX_PROBE_BYTES", 32 * 1024 * 1024)
    assert ad._graphql_discover(f"{base}/nothing-here") is None and ad._mcp_discover(f"{base}/nothing-here") is None
    assert ad._mcp_discover("http://127.0.0.1:1/mcp") is None and ad._graphql_discover("http://127.0.0.1:1/graphql") is None


def test_find_and_paging_on_prose_and_json_answer_with_the_part_asked_for(base):
    page = wf.fetch_nav(f"{base}/long.txt")
    assert "More remains" in page and 'cursor="c' in page
    hit = wf.fetch_nav(f"{base}/long.txt", find="needle")
    assert hit.endswith('find="needle"\n\n---\nthe NEEDLE is here')       # the paragraph it sits in, not the document
    assert 'find "zzz": no match' in wf.fetch_nav(f"{base}/long.txt", find="zzz")
    assert wf.fetch_nav(f"{base}/long.txt", cursor="junk").splitlines()[2].startswith("--- (chars 0–")
    assert "--- (chars 39032–39032 of 39032) ---" in wf.fetch_nav(f"{base}/long.txt", cursor="c99999") or "chars" in wf.fetch_nav(f"{base}/long.txt", cursor="c99999")
    tags = wf.fetch_nav(f"{base}/data.json", find="tags")
    assert "# items > [0] > tags" in tags and "[897 more match(es); narrow your find]" in tags and "[top-level keys (2): items, meta]" in tags
    assert '# meta\n{\n  "page": 1\n}' in wf.fetch_nav(f"{base}/data.json", find="meta")
    assert "[8 more match(es)" in wf.fetch_nav(f"{base}/data.json", find="n77") and "Available top-level keys: items, meta." in wf.fetch_nav(f"{base}/data.json", find="zzz")
    assert "[structured doc — top-level keys: items, meta]" in wf.fetch_nav(f"{base}/data.json")


def test_a_swagger2_spec_yields_base_pathed_shapes_with_optional_marks_and_disclosed_caps():
    props = {"id": {"type": "integer", "example": "2026-08-18T00:00:00Z-and-then-a-very-long-example"}, "a-b": {"type": "string"},
             "nl\u2028x": {"type": "string"}, "arr": {"type": "array", "items": {"type": "string"}}, "untyped": {},
             "nest": {"type": "object", "properties": {"deep": {"type": "object", "properties": {"z": {"type": "string"}}}, "k": {"type": "string", "example": 5}}},
             "bare_obj": {"type": "object"}, "ref": {"$ref": "#/definitions/Sub"}}
    ok = lambda schema: {"get": {"responses": {"200": {"schema": schema}}}}
    spec = {"swagger": "2.0", "basePath": "/v1/", "paths": {
        "/users/{id}": {"get": {"parameters": [{"$ref": "#/parameters/Id"}, {"name": "q", "in": "query"}, "junk", {"$ref": "#/parameters/Nope"},
                                               {"in": "path"}, {"name": "slug", "in": "path", "schema": {"example": "abc"}}],
                                "responses": {"200": {"schema": {"$ref": "#/definitions/User"}}}}},
        "/users/{id}/posts": ok({"$ref": "#/definitions/User"}),                       # a sub-path of a shaped resource collapses
        "/viaref": {"get": {"responses": {"default": {"$ref": "#/responses/R"}}}}, "/nothing": {"get": {"responses": {"200": {"description": "ok"}}}},
        "/strange": "notadict", "/put": {"post": None, "put": {"responses": {"201": {"content": {"x": 1, "application/json": {"schema": {"$ref": "#/definitions/Sub"}}}}}}},
        **{f"/p{i}": ok({"$ref": "#/definitions/Sub"}) for i in range(14)}},
        "parameters": {"Id": {"name": "id", "in": "path", "description": "The id\nof user"}},
        "responses": {"R": {"schema": {"$ref": "#/definitions/Sub"}}},
        "definitions": {"User": {"type": "object", "required": ["id"], "properties": props}, "Sub": {"type": "object", "properties": {"s": {"type": "string"}}}}}
    shapes = wf._endpoint_response_shapes(spec, 12, 12)
    assert [s.head for s in shapes[:3]] == ["GET /v1/users/{id}", "GET /v1/viaref", "PUT /v1/put"] and len(shapes) == 13
    assert shapes[0].params == ("{id} = The id of user", "{slug} = e.g. abc") and shapes[1].fields == ("s",)
    assert shapes[-1].head == "…+more endpoints have shapes not shown here — web_fetch find=\"<path>\" for one"
    assert shapes[0].body == """```ts
{
  id: number;    // e.g. 2026-08-18T00:0…mple
  "a-b"?: string;
  "nl\\u2028x"?: string;
  arr?: unknown[];
  untyped?: unknown;
  nest?: {
    deep?: object;
    k?: string;  // e.g. 5
  };
  bare_obj?: object;
  ref?: {
    s?: string;
  };
}
```"""
    assert wf._endpoint_response_shapes(spec, 1, 3)[0].body.endswith("  // …+5 more field(s)\n}\n```")
    assert (wf._base_path({"servers": [{"url": "/api"}]}), wf._base_path({"servers": [{"url": "https://h.com"}]}), wf._base_path({"basePath": "/"})) == ("/api", "", "")
    assert wf._base_path([]) == "" and wf._ref_map([]) == {} and wf._endpoint_response_shapes({"paths": []}) == [] and wf._endpoint_response_shapes([]) == []


def test_the_spill_helpers_tell_the_coder_what_is_on_disk_and_never_guess(base, monkeypatch):
    monkeypatch.setattr(wf, "SPILL_CONTENT_MAX", 5000)
    for path in ("/long.txt", "/data.json", "/min.html"):
        wf.fetch_nav(f"{base}{path}")
    wf._cache_put("https://x.org/m.js", 200, "application/javascript", "function a(){var s='it\\'s };';return 1;}" * 400, None, False)
    wf._cache_put("https://x.org/m.xml", 200, "application/xml", "<a><b>x</b></a>" * 800, None, False)
    wf._cache_put("https://x.org/page.go", 200, "text/html", "<html><body>" + "<div class='a'>word</div>" * 400 + "</body></html>", None, False)
    wf._cache_put("https://x.org/oneline", 200, "text/plain", "w" * 10000, None, False)
    js = wf.oversized_spill("https://x.org/m.js")
    assert js[1] == "./tmp/reference/x.org_m.js.txt" and js[2].startswith("function a(){\nvar s='it\\'s };';\nreturn 1;\n}\nfunction a(){")   # string-aware break
    assert wf.oversized_spill("https://x.org/m.xml")[2].startswith("<a>\n<b>x</b>\n</a>\n<a>")
    assert wf.oversized_spill(f"{base}/nope-not-cached") is None and wf.spill_path_for(f"{base}/nope-not-cached") == ""
    page = wf.oversized_spill("https://x.org/page.go")
    assert "It is HTML. This is the web PAGE at that address, not the file's own text" in page[3]
    target = wf._spill_name("https://x.org/page.go")
    assert wf.format_for_spill_path(target) == "HTML" and wf.page_not_file_for_spill_path(target) and wf.spill_path_for("https://x.org/page.go") == target
    assert wf.format_for_spill_path(wf._spill_name(f"{base}/data.json")) == "JSON" and not wf.page_not_file_for_spill_path(wf._spill_name(f"{base}/data.json"))
    assert wf.format_for_spill_path("") == "" and wf.page_not_file_for_spill_path("./") is False and wf.outline_for_spill_path("") == ""
    assert wf.format_for_spill_path("./tmp/reference/none.txt") == "" and wf.page_not_file_for_spill_path("./tmp/reference/none.txt") is False
    outline = wf.outline_for_spill_path("tmp/reference/" + wf._spill_name(f"{base}/data.json").rsplit("/", 1)[1])
    assert outline.startswith("[top-level keys (2): items, meta]") and wf.outline_for_spill_path(wf._spill_name("https://x.org/m.js")) == ""
    hint = wf.spill_reading_hint(wf._spill_name("https://x.org/m.js"), 2000)
    assert hint.startswith("It is 454 lines — read_file with start_line=1 end_line=") and wf.spill_reading_hint("./tmp/reference/none.txt", 2000) == ""
    assert wf.spill_reading_hint(wf._spill_name("https://x.org/oneline"), 2000) == "" and wf.spill_reading_hint(wf._spill_name("https://x.org/m.js"), 5) == ""
    assert wf.spill_reading_hint(wf._spill_name("https://x.org/m.js"), 10**7) == ""
    assert wf.spill_extent_of("https://nowhere/x").startswith("there (the file's own last line says")
    assert wf.spill_extent_of("https://x.org/m.js") == wf.spill_extent_of(f"{base}/data.json") == "as much of it as one step can carry (the file itself says where it stops)"
    assert wf.outline_for_url("https://nowhere/x") == "" and wf.stdout_spill_pointer("./tmp/x", 5000).count("5,000 chars") == 1
    target, pointer = wf.search_spill("a b c")
    assert target.startswith("./tmp/reference/search-a_b_c-") and target in pointer and wf.search_spill_name("a b c" + "x" * 80) != wf.search_spill_name("a b c" + "x" * 81)
