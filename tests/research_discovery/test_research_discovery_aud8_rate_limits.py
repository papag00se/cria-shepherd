"""Outbound HTTP honours a server's stated rate limit: every dialect of "wait" is read, the wait is shared across the process,
a request is never sent early, and the one retry comes after exactly the stated time (fake server, injected clock)."""
import http.server
import threading

import pytest

from cria import apidiscovery, ratelimit, webfetch

NOW = 1_700_000_000.0


class H(dict):
    get = lambda self, k, d=None: next((v for kk, v in self.items() if kk.lower() == k.lower()), d)  # noqa: E731


@pytest.mark.parametrize("headers, body, refused, expected", [
    ({"Retry-After": "7"}, None, True, 7000),
    ({"Retry-After-Ms": "250"}, None, True, 250),
    ({"Retry-After": "Tue, 14 Nov 2023 22:13:30 GMT"}, None, True, 10000),               # an HTTP date, 10 s after NOW
    ({"X-RateLimit-Reset-After": "1.5"}, None, True, 1500),
    ({"RateLimit-Reset": "12"}, None, True, 12000),                                      # IETF draft: delta seconds
    ({"RateLimit": "limit=100, remaining=0, reset=5"}, None, True, 5000),                # IETF structured field
    ({"X-RateLimit-Reset": "1700000030"}, None, True, 30000),                            # epoch seconds (GitHub)
    ({"X-RateLimit-Reset": "3"}, None, True, 3000),                                      # delta seconds
    ({"X-RateLimit-Remaining": "0, 14999", "X-RateLimit-Reset": "1, 2345678"}, None, True, 1000),   # Brave: only the exhausted window
    ({"X-RateLimit-Reset-Requests": "6m0s"}, None, True, 360000),                        # OpenAI duration strings
    ({"X-RateLimit-Reset-Requests": "20ms"}, None, True, 20),
    ({"Retry-After": "2", "X-RateLimit-Reset-After": "9"}, None, True, 9000),            # the longest signal wins
    ({}, b'{"message": "You are being rate limited.", "retry_after": 1.5, "global": false}', True, 1500),    # Discord
    ({}, b'{"error": {"code": 429, "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3.5s"}]}}', True, 3500),
    ({}, b'{"error": {"message": "Rate limit reached. Please try again in 1.5s."}}', True, 1500),              # OpenAI / Groq prose
    ({}, b'API Error: 429 {"error": {"message": "slow down", "retry_after": 4}}', True, 4000),               # JSON inside prose
    ({}, b"Too many requests, retry after 9 seconds", True, 9000),
    ({"Retry-After": "-3"}, None, True, None), ({"Retry-After": "soon"}, None, True, None), ({}, None, True, None), (None, None, True, None),
    ({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "4"}, None, False, 4000),        # a SUCCESS that spent the window: the next request waits
    ({"X-RateLimit-Remaining": "37", "X-RateLimit-Reset": "4"}, None, False, None),       # budget left: no wait
    ({"X-RateLimit-Reset": "4"}, b'{"retry_after": 9}', False, None),                     # a success is never read for a body delay
])
def test_a_stated_delay_is_read_from_every_signal_a_server_uses(headers, body, refused, expected):
    assert ratelimit.delay_ms(H(headers) if headers is not None else None, body, now=lambda: NOW, refused=refused) == expected


@pytest.mark.parametrize("prose, expected", [
    ("You've hit your limit · resets 5pm (America/Los_Angeles)", 10_000_000),             # 14:13 in LA at NOW: 2 h 46 m 40 s
    ("Claude usage limit reached. Your limit will reset at 5pm (Europe/Berlin).", 64_000_000),     # 23:13 in Berlin: 5pm is tomorrow's
    ("resets 2pm (America/Los_Angeles)", 85_600_000),                                     # already past today in LA: tomorrow
    ('{"result": "You\'ve hit your limit · resets 12am (UTC)"}', 6_400_000),               # inside JSON; midnight is 12am
    ("resets Nov 20 at 12pm (UTC)", 481_600_000), ("resets Jan 2, 9:30am (UTC)", 4_187_800_000),   # a named day (past this year: next)
    ("resets 5 pm (Asia/Tokyo)", 35_200_000),                                             # 07:13 in Tokyo: "5 pm" with a space
    ("resets 13pm (UTC)", None), ("resets 5pm (Mars/Olympus)", None),                      # impossible hour; a zone this machine cannot read
    ("the cache resets 5 times", None), ("password reset email sent", None),
])
def test_the_claude_cli_prose_that_names_a_clock_time_is_read_in_the_zone_it_names(prose, expected):
    assert ratelimit.delay_ms(None, prose.encode(), now=lambda: NOW) == expected


def test_a_reset_time_without_a_zone_is_read_in_this_machines_zone(monkeypatch):
    import time
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    try:
        assert ratelimit.delay_ms(None, b"resets 5pm", now=lambda: NOW) == 35_200_000
    finally:
        monkeypatch.undo()
        time.tzset()


class Clock:
    """A fake clock whose sleep advances it, and remembers each sleep."""
    def __init__(self):
        self.t, self.slept = 0.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_a_cooldown_is_waited_out_by_every_caller_and_never_slept_when_longer_than_a_turn_can_hold():
    clock = Clock()
    state = ratelimit.WaitState(clock.now, clock.sleep)
    state.note("a:1", 5000)
    state.note("a:1", 2000)                                    # never shortens a longer wait
    state.hold("b:1")                                           # another host is unaffected
    assert clock.slept == []
    state.hold("a:1")
    assert clock.slept == [5.0]
    state.note("a:1", 60_000)
    with pytest.raises(ratelimit.RateLimited) as held:
        state.hold("a:1", max_wait_ms=30_000)
    assert clock.slept == [5.0] and held.value.retry_after_ms == 60_000 and held.value.code == 429


