"""Multipart consumer; no executor.

Producer contract: one ASCII JSON line per harness result. Source identity and
selected-stream identity must agree on every page; offsets are stream offsets.
A caller MUST NOT publish any page or grant read credit until finish() succeeds.
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
from dataclasses import dataclass, field

STDOUT_LIMIT = 10_000
# Record limits of the re-fetches that follow a cut result whose record did not survive (one per consecutive miss). A shell
# that prints before/after the program makes the harness cut the page in the middle; a smaller page is asked for again until
# one arrives whole, and its surroundings are then MEASURED (see MultipartRead.take). Smaller than the page itself, so the
# first of them also fits beside a few KB of noise untruncated.
REFETCH_LIMITS = (2000, 1000, 500)
MAX_REFETCH = 8
_CUT_MARK = re.compile('…(\\d+) chars truncated…')


class InvalidPage(ValueError):
    pass


class CutPage(InvalidPage):
    """The harness cut the output and no page record survived, and the re-fetches are used up."""


class BridgeError(ValueError):
    pass


@dataclass(frozen=True)
class UnverifiedCarrier:
    """Request-private provenance for exact tool-result display, not credit."""
    pass


def _pairs(items):
    d = {}
    for key, value in items:
        if key in d:
            raise InvalidPage('duplicate key')
        d[key] = value
    return d


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _nat(value):
    return type(value) is int and value >= 0


def _identity(value):
    """A source identity as the producer reports it: [dev, ino, size, mtime_ns], or None (absent)."""
    return value is None or (type(value) is list and len(value) == 4 and all(_nat(v) for v in value))


def _snapshot(value):
    """The typed `snapshot` object of a page. mode `snapshot`: the page was served from (or took) the private snapshot,
    `taken` is the source identity when it was taken and `now` the path's identity as of this page. mode `live`: no snapshot
    (single page, or `reason` says why not: over_cap | unavailable) and nothing else is claimed."""
    if not isinstance(value, dict) or set(value) != {'mode', 'reason', 'taken', 'now'}:
        raise InvalidPage('invalid snapshot object')
    mode, reason, taken, now = value['mode'], value['reason'], value['taken'], value['now']
    if not _identity(taken) or not _identity(now):
        raise InvalidPage('invalid snapshot identity')
    if mode == 'snapshot':
        if reason is not None or taken is None:
            raise InvalidPage('invalid snapshot object')
    elif mode == 'live':
        if reason not in (None, 'over_cap', 'unavailable') or taken is not None or now is not None:
            raise InvalidPage('invalid snapshot object')
    else:
        raise InvalidPage('invalid snapshot mode')
    return mode, reason, None if taken is None else tuple(taken), None if now is None else tuple(now)


@dataclass
class MultipartRead:
    token: str
    outcome: str
    semantics: str
    offset: int = 0
    identity: tuple | None = None
    result_outcome: str | None = None
    exit_code: int | None = None
    write_outcome: str | None = None
    snapshot: tuple | None = None       # (mode, reason, taken) as the FIRST page declared; later pages must repeat mode and taken
    snapshot_now: tuple | None = None   # the path's identity as of the LAST page; compared with `taken` at delivery
    noise: int = 0                      # the most bytes seen around a page record (shell output before/after the program)
    intact: int = 0                     # the largest record that survived a harness cut whole (a floor for the page size)
    misses: int = 0                     # consecutive cut results whose record did not survive
    refetches: int = 0
    _parts: list[bytes] = field(default_factory=list, repr=False)
    _failed: bool = False
    _complete: bool = False

    def accept(self, wire: bytes) -> bool:
        """Consume exactly the stdout record, not a searched marker or envelope.

        Returns true only on verified completion. A failure poisons the whole
        assembly; no prefix remains publishable, including after a later retry.
        """
        if self._failed or self._complete:
            raise InvalidPage('assembly is closed')
        try:
            return self._accept(wire)
        except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
            self._failed = True
            self._parts.clear()
            raise InvalidPage(str(exc)) from exc

    @property
    def limit(self) -> int:
        """The record byte limit of the NEXT page command: the harness limit less the noise measured around the last
        records (a re-fetch uses its smaller probe limit), never below a record already seen to arrive whole."""
        if self.misses:
            return REFETCH_LIMITS[self.misses - 1]
        return max(STDOUT_LIMIT - self.noise, self.intact)

    def take(self, text: str, cut: bool = False) -> bool:
        """Consume one harness result that may carry shell output around the producer's record.

        The record is the one line that starts with this read's private token (`{"v":1,"token":"<hex>"`: not guessable by
        a shell, never in the file's bytes, which ride base64); everything else is noise, whose size is measured: its
        bytes, plus the harness's own `…N chars truncated…` count when it cut the result around a record that survived.
        A cut result whose record did not survive asks for the same page again (False, offset unchanged) with a smaller
        limit; when those are used up, CutPage. The record itself is verified exactly as before (digests, offsets).
        Returns true only on verified completion."""
        if self._failed or self._complete:
            raise InvalidPage('assembly is closed')
        payload = text.encode('utf-8')
        prefix = b'{"v":1,"token":"' + self.token.encode() + b'"'
        start = payload.find(prefix) if self.token else -1
        end = payload.find(b'\n', start) + 1 if start >= 0 else 0
        if start >= 0 and payload.find(prefix, start + 1) >= 0:
            end = 0                                   # two candidate records: ambiguous, never pick one
            start = -1
        mark = _CUT_MARK.search(text) if cut else None
        at = payload.find(mark.group(0).encode()) if mark else -1
        if start >= 0 and end and start <= at < end:
            end = 0                                   # the harness cut INSIDE the record: its two halves are not a page
        if start < 0 or not end:
            if cut and self.misses < len(REFETCH_LIMITS) and self.refetches < MAX_REFETCH:
                self.misses += 1
                self.refetches += 1
                return False
            self._failed = True
            self._parts.clear()
            raise (CutPage if cut else InvalidPage)('no page record in the output')
        record = payload[start:end]
        noise = len(payload) - len(record) + (int(mark.group(1)) - len(mark.group(0).encode()) if mark else 0)
        complete = self.accept(record)
        self.misses = 0
        self.noise = max(self.noise, noise)
        if cut:
            self.intact = max(self.intact, len(record))
        return complete

    def _accept(self, wire):
        if not isinstance(wire, bytes) or len(wire) > STDOUT_LIMIT or not wire.endswith(b'\n') or b'\n' in wire[:-1]:
            raise InvalidPage('invalid or oversized stdout')
        obj = json.loads(wire[:-1].removesuffix(b'\r').decode('ascii'), object_pairs_hook=_pairs)
        keys = {'v','token','outcome','semantics','source_length','source_sha256',
                'stream_length','stream_sha256','offset','length','page_sha256','data',
                'exit_code','write_outcome','snapshot'}
        if not isinstance(obj, dict) or set(obj) != keys or type(obj['v']) is not int or obj['v'] != 1:
            raise InvalidPage('invalid schema')
        if obj['token'] != self.token or not self.token or obj['semantics'] != self.semantics:
            raise InvalidPage('correlation or semantics mismatch')
        if self.outcome not in ('read','read-instead') or self.semantics not in ('whole','range'):
            raise InvalidPage('invalid request')
        if obj['outcome'] not in (self.outcome, 'refused', 'error'):
            raise InvalidPage('invalid outcome')
        valid_write = ('not_run', 'unknown') if self.outcome == 'read-instead' else ('not_applicable',)
        if obj['write_outcome'] not in valid_write:
            raise InvalidPage('invalid write outcome')
        no_source = obj['source_length'] is None and obj['source_sha256'] is None
        source_valid = _nat(obj['source_length']) and _hash(obj['source_sha256'])
        if (not source_valid and not (no_source and obj['outcome'] in ('refused', 'error'))
            or not all(_nat(obj[k]) for k in ('stream_length','offset','length','exit_code'))
            or not all(_hash(obj[k]) for k in ('stream_sha256','page_sha256'))):
            raise InvalidPage('invalid lengths or digests')
        mode, reason, taken, now = _snapshot(obj['snapshot'])
        identity = (obj['source_length'],obj['source_sha256'],obj['stream_length'],obj['stream_sha256'],
                    obj['outcome'],obj['exit_code'],obj['write_outcome'],mode,taken)
        if self.identity is not None and identity != self.identity:
            raise InvalidPage('snapshot or stream changed')
        if obj['offset'] != self.offset:
            raise InvalidPage('noncontiguous page')
        data = base64.b64decode(obj['data'], validate=True)
        if len(data) != obj['length'] or hashlib.sha256(data).hexdigest() != obj['page_sha256']:
            raise InvalidPage('page length or digest mismatch')
        end = self.offset + len(data)
        if end > obj['stream_length'] or (not data and end != obj['stream_length']):
            raise InvalidPage('invalid page extent')
        self.identity = identity
        if self.snapshot is None:
            self.snapshot = (mode, reason, taken)      # the first page owns the reason; later live pages claim nothing
        self.snapshot_now = now
        self.result_outcome = obj['outcome']
        self.exit_code = obj['exit_code']
        self.write_outcome = obj['write_outcome']
        self.offset = end
        self._parts.append(data)
        if end == obj['stream_length']:
            joined = b''.join(self._parts)
            if hashlib.sha256(joined).hexdigest() != obj['stream_sha256']:
                raise InvalidPage('assembled stream digest mismatch')
            self._complete = True
        return self._complete

    @property
    def live_pages(self) -> bool:
        """True when the first page took no snapshot, so later pages read the path itself."""
        return self.snapshot is not None and self.snapshot[0] == 'live'

    @property
    def source_changed(self) -> bool:
        """The path's identity at the last page differs from the one the snapshot was taken from (absent counts)."""
        return self.snapshot is not None and self.snapshot[0] == 'snapshot' and self.snapshot_now != self.snapshot[2]

    def finish(self) -> bytes:
        if self._failed or not self._complete:
            raise InvalidPage('incomplete or failed assembly')
        return b''.join(self._parts)
