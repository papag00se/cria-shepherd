import email.message
import io
import json
import unittest
import urllib.error

from cria import webfetch as wf


class FindJsonTests(unittest.TestCase):
    def test_find_returns_subtree_spine_and_resolves_ref(self):
        # port of content_reduce.rs::find_json_returns_subtree_spine_and_resolves_ref
        spec = json.loads('{"paths":{"/handles/{handle}":{"get":{"summary":"Resolve a handle",'
                          '"responses":{"200":{"schema":{"$ref":"#/defs/Handle"}}}}}},'
                          '"defs":{"Handle":{"type":"object","properties":{"name":{"type":"string"}}}}}')
        out = wf.find_json(spec, "handles", 4000)
        self.assertIn("paths > /handles/{handle}", out)   # ancestor spine
        self.assertIn("Resolve a handle", out)            # subtree content
        self.assertIn("properties", out)                  # $ref inlined one hop
        self.assertIn('"name"', out)
        self.assertNotIn("$ref", out)                     # no dangling ref

    def test_no_match_lists_top_keys(self):
        out = wf.find_json({"paths": {}, "components": {}, "info": {}}, "zzzznope", 4000)
        self.assertIn("no match", out)
        for k in ("paths", "components", "info"):
            self.assertIn(k, out)
        self.assertNotIn("Closest field names", out)   # a distant miss → root-key fallback only

    def test_no_match_suggests_the_closest_deep_field_name(self):
        # miss-diagnosis: a near-miss (typo) that ISN'T a substring of any key gets pointed at the
        # closest real field name anywhere in the doc — including a DEEP key root-keys never surface.
        spec = {"openapi": "3.0", "components": {"schemas": {"ResolvedAddress": {"operationId": "x"}}}}
        out = wf.find_json(spec, "operatoinId", 4000)   # typo of operationId
        self.assertIn("no match", out)
        self.assertIn("Closest field names", out)
        self.assertIn("operationId", out)

    def test_find_in_strips_surrounding_quotes(self):
        obj = {"components": {"schemas": {"Holder": {"type": "object"}}}}
        red = json.dumps(obj)
        for q in ("Holder", '"Holder"', "'Holder'", '  "Holder"  '):
            self.assertNotIn("no match", wf.find_in(red, obj, q, 4000), q)


class PageTests(unittest.TestCase):
    def test_page_from_walks_and_reports_remaining(self):
        body = "\n".join(f"line {i}" for i in range(50))
        p1, nxt, total = wf.page_from(body, 0, 20)
        self.assertTrue(p1.startswith("line 0"))
        self.assertTrue(0 < nxt < total)
        p2, _, _ = wf.page_from(body, nxt, 20)
        self.assertNotEqual(p1, p2)
        end, n2, t2 = wf.page_from(body, total + 999, 20)   # past the end → graceful
        self.assertEqual(end, "")
        self.assertEqual(n2, t2)
        self.assertEqual(t2, total)


class YamlStructuralTests(unittest.TestCase):
    def test_yaml_reduced_structurally_and_findable(self):
        if wf._yaml is None:
            self.skipTest("PyYAML not installed")
        y = ("openapi: 3.0.3\npaths:\n  /resolve/{handle}:\n    get:\n"
             "      summary: Resolve a handle\n")
        reduced, parsed = wf.reduce_for_cache(y, "application/x-yaml", "http://x/api.yaml")
        self.assertIsNotNone(parsed)                       # structurally parsed, not text
        self.assertIn("Resolve a handle", wf.find_in(reduced, parsed, "resolve", 4000))