class Limiter(http.server.BaseHTTPRequestHandler):
    """Scripted server: `script` is a list of (status, headers, body); every request is logged with how many sleeps preceded it."""
    script: list
    seen: list
    clock: Clock

    def do_GET(self):
        self.seen.append((self.path, len(self.clock.slept)))
        status, headers, body = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, *a):
        pass


@pytest.fixture
def limited(monkeypatch):
    """A scripted server and the process wait state replaced by one on a fake clock: (url, script, seen, clock)."""
    clock = Clock()
    monkeypatch.setattr(ratelimit, "STATE", ratelimit.WaitState(clock.now, clock.sleep))
    handler = type("H", (Limiter,), {"script": [], "seen": [], "clock": clock})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", handler.script, handler.seen, clock
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("headers, body, stated", [
    ({"Retry-After": "7"}, b"slow down", 7.0),
    ({"Retry-After-Ms": "1500"}, b"slow down", 1.5),
    ({"RateLimit-Reset": "3"}, b"slow down", 3.0),
    ({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "2"}, b"slow down", 2.0),
    ({"x-ratelimit-reset-requests": "1m0s"}, b"slow down", None),     # 60 s is over what a turn can hold: reported, not slept (below)
    ({}, b'{"retry_after": 0.5}', 0.5),
])
def test_a_429_is_retried_once_after_exactly_the_stated_wait_and_never_before(limited, headers, body, stated):
    """The server sees the retry only AFTER the stated sleep; a wait longer than a turn can hold is returned, not slept, and the host is then not asked at all."""
    url, script, seen, clock = limited
    script += [(429, headers, body), (200, {}, b'{"ok": true}')]
    req = webfetch.urllib.request.Request(url + "/x")
    if stated is None:                                         # a 60 s wait: no retry, the refusal comes back with its body
        resp = ratelimit.open_response(req, 5)
        assert resp.code == 429 and resp.read() == b"slow down" and len(seen) == 1 and clock.slept == []
        with pytest.raises(ratelimit.RateLimited):
            ratelimit.open_response(req, 5)
        assert len(seen) == 1                                  # NOT sent
        return
    with ratelimit.open_response(req, 5) as resp:
        assert resp.status == 200 and resp.read() == b'{"ok": true}'
    assert clock.slept == [stated] and [n for _, n in seen] == [0, 1]


def test_a_success_that_spent_the_window_makes_the_next_request_wait_for_the_reset(limited):
    url, script, seen, clock = limited
    script += [(200, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "4"}, b"first"), (200, {}, b"second")]
    req = webfetch.urllib.request.Request(url + "/x")
    with ratelimit.open_response(req, 5) as resp:
        assert resp.read() == b"first" and clock.slept == []
    with ratelimit.open_response(req, 5) as resp:
        assert resp.read() == b"second"
    assert clock.slept == [4.0] and [n for _, n in seen] == [0, 1]


def test_a_fetch_that_was_rate_limited_tells_the_model_the_stated_wait_and_the_next_fetch_is_not_sent(limited):
    """web_fetch: the 429 keeps its body, says how long the host asked for, and a second fetch of ANY path on that host inside the window is answered without a request."""
    url, script, seen, clock = limited
    script.append((429, {"Retry-After": "120"}, b'{"error": "quota"}'))
    first = webfetch.fetch_nav(url + "/a")
    assert "HTTP 429" in first and '{"error":"quota"}' in first and "120 more seconds" in first
    again = webfetch.fetch_nav(url + "/b")
    assert "NOT sent" in again and "120" in again and len(seen) == 1 and clock.slept == []


def test_a_short_429_on_a_fetch_is_waited_and_the_page_is_returned(limited):
    url, script, seen, clock = limited
    script += [(429, {"Retry-After": "2"}, b"busy"), (200, {}, b'{"answer": 42}')]
    page = webfetch.fetch_nav(url + "/a")
    assert "HTTP 200" in page and "42" in page and clock.slept == [2.0] and len(seen) == 2


def test_the_protocol_probe_honours_the_same_wait(limited):
    """apidiscovery's JSON-RPC POST goes through the same opener: a 429 with Retry-After is retried once after the wait."""
    url, script, seen, clock = limited
    script += [(429, {"Retry-After": "3"}, b"busy"), (200, {}, b'{"result": {}}')]
    status, body, _ = apidiscovery._post_json(url + "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {})
    assert status == 200 and clock.slept == [3.0] and len(seen) == 2


@pytest.fixture
def http_only_redirects(monkeypatch):
    """The process-wide opener `python -m cria` installs at startup, replaced for the test and restored after."""
    from cria import httpread
    monkeypatch.setattr(webfetch.urllib.request, "_opener", None)
    httpread.install_http_only_redirects()


def test_a_redirect_to_another_protocol_is_not_followed_and_a_redirect_to_http_still_is(limited, http_only_redirects):
    """A real local 302 to `ftp://` used to be followed by urllib's default opener (a refused ftp connection surfaced as a transport error);
    the 302 itself is now the answer, while a redirect to a path on the same host is followed as before."""
    url, script, seen, _clock = limited
    script += [(302, {"Location": "ftp://127.0.0.1:9/secret"}, b"")]
    page = webfetch.fetch(url + "/a")
    assert page.status == 302 and len(seen) == 1
    script[:] = [(302, {"Location": "/b"}, b""), (200, {"Content-Type": "text/plain"}, b"landed")]
    seen.clear()
    followed = webfetch.fetch(url + "/a")
    assert followed.status == 200 and "landed" in followed.body and [p for p, _ in seen] == ["/a", "/b"]
