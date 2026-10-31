"""A coder reads a docs site over real HTTP (the host is rewritten to a local server, so URLs stay external and gated):
an OpenAPI spec is navigated by find/cursor, an api-catalog lists the specs, an HTML guide is flattened, a binary and a
404 are reported honestly, and the third wrong guess in a row is told to stop guessing and an exact repeat is refused."""
import http.server
import json
import threading

import pytest

from cria import webfetch as wf

HOST = "https://docs.example.com"
SPEC = {"openapi": "3.0.3", "info": {"title": "Handles"}, "servers": [{"url": "https://api.example.com/v2"}], "paths": {
    "/handles/{handle}": {"parameters": [{"name": "handle", "in": "path", "description": "The handle, without the $ prefix"}],
                          "get": {"summary": "Resolve a handle", "parameters": [{"$ref": "#/components/parameters/Net"}, {"name": "q", "in": "query"}],
                                  "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Handle"}}}}}}},
    "/holders/{stake}": {"get": {"summary": "List holders", "parameters": [{"name": "stake", "in": "path", "schema": {"example": "stake1u85"}}],
                                 "responses": {"200": {"content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Holder"}}}}}}}},
    "/mint": {"post": {"summary": "Mint a handle", "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/MintReq"}}}}}},
    **{f"/pad{i}": {"get": {"summary": "padding " + "x" * 300}} for i in range(60)}},
    "components": {"parameters": {"Net": {"name": "net", "in": "path", "description": "mainnet or preprod"}}, "schemas": {
        "Handle": {"type": "object", "required": ["name"], "properties": {
            "name": {"type": "string", "description": "the handle"}, "kind": {"type": "string", "enum": ["og", "normal"]},
            "resolved_addresses": {"type": "object", "properties": {"ada": {"type": "string", "example": "addr1q"}}},
            "holder": {"$ref": "#/components/schemas/Holder"}}},
        "Holder": {"allOf": [{"type": "object", "properties": {"stake": {"type": "string"}, "total_handles": {"type": "integer"}}}]},
        "MintReq": {"oneOf": [{"type": "object", "properties": {"name": {"type": "string"}}}, {"type": "string"}]}}}}
CATALOG = {"linkset": [{"anchor": f"https://api.example.com/v{i}", "service-desc": [{"href": f"https://api.example.com/v{i}/openapi.json"}],
                        "service-doc": [{"href": f"https://docs.example.com/v{i}"}], "status": "ignored"} for i in range(24)]}
GUIDE = ("<html><head><title>Guide</title><style>.x{color:red}</style><script>var secret=1;</script></head><body>"
         "<nav><a href='/a'>Home</a></nav><h1>Resolving</h1><p>Call <code>GET /handles/{handle}</code> first.</p>"
         "<table><tr><th>Field</th><th>Meaning</th></tr><tr><td>kind</td><td>og or normal</td></tr></table>"
         "<pre>curl https://api.example.com/v2/handles/goose</pre>" + "<p>filler paragraph about caching.</p>" * 600 +
         "<p>The needle lives here: rate limit is 50 per minute.</p></body></html>")
ROUTES = {"/openapi.json": ("application/json", json.dumps(SPEC).encode(), 200),
          "/.well-known/api-catalog": ("application/linkset+json", json.dumps(CATALOG).encode(), 200),
          "/guide": ("text/html; charset=utf-8", GUIDE.encode(), 200),
          "/logo.png": ("image/png", bytes(range(256)) * 4, 200), "/nope": ("application/json", b'{"error":"route_not_found"}', 404)}


class Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ct, body, code = ROUTES.get(self.path, ("text/plain", b"", 404))
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def site(monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    real = wf.fetch
    monkeypatch.setattr(wf, "fetch", lambda url, ua=None: real(url.replace(HOST, f"http://127.0.0.1:{server.server_port}"), ua))
    wf.clear_cache()
    yield
    server.shutdown()
    wf.clear_cache()


def test_a_docs_site_is_navigated_without_losing_what_the_spec_declares_or_lying_about_failures(site):
    text, refused, status, facts = wf.fetch_nav_result(f"{HOST}/openapi.json", session="s")
    assert (refused, status) == (False, 200) and "(chars 0–" in text and "API endpoints (63)" in text
    assert "/v2/handles/{handle}" in facts["routes"] and facts["shapes"][0]["params"] == ["{net} = mainnet or preprod", "{handle} = The handle, without the $ prefix"]
    assert "name: string;    // the handle" in text and "ada?: string;  // e.g. addr1q" in text
    page2 = wf.fetch_nav(f"{HOST}/openapi.json", cursor="c6000", session="s")
    assert "--- (chars 6000–14616 of 21863) ---" in page2 and '(7247 of 21863 chars left). Continue with the SAME url and cursor="c14616"' in page2
    one = wf.fetch_nav(f"{HOST}/openapi.json", find="/holders/{stake}", session="s")
    assert "List holders" in one and "total_handles" in one and "stake1u85" in one
    miss = wf.fetch_nav(f"{HOST}/openapi.json", find="zzz_absent", session="s")
    assert "no match" in miss and "paths" in miss and "components" in miss
    many = wf.fetch_nav(f"{HOST}/openapi.json", find="paths", session="s")
    assert "narrow it" in many and "./tmp/reference/docs.example.com_openapi.json.txt" in many

    catalog = wf.fetch_nav(f"{HOST}/.well-known/api-catalog", session="s")
    assert "[API descriptions (21)" in catalog and "…+4 more catalogued API(s) not shown" in catalog
    assert "https://api.example.com/v0 → service-desc: https://api.example.com/v0/openapi.json; service-doc: https://docs.example.com/v0" in catalog
    assert "ignored" not in catalog.split("\n", 3)[3].split("…+4")[0]

    guide = wf.fetch_nav(f"{HOST}/guide", session="s")
    assert "Resolving Call GET /handles/{handle} first." in guide and "Home (https://docs.example.com/a)" in guide
    assert "secret" not in guide and "color:red" not in guide and "of 19413) ---" in guide.splitlines()[2]
    assert "no match. Links on this page:\nhttps://docs.example.com/a" in wf.fetch_nav(f"{HOST}/guide", find="zzzqq", session="s")
    assert "<script>" in wf.fetch_nav(f"{HOST}/guide", raw=True, find="secret", session="s")
    assert "[non-text response: 1024 bytes, content-type=image/png" in wf.fetch_nav(f"{HOST}/logo.png", session="s")


def test_wrong_guesses_are_labelled_by_whose_fault_they_are_and_an_exact_repeat_is_refused_only_while_visible(site):
    first = wf.fetch_nav(f"{HOST}/nope", session="g")
    assert "HTTP 404 Not Found" in first and '{"error":"route_not_found"}' in first and "failure is on your side" in first
    assert "guessing" not in first and "guessing" not in wf.fetch_nav(f"{HOST}/nope2", session="g")
    assert "guessing" in wf.fetch_nav(f"{HOST}/nope3", session="g")                       # the third consecutive miss
    assert "guessing" not in wf.fetch_nav(f"{HOST}/openapi.json", session="g")             # a success resets the streak
    wf.set_visible("g", [(f"{HOST}/openapi.json", "", "")], [])
    text, refused, status, facts = wf.fetch_nav_result(f"{HOST}/openapi.json", session="g")
    assert refused and status is None and facts is None and "already fetched" in text
    assert wf.fetch_nav_result(f"{HOST}/openapi.json", find="mint", session="g")[1] is False   # a narrower question is a new one