class XmlAndRawSourceTests(unittest.TestCase):
    """XML is STRUCTURED data — it must not be prose-flattened like HTML (that destroys an RSS/Atom/SVG/
    SOAP feed). And a caller can ask for the LITERAL source with raw=True (front-end debugging)."""

    def test_xml_is_preserved_not_flattened(self):
        xml = '<rss><channel><item><title>Post</title><link>http://a/b</link></item></channel></rss>'
        reduced, parsed = wf.reduce_for_cache(xml, "application/rss+xml", "http://h/feed")
        self.assertIn("<item>", reduced)                   # tags survive — structure intact
        self.assertIn("<title>Post</title>", reduced)      # before the fix this flattened to "Post http://a/b"

    def test_svg_xml_keeps_its_markup(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
        reduced, _ = wf.reduce_for_cache(svg, "image/svg+xml", "http://h/i.svg")
        self.assertIn("<rect", reduced)

    def test_html_default_flattens_but_raw_returns_source(self):
        html = '<html><body><h1>Hi</h1><a href="/x">link</a><script>var z=1</script></body></html>'
        flat, _ = wf.reduce_for_cache(html, "text/html", "http://h")
        self.assertNotIn("<h1>", flat)                     # default: readable text, tags stripped
        self.assertIn("Hi", flat)
        raw, _ = wf.reduce_for_cache(html, "text/html", "http://h", raw=True)
        self.assertIn("<h1>Hi</h1>", raw)                  # raw: literal markup, incl. script
        self.assertIn("<script>", raw)

    def test_raw_fetch_not_refused_after_a_reduced_fetch_of_the_same_url(self):
        # raw source and the reduced view are distinct fetch identities — asking for the source after
        # reading the text must NOT be refused as an "already fetched" repeat.
        wf.clear_cache()
        orig = wf.fetch
        wf.fetch = lambda u, ua=None: wf.FetchResult(200, u, "text/html", "<b>hi</b>", False)
        try:
            url = "https://site.x/page"
            self.assertIn("HTTP 200", wf.fetch_nav(url, session="s1"))          # reduced view
            wf.set_visible("s1", [(url, "", "")], [])                           # its result is in context
            self.assertIn("still above", wf.fetch_nav(url, session="s1"))       # reduced repeat → refused
            out = wf.fetch_nav(url, session="s1", raw=True)                     # raw is a DIFFERENT identity
            self.assertIn("<b>hi</b>", out)                                     # → served, not refused
            self.assertNotIn("still above", out)
        finally:
            wf.fetch = orig
            wf.clear_cache()


class StatusAndHostTests(unittest.TestCase):
    def test_status_label(self):
        self.assertEqual(wf.status_label(404), "HTTP 404 Not Found")
        self.assertEqual(wf.status_label(200), "HTTP 200 OK")
        self.assertEqual(wf.status_label(599), "HTTP 599")

    def test_internal_hosts(self):
        for u in ("http://localhost:3000/x", "http://127.0.0.1/api", "http://[::1]:8080/",
                  "http://192.168.1.10/s", "http://10.0.0.5:9000/x", "http://myapp.local/"):
            self.assertTrue(wf.is_internal_url(u), u)
        for u in ("https://api.handle.me/x", "https://example.com", "http://172.32.0.1/"):
            self.assertFalse(wf.is_internal_url(u), u)

    def test_guess_hint_only_after_threshold(self):
        self.assertEqual(wf.guess_hint(404, 1), "")
        self.assertEqual(wf.guess_hint(404, 2), "")
        self.assertIn("guessing", wf.guess_hint(404, 3))
        self.assertEqual(wf.guess_hint(200, 9), "")   # a 2xx never nags


def _fake_urlopen(status, body: bytes, ct="application/json", url="https://api.handle.me/openapi.json"):
    hdrs = email.message.Message()
    if ct is not None:
        hdrs["Content-Type"] = ct

    def opener(req, timeout=None):
        if 200 <= status < 300:
            class _R:
                def __init__(s):
                    s.status, s._fp = status, io.BytesIO(body)
                def geturl(s):
                    return url
                @property
                def headers(s):
                    return hdrs
                def read(s, n=-1):
                    return s._fp.read(n)
                def __enter__(s):
                    return s
                def __exit__(s, *a):
                    return False
            return _R()
        raise urllib.error.HTTPError(url, status, _STATUS_REASON.get(status, ""), hdrs, io.BytesIO(body))
    return opener


_STATUS_REASON = {404: "Not Found", 500: "Internal Server Error"}


class FetchTests(unittest.TestCase):
    def setUp(self):
        wf.clear_cache()

    def test_rejects_non_http_scheme(self):
        with self.assertRaises(ValueError):
            wf.fetch("file:///etc/passwd")

    def test_non_2xx_keeps_body_and_status(self):
        # api.handle.me serves real docs on its 404 — the body must survive with the status.
        orig = wf.urllib.request.urlopen
        wf.urllib.request.urlopen = _fake_urlopen(404, b'{"available":["/handles","/holders"]}')
        try:
            r = wf.fetch("https://api.handle.me/openapi.json")
        finally:
            wf.urllib.request.urlopen = orig
        self.assertEqual(r.status, 404)
        self.assertIn("available", r.body)


class FetchNavSeedTests(unittest.TestCase):
    """The Ada-handle seed: a large single-line JSON must be NAVIGABLE, not truncated to an
    unusable prefix that the model mistakes for a 404."""

    def setUp(self):
        wf.clear_cache()

    def test_large_single_line_json_is_navigable(self):
        big = json.dumps({
            "openapi": "3.0.3",
            "info": {"title": "Handles Public API"},
            "paths": {f"/p{i}": {"get": {"summary": f"op {i}"}} for i in range(200)},
            "defs": {"Handle": {"type": "object"}},
        }, separators=(",", ":"))
        orig = wf.fetch
        wf.fetch = lambda url, ua=None: wf.FetchResult(200, url, "application/json", big, False)
        try:
            page1 = wf.fetch_nav("https://api.handle.me/openapi.json", cap_tokens=200)
            self.assertIn("HTTP 200", page1)
            self.assertIn("top-level keys", page1)     # the shape is surfaced, not a raw blob
            self.assertIn("openapi", page1)
            self.assertIn("More remains", page1)       # paged, not silently truncated
            # find, served from the cache (no re-fetch), jumps straight to the endpoint
            found = wf.fetch_nav("https://api.handle.me/openapi.json", find="p150")
            self.assertIn("op 150", found)
        finally:
            wf.fetch = orig

    def test_api_spec_surfaces_endpoint_routes_in_outline(self):
        # An API spec's outline must advertise the actual ENDPOINT ROUTES up front, so a model
        # reaching for "the endpoint" sees /handles/{handle} instead of drilling into schemas and
        # guessing the URL. Detected by SHAPE (top-level object of /-paths), not the key name.
        big = json.dumps({
            "openapi": "3.0.3", "info": {"title": "X"},
            "routes": {f"/p{i}": {"get": {}} for i in range(200)} | {"/handles/{handle}": {"get": {}}},
            "components": {"schemas": {"Handle": {"type": "object"}}},
        }, separators=(",", ":"))
        orig = wf.fetch
        wf.fetch = lambda url, ua=None: wf.FetchResult(200, url, "application/json", big, False)
        try:
            page1 = wf.fetch_nav("https://api.x/openapi.json", cap_tokens=200)
            self.assertIn("API endpoints", page1)                 # routes surfaced (key was "routes", not "paths")
            self.assertIn("/handles/{handle}", page1.split("--- (chars", 1)[0])  # in the HEADER, up front
        finally:
            wf.fetch = orig

    def test_non_spec_doc_gets_no_routes_line(self):
        # A structured doc that isn't route-shaped must NOT invent an endpoints line.
        from cria.webfetch import _endpoint_routes
        self.assertEqual(_endpoint_routes({"name": "x", "config": {"a": 1, "b": 2}}), [])
        self.assertEqual(_endpoint_routes({"paths": {"/a": {}, "/b": {}}}), ["/a", "/b"])

    def test_empty_body_is_explicit(self):
        orig = wf.fetch
        wf.fetch = lambda url, ua=None: wf.FetchResult(200, url, "text/plain", "", False)
        try:
            out = wf.fetch_nav("https://e.com/x")
        finally:
            wf.fetch = orig
        self.assertIn("EMPTY", out)

    def _serve(self, body, ct="application/json"):
        wf.clear_cache()
        orig = wf.fetch
        wf.fetch = lambda url, ua=None: wf.FetchResult(200, url, ct, body, False)
        return orig

    def test_minified_css_is_broken_for_grep(self):
        orig = self._serve("a{margin:0}b{color:red;font-size:2em}" * 800, ct="text/css")
        try:
            wf.fetch_nav("https://x/s.css")
            content = wf.oversized_spill("https://x/s.css")[2]
            self.assertGreater(content.count("\n"), 500)   # line-oriented, not one mega-line
        finally:
            wf.fetch = orig

    def test_minified_js_break_is_string_aware(self):
        # a `{` INSIDE a string literal must NOT trigger a break — that would corrupt the greppable view.
        orig = self._serve("const u='https://a.com/{id}';function f(){return u}" * 800, ct="application/javascript")
        try:
            wf.fetch_nav("https://x/app.js")
            content = wf.oversized_spill("https://x/app.js")[2]
            self.assertGreater(content.count("\n"), 500)
            self.assertIn("'https://a.com/{id}'", content)   # brace-in-string intact
        finally:
            wf.fetch = orig

    def test_oversized_doc_spills_full_content_and_pointer(self):
        # A big doc: oversized_spill returns the FULL greppable content (not just page-1 front matter)
        # + a ./tmp target + a grep/find pointer message. This is the fix for the model saving the
        # 473-byte info block: it now gets the whole spec on disk, pointed at the fields it needs.
        big = json.dumps({"openapi": "3.0.3", "info": {"title": "X", "license": {"name": "MPL"}},
                          "paths": {f"/p{i}": {"get": {"summary": "s" * 60}} for i in range(400)},
                          "components": {"schemas": {"Handle": {"resolved_addresses": {"type": "object"}}}}},
                         separators=(",", ":"))
        orig = self._serve(big)
        try:
            wf.fetch_nav("https://api.x/openapi.json")            # populate the cache
            spill = wf.oversized_spill("https://api.x/openapi.json")
            self.assertIsNotNone(spill)
            status, target, content, msg = spill
            self.assertTrue(target.startswith("./tmp/"))
            self.assertIn("resolved_addresses", content)         # the FULL doc, not the info block
            self.assertGreater(content.count("\n"), 100)         # pretty-printed → greppable
            self.assertIn("grep", msg)
            self.assertIn(target, msg)
            self.assertIn("find=", msg)
            # the spill message leads with the ROUTE OUTLINE (this spec is route-shaped) so the model
            # greps straight to an endpoint instead of paging the whole file — and no <keyword> to echo
            self.assertIn("API endpoints (400)", msg)
            self.assertIn("/p0", msg)
            self.assertNotIn("<keyword>", msg)
        finally:
            wf.fetch = orig

    def test_raw_fetch_of_a_spec_still_gets_the_route_outline(self):
        # THE FOOTGUN (live run 0726-130831): `raw=true` returned parsed=None, and parsed is what every
        # structural surface is built from — so an oversized spec fetched raw spilled with NO outline at
        # all: no routes, no response fields, not even top-level keys. The coder got "saved 59,210 chars,
        # go grep it", grepped for its own guess ("resolve" — 2 useless hits) while /handles/{handle} sat
        # at line 363, and shipped https://api.handle.me/resolve-handle → 404. `raw` governs the BYTES the
        # model reads, never whether cria understands the doc's shape.
        big = json.dumps({"openapi": "3.0.3", "info": {"title": "Handles"},
                          "paths": {"/handles/{handle}": {"get": {"summary": "s" * 60}},
                                    "/holders/{address}": {"get": {"summary": "s" * 60}},
                                    **{f"/pad{i}": {"get": {"summary": "s" * 80}} for i in range(400)}}},
                         separators=(",", ":"))
        orig = self._serve(big)
        try:
            wf.fetch_nav("https://api.x/openapi.json", raw=True)   # populate the cache RAW
            status, target, content, msg = wf.oversized_spill("https://api.x/openapi.json")
            self.assertIn("API endpoints (402)", msg)              # the outline is there...
            self.assertIn("/handles/{handle}", msg)                # ...naming the REAL route
            self.assertIn("/holders/{address}", msg)
            self.assertIn(target, msg)
        finally:
            wf.fetch = orig

    def test_raw_HONORS_find_instead_of_silently_discarding_it(self):
        # THE FOOTGUN (live run 0726-134700): `raw` nulled `find` alongside `cursor`, discarding the
        # model's narrowing request with NO notice — it asked one question and was answered another,
        # undetectably. The coder sent find="resolve" with raw=true FIFTEEN times and got the same
        # "saved 96,199 chars, go grep it" spill every time. Honoring it would have ended the run:
        # "resolve" matches `resolved_addresses`, the exact field the task needed.
        big = json.dumps({"openapi": "3.0.3",
                          "paths": {"/handles/{handle}": {"get": {"summary": "s" * 60}},
                                    **{f"/pad{i}": {"get": {"summary": "s" * 80}} for i in range(400)}},
                          "components": {"schemas": {"Handle": {"properties": {
                              "resolved_addresses": {"type": "object", "properties": {"ada": {}}}}}}}},
                         separators=(",", ":"))
        orig = self._serve(big)
        try:
            out = wf.fetch_nav("https://api.x/openapi.json", find="resolve", raw=True)
        finally:
            wf.fetch = orig
        self.assertIn('find="resolve"', out)              # the find was RUN, not dropped
        self.assertIn("resolved_addresses", out)          # ...and it found the field that ends the hunt
        self.assertNotIn("too large for the context", out)  # not the whole-doc spill it kept re-sending

    def test_raw_reduction_still_passes_the_body_through_untouched(self):
        # `raw` must keep its own contract: the REDUCED text is the literal source, byte for byte. Only
        # the structure is additionally learned — nothing about the model's bytes changes.
        body = '{"a":1,   "b":[2,3]}'
        reduced, parsed = wf.reduce_for_cache(body, "application/json", "https://api.x/x.json", raw=True)
        self.assertEqual(reduced, body)                            # untouched, whitespace and all
        self.assertEqual(parsed, {"a": 1, "b": [2, 3]})            # but the shape is known
        html, hparsed = wf.reduce_for_cache("<p>hi</p>", "text/html", "https://x/", raw=True)
        self.assertEqual(html, "<p>hi</p>")                        # raw HTML not flattened...
        self.assertIsNone(hparsed)                                 # ...and has no structure to learn

    def test_small_doc_does_not_spill(self):
        orig = self._serve(json.dumps({"status": "ok"}))
        try:
            wf.fetch_nav("https://api.x/health")
            self.assertIsNone(wf.oversized_spill("https://api.x/health"))
        finally:
            wf.fetch = orig

    def _spill_msg(self, url, body, content_type):
        wf._cache_put(url, 200, content_type,
                      *wf.reduce_for_cache(body, content_type, url), False)
        return wf.oversized_spill(url)[3]

    def test_spill_outline_surfaces_routes_for_spec_shaped_json(self):
        pad = "x" * (wf.OVERSIZE_CHARS + 500)
        body = json.dumps({"openapi": "3.0.0", "info": {"description": pad},
                           "paths": {"/handles/{handle}": {}, "/holders/{address}": {}, "/health": {}}})
        msg = self._spill_msg("https://api.handle.me/openapi.json", body, "application/json")
        self.assertIn("API endpoints (3)", msg)
        self.assertIn("/handles/{handle}", msg)
        self.assertIn("/holders/{address}", msg)
        # points the model at the endpoint LIST, not a single seeded route: a seeded routes[0] can be a
        # useless meta-path (real spec: routes[0]=="/" → the degenerate `grep -n "/"`), which sent the
        # coder crawling the /openapi.json//swagger.json aliases at the top of the list.
        self.assertIn("FROM THAT LIST", msg)
        self.assertNotIn('grep -n "/"', msg)                 # no degenerate example
        self.assertNotIn("<keyword>", msg)

    def test_spill_outline_surfaces_dereferenced_response_fields(self):
        # The recurring last-mile bug: the coder has the right endpoint but GUESSES the response shape
        # (a wrapper, a singular field, wrong nesting) because the response schema is a $ref it never
        # follows. cria now dereferences the $ref and surfaces the REAL fields incl. one level of nesting.
        pad = "x" * (wf.OVERSIZE_CHARS + 500)
        spec = {
            "openapi": "3.0.0", "info": {"description": pad},
            "paths": {
                "/handles/{handle}": {"get": {"responses": {"200": {"content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Handle"}}}}}}},
                "/holders/{address}": {"get": {"responses": {"200": {"content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Holder"}}}}}}},
            },
            "components": {"schemas": {
                "Handle": {"type": "object", "properties": {
                    "holder": {"type": "string"},
                    "resolved_addresses": {"type": "object", "properties": {
                        "ada": {"type": "string"}, "eth": {"type": "string"}}},
                    "total_handles": {"type": "integer"}}},
                "Holder": {"type": "object", "properties": {"total_handles": {"type": "integer"}}}}},
        }
        msg = self._spill_msg("https://api.handle.me/openapi.json", json.dumps(spec), "application/json")
        self.assertIn("response shape", msg)
        self.assertIn("holder", msg)
        self.assertIn("resolved_addresses{ada, eth}", msg)   # $ref dereferenced + nesting expanded
        self.assertNotIn("$ref", msg)                        # the ref is resolved, not shown raw

    def test_response_shape_collapses_subpaths_so_distinct_resources_survive(self):
        # LIVE footgun: a spec front-loaded 8 /handles/{handle}/* sub-variants, filling the endpoint budget
        # in spec order and CROWDING OUT /holders/{address} — so its response shape was never surfaced and
        # the coder guessed the holder's total (invented a `holders` key). Sub-paths of a parameterized
        # resource are now collapsed (the base is shaped; the routes list still shows the sub-paths), so a
        # distinct resource that comes AFTER the variants keeps its shape.
        def ep():
            return {"get": {"responses": {"200": {"content": {"application/json": {
                "schema": {"type": "object", "properties": {"x": {"type": "string"}}}}}}}}}
        paths = {"/handles/{handle}": ep()}
        for sub in ("utxo", "script", "datum", "personalized", "reference_token"):
            paths[f"/handles/{{handle}}/{sub}"] = ep()
        paths["/holders/{address}"] = ep()   # a DISTINCT resource, AFTER the sub-variants
        shapes = " ".join(wf._endpoint_response_fields({"openapi": "3.0.0", "paths": paths}, max_endpoints=3))
        self.assertIn("/handles/{handle} →", shapes)       # base resource shaped
        self.assertIn("/holders/{address} →", shapes)      # the DISTINCT resource SURVIVES the cap
        self.assertNotIn("/handles/{handle}/utxo", shapes)  # its sub-paths are collapsed, not shaped

    def test_response_fields_empty_for_non_spec_doc(self):
        # no paths → not a spec → surface nothing (never invent a shape)
        self.assertEqual(wf._endpoint_response_fields({"name": "x", "items": [1, 2]}), [])

    def test_spill_outline_surfaces_routes_for_spec_shaped_YAML(self):
        # OpenAPI served as YAML parses through the SAME shape-branch (PyYAML) → same route outline.
        self.assertIsNotNone(wf._yaml, "PyYAML must be installed (declared dependency)")
        pad = "x" * (wf.OVERSIZE_CHARS + 500)
        body = ("openapi: 3.0.0\ninfo:\n  description: " + pad +
                "\npaths:\n  /handles/{handle}:\n    get: {}\n  /holders/{address}:\n    get: {}\n")
        msg = self._spill_msg("https://ex.com/openapi.yaml", body, "application/yaml")
        self.assertIn("API endpoints (2)", msg)
        self.assertIn("/handles/{handle}", msg)
        self.assertIn("/holders/{address}", msg)

    def test_spill_outline_falls_back_to_top_level_keys_for_plain_json(self):
        pad = "x" * (wf.OVERSIZE_CHARS + 500)
        body = json.dumps({"name": "x", "holder": "y", "total": 3, "blob": pad})
        msg = self._spill_msg("https://ex.com/data.json", body, "application/json")
        self.assertIn("top-level keys (4)", msg)
        self.assertIn("holder", msg)
        self.assertNotIn("API endpoints", msg)   # not route-shaped → no invented routes

    def test_spill_outline_absent_for_unstructured_html(self):
        pad = "x" * (wf.OVERSIZE_CHARS + 500)
        msg = self._spill_msg("https://ex.com/big.html", "<html><body>" + pad + "</body></html>", "text/html")
        self.assertNotIn("API endpoints", msg)   # nothing walkable → nothing invented
        self.assertNotIn("top-level keys", msg)

    def test_broad_find_is_bounded_not_a_wall(self):
        big = json.dumps({"paths": {f"/p{i}": {"get": {"summary": "y" * 80}} for i in range(500)}},
                         separators=(",", ":"))
        orig = self._serve(big)
        try:
            out = wf.fetch_nav("https://api.x/spec.json", find="paths")
            self.assertLess(len(out), wf.OVERSIZE_CHARS + 3000)   # windowed, not the whole subtree
            self.assertIn("narrow", out.lower())
        finally:
            wf.fetch = orig


