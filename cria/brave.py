"""One definition of the Brave Search request — endpoint, URL encoding, headers — and the one in-process call
(:func:`search`) that both the planner's `web_search` and the coder's lowered `web_search` build on, so the two can't
drift (they had: one used `urlencode`, the other `sed 's/ /+/g'` and dropped headers)."""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from . import httpread, ratelimit
from .envfile import env_secret

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
# Matches Brave Browser on Linux desktop (it identifies as Chrome on purpose).
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
# The web-search key's env var has exactly ONE name — Brave's own — so it is a code constant,
# not a config knob. (The key VALUE is never in config; it's read from the environment at runtime.)
API_KEY_ENV = "BRAVE_SEARCH_API_KEY"


def api_key() -> str | None:
    """The Brave Search API key from the environment (CRLF/quote-normalized), or None when unset."""
    return env_secret(API_KEY_ENV)


def query_url(query: str, count: int = 20) -> str:
    """The full request URL with a properly %-encoded query (handles & ? # + and unicode).
    Default requests Brave's per-request maximum (20): a caller that doesn't specify a count
    should see the FULL result set, not a silent top-5 under-fetch. The clamp below is the only
    bound — it prevents an invalid over-20 request, it never hides results the API would return."""
    count = max(1, min(20, count))
    return ENDPOINT + "?" + urllib.parse.urlencode({"q": query or "", "count": count})


def headers(api_key: str) -> dict:
    return {"X-Subscription-Token": api_key, "Accept": "application/json", "User-Agent": USER_AGENT}


SEARCH_TIMEOUT_S = 20
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class Answer:
    """What one in-process search brought back. ``body`` is the compact JSON the lowered parser reads (only the fields it
    prints: each result's title / url / description, and the API's own ``error`` / ``message``); ``""`` when nothing readable
    arrived. ``refused`` is the HTTP status of a 429/503 (0 otherwise) and ``wait_ms`` how long the service said to wait
    (from the process's wait state, which the shared reader filled from the service's own headers or body)."""
    body: str = ""
    refused: int = 0
    wait_ms: int = 0


def search(query: str, api_key: str, count: int = 20, *, state: Optional[ratelimit.WaitState] = None,
           opener: Optional[Callable] = None, now: Callable[[], float] = time.time) -> Answer:
    """ONE Brave Search GET, made by cria itself through the shared rate-limit opener: a cooldown is waited out, a short 429 is
    retried once after exactly the stated wait, a long one is reported unsent. The free plan allows one request a second, so
    a harness-run ``curl`` could neither wait nor say how long; cria can do both."""
    state = ratelimit.STATE if state is None else state
    url = query_url(query, count)
    req = urllib.request.Request(url, headers=headers(api_key))
    key = ratelimit.key_for(url)
    try:
        resp = ratelimit.open_response(req, SEARCH_TIMEOUT_S, state=state, opener=opener, now=now)
    except ratelimit.RateLimited as held:
        return Answer(refused=429, wait_ms=held.retry_after_ms)
    except (OSError, ValueError, http.client.HTTPException):
        return Answer()                                          # a transport failure: nothing readable (the parser's own fallback line)
    with resp:
        status = int(getattr(resp, "status", 0) or getattr(resp, "code", 0) or 0)
        try:
            raw = httpread.read_bounded(resp, _MAX_RESPONSE_BYTES)
        except (OSError, http.client.HTTPException):
            raw = b""
    if status in (429, 503):
        return Answer(refused=status, wait_ms=state.remaining_ms(key))
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return Answer()
    if not isinstance(data, dict):
        return Answer()
    results = [{"title": x.get("title", ""), "url": x.get("url", ""), "description": x.get("description", "")}
               for x in ((data.get("web") or {}).get("results") or []) if isinstance(x, dict)]
    compact = {"web": {"results": results}, "error": data.get("error"), "message": data.get("message")}
    return Answer(body=json.dumps(compact, ensure_ascii=True))
