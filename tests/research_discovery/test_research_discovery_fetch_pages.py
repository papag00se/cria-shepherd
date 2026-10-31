"""What a fetch hands the model: navigable, never silently truncated, honest about what it is and why it failed."""
import http.server
import json
import threading

import pytest

from cria import content_reduce, webfetch as wf

SPEC = {"openapi": "3.0.3", "info": {"title": "H"},
        "paths": {f"/p{i}": {"get": {"summary": f"op {i}"}} for i in range(200)} | {"/handles/{handle}": {"get": {"summary": "Resolve a handle"}}},
        "defs": {"Handle": {"type": "object"}}}

@pytest.fixture(autouse=True)
def fresh_cache():
    wf.clear_cache()
    yield
    wf.clear_cache()

@pytest.fixture
def served(monkeypatch):
    """Serve `body` as `ct` from fetch(); returns the url. The network boundary is the only thing replaced."""
    def serve(body, ct="application/json", status=200, truncated=False, url="https://api.x/openapi.json"):
        monkeypatch.setattr(wf, "fetch", lambda u, ua=None: wf.FetchResult(status, u, ct, body, truncated))
        return url
    return serve

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code, body = {"/gone": (404, b'{"error":"route_not_found","message":"Route not found: /handle/goose"}'),
                      "/wall": (403, b"Just a moment... Enable JavaScript and cookies to continue"),
                      "/empty": (200, b"")}[self.path]
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