class UncappedNavHintsTests(unittest.TestCase):
    """Navigation hints on a MISS must be complete — a cap would hide the very key/section the
    model needs to re-target (its target may be key #27)."""

    def test_top_level_keys_are_uncapped(self):
        root = {f"k{i}": i for i in range(30)}
        keys = wf.top_level_keys(root)
        self.assertEqual(len(keys), 30)            # no 20-cap
        self.assertIn("k27", keys)

    def test_find_json_miss_lists_all_top_keys(self):
        root = {f"section{i}": {} for i in range(30)}
        out = wf.find_json(root, "zzzznope", 4000)
        self.assertIn("no match", out)
        self.assertIn("section27", out)            # a beyond-20th key still surfaces on a miss

    def test_find_text_miss_lists_all_headings(self):
        body = "\n".join(f"# Heading {i}" for i in range(30))
        out = wf.find_text(body, "zzzznope", 4000)
        self.assertIn("no match", out)
        self.assertIn("# Heading 27", out)         # no 15-cap on the Sections outline

    def test_find_text_miss_on_a_small_doc_returns_the_WHOLE_doc(self):
        # THE FOOTGUN (live run 0726-133755): the coder fetched https://api.handle.me — a 705-char index
        # page whose entire value is its link list, including the OpenAPI spec — with find="resolve".
        # "resolve" is nowhere on it, so cria answered `find "resolve": no match.` and NOTHING else,
        # destroying the one page that names the spec. A missed narrowing must never be worse than not
        # narrowing: when the document fits a page, hand it back.
        body = ('<h1>api.handle.me</h1><ul><li><a href="/swagger">Swagger UI</a></li>'
                '<li><a href="/openapi.json">OpenAPI spec (JSON)</a></li></ul>')
        out = wf.find_text(body, "resolve", 4000)
        self.assertIn("no match", out)                 # the miss is still disclosed, not hidden
        self.assertIn("/openapi.json", out)            # ...and the document survives it
        self.assertIn("Swagger UI", out)

    def test_find_text_miss_on_an_oversized_doc_does_not_dump_it(self):
        # The other half of the rule: returning a huge doc here would be the truncation-by-window this
        # very rule forbids. No headings to outline → say how to re-target, don't dump.
        body = "x" * (4000 * 4 + 5000)
        out = wf.find_text(body, "zzzznope", 4000)
        self.assertIn("no match", out)
        self.assertLess(len(out), 500)                 # not the document
        self.assertIn("without find", out)             # concrete re-target guidance

    def test_find_text_hit_discloses_residual_matches(self):
        # 5 distinct paragraphs each contain the query → top-FIND_TOP_K shown, the rest DISCLOSED,
        # never silently stopped at FIND_TOP_K (the match the model wants may be the 4th).
        body = "\n\n".join(f"Paragraph {i} mentions the needle right here." for i in range(5))
        out = wf.find_text(body, "needle", 4000)
        self.assertIn(f"{5 - wf.FIND_TOP_K} more match(es)", out)


