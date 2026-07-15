"""One definition of the Brave Search request — endpoint, URL encoding, headers — shared by the
planner's in-process `web_search` (urlopen) and the writeproxy's shell-lowered `web_search` (curl),
so the two can't drift (they had: one used `urlencode`, the other `sed 's/ /+/g'` and dropped
headers)."""

from __future__ import annotations

import urllib.parse

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
# Matches Brave Browser on Linux desktop (it identifies as Chrome on purpose).
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"


def query_url(query: str, count: int = 5) -> str:
    """The full request URL with a properly %-encoded query (handles & ? # + and unicode)."""
    count = max(1, min(20, count))
    return ENDPOINT + "?" + urllib.parse.urlencode({"q": query or "", "count": count})


def headers(api_key: str) -> dict:
    return {"X-Subscription-Token": api_key, "Accept": "application/json", "User-Agent": USER_AGENT}
