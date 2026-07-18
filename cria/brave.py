"""One definition of the Brave Search request — endpoint, URL encoding, headers — shared by the
planner's in-process `web_search` (urlopen) and the writeproxy's shell-lowered `web_search` (curl),
so the two can't drift (they had: one used `urlencode`, the other `sed 's/ /+/g'` and dropped
headers)."""

from __future__ import annotations

import urllib.parse

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