class TruncationDisclosureTests(unittest.TestCase):
    """A body cut at the read cap must be DISCLOSED — the paging/find end must never look like a
    clean end-of-document (the silent-slice lie)."""

    def setUp(self):
        wf.clear_cache()

    def test_final_page_discloses_truncation(self):
        out = wf.render_page("https://x/big", 200, "text/plain", "body content", None, 0, 200, True)
        self.assertNotIn("More remains", out)
        self.assertIn("fetch limit", out)
        self.assertIn("NOT fetched", out)

    def test_final_page_no_disclosure_when_not_truncated(self):
        out = wf.render_page("https://x/big", 200, "text/plain", "body content", None, 0, 200, False)
        self.assertNotIn("fetch limit", out)

    def test_fetch_nav_discloses_truncation_at_end(self):
        orig = wf.fetch
        wf.fetch = lambda url, ua=None: wf.FetchResult(200, url, "text/plain", "line0\nline1\nline2", True)
        try:
            out = wf.fetch_nav("https://x/big")
        finally:
            wf.fetch = orig
        self.assertIn("fetch limit", out)

    def test_find_miss_on_truncated_doc_discloses(self):
        orig = wf.fetch
        wf.fetch = lambda url, ua=None: wf.FetchResult(200, url, "application/json", '{"a":1}', True)
        try:
            out = wf.fetch_nav("https://x/spec", find="nonexistentkey")
        finally:
            wf.fetch = orig
        self.assertIn("no match", out)
        self.assertIn("fetch limit", out)          # a miss may be a cut, not an absence