def test_a_failed_fetch_keeps_its_body_and_names_the_real_reason():
    """api.handle.me answers 404 with the diagnosis; a bot wall's 403 is a refusal, not 'your URL is wrong'; file:// is refused."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        gone = wf.fetch_nav(base + "/gone", session="s")
        assert "HTTP 404" in gone and "Route not found: /handle/goose" in gone
        assert "EMPTY" in wf.fetch_nav(base + "/empty")
        wall = wf.fetch_nav(base + "/wall")
        assert "Just a moment" in wall and "REFUSED" in wall and "on your side" not in wall
    finally:
        server.shutdown()
    with pytest.raises(ValueError):
        wf.fetch("file:///etc/passwd")
    assert "on your side" in wf.client_error_note(404, "nf") and "how the URL should be formed" in wf.client_error_note(400, "Shorthand URLs")
    assert wf.client_error_note(503, "down") == ""
    for code in (401, 403, 407, 429, 451):   # a refusal names no cause (credential / rate limit / bot) and never blames the address
        note = wf.client_error_note(code, "body")
        assert f"HTTP {code}" in note and "on your side" not in note and "rate limit" not in note.lower()
    assert "sent nothing back" in wf.client_error_note(403, "") and "read that first" not in wf.client_error_note(403, "")

def test_a_big_spec_is_navigable_and_find_answers_from_the_cache(served):
    """The Ada-handle seed: a one-line 200-route JSON must be paged with its routes up front, never cut to a prefix that reads as a 404."""
    url = served(json.dumps(SPEC, separators=(",", ":")))
    page = wf.fetch_nav(url, cap_tokens=200)
    header = page.split("--- (chars", 1)[0]
    assert "HTTP 200" in page and "top-level keys" in page and "More remains" in page
    assert "API endpoints" in header and "/handles/{handle}" in header
    wf.fetch = lambda *a, **k: pytest.fail("find must be served from the cache")
    assert "op 150" in wf.fetch_nav(url, find="p150")
    assert wf.page_from("\n".join(f"line {i}" for i in range(50)), 10_000, 20)[0] == ""   # past the end: graceful

def test_find_answers_every_term_and_never_calls_a_present_term_absent():
    """run 0727-124354: `holder_address|total_handles` read 'no match' about a document holding both; 10 fetches + 66 calls followed."""
    body = {"paths": {"/a": {"get": {"summary": "holder_address x"}}, "/b": {"get": {"summary": "total_handles"}}}, "a|b": {"k": "v"}}
    red, parsed = wf.reduce_for_cache(json.dumps(body), "application/json", "http://x/s.json")
    for q in ("holder_address|total_handles", "holder_address, total_handles", "holder_address OR total_handles"):
        out = wf.find_in(red, parsed, q, 4000)
        assert "holder_address x" in out and "total_handles" in out, q
    assert "no match in this document for: zzz_absent" in wf.find_in(red, parsed, "holder_address|zzz_absent", 4000)
    assert "no match for any of" in wf.find_in(red, parsed, "nope1|nope2", 4000)
    assert "a|b" in wf.find_in(red, parsed, "a|b", 4000) and '"v"' in wf.find_in(red, parsed, "a|b", 4000)   # a pipe inside one real key
    for q in ('"paths"', "'paths'"):
        assert "no match" not in wf.find_in(red, parsed, q, 4000)
    miss = wf.find_in(red, parsed, "operatoinId", 4000)   # a near-miss names what IS there
    assert "no match" in miss and "paths" in miss
    assert "Sections:" in wf.find_text("# Title\n## Install\nfoo\n## Usage\nbar", "zzz", 4000)

def test_a_find_on_a_document_that_fits_never_deletes_it(served):
    """A find on a small doc returns the WHOLE doc; only a transport-cut body narrows (and says so)."""
    small = json.dumps({"paths": {"/a": {}}, "info": {"title": "tiny"}})
    url = served(small, url="https://x/small")
    for q in ("paths", "zzznope"):
        out = wf.fetch_nav(url, find=q)
        assert '"title": "tiny"' in out or "tiny" in out, q
    cut = served('{"a":1}', truncated=True, url="https://x/cut")
    out = wf.fetch_nav(cut, find="nonexistentkey")
    assert "no match" in out and "fetch limit" in out   # a miss on a cut body may be a cut, not an absence

def test_a_cut_body_is_disclosed_on_every_exit():
    """The paging end must never look like a clean end-of-document."""
    cut = wf.render_page("https://x/big", 200, "text/plain", "body", None, 0, 200, True)
    assert "More remains" not in cut and "fetch limit" in cut and "NOT fetched" in cut
    assert "fetch limit" not in wf.render_page("https://x/big", 200, "text/plain", "body", None, 0, 200, False)
    sch = {"type": "object", "properties": {"nested": {"type": "object", "properties": {f"f{i}": {"type": "string"} for i in range(wf.FIELD_CAP + 5)}}}}
    out = wf._schema_field_summary(sch, {}, wf.FIELD_CAP)
    assert out[-1] == "nested: …+5 more field(s)"   # the cap discloses itself INSIDE the nesting, where a slice removed it

def test_content_is_reduced_by_shape_raw_is_its_own_identity_and_nothing_is_reworded(served):
    """XML/SVG keep their markup; HTML flattens unless raw; raw after reduced is not 'already fetched'; reducing never rewords a sentence."""
    assert "<item>" in wf.reduce_for_cache("<rss><channel><item><title>Post</title></item></channel></rss>", "application/rss+xml", "http://h/f")[0]
    flat = wf.reduce_for_cache("<html><h1>Hi</h1><script>var z=1</script></html>", "text/html", "http://h")[0]
    assert "<h1>" not in flat and "Hi" in flat
    assert "<script>" in wf.reduce_for_cache("<html><h1>Hi</h1><script>var z=1</script></html>", "text/html", "http://h", raw=True)[0]
    url = served("<b>hi</b>", ct="text/html", url="https://site.x/page")
    assert "HTTP 200" in wf.fetch_nav(url, session="s1")
    wf.set_visible("s1", [(url, "", "")], [])
    assert "already fetched" in wf.fetch_nav(url, session="s1")
    raw = wf.fetch_nav(url, session="s1", raw=True)
    assert "<b>hi</b>" in raw and "already fetched" not in raw
    body = json.dumps({"items": [{"message": "the request could not be read from the server because the token is not valid"}] * 40})
    for reduce in (content_reduce.digest_reduce, content_reduce.content_reduce):
        assert "could not be read from the server" in reduce(body, "application/json", 50)   # function-word deletion once inverted this

def test_spec_fields_carry_what_the_spec_declares_and_nothing_it_does_not():
    """Optional fields are marked, the optional marker never becomes part of a key, examples/placeholder runs are handled."""
    spec = {"openapi": "3.0.0", "paths": {"/h/{handle}": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {
        "type": "object", "required": ["name"], "properties": {"name": {"type": "string", "example": "goose"},
        "holder": {"type": "string", "example": "xxxxxxxxxx"}, "count": {"type": "integer"},
        "my-key": {"type": "string"}}}}}}}}}}}
    ts = wf._endpoint_response_shapes(spec)[0].body
    assert "name: string" in ts and "holder?: string" in ts and "count?: number" in ts and '"my-key"?: string' in ts
    assert "// e.g. goose" in ts and '"holder?"' not in ts and "xxxxxxxxxx" not in ts   # a placeholder run is dropped entirely
