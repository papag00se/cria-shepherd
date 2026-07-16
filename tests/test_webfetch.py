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

    def test_empty_body_is_explicit(self):
        orig = wf.fetch
        wf.fetch = lambda url, ua=None: wf.FetchResult(200, url, "text/plain", "", False)
        try:
            out = wf.fetch_nav("https://e.com/x")
        finally:
            wf.fetch = orig
        self.assertIn("EMPTY", out)


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
        self.assertIn("HTTP 400", r)
        self.assertIn("still above", r)
        wf.set_visible("s1", [], [])                                  # compacted away → allowed again
        self.assertIsNone(wf.gate_search("s1", "ada handle api"))
        self.assertIsNone(wf.gate_search(None, "x"))

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

    def test_guess_streak_nudge_after_three_non_2xx(self):
        wf.fetch = lambda u, ua=None: wf.FetchResult(404, u, "text/plain", "nope", False)
        self.assertNotIn("guessing", wf.fetch_nav("https://api.x/miss0", session="s1"))
        self.assertNotIn("guessing", wf.fetch_nav("https://api.x/miss1", session="s1"))
        self.assertIn("guessing", wf.fetch_nav("https://api.x/miss2", session="s1"))   # 3rd in a row