if __name__ == "__main__":
    unittest.main()


class GateTests(unittest.TestCase):
    """The exact-repeat gate refuses a repeat ONLY while its result is still visible (set_visible);
    once compaction elides it, the model may re-read — the footgun fix. Plus the stop-guessing nudge."""

    def setUp(self):
        wf.clear_cache()
        self._orig = wf.fetch
        self.addCleanup(lambda: setattr(wf, "fetch", self._orig))

    def test_search_repeat_refused_only_while_visible(self):
        self.assertIsNone(wf.gate_search("s1", "ada handle api"))     # nothing visible → proceed
        wf.set_visible("s1", [], ["ada handle api"])                  # result now in context
        r = wf.gate_search("s1", "ada handle api")
        self.assertIn("already ran", r)          # gentle re-point, not a fake HTTP-400 error
        self.assertNotIn("HTTP 400", r)
        # It must name WHERE the earlier results are. Saying "its results are still above" was a lie:
        # cria spills them to a file and says in the same breath they are NOT inlined, so the coder
        # was sent to look above at nothing and searched again (8× in run 0726-135324).
        self.assertNotIn("still above", r)
        self.assertIn(wf.search_spill_name("ada handle api"), r)   # the real file, named
        self.assertIn("grep -n", r)                                 # ...and how to read it
        wf.set_visible("s1", [], [])                                  # compacted away → allowed again
        self.assertIsNone(wf.gate_search("s1", "ada handle api"))
        self.assertIsNone(wf.gate_search(None, "x"))

    def test_search_gate_matches_near_duplicate_word_set_not_just_exact(self):
        # a weak model evades an EXACT-string gate by tweaking the wording; the word-set matcher
        # (searchloop, the codex-local port) catches the re-hunt. Real case: fabliq alternated
        # "…API resolve…" / "…API endpoint resolve…" ~30x. Both, once visible, block their repeats,
        # and a word-swap re-hunt is refused; a genuinely new direction still proceeds.
        A = "ADA Handle API resolve handle to address holder address total handles"
        B = "ADA Handle API endpoint resolve handle to address holder address total handles"
        wf.set_visible("s1", [], [A, B])
        self.assertIn("already ran", wf.gate_search("s1", A))                    # exact repeat of a visible
        self.assertIn("already ran", wf.gate_search("s1", B))
        self.assertIn("already ran", wf.gate_search("s1", "ADA Handle API resolve handle holder"))  # word-swap re-hunt
        self.assertIsNone(wf.gate_search("s1", "python requests connection timeout retry"))       # new direction → proceed

    def test_search_gate_steers_to_fetch_a_named_domain(self):
        wf.set_visible("s1", [], ["resolve handle address holder api.handle.me"])
        r = wf.gate_search("s1", "resolve handle address total api.handle.me")  # swaps holder→total; re-hunt naming a domain
        self.assertIn("already ran", r)
        self.assertIn("web_fetch https://api.handle.me", r)

    def test_fetch_repeat_refused_only_while_visible(self):
        wf.fetch = lambda u, ua=None: wf.FetchResult(200, u, "application/json", '{"a":1}', False)
        url = "https://api.x/openapi.json"
        self.assertIn("HTTP 200", wf.fetch_nav(url, session="s1"))            # first fetch
        wf.set_visible("s1", [(url, "", "")], [])                            # its result is in context
        self.assertIn("still above", wf.fetch_nav(url, session="s1"))        # → refused
        wf.set_visible("s1", [], [])                                         # compaction elided it
        self.assertIn("HTTP 200", wf.fetch_nav(url, session="s1"))           # → re-read ALLOWED (the fix)
        # internal host is never gated, even when marked visible
        wf.fetch = lambda u, ua=None: wf.FetchResult(200, u, "text/plain", "up", False)
        iu = "http://localhost:8080/health"
        wf.set_visible("s1", [(iu, "", "")], [])
        self.assertNotIn("still above", wf.fetch_nav(iu, session="s1"))

    def test_find_cursor_gated_by_the_full_key(self):
        # the gate key is (url, find, cursor) — a find/cursor repeat is handled just like a plain one
        wf.fetch = lambda u, ua=None: wf.FetchResult(200, u, "application/json", '{"paths":{}}', False)
        url = "https://x/spec"
        wf.set_visible("s1", [(url, "resolve", "c500")], [])
        self.assertIn("still above", wf.fetch_nav(url, find="resolve", cursor="c500", session="s1"))  # exact repeat
        self.assertNotIn("still above", wf.fetch_nav(url, find="holders", session="s1"))  # a DIFFERENT find = new nav
        wf.set_visible("s1", [], [])                                                       # compaction elided it
        self.assertNotIn("still above", wf.fetch_nav(url, find="resolve", cursor="c500", session="s1"))  # allowed

    def test_guess_streak_nudge_after_three_non_2xx(self):
        wf.fetch = lambda u, ua=None: wf.FetchResult(404, u, "text/plain", "nope", False)
        self.assertNotIn("guessing", wf.fetch_nav("https://api.x/miss0", session="s1"))
        self.assertNotIn("guessing", wf.fetch_nav("https://api.x/miss1", session="s1"))
        self.assertIn("guessing", wf.fetch_nav("https://api.x/miss2", session="s1"))   # 3rd in a row
