"""Reading an HTTP response body: bounded in TOTAL time as well as size, and decoded with the charset the server declared.

``urlopen``'s timeout is a per-SOCKET-READ deadline: a server that sends one byte every 29 seconds never trips it, and a
byte-count cap alone would take months to fill at that rate. :func:`read_bounded` adds the missing total deadline.
:func:`decode` honours the declared charset (BOM, ``Content-Type: …; charset=``, an HTML ``<meta charset>``); decoding
latin-1 or Shift-JIS as UTF-8-with-replacement destroys every accented or CJK character in a document the model is
about to read as if it were faithful.
"""
from __future__ import annotations

import codecs
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

TOTAL_READ_SECONDS = 120   # one fetch's whole body: a slow-drip server is cut off here, said plainly, never waited on forever
_CHUNK = 64 * 1024

_CHARSET_PARAM = re.compile(rb"charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:\-]+)", re.IGNORECASE)
_BOMS = ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
         (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))


class HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect is followed only to http or https. urllib's default also follows ``ftp://`` (and an empty scheme); a fetch
    that was told to read a web page must not be walked onto another protocol by a server's ``Location`` header. The 3xx
    itself is then the response (an ``HTTPError``, which every caller already reads like a response)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        scheme = urllib.parse.urlsplit(newurl).scheme.lower()
        if scheme not in ("http", "https"):
            raise urllib.error.HTTPError(req.full_url, code, f"{msg}: redirect to '{newurl}' not followed (only http/https)", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def install_http_only_redirects() -> None:
    """Install the one process-wide default opener, once at startup. ``urllib.request.urlopen`` stays the name every caller (and
    every test that pins it as the no-network seam) goes through; only what it does on a redirect changes."""
    urllib.request.install_opener(urllib.request.build_opener(HttpOnlyRedirects))


class SlowBody(TimeoutError):
    """The server stopped (or dripped) its body past the total deadline; carries what was received so far."""

    def __init__(self, received: int, seconds: float):
        self.received = received
        super().__init__(f"the server was still sending after {seconds:g} s and only {received:,} bytes had arrived; "
                         f"the transfer was abandoned (a response that arrives this slowly is not read)")


def read_bounded(resp, limit: int, *, total_seconds: float | None = None,
                 clock: Callable[[], float] = time.monotonic) -> bytes:
    """Up to ``limit`` bytes of the body (``limit`` bytes means "at least that much exists"). Raises :class:`SlowBody`
    when the whole read outlasts ``total_seconds``. Reads whatever each socket read delivers (``read1``) so the deadline
    is checked between reads, not only after a full buffer that a slow server may never fill."""
    total_seconds = TOTAL_READ_SECONDS if total_seconds is None else total_seconds
    take = getattr(resp, "read1", None) or resp.read
    deadline = clock() + total_seconds
    chunks: list[bytes] = []
    got = 0
    while got < limit:
        chunk = take(min(_CHUNK, limit - got))
        if not chunk:
            break
        chunks.append(chunk)
        got += len(chunk)
        if got < limit and clock() > deadline:
            raise SlowBody(got, total_seconds)
    return b"".join(chunks)


def _declared(raw: bytes, content_type: str | None) -> str | None:
    for bom, name in _BOMS:
        if raw.startswith(bom):
            return name
    header = _CHARSET_PARAM.search((content_type or "").encode("latin-1", "replace"))
    found = header.group(1) if header else None
    if found is None and (not content_type or "html" in content_type.lower() or "xml" in content_type.lower()):
        meta = _CHARSET_PARAM.search(raw[:2048])
        found = meta.group(1) if meta else None
    if found is not None:
        try:
            return codecs.lookup(found.decode("ascii", "replace")).name
        except LookupError:
            return None
    return None


def decode(raw: bytes, content_type: str | None) -> str:
    """The text of ``raw``: its declared charset when it names a real one, else UTF-8, else Windows-1252 (the web's own
    default for undeclared non-UTF-8 bytes — it maps every byte a latin-1 page uses to its character, where UTF-8 with
    replacement would turn each into U+FFFD)."""
    charset = _declared(raw, content_type)
    if charset is not None:
        return raw.decode(charset, "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")
